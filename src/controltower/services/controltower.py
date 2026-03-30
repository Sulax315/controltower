from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import quote, urlencode

from controltower.adapters.profitintel import ProfitIntelAdapter
from controltower.adapters.schedulelab import ScheduleLabAdapter
from controltower.config import ControlTowerConfig
from controltower.domain.models import (
    ActionQueueGroup,
    ActionQueueItem,
    ActionQueueView,
    ArenaItem,
    ArenaMetric,
    ArenaView,
    ChangeAnswer,
    ChangeIntelligenceSummary,
    ComparisonTrust,
    ContinuityResolvedItem,
    ContinuityView,
    ControlTowerAttentionItem,
    ControlTowerHeadline,
    ControlTowerView,
    DeterministicPanelValue,
    DomainCoverage,
    DriverChangeInvestigation,
    ExportRecord,
    FinishDriverDetail,
    FinishDriverInvestigation,
    FinishDriverSummary,
    MeetingPacketItem,
    MeetingPacketView,
    PublishArtifactAvailability,
    PublishArtifactPreviewMetadata,
    PublishArtifactView,
    PublishContinuityView,
    PublishHistoryItem,
    PublishProjectOption,
    PublishView,
    ProjectCommandView,
    ProjectContinuitySummary,
    NarrativeBullet,
    NarrativeSection,
    PortfolioSummary,
    ProjectDelta,
    ProjectIdentity,
    ProjectSnapshot,
    SecondarySurfaceLink,
    SourceArtifactRef,
    SurfaceScanCard,
    utc_now_iso,
)
from controltower.obsidian.exporter import write_export_bundle
from controltower.render.markdown import (
    publishable_markdown,
    parse_markdown_frontmatter,
    render_arena_export_artifact,
    render_portfolio_summary,
    render_publish_markdown_preview,
    render_project_dossier,
    render_project_weekly_brief,
    validate_markdown_templates,
)
from controltower.services.delta import (
    compute_project_deltas,
    describe_comparison_trust,
    index_projects_by_id,
    load_previous_run_record,
    load_run_history,
    load_run_record,
    record_matches_current,
    select_comparison_run_record,
)
from controltower.services.execution_brief import ExecutionBriefService
from controltower.services.health import assess_project_health, posture_text
from controltower.services.identity_reconciliation import IdentityReconciliationService
from controltower.services.runtime_state import LATEST_RELEASE_JSON, RELEASE_ROOT_NAME, read_json


class ControlTowerService:
    def __init__(self, config: ControlTowerConfig) -> None:
        self.config = config
        validate_markdown_templates()
        self.identity_registry = IdentityReconciliationService.load(config.identity.registry_path)
        self.schedulelab = ScheduleLabAdapter(config.sources.schedulelab.published_root)
        self.profitintel = ProfitIntelAdapter(
            config.sources.profitintel.database_path,
            validation_search_roots=config.sources.profitintel.validation_search_roots,
        )
        self.execution_brief_service = ExecutionBriefService()

    def validate_sources(self) -> list[str]:
        return self.schedulelab.validate() + self.profitintel.validate()

    def build_projects(self) -> list[ProjectSnapshot]:
        projects, _comparison_trust = self._build_ranked_projects()
        return projects

    def build_portfolio(self) -> PortfolioSummary:
        projects, comparison_trust = self._build_ranked_projects()
        generated_at = utc_now_iso()
        tier_counts = {
            "healthy": sum(1 for project in projects if project.health.tier == "healthy"),
            "watch": sum(1 for project in projects if project.health.tier == "watch"),
            "at_risk": sum(1 for project in projects if project.health.tier == "at_risk"),
            "critical": sum(1 for project in projects if project.health.tier == "critical"),
        }
        risk_distribution = {
            "LOW": sum(1 for project in projects if project.health.risk_level == "LOW"),
            "MEDIUM": sum(1 for project in projects if project.health.risk_level == "MEDIUM"),
            "HIGH": sum(1 for project in projects if project.health.risk_level == "HIGH"),
        }
        avg = round(sum(project.health.health_score for project in projects) / len(projects), 1) if projects else None
        top_at_risk = [project.project_name for project in projects if project.health.risk_level == "HIGH"][:5]
        key_actions = [
            self._portfolio_action_line(project, comparison_trust)
            for project in projects
            if project.health.required_actions
        ][:8]
        provenance: list[SourceArtifactRef] = []
        for project in projects:
            provenance.extend(project.provenance)
        return PortfolioSummary(
            generated_at=generated_at,
            project_count=len(projects),
            active_project_count=len(projects),
            tier_counts=tier_counts,
            average_health_score=avg,
            overall_posture=posture_text(projects),
            risk_distribution=risk_distribution,
            top_at_risk_projects=top_at_risk,
            top_5_at_risk_projects=top_at_risk,
            cross_project_risk_themes=self._cross_project_risk_themes(projects),
            biggest_movers=self._portfolio_changes(projects, comparison_trust),
            key_actions_this_week=key_actions,
            portfolio_changes=self._portfolio_changes(projects, comparison_trust)[:5],
            project_rankings=projects,
            provenance=_dedupe_provenance(provenance)[:20],
            comparison_trust=comparison_trust,
            domain_coverage=self._domain_coverage(projects),
        )
 
    def build_control_tower(self, selected_arena_codes: list[str] | None = None) -> ControlTowerView:
        portfolio = self.build_portfolio()
        selected_codes = self._normalize_selection(selected_arena_codes, portfolio.project_rankings)
        operational_scope_projects = self._operational_scope_projects(
            portfolio.project_rankings,
            selected_codes,
            fallback_to_current_lead=True,
        )
        top_attention = [self._build_attention_item(project, selected_codes, portfolio.comparison_trust) for project in portfolio.project_rankings[:8]]
        intervention_required = [
            self._build_attention_item(project, selected_codes, portfolio.comparison_trust)
            for project in portfolio.project_rankings
            if project.health.risk_level == "HIGH" or any(action.priority == "high" for action in project.health.required_actions)
        ][:6]
        arena_candidates = [
            self._build_attention_item(project, selected_codes, portfolio.comparison_trust)
            for project in portfolio.project_rankings
            if project.health.risk_level == "HIGH"
            or project.trust_indicator.status != "high"
            or (portfolio.comparison_trust.delta_ranking_enabled and self._delta_attention_score(project) > 0)
        ][:6]
        watch_items = [
            self._build_attention_item(project, selected_codes, portfolio.comparison_trust)
            for project in portfolio.project_rankings
            if project.health.risk_level == "MEDIUM" or project.health.tier == "watch"
        ][:6]
        readiness_status, readiness_summary = self._latest_release_posture()
        immediate_action_count = sum(
            1 for project in portfolio.project_rankings if any(action.priority == "high" for action in project.health.required_actions)
        )
        headline = ControlTowerHeadline(
            overall_posture=portfolio.overall_posture,
            intervention_count=len(intervention_required),
            high_risk_count=portfolio.risk_distribution.get("HIGH", 0),
            immediate_action_count=immediate_action_count,
            readiness_status=readiness_status,
            readiness_summary=readiness_summary,
            arena_candidate_count=len(arena_candidates),
        )
        material_changes_section = self._build_narrative_section(
            key="material-changes",
            label="What changed materially",
            title="Material Changes",
            items=[self._change_bullet(item) for item in top_attention[:4]],
            empty_summary="No material change is leading the current run.",
        )
        required_actions_section = self._build_narrative_section(
            key="required-actions",
            label="What requires action or decision now",
            title="Required Actions / Decisions",
            items=[self._action_bullet(item) for item in intervention_required[:4]],
            empty_summary="No immediate decision or action is leading the current run.",
        )
        rising_risks_section = self._build_narrative_section(
            key="rising-risks",
            label="Where risk is rising",
            title="Rising Risks / Watch Items",
            items=[self._risk_bullet(item) for item in top_attention if item.risk_level == "HIGH"][:4],
            empty_summary="No rising high-risk signal is leading the current run.",
        )
        watch_items_section = self._build_narrative_section(
            key="watch-items",
            label="Watch items",
            title="Watch Items",
            items=[self._change_bullet(item) for item in watch_items[:4]],
            empty_summary="No watch item is leading the current run.",
        )
        executive_scan = self._build_control_tower_scan_cards(
            headline=headline,
            comparison_trust=portfolio.comparison_trust,
            material_changes=material_changes_section,
            required_actions=required_actions_section,
            rising_risks=rising_risks_section,
            watch_items=watch_items_section,
        )
        meeting_scope_summary = self._arena_scope_summary(
            [project.canonical_project_code for project in operational_scope_projects],
            fallback_to_current_lead=not selected_codes and bool(portfolio.project_rankings),
        )
        return ControlTowerView(
            generated_at=portfolio.generated_at,
            headline=headline,
            comparison_trust=portfolio.comparison_trust,
            primary_project_answer=(
                self.build_project_command_view(portfolio.project_rankings[0], portfolio.comparison_trust)
                if portfolio.project_rankings
                else None
            ),
            executive_scan=executive_scan,
            material_changes_section=material_changes_section,
            required_actions_section=required_actions_section,
            rising_risks_section=rising_risks_section,
            watch_items_section=watch_items_section,
            domain_coverage=portfolio.domain_coverage,
            top_attention=top_attention,
            intervention_required=intervention_required,
            arena_candidates=arena_candidates,
            selected_arena_codes=selected_codes,
            arena_path=self._arena_path(selected_codes),
            arena_export_path=self._arena_path(selected_codes, export_mode=True),
            arena_artifact_path=self._arena_artifact_path(selected_codes),
            meeting_packet=self._build_meeting_packet_view(operational_scope_projects, meeting_scope_summary),
            action_queue=self._build_action_queue_view(operational_scope_projects, meeting_scope_summary),
            continuity=self._build_continuity_view(operational_scope_projects, meeting_scope_summary),
            secondary_links=[
                SecondarySurfaceLink(
                    label="Project Ledger",
                    path="/projects",
                    detail="Supporting drill-down for the full ranked list and comparison pages.",
                ),
                SecondarySurfaceLink(
                    label="Publish",
                    path="/publish",
                    detail="Review the latest command brief, clean artifact previews, and run history.",
                ),
                SecondarySurfaceLink(
                    label="Run History",
                    path="/runs",
                    detail="Audit prior exports, manifests, and runtime output roots.",
                ),
                SecondarySurfaceLink(
                    label="Diagnostics",
                    path="/diagnostics",
                    detail="Inspect release readiness, runtime artifacts, and environment provenance.",
                ),
            ],
        )

    def build_arena(self, selected_arena_codes: list[str] | None = None) -> ArenaView:
        portfolio = self.build_portfolio()
        explicit_selected_codes = self._normalize_selection(selected_arena_codes, portfolio.project_rankings)
        fallback_to_current_lead = not explicit_selected_codes and bool(portfolio.project_rankings)
        selected_codes = (
            explicit_selected_codes
            or ([portfolio.project_rankings[0].canonical_project_code] if fallback_to_current_lead else [])
        )
        project_lookup = {project.canonical_project_code: project for project in portfolio.project_rankings}
        items: list[ArenaItem] = []
        selected_projects: list[ProjectSnapshot] = []
        for index, code in enumerate(selected_codes):
            project = project_lookup.get(code)
            if project is None:
                continue
            selected_projects.append(project)
            command_view = self.build_project_command_view(project, portfolio.comparison_trust)
            items.append(
                ArenaItem(
                    canonical_project_code=project.canonical_project_code,
                    project_name=project.project_name,
                    domain=project.domain,
                    group="Professional Portfolio" if project.domain == "professional" else "Personal Operating Items",
                    posture=project.executive_summary,
                    headline=self._arena_headline(project, portfolio.comparison_trust),
                    risk_statement=self._arena_risk_statement(project),
                    why_it_matters_statement=self._arena_why_it_matters(project),
                    action_statement=self._arena_action_statement(project),
                    change_statement=self._arena_change_statement(project, portfolio.comparison_trust),
                    cause_statement=self._project_cause(project),
                    impact_statement=self._project_impact(project, portfolio.comparison_trust),
                    action_timing=self._project_action_timing(project),
                    schedule_signal=self._project_schedule_signal(project, portfolio.comparison_trust),
                    current_finish_date=project.delta.schedule.current_finish_date
                    or (project.schedule.finish_date if project.schedule else None),
                    finish_delta_days=project.delta.schedule.finish_date_movement_days,
                    finish_statement=self._project_finish_statement(project),
                    delta_statement=self._project_delta_statement(project),
                    finish_authority_state=command_view.finish_authority_state,
                    finish_source_label=command_view.finish_source_label,
                    finish_source_detail=command_view.finish_source_detail,
                    comparison_label=portfolio.comparison_trust.ranking_label,
                    comparison_detail=self._project_comparison_detail(project, portfolio.comparison_trust),
                    finish_driver=project.finish_driver,
                    change_intelligence=project.change_intelligence,
                    challenge_next=project.challenge_next,
                    metrics=self._arena_metrics(project),
                    evidence_points=self._arena_evidence(project),
                    move_up_path=self._arena_path(self._move_selection(selected_codes, code, -1)) if index > 0 else None,
                    move_down_path=self._arena_path(self._move_selection(selected_codes, code, 1))
                    if index < len(selected_codes) - 1
                    else None,
                    remove_path=self._arena_path([item for item in selected_codes if item != code]),
                    drilldown_path=f"/projects/{project.canonical_project_code}",
                    compare_path=f"/projects/{project.canonical_project_code}/compare",
                )
            )
        headline_posture = posture_text(selected_projects) if selected_projects else portfolio.overall_posture
        scope_summary = self._arena_scope_summary(selected_codes, fallback_to_current_lead=fallback_to_current_lead)
        selection_summary = self._arena_selection_summary(selected_codes, fallback_to_current_lead=fallback_to_current_lead)
        promotion_summary = (
            "No explicit Arena selection was stored. Control Tower is showing the current lead project for immediate finish review."
            if fallback_to_current_lead
            else "Agenda order follows the current Control Tower promotion sequence."
        )
        material_changes_section = self._build_narrative_section(
            key="material-changes",
            label="What changed",
            title="Material Changes",
            items=[self._arena_change_bullet(item) for item in items[:4]],
            empty_summary="No promoted item is in the meeting slate yet.",
        )
        why_it_matters_section = self._build_narrative_section(
            key="why-it-matters",
            label="Why it matters",
            title="Why It Matters",
            items=[self._arena_impact_bullet(item) for item in items[:4]],
            empty_summary="Why-it-matters narrative will appear once an item is promoted.",
        )
        required_actions_section = self._build_narrative_section(
            key="required-actions",
            label="What needs decision",
            title="Required Actions / Decisions",
            items=[self._arena_action_required_bullet(item) for item in items[:4]],
            empty_summary="No decision-ready item is currently selected.",
        )
        rising_risks_section = self._build_narrative_section(
            key="rising-risks",
            label="Rising risks",
            title="Rising Risks / Watch Items",
            items=[self._arena_risk_bullet(item) for item in items[:4]],
            empty_summary="No rising risk is leading the meeting slate.",
        )
        executive_scan = self._build_arena_scan_cards(
            headline_posture=headline_posture,
            material_changes=material_changes_section,
            why_it_matters=why_it_matters_section,
            required_actions=required_actions_section,
            rising_risks=rising_risks_section,
        )
        return ArenaView(
            generated_at=portfolio.generated_at,
            title="Arena",
            subtitle="Room-ready narrative surface for live reviews, screenshares, and executive handoffs.",
            export_title="Print / PDF view is presentation-only. Use the authoritative Markdown artifact for handoff.",
            export_path=self._arena_path(selected_codes, export_mode=True),
            artifact_title="Arena Executive Handoff",
            artifact_path=self._arena_artifact_path(selected_codes),
            scope_summary=scope_summary,
            selection_summary=selection_summary,
            promotion_summary=promotion_summary,
            headline_posture=headline_posture,
            project_answers=[
                self.build_project_command_view(project, portfolio.comparison_trust) for project in selected_projects
            ],
            executive_scan=executive_scan,
            material_changes_section=material_changes_section,
            why_it_matters_section=why_it_matters_section,
            required_actions_section=required_actions_section,
            rising_risks_section=rising_risks_section,
            comparison_trust=portfolio.comparison_trust,
            items=items,
            selected_arena_codes=selected_codes,
            meeting_packet=self._build_meeting_packet_view(selected_projects, scope_summary),
            action_queue=self._build_action_queue_view(selected_projects, scope_summary),
            continuity=self._build_continuity_view(selected_projects, scope_summary),
            empty_state=(
                "No projects are currently available for Arena."
                if not portfolio.project_rankings
                else "No explicit Arena selection was stored. Control Tower is showing the current lead project for immediate finish review."
            ),
        )

    def build_arena_export_artifact(self, selected_arena_codes: list[str] | None = None) -> tuple[ArenaView, str, str]:
        arena = self.build_arena(selected_arena_codes)
        filename = self._arena_artifact_filename(arena.selected_arena_codes)
        body = render_arena_export_artifact(arena)
        return arena, filename, body

    def build_runtime_coherence_snapshot(self, selected_arena_codes: list[str] | None = None) -> dict[str, object]:
        projects, comparison_trust = self._build_ranked_projects()
        current_projects = [(project.identity, project.schedule, project.financial) for project in projects]
        comparison_record = select_comparison_run_record(self.config.runtime.state_root, current_projects)
        history = load_run_history(self.config.runtime.state_root)
        latest_record = history[0] if history else None
        selected_codes = self._normalize_selection(selected_arena_codes, projects)
        arena = self.build_arena(selected_codes)
        status_counts = {
            "trusted": sum(1 for project in projects if project.comparison_status == "trusted"),
            "contained": sum(1 for project in projects if project.comparison_status == "contained"),
            "unavailable": sum(1 for project in projects if project.comparison_status == "unavailable"),
        }
        return {
            "generated_at": arena.generated_at,
            "comparison_trust": comparison_trust.model_dump(mode="json"),
            "comparison_run_id": comparison_record.run_id if comparison_record else None,
            "comparison_run_matches_surface": (comparison_record.run_id if comparison_record else None) == comparison_trust.comparison_run_id,
            "delta_ranking_consistent_with_baseline": comparison_trust.delta_ranking_enabled == bool(comparison_record),
            "latest_run_id": latest_record.run_id if latest_record else None,
            "latest_run_matches_current": record_matches_current(latest_record, current_projects) if latest_record else False,
            "no_distinct_prior_baseline": comparison_trust.reason_code == "no_distinct_prior_run",
            "contained_blocks_authoritative_delta": not (
                comparison_trust.reason_code == "no_distinct_prior_run" and comparison_trust.delta_ranking_enabled
            ),
            "ranking_authority": comparison_trust.ranking_authority,
            "selected_arena_codes": list(arena.selected_arena_codes),
            "arena_item_codes": [item.canonical_project_code for item in arena.items],
            "arena_export_path": arena.export_path,
            "arena_artifact_path": arena.artifact_path,
            "project_comparison_status_counts": status_counts,
        }

    def build_notes(self, project_code: str | None = None) -> tuple[PortfolioSummary, list]:
        portfolio = self.build_portfolio()
        projects = portfolio.project_rankings
        if project_code:
            projects = [project for project in portfolio.project_rankings if project.canonical_project_code == project_code]
        notes = [render_portfolio_summary(portfolio, self.config.obsidian)]
        for project in projects:
            notes.append(render_project_dossier(project, self.config.obsidian, portfolio.generated_at))
            notes.append(render_project_weekly_brief(project, self.config.obsidian, portfolio.generated_at))
        return portfolio, notes

    def export_notes(self, *, preview_only: bool, project_code: str | None = None) -> ExportRecord:
        portfolio, notes = self.build_notes(project_code=project_code)
        issues = self.validate_sources()
        previous_record = load_previous_run_record(self.config.runtime.state_root)
        selected_projects = portfolio.project_rankings
        if project_code:
            selected_projects = [project for project in portfolio.project_rankings if project.canonical_project_code == project_code]
        return write_export_bundle(
            run_id=portfolio.generated_at.replace(":", "-"),
            generated_at=portfolio.generated_at,
            notes=notes,
            vault_root=self.config.obsidian.vault_root,
            state_root=self.config.runtime.state_root,
            preview_only=preview_only,
            timestamped_weekly_notes=self.config.obsidian.timestamped_weekly_notes,
            exports_folder=self.config.obsidian.exports_folder,
            source_artifacts=portfolio.provenance,
            issues=issues,
            previous_run_id=previous_record.run_id if previous_record else None,
            portfolio_snapshot=portfolio,
            project_snapshots=selected_projects,
            project_deltas=[ProjectDelta(project_id=project.canonical_project_id, delta=project.delta) for project in selected_projects],
        )

    def build_publish_view(
        self,
        *,
        run_id: str | None = None,
        artifact_id: str | None = None,
        project_code: str | None = None,
    ) -> PublishView:
        history = self.list_runs()
        if not history:
            return PublishView(history=[])

        selected_record = history[0]
        if run_id:
            selected_record = next((record for record in history if record.run_id == run_id), None)
            if selected_record is None:
                raise KeyError(run_id)

        comparison_trust = (
            selected_record.portfolio_snapshot.comparison_trust
            if selected_record.portfolio_snapshot
            else self.build_portfolio().comparison_trust
        )
        selected_project = (
            next(
                (
                    project
                    for project in selected_record.project_snapshots
                    if project.canonical_project_code == project_code
                ),
                None,
            )
            if project_code
            else None
        )
        lead_project = selected_project or (selected_record.project_snapshots[0] if selected_record.project_snapshots else None)
        command_brief = self.build_project_command_view(lead_project, comparison_trust) if lead_project else None
        command_status_label, command_status_class = self._publish_command_status(command_brief)
        comparison_record = self._publish_comparison_record(selected_record, history)
        comparison_project = (
            self._publish_record_project(comparison_record, lead_project.canonical_project_code)
            if comparison_record and lead_project
            else None
        )
        continuity = self._build_publish_continuity(lead_project, comparison_project, comparison_record)
        artifacts = self._build_publish_artifacts(
            selected_record,
            artifact_id=artifact_id,
            lead_project=lead_project,
            latest_run_id=history[0].run_id,
            comparison_record=comparison_record,
            previous_project=comparison_project,
        )
        selected_artifact = next((item for item in artifacts if item.is_selected), artifacts[0] if artifacts else None)
        history_items = self._build_publish_history(
            history,
            focus_project=lead_project,
            selected_artifact=selected_artifact,
        )
        return PublishView(
            available=True,
            run_id=selected_record.run_id,
            generated_at=selected_record.generated_at,
            status=selected_record.status,
            preview_only=selected_record.preview_only,
            command_brief=command_brief,
            command_status_label=command_status_label,
            command_status_class=command_status_class,
            command_brief_copy_text=self._publish_brief_copy_text(command_brief),
            comparison_summary_lines=continuity.detail_lines or [continuity.summary],
            continuity=continuity,
            arena_path=self._publish_arena_path(command_brief),
            present_path=self._publish_present_path(
                selected_record.run_id,
                lead_project.canonical_project_code if lead_project else None,
            ),
            print_path=self._publish_surface_path(selected_record.run_id, selected_artifact.artifact_id if selected_artifact else None, print_mode=True),
            latest_artifact_path=selected_artifact.open_path if selected_artifact else None,
            obsidian_artifact_path=selected_artifact.obsidian_url if selected_artifact else None,
            exports_debug_path="/exports/latest",
            selected_artifact=selected_artifact,
            artifacts=artifacts,
            project_switches=self._build_publish_project_switches(selected_record, lead_project, selected_artifact),
            history=history_items,
        )

    def list_runs(self) -> list[ExportRecord]:
        return load_run_history(self.config.runtime.state_root)

    def get_run(self, run_id: str) -> ExportRecord | None:
        return load_run_record(self.config.runtime.state_root, run_id)

    def get_publish_artifact_markdown(self, run_id: str, artifact_id: str) -> tuple[str, str] | None:
        record = self.get_run(run_id)
        if record is None:
            return None
        for note in record.notes:
            current_id = self._publish_artifact_id(note.note_kind, note.canonical_project_code, note.title)
            if current_id == artifact_id:
                filename = f"{current_id}.md"
                return (filename, note.body)
        return None

    def get_project_compare(self, project_code: str) -> dict[str, object] | None:
        projects, comparison_trust = self._build_ranked_projects()
        current = next((item for item in projects if item.canonical_project_code == project_code), None)
        if current is None:
            return None
        previous_record = select_comparison_run_record(
            self.config.runtime.state_root,
            [(project.identity, project.schedule, project.financial) for project in projects],
        )
        previous_project = None
        if previous_record:
            previous_project = next(
                (item for item in previous_record.project_snapshots if item.canonical_project_id == current.canonical_project_id),
                None,
            )
        return {
            "current": current,
            "previous": previous_project,
            "previous_run_id": previous_record.run_id if previous_record else None,
            "comparison_trust": comparison_trust,
        }

    def _build_ranked_projects(self) -> tuple[list[ProjectSnapshot], ComparisonTrust]:
        merged_entries = self._merge_projects()
        current_projects = [(entry["identity"], entry.get("schedule"), entry.get("financial")) for entry in merged_entries]
        comparison_trust = describe_comparison_trust(self.config.runtime.state_root, current_projects)
        previous_record = select_comparison_run_record(self.config.runtime.state_root, current_projects)
        previous_projects = index_projects_by_id(previous_record)
        project_deltas = {
            item.project_id: item.delta
            for item in compute_project_deltas(
                current_projects,
                previous_projects,
            )
        }

        projects: list[ProjectSnapshot] = []
        for entry in merged_entries:
            identity: ProjectIdentity = entry["identity"]
            schedule = entry.get("schedule")
            financial = entry.get("financial")
            previous_project = previous_projects.get(identity.canonical_project_id)
            delta = project_deltas[identity.canonical_project_id]
            health, issues, actions, changes, executive_summary, trust, missing = assess_project_health(
                project_name=identity.project_name,
                schedule=schedule,
                financial=financial,
                delta=delta,
            )
            provenance: list[SourceArtifactRef] = []
            if schedule:
                provenance.extend(schedule.provenance)
            if financial:
                provenance.extend(financial.provenance)
            snapshot_timestamp = (
                (schedule.run_timestamp if schedule and schedule.run_timestamp else None)
                or (financial.snapshot_timestamp if financial and financial.snapshot_timestamp else None)
                or utc_now_iso()
            )
            source_project_keys = dict(entry["source_project_keys"])
            source_keys = sorted(entry["source_keys"])
            comparison_status = "trusted" if previous_project else ("unavailable" if comparison_trust.status == "trusted" else comparison_trust.status)
            snapshot = ProjectSnapshot(
                identity=identity.model_copy(update={"source_keys": source_keys}),
                canonical_project_id=identity.canonical_project_id,
                canonical_project_code=identity.canonical_project_code,
                project_name=identity.project_name,
                domain=self._classify_domain(source_keys),
                source_keys=source_keys,
                source_project_keys=source_project_keys,
                snapshot_timestamp=snapshot_timestamp,
                schedule=schedule,
                financial=financial,
                delta=delta,
                health=health,
                top_issues=issues,
                recommended_actions=actions,
                latest_notable_changes=changes,
                executive_summary=executive_summary,
                provenance=provenance,
                missing_data_flags=missing,
                trust_indicator=trust,
                comparison_status=comparison_status,
                comparison_run_id=previous_record.run_id if previous_project and previous_record else None,
            )
            finish_driver = self._build_finish_driver_summary(snapshot, previous_project)
            finish_driver_investigation = self._build_finish_driver_investigation(snapshot, previous_project, finish_driver)
            driver_change_investigation = self._build_driver_change_investigation(
                snapshot,
                previous_project,
                finish_driver,
                finish_driver_investigation,
            )
            change_intelligence = self._build_change_intelligence(snapshot, previous_project, finish_driver)
            materialized_snapshot = snapshot.model_copy(
                update={
                    "finish_driver": finish_driver,
                    "finish_driver_investigation": finish_driver_investigation,
                    "driver_change_investigation": driver_change_investigation,
                    "change_intelligence": change_intelligence,
                    "challenge_next": self._build_challenge_next(snapshot, finish_driver, change_intelligence),
                }
            )
            action_queue = self._build_action_queue(materialized_snapshot, previous_project)
            continuity = self._build_project_continuity(materialized_snapshot, previous_project, action_queue)
            meeting_packet = self._build_project_meeting_packet(materialized_snapshot, comparison_trust, action_queue)
            projects.append(
                materialized_snapshot.model_copy(
                    update={
                        "action_queue": action_queue,
                        "continuity": continuity,
                        "meeting_packet": meeting_packet,
                    }
                )
            )

        ranked_projects = sorted(
            projects,
            key=lambda item: (-self._attention_score(item, comparison_trust), item.health.health_score, item.project_name),
        )
        result: list[ProjectSnapshot] = []
        for rank, project in enumerate(ranked_projects, start=1):
            result.append(
                project.model_copy(
                    update={
                        "attention_rank": rank,
                        "attention_score": self._attention_score(project, comparison_trust),
                    }
                )
            )
        return result, comparison_trust

    def _merge_projects(self) -> list[dict]:
        schedule_projects = self.schedulelab.list_projects()
        financial_projects = self.profitintel.list_projects()
        merged: dict[str, dict] = {}

        for schedule in schedule_projects:
            identity = self.identity_registry.resolve("schedulelab", schedule.project_code, schedule.project_name)
            bucket = merged.setdefault(
                identity.canonical_project_id,
                {
                    "identity": identity,
                    "schedule": None,
                    "financial": None,
                    "source_keys": set(identity.source_keys),
                    "source_project_keys": {},
                },
            )
            bucket["schedule"] = schedule
            bucket["source_keys"].add(f"schedulelab:{schedule.project_code}")
            bucket["source_project_keys"]["schedulelab"] = schedule.project_code
            bucket["identity"] = _merge_identity(bucket["identity"], identity)

        for financial in financial_projects:
            identity = self.identity_registry.resolve("profitintel", financial.project_slug, financial.project_slug)
            bucket = merged.setdefault(
                identity.canonical_project_id,
                {
                    "identity": identity,
                    "schedule": None,
                    "financial": None,
                    "source_keys": set(identity.source_keys),
                    "source_project_keys": {},
                },
            )
            bucket["financial"] = financial
            bucket["source_keys"].add(f"profitintel:{financial.project_slug}")
            bucket["source_project_keys"]["profitintel"] = financial.project_slug
            bucket["identity"] = _merge_identity(bucket["identity"], identity)

        return [merged[key] for key in sorted(merged.keys())]

    def _cross_project_risk_themes(self, projects: list[ProjectSnapshot]) -> list[str]:
        theme_counts: dict[str, int] = {}
        for project in projects:
            labels = [issue.label for issue in project.top_issues[:4]]
            for label in labels:
                theme_counts[label] = theme_counts.get(label, 0) + 1
        ranked = sorted(theme_counts.items(), key=lambda item: (-item[1], item[0]))
        return [f"{label} ({count})" for label, count in ranked[:5]]

    def _portfolio_changes(self, projects: list[ProjectSnapshot], comparison_trust: ComparisonTrust) -> list[str]:
        if not comparison_trust.delta_ranking_enabled:
            return [f"{project.canonical_project_code}: {self._project_change(project, comparison_trust)}" for project in projects[:5]]
        return [
            f"{project.canonical_project_code}: {self._project_change(project, comparison_trust)}"
            for project in projects
            if project.delta.summary and "baseline established" not in project.delta.summary.lower()
        ][:8]

    def _domain_coverage(self, projects: list[ProjectSnapshot]) -> list[DomainCoverage]:
        professional_count = sum(1 for project in projects if project.domain == "professional")
        personal_count = sum(1 for project in projects if project.domain == "personal")
        return [
            DomainCoverage(
                domain="professional",
                label="Professional / Project Control",
                available=professional_count > 0,
                item_count=professional_count,
                detail=(
                    "Current adapters cover schedule, cost, profit, and release posture."
                    if professional_count
                    else "No professional project-control entities resolved in the current run."
                ),
            ),
            DomainCoverage(
                domain="personal",
                label="Personal Operating Items",
                available=personal_count > 0,
                item_count=personal_count,
                detail=(
                    "Personal operating items are active in the current run."
                    if personal_count
                    else "Personal domain is not yet backed by a current adapter in this build, so Control Tower shows a bounded fallback state."
                ),
            ),
        ]

    def _build_finish_driver_summary(
        self,
        project: ProjectSnapshot,
        previous_project: ProjectSnapshot | None,
    ) -> FinishDriverSummary:
        current = self._driver_fact(project)
        if project.comparison_status != "trusted" or previous_project is None:
            return FinishDriverSummary(
                controlling_driver=current["label"],
                driver_type=current["driver_type"],
                why_it_matters=current["why"],
                comparison_state="unavailable",
                comparison_label="No trusted prior driver comparison available",
                comparison_detail="No trusted prior driver comparison is available for this project.",
            )
        previous = self._driver_fact(previous_project)
        if current["comparison_key"] is None or previous["comparison_key"] is None:
            return FinishDriverSummary(
                controlling_driver=current["label"],
                driver_type=current["driver_type"],
                why_it_matters=current["why"],
                comparison_state="unavailable",
                comparison_label="No trusted prior driver comparison available",
                comparison_detail="A trusted prior run exists, but one side does not expose a deterministic driver signal.",
                previous_driver=previous["label"],
            )
        if current["comparison_key"] == previous["comparison_key"]:
            return FinishDriverSummary(
                controlling_driver=current["label"],
                driver_type=current["driver_type"],
                why_it_matters=current["why"],
                comparison_state="same",
                comparison_label="Same driver as prior trusted run",
                comparison_detail="The controlling finish driver matches the prior trusted run.",
                previous_driver=previous["label"],
            )
        return FinishDriverSummary(
            controlling_driver=current["label"],
            driver_type=current["driver_type"],
            why_it_matters=current["why"],
            comparison_state="changed",
            comparison_label="Changed controlling driver",
            comparison_detail=f"Controlling driver changed from {previous['label']}.",
            previous_driver=previous["label"],
        )

    def _build_change_intelligence(
        self,
        project: ProjectSnapshot,
        previous_project: ProjectSnapshot | None,
        finish_driver: FinishDriverSummary,
    ) -> ChangeIntelligenceSummary:
        movement = project.delta.schedule.finish_date_movement_days
        if movement is None:
            finish_answer = ChangeAnswer(
                state="unavailable",
                label="Finish movement unavailable",
                detail=self._project_delta_reason(project),
            )
        elif movement == 0:
            finish_answer = ChangeAnswer(
                state="unchanged",
                label="Finish did not move",
                detail="Projected finish held flat versus the prior trusted run.",
            )
        else:
            finish_answer = ChangeAnswer(
                state="changed",
                label="Finish moved",
                detail=f"Projected finish moved {self._project_delta_label(project)} versus the prior trusted run.",
            )

        if finish_driver.comparison_state == "same":
            driver_answer = ChangeAnswer(
                state="unchanged",
                label="Driver did not change",
                detail=finish_driver.comparison_detail,
            )
        elif finish_driver.comparison_state == "changed":
            driver_answer = ChangeAnswer(
                state="changed",
                label="Driver changed",
                detail=finish_driver.comparison_detail,
            )
        else:
            driver_answer = ChangeAnswer(
                state="unavailable",
                label="Driver comparison unavailable",
                detail=finish_driver.comparison_detail,
            )

        if project.comparison_status != "trusted" or previous_project is None:
            risk_answer = ChangeAnswer(
                state="unavailable",
                label="New risk comparison unavailable",
                detail="No trusted prior risk comparison is available.",
            )
            action_answer = ChangeAnswer(
                state="unavailable",
                label="Action comparison unavailable",
                detail="No trusted prior action comparison is available.",
            )
        else:
            if project.delta.risk.new_risks:
                risk_answer = ChangeAnswer(
                    state="changed",
                    label="New risk introduced",
                    detail="New risk signals: " + ", ".join(project.delta.risk.new_risks[:3]).replace("_", " ") + ".",
                )
            else:
                risk_answer = ChangeAnswer(
                    state="unchanged",
                    label="No new risk introduced",
                    detail="No new deterministic risk signal appeared versus the prior trusted run.",
                )

            current_action = self._action_signature(project)
            previous_action = self._action_signature(previous_project)
            if current_action and previous_action and current_action != previous_action:
                action_answer = ChangeAnswer(
                    state="changed",
                    label="Action changed",
                    detail=f"Primary action changed from {previous_action} to {current_action}.",
                )
            elif current_action and previous_action:
                action_answer = ChangeAnswer(
                    state="unchanged",
                    label="Action did not change",
                    detail="Primary required action matches the prior trusted run.",
                )
            else:
                action_answer = ChangeAnswer(
                    state="unavailable",
                    label="Action comparison unavailable",
                    detail="A trusted prior run exists, but one side does not expose a primary required action.",
                )

        return ChangeIntelligenceSummary(
            finish=finish_answer,
            driver=driver_answer,
            risk=risk_answer,
            action=action_answer,
        )

    def _build_challenge_next(
        self,
        project: ProjectSnapshot,
        finish_driver: FinishDriverSummary,
        change_intelligence: ChangeIntelligenceSummary,
    ) -> str | None:
        if finish_driver.comparison_state == "changed" and finish_driver.previous_driver:
            return (
                "Challenge why the controlling driver shifted from "
                f"{finish_driver.previous_driver} to {finish_driver.controlling_driver}."
            )
        if project.schedule and (project.schedule.cycle_count or 0) > 0 and project.delta.schedule.finish_date_movement_days == 0:
            return "Challenge why cycles remain unresolved despite no finish movement."
        if project.health.risk_level == "HIGH" and project.delta.schedule.finish_date_movement_days == 0:
            return "Challenge why high risk persists while finish remains flat."
        if (
            change_intelligence.risk.state == "changed"
            and project.delta.schedule.finish_date_movement_days == 0
            and project.delta.risk.new_risks
        ):
            return "Challenge why new risk signals appeared while finish remained flat."
        return None

    def _build_finish_driver_investigation(
        self,
        project: ProjectSnapshot,
        previous_project: ProjectSnapshot | None,
        finish_driver: FinishDriverSummary,
    ) -> FinishDriverInvestigation:
        current_driver = self._build_finish_driver_detail(project)
        if project.comparison_status != "trusted" or previous_project is None:
            return FinishDriverInvestigation(
                current_driver=current_driver,
                prior_driver_presence=self._panel_value_unavailable("No trusted prior run is available for this project."),
                replacement_detail=self._panel_value_unavailable(
                    "No trusted prior driver comparison is available for this project."
                ),
                comparison_summary=finish_driver.comparison_detail,
            )

        current_fact = self._driver_fact(project)
        previous_fact = self._driver_fact(previous_project)
        comparison_reason = "A trusted prior run exists, but one side does not expose a deterministic driver signal."
        if current_fact["comparison_key"] is None or previous_fact["comparison_key"] is None:
            return FinishDriverInvestigation(
                current_driver=current_driver,
                prior_driver_presence=self._panel_value_unavailable(comparison_reason),
                replacement_detail=self._panel_value_unavailable(comparison_reason),
                comparison_summary=finish_driver.comparison_detail,
            )

        if current_fact["comparison_key"] == previous_fact["comparison_key"]:
            return FinishDriverInvestigation(
                current_driver=current_driver,
                prior_driver_presence=self._panel_value(
                    "Yes. The same controlling driver was present in the prior trusted run."
                ),
                replacement_detail=self._panel_value("Not replaced. The same driver still controls finish."),
                comparison_summary=finish_driver.comparison_detail,
            )

        was_present_before = self._driver_present_in_project(current_fact, previous_project)
        if was_present_before:
            prior_presence = self._panel_value(
                f"Yes, but not as the controlling driver. Prior controlling driver was {previous_fact['label']}."
            )
        else:
            prior_presence = self._panel_value(f"No. Prior controlling driver was {previous_fact['label']}.")

        return FinishDriverInvestigation(
            current_driver=current_driver,
            prior_driver_presence=prior_presence,
            replacement_detail=self._panel_value(
                f"It replaced {previous_fact['label']} as the controlling finish driver."
            ),
            comparison_summary=finish_driver.comparison_detail,
        )

    def _build_driver_change_investigation(
        self,
        project: ProjectSnapshot,
        previous_project: ProjectSnapshot | None,
        finish_driver: FinishDriverSummary,
        finish_driver_investigation: FinishDriverInvestigation,
    ) -> DriverChangeInvestigation:
        current_driver = finish_driver_investigation.current_driver
        if finish_driver.comparison_state != "changed" or project.comparison_status != "trusted" or previous_project is None:
            return DriverChangeInvestigation(
                available=False,
                reason=finish_driver.comparison_detail,
                difference_summary=finish_driver.comparison_detail,
                current_driver=current_driver,
                prior_driver=(
                    self._build_finish_driver_detail(previous_project) if previous_project is not None else FinishDriverDetail()
                ),
            )

        prior_driver = self._build_finish_driver_detail(previous_project)
        if prior_driver.driver_type == current_driver.driver_type:
            type_summary = f"Driver type remained {current_driver.driver_type.replace('_', ' ')}."
        else:
            type_summary = (
                "Driver type shifted from "
                f"{prior_driver.driver_type.replace('_', ' ')} to {current_driver.driver_type.replace('_', ' ')}."
            )
        difference_summary = " ".join(
            part
            for part in (
                f"Prior trusted run driver: {prior_driver.driver_label}.",
                f"Current run driver: {current_driver.driver_label}.",
                type_summary,
                finish_driver_investigation.prior_driver_presence.value
                if finish_driver_investigation.prior_driver_presence.available
                else None,
            )
            if part
        )
        return DriverChangeInvestigation(
            available=True,
            reason="Driver changed versus the prior trusted run.",
            difference_summary=difference_summary,
            current_driver=current_driver,
            prior_driver=prior_driver,
        )

    def _build_finish_driver_detail(self, project: ProjectSnapshot) -> FinishDriverDetail:
        fact = self._driver_fact(project)
        schedule = project.schedule
        activity_reason = (
            "No published schedule artifact is available for this project."
            if schedule is None
            else "This controlling signal is derived from a schedule condition, not a single activity record."
        )
        if fact["driver_type"] == "activity":
            activity_reason = "The published driver activity does not expose a deterministic activity ID or name."
        elif fact["driver_type"] == "milestone":
            activity_reason = "The published finish milestone signal does not expose a deterministic activity ID or name."
        return FinishDriverDetail(
            driver_label=str(fact["label"] or "Driver unavailable"),
            driver_type=str(fact["driver_type"] or "unknown"),
            activity_id=(
                self._panel_value(str(fact["activity_id"]))
                if fact["activity_id"]
                else self._panel_value_unavailable(activity_reason)
            ),
            activity_name=(
                self._panel_value(str(fact["activity_name"]))
                if fact["activity_name"]
                else self._panel_value_unavailable(activity_reason)
            ),
            why_controlling_finish=str(fact["why"] or "No published finish-driver signal is available for this project."),
            float_signal=self._driver_float_signal(project),
            constraint_signal=self._driver_constraint_signal(project),
            sequence_context=self._driver_sequence_context(project, fact),
        )

    def _driver_fact(self, project: ProjectSnapshot) -> dict[str, object | None]:
        schedule = project.schedule
        if schedule is None:
            return {
                "label": "Driver unavailable",
                "driver_type": "unknown",
                "why": "No published schedule artifact is available for this project.",
                "comparison_key": None,
                "activity_id": None,
                "activity_name": None,
                "driver_score": None,
                "driver_rank": None,
            }
        if schedule.top_drivers:
            driver = schedule.top_drivers[0]
            why = self._sentence_from_parts(
                [
                    driver.rationale or "This is the top published ScheduleLab driver activity.",
                    "It is the leading finish-driving path signal in the current run",
                ]
            )
            return {
                "label": driver.label or "Published driver activity",
                "driver_type": "activity",
                "why": why,
                "comparison_key": f"activity:{driver.label or ''}",
                "activity_id": driver.activity_id,
                "activity_name": driver.activity_name,
                "driver_score": driver.score,
                "driver_rank": 1,
            }
        if (schedule.cycle_count or 0) > 0:
            count = schedule.cycle_count or 0
            return {
                "label": f"{count} schedule cycle(s)",
                "driver_type": "cycle",
                "why": f"{count} cycle(s) remain in the published logic, so the finish path cannot be defended until the loop is removed.",
                "comparison_key": f"cycle:{count}",
                "activity_id": None,
                "activity_name": None,
                "driver_score": None,
                "driver_rank": None,
            }
        if (schedule.negative_float_count or 0) > 0:
            count = schedule.negative_float_count or 0
            return {
                "label": f"{count} activity(ies) with negative float",
                "driver_type": "float_issue",
                "why": f"{count} activity(ies) still carry negative float, which is constraining the current finish path.",
                "comparison_key": f"float_issue:{count}",
                "activity_id": None,
                "activity_name": None,
                "driver_score": None,
                "driver_rank": None,
            }
        open_ends = (schedule.open_start_count or 0) + (schedule.open_finish_count or 0)
        if open_ends > 0:
            return {
                "label": f"{open_ends} open-end condition(s)",
                "driver_type": "open_end",
                "why": f"{open_ends} open-end condition(s) remain, leaving finish-driving logic incomplete.",
                "comparison_key": f"open_end:{open_ends}",
                "activity_id": None,
                "activity_name": None,
                "driver_score": None,
                "driver_rank": None,
            }
        if schedule.finish_source == "published_milestone_drift_log" or schedule.finish_activity_name or schedule.finish_activity_id:
            label = self._finish_activity_label(schedule)
            return {
                "label": label,
                "driver_type": "milestone",
                "why": "The current finish is being taken from the published finish milestone signal.",
                "comparison_key": f"milestone:{label}",
                "activity_id": schedule.finish_activity_id,
                "activity_name": schedule.finish_activity_name,
                "driver_score": None,
                "driver_rank": None,
            }
        return {
            "label": "Driver unavailable",
            "driver_type": "unknown",
            "why": self._projected_finish_reason(project) or "No published finish-driver signal is available for this project.",
            "comparison_key": None,
            "activity_id": None,
            "activity_name": None,
            "driver_score": None,
            "driver_rank": None,
        }

    def _finish_activity_label(self, schedule) -> str:
        parts = [part for part in [schedule.finish_activity_id, schedule.finish_activity_name] if part]
        if parts:
            return " - ".join(parts)
        return "Published finish milestone"

    def _panel_value(self, value: str) -> DeterministicPanelValue:
        return DeterministicPanelValue(value=value, available=True)

    def _panel_value_unavailable(self, reason: str) -> DeterministicPanelValue:
        return DeterministicPanelValue(value="not available", available=False, reason=reason)

    def _driver_float_signal(self, project: ProjectSnapshot) -> DeterministicPanelValue:
        schedule = project.schedule
        if schedule is None:
            return self._panel_value_unavailable("No published schedule artifact is available for this project.")
        if schedule.total_float_days is None:
            return self._panel_value_unavailable("The published schedule summary does not expose total float days.")
        return self._panel_value(f"{schedule.total_float_days:.1f} day(s) total float in the published schedule summary.")

    def _driver_constraint_signal(self, project: ProjectSnapshot) -> DeterministicPanelValue:
        schedule = project.schedule
        if schedule is None:
            return self._panel_value_unavailable("No published schedule artifact is available for this project.")
        parts: list[str] = []
        if (schedule.negative_float_count or 0) > 0:
            parts.append(f"{schedule.negative_float_count} negative-float activity(ies)")
        open_ends = (schedule.open_start_count or 0) + (schedule.open_finish_count or 0)
        if open_ends > 0:
            parts.append(f"{open_ends} open-end condition(s)")
        if (schedule.cycle_count or 0) > 0:
            parts.append(f"{schedule.cycle_count} cycle(s)")
        if parts:
            return self._panel_value("Published schedule constraints: " + "; ".join(parts) + ".")
        if schedule.risk_flags:
            return self._panel_value(
                "Published schedule flags: " + ", ".join(flag.replace("_", " ") for flag in schedule.risk_flags[:3]) + "."
            )
        return self._panel_value_unavailable(
            "The published schedule artifact does not expose an active constraint count for this driver."
        )

    def _driver_sequence_context(
        self,
        project: ProjectSnapshot,
        driver_fact: dict[str, object | None],
    ) -> DeterministicPanelValue:
        schedule = project.schedule
        if schedule is None:
            return self._panel_value_unavailable("No published schedule artifact is available for this project.")
        parts: list[str] = []
        if driver_fact["driver_type"] == "activity":
            total_drivers = schedule.top_driver_count or len(schedule.top_drivers)
            rank = driver_fact["driver_rank"]
            score = driver_fact["driver_score"]
            if rank and total_drivers:
                detail = f"Published as driver {rank} of {total_drivers}"
                if isinstance(score, float):
                    detail += f" with score {score:.1f}"
                parts.append(detail + ".")
        elif driver_fact["driver_type"] == "milestone" and schedule.finish_detail:
            parts.append(schedule.finish_detail.rstrip(".") + ".")
        if schedule.critical_path_activity_count is not None:
            parts.append(f"Critical path activity count: {schedule.critical_path_activity_count}.")
        if schedule.risk_path_count is not None:
            parts.append(f"Risk path count: {schedule.risk_path_count}.")
        if not parts:
            return self._panel_value_unavailable(
                "The published schedule artifact does not expose additional sequence context for this driver."
            )
        return self._panel_value(" ".join(parts))

    def _driver_present_in_project(
        self,
        driver_fact: dict[str, object | None],
        project: ProjectSnapshot,
    ) -> bool:
        schedule = project.schedule
        if schedule is None:
            return False
        driver_type = driver_fact["driver_type"]
        comparison_key = driver_fact["comparison_key"]
        if comparison_key is None:
            return False
        if driver_type == "activity":
            activity_id = str(driver_fact["activity_id"] or "")
            activity_name = str(driver_fact["activity_name"] or "")
            label = str(driver_fact["label"] or "")
            return any(
                (
                    activity_id
                    and driver.activity_id
                    and driver.activity_id == activity_id
                )
                or (
                    activity_name
                    and driver.activity_name
                    and driver.activity_name == activity_name
                )
                or driver.label == label
                for driver in schedule.top_drivers
            )
        if driver_type == "milestone":
            return (
                str(driver_fact["activity_id"] or "") != ""
                and schedule.finish_activity_id == driver_fact["activity_id"]
            ) or (
                str(driver_fact["activity_name"] or "") != ""
                and schedule.finish_activity_name == driver_fact["activity_name"]
            )
        if driver_type == "cycle":
            return (schedule.cycle_count or 0) > 0
        if driver_type == "float_issue":
            return (schedule.negative_float_count or 0) > 0
        if driver_type == "open_end":
            return ((schedule.open_start_count or 0) + (schedule.open_finish_count or 0)) > 0
        return False

    def _action_signature(self, project: ProjectSnapshot | None) -> str | None:
        if project is None or not project.health.required_actions:
            return None
        action = project.health.required_actions[0]
        return f"{action.owner_hint}: {action.action}"

    def _action_signatures(self, project: ProjectSnapshot | None) -> set[str]:
        if project is None:
            return set()
        return {f"{action.owner_hint}: {action.action}" for action in project.health.required_actions}

    def _issue_signature(self, issue) -> tuple[str, str, str]:
        return (issue.source, issue.label, issue.detail)

    def _project_status(self, project: ProjectSnapshot) -> tuple[str, str]:
        movement = project.delta.schedule.finish_date_movement_days
        if movement is None:
            return ("DELTA UNAVAILABLE", self._project_delta_reason(project))
        if movement > 0:
            return ("SLIPPING", f"Projected finish slipped by {movement} day(s) versus the prior trusted run.")
        if movement < 0:
            return ("RECOVERING", f"Projected finish improved by {abs(movement)} day(s) versus the prior trusted run.")
        return ("ON TRACK", "Projected finish held flat versus the prior trusted run.")

    def _project_supporting_evidence(self, project: ProjectSnapshot) -> list[str]:
        evidence: list[str] = []
        evidence.append(self._project_finish_statement(project))
        evidence.append(self._project_delta_statement(project))
        evidence.extend(f"{issue.label}: {issue.detail}" for issue in project.top_issues[:2])
        evidence.extend(change.summary for change in project.latest_notable_changes[:2])
        if project.schedule and project.schedule.finish_source_label:
            evidence.append(f"Finish source: {project.schedule.finish_source_label}. {self._project_finish_source_detail(project)}")
        evidence.extend(project.trust_indicator.rationale[:1])
        return [item for index, item in enumerate(evidence) if item and item not in evidence[:index]][:6]

    def _build_project_meeting_packet(
        self,
        project: ProjectSnapshot,
        comparison_trust: ComparisonTrust,
        action_queue: list[ActionQueueItem],
    ) -> MeetingPacketItem:
        status_label, status_detail = self._project_status(project)
        what_changed = [
            f"Finish: {project.change_intelligence.finish.detail}",
            f"Driver: {project.change_intelligence.driver.detail}",
            f"Risk: {project.change_intelligence.risk.detail}",
            f"Action: {project.change_intelligence.action.detail}",
        ]
        required_actions = [
            f"{item.owner_role} | {item.timing} | {item.action_text}"
            + (f" | {item.continuity_label}" if item.continuity_state != "comparison_unavailable" else "")
            for item in action_queue
        ] or ["No required action was emitted from deterministic signals."]
        return MeetingPacketItem(
            canonical_project_code=project.canonical_project_code,
            project_name=project.project_name,
            finish_statement=self._project_finish_statement(project),
            delta_statement=self._project_delta_statement(project),
            status_label=status_label,
            status_detail=status_detail,
            controlling_driver=project.finish_driver.controlling_driver,
            driver_reason=project.finish_driver.why_it_matters,
            what_changed=what_changed,
            challenge_next=project.challenge_next or "None emitted from deterministic signals.",
            required_actions=required_actions,
            supporting_evidence=self._project_supporting_evidence(project),
            trust_posture=self._comparison_label_for_project(project),
            baseline_posture=self._project_comparison_detail(project, comparison_trust),
            drilldown_path=f"/projects/{project.canonical_project_code}",
            compare_path=f"/projects/{project.canonical_project_code}/compare",
        )

    def _action_queue_id(self, project: ProjectSnapshot, owner_hint: str, action_text: str) -> str:
        base = f"{project.canonical_project_code}-{owner_hint}-{action_text}".lower()
        sanitized = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
        return sanitized[:96] or f"{project.canonical_project_code.lower()}-action"

    def _action_reason_signal(self, project: ProjectSnapshot, action) -> str:
        lowered = action.action.lower()
        schedule = project.schedule
        if schedule and "cycle" in lowered and (schedule.cycle_count or 0) > 0:
            return f"Circular schedule logic: {schedule.cycle_count} cycle(s) remain in the latest published schedule output."
        if schedule and ("open-end" in lowered or "successors and predecessors" in lowered):
            return (
                "Open-end exposure: "
                f"{schedule.open_start_count or 0} open starts and {schedule.open_finish_count or 0} open finishes remain."
            )
        if schedule and "parser warning" in lowered and (schedule.parser_warning_count or 0) > 0:
            return f"Parser warnings remain elevated at {schedule.parser_warning_count} warning(s)."
        if project.delta.schedule.finish_date_movement_days and "slippage" in lowered:
            return f"Finish date slippage: finish moved +{project.delta.schedule.finish_date_movement_days} day(s) versus the prior trusted run."
        if project.delta.schedule.critical_path_changed and ("critical-path" in lowered or "logic ties" in lowered):
            return "Critical-path signature changed from the prior trusted run."
        if project.delta.schedule.float_movement_days is not None and project.delta.schedule.float_movement_days < 0 and (
            "float compression" in lowered or "path" in lowered
        ):
            return (
                f"Float compression: total float compressed by {abs(project.delta.schedule.float_movement_days):.1f} day(s)"
                f" on {project.finish_driver.controlling_driver}."
            )
        if project.delta.financial.cost_variance_change is not None and project.delta.financial.cost_variance_change > 0 and (
            "budget drift" in lowered or "cost overrun" in lowered or "forecast" in lowered
        ):
            return f"Cost variance growth: cost variance worsened by ${project.delta.financial.cost_variance_change:,.0f} versus the prior run."
        if project.delta.financial.margin_movement is not None and project.delta.financial.margin_movement < 0 and "margin" in lowered:
            return f"Margin pressure: margin moved down {abs(project.delta.financial.margin_movement):.2f} pts versus the prior run."
        if project.delta.risk.new_risks and "risk" in lowered:
            return "New risk signals: " + ", ".join(project.delta.risk.new_risks[:4]).replace("_", " ") + "."
        if project.top_issues:
            lead_issue = project.top_issues[0]
            return f"{lead_issue.label}: {lead_issue.detail}"
        return project.delta.summary or project.executive_summary

    def _action_priority_basis(self, action, reason_source_signal: str) -> str | None:
        if action.priority is None:
            return None
        return f"Priority {action.priority.upper()} is derived from deterministic health rules because {reason_source_signal.rstrip('.')}."

    def _build_action_queue(
        self,
        project: ProjectSnapshot,
        previous_project: ProjectSnapshot | None,
    ) -> list[ActionQueueItem]:
        previous_signatures = self._action_signatures(previous_project)
        items: list[ActionQueueItem] = []
        for action in project.health.required_actions:
            signature = f"{action.owner_hint}: {action.action}"
            if project.comparison_status != "trusted" or previous_project is None:
                continuity_state = "comparison_unavailable"
                continuity_label = "Current-run only"
                continuity_detail = "No trusted prior action comparison is available for this project."
            elif signature in previous_signatures:
                continuity_state = "carry_forward"
                continuity_label = "Carry-forward"
                continuity_detail = "Action matched the prior trusted run and remains open in the current deterministic queue."
            else:
                continuity_state = "new_this_run"
                continuity_label = "New this run"
                continuity_detail = "Action did not appear in the prior trusted run and is newly surfaced this week."
            reason_source_signal = self._action_reason_signal(project, action)
            items.append(
                ActionQueueItem(
                    queue_id=self._action_queue_id(project, action.owner_hint, action.action),
                    canonical_project_code=project.canonical_project_code,
                    project_name=project.project_name,
                    owner_role=action.owner_hint,
                    action_text=action.action,
                    timing=self._action_timing_from_text(action.action, action.priority),
                    reason_source_signal=reason_source_signal,
                    priority=action.priority,
                    priority_basis=self._action_priority_basis(action, reason_source_signal),
                    continuity_state=continuity_state,
                    continuity_label=continuity_label,
                    continuity_detail=continuity_detail,
                    drilldown_path=f"/projects/{project.canonical_project_code}",
                    compare_path=f"/projects/{project.canonical_project_code}/compare",
                )
            )
        return items

    def _build_project_continuity(
        self,
        project: ProjectSnapshot,
        previous_project: ProjectSnapshot | None,
        action_queue: list[ActionQueueItem],
    ) -> ProjectContinuitySummary:
        if project.comparison_status != "trusted" or previous_project is None:
            return ProjectContinuitySummary(
                comparison_state=project.comparison_status,
                comparison_label="Current-run continuity only",
                comparison_detail="No trusted prior continuity baseline is available for this project.",
                new_action_count=0,
                carry_forward_action_count=0,
                resolved_item_count=0,
                resolved_items=[],
                summary="No trusted prior continuity baseline is available for this project.",
            )

        current_issue_signatures = {self._issue_signature(issue) for issue in project.top_issues}
        resolved_items: list[ContinuityResolvedItem] = []
        for issue in previous_project.top_issues:
            signature = self._issue_signature(issue)
            if signature in current_issue_signatures:
                continue
            resolved_items.append(
                ContinuityResolvedItem(
                    canonical_project_code=project.canonical_project_code,
                    project_name=project.project_name,
                    item_type="issue",
                    summary=issue.label,
                    detail=issue.detail,
                    resolution_basis="Previously surfaced in the prior trusted run and no longer present in the current deterministic issue set.",
                    compare_path=f"/projects/{project.canonical_project_code}/compare",
                )
            )
        new_count = sum(1 for item in action_queue if item.continuity_state == "new_this_run")
        carry_count = sum(1 for item in action_queue if item.continuity_state == "carry_forward")
        summary = (
            f"{new_count} new action(s), {carry_count} carry-forward action(s), and "
            f"{len(resolved_items)} previously surfaced issue(s) no longer present versus the prior trusted run."
        )
        return ProjectContinuitySummary(
            comparison_state=project.comparison_status,
            comparison_label="Trusted continuity comparison",
            comparison_detail="Continuity is compared against the prior trusted run for this project.",
            new_action_count=new_count,
            carry_forward_action_count=carry_count,
            resolved_item_count=len(resolved_items),
            resolved_items=resolved_items,
            summary=summary,
        )

    def _operational_scope_projects(
        self,
        projects: list[ProjectSnapshot],
        selected_codes: list[str],
        *,
        fallback_to_current_lead: bool,
    ) -> list[ProjectSnapshot]:
        project_lookup = {project.canonical_project_code: project for project in projects}
        selected_projects = [project_lookup[code] for code in selected_codes if code in project_lookup]
        if selected_projects:
            return selected_projects
        if fallback_to_current_lead and projects:
            return [projects[0]]
        return []

    def _build_meeting_packet_view(self, projects: list[ProjectSnapshot], scope_summary: str) -> MeetingPacketView:
        if not projects:
            return MeetingPacketView(
                summary="No meeting packet items are currently in scope.",
                item_count=0,
                items=[],
            )
        item_count = len(projects)
        return MeetingPacketView(
            summary=f"{scope_summary}. {self._count_phrase(item_count)} prepared in deterministic meeting order.",
            item_count=item_count,
            items=[project.meeting_packet for project in projects],
        )

    def _build_action_queue_view(self, projects: list[ProjectSnapshot], scope_summary: str) -> ActionQueueView:
        items = [action for project in projects for action in project.action_queue]
        if not items:
            return ActionQueueView(
                summary=f"{scope_summary}. No trackable actions were emitted from the current deterministic signals.",
                item_count=0,
                groups=[],
            )
        groups: list[ActionQueueGroup] = []
        for key, label, summary in (
            ("new_this_run", "New This Run", "Action did not appear in the prior trusted run."),
            ("carry_forward", "Carry-Forward", "Action remains open from the prior trusted run."),
            ("comparison_unavailable", "Current-Run Only", "No trusted prior action baseline is available for this item."),
        ):
            group_items = [item for item in items if item.continuity_state == key]
            if not group_items:
                continue
            groups.append(
                ActionQueueGroup(
                    key=key,
                    label=label,
                    summary=summary,
                    item_count=len(group_items),
                    items=group_items,
                )
            )
        return ActionQueueView(
            summary=f"{scope_summary}. {self._count_phrase(len(items))} ready for post-meeting tracking.",
            item_count=len(items),
            groups=groups,
        )

    def _build_continuity_view(self, projects: list[ProjectSnapshot], scope_summary: str) -> ContinuityView:
        if not projects:
            return ContinuityView(summary="No continuity scope is currently selected.")
        new_count = sum(project.continuity.new_action_count for project in projects)
        carry_count = sum(project.continuity.carry_forward_action_count for project in projects)
        resolved_items = [item for project in projects for item in project.continuity.resolved_items]
        trusted_count = sum(1 for project in projects if project.comparison_status == "trusted")
        if trusted_count == 0:
            return ContinuityView(
                summary=f"{scope_summary}. No trusted prior continuity baseline is available for the current scope.",
                comparison_label="Current-run continuity only",
                comparison_detail="Carry-forward and resolved counts are suppressed because no in-scope project has a trusted prior comparison.",
                new_action_count=0,
                carry_forward_action_count=0,
                resolved_item_count=0,
                resolved_items=[],
            )
        comparison_label = (
            "Trusted continuity comparison"
            if trusted_count == len(projects)
            else "Mixed continuity baseline"
        )
        comparison_detail = (
            "All in-scope projects are compared against their prior trusted run."
            if trusted_count == len(projects)
            else "Carry-forward and resolved counts apply only to projects with a trusted prior comparison; current-run-only projects remain explicitly bounded."
        )
        return ContinuityView(
            summary=(
                f"{scope_summary}. {new_count} new action(s), {carry_count} carry-forward action(s), and "
                f"{len(resolved_items)} previously surfaced issue(s) no longer present."
            ),
            comparison_label=comparison_label,
            comparison_detail=comparison_detail,
            new_action_count=new_count,
            carry_forward_action_count=carry_count,
            resolved_item_count=len(resolved_items),
            resolved_items=resolved_items,
        )

    def build_project_command_view(
        self,
        project: ProjectSnapshot,
        comparison_trust: ComparisonTrust,
    ) -> ProjectCommandView:
        return ProjectCommandView(
            canonical_project_code=project.canonical_project_code,
            project_name=project.project_name,
            projected_finish_date=self._current_finish_date(project),
            projected_finish_label=self._projected_finish_label(project),
            projected_finish_reason=self._projected_finish_reason(project),
            movement_days=project.delta.schedule.finish_date_movement_days,
            movement_label=self._project_delta_label(project),
            movement_reason=self._project_delta_reason(project),
            risk_level=project.health.risk_level,
            finish_authority_state=self._finish_authority_state(project),
            finish_source_label=project.schedule.finish_source_label if project.schedule else "No published schedule artifact",
            finish_source_detail=self._project_finish_source_detail(project),
            primary_issue=self._project_cause(project),
            action_owner=self._project_action_owner(project),
            action_summary=self._project_action(project),
            required_action=f"{self._project_action_owner(project)}: {self._project_action(project)}",
            action_timing=self._project_action_timing(project),
            trust_label=self._comparison_label_for_project(project),
            trust_detail=self._project_comparison_detail(project, comparison_trust),
            finish_driver=project.finish_driver,
            finish_driver_investigation=project.finish_driver_investigation,
            driver_change_investigation=project.driver_change_investigation,
            change_intelligence=project.change_intelligence,
            execution_brief=self.execution_brief_service.build(project, comparison_trust),
            challenge_next=project.challenge_next,
            drilldown_path=f"/projects/{project.canonical_project_code}",
        )

    def build_project_operational_views(
        self,
        project: ProjectSnapshot,
    ) -> tuple[MeetingPacketView, ActionQueueView, ContinuityView]:
        scope_summary = f"Project detail scope: {project.canonical_project_code}"
        return (
            self._build_meeting_packet_view([project], scope_summary),
            self._build_action_queue_view([project], scope_summary),
            self._build_continuity_view([project], scope_summary),
        )

    def _build_publish_artifacts(
        self,
        record: ExportRecord,
        *,
        artifact_id: str | None,
        lead_project: ProjectSnapshot | None,
        latest_run_id: str,
        comparison_record: ExportRecord | None,
        previous_project: ProjectSnapshot | None,
    ) -> list[PublishArtifactView]:
        preferred_id = artifact_id or self._default_publish_artifact_id(record, lead_project)
        ordered_notes = sorted(
            record.notes,
            key=lambda note: (
                self._publish_note_priority(note.note_kind, note.canonical_project_code == (lead_project.canonical_project_code if lead_project else None)),
                note.title.lower(),
            ),
        )
        artifacts: list[PublishArtifactView] = []
        for note in ordered_notes:
            note_artifact_id = self._publish_artifact_id(note.note_kind, note.canonical_project_code, note.title)
            frontmatter, _artifact_body = parse_markdown_frontmatter(note.body)
            cleaned_markdown = publishable_markdown(note.body)
            issue_state_label, issue_state_class, authority_label = self._publish_issue_state(
                is_latest=record.run_id == latest_run_id,
                preview_only=record.preview_only,
            )
            artifacts.append(
                PublishArtifactView(
                    artifact_id=note_artifact_id,
                    note_kind=note.note_kind,
                    artifact_type_label=self._publish_note_kind_label(note.note_kind),
                    title=note.title,
                    project_name=note.title.split(" - ", 1)[0] if note.canonical_project_code else None,
                    project_code=note.canonical_project_code,
                    generated_at=record.generated_at,
                    is_latest=record.run_id == latest_run_id,
                    is_selected=note_artifact_id == preferred_id,
                    issue_state_label=issue_state_label,
                    issue_state_class=issue_state_class,
                    authority_label=authority_label,
                    source_run_id=record.run_id,
                    preview_metadata=self._build_publish_artifact_preview_metadata(
                        note_title=note.title,
                        project_code=note.canonical_project_code,
                        generated_at=record.generated_at,
                        frontmatter=frontmatter,
                    ),
                    preview_html=render_publish_markdown_preview(note.body),
                    preview_summary=self._publish_artifact_summary(cleaned_markdown),
                    copy_text=cleaned_markdown,
                    open_path=self._publish_surface_path(record.run_id, note_artifact_id),
                    print_path=self._publish_surface_path(record.run_id, note_artifact_id, print_mode=True),
                    source_path=self._publish_source_path(record.run_id, note_artifact_id),
                    obsidian_url=self._publish_obsidian_url(note.output_path.as_posix()) if not record.preview_only else None,
                    continuity=self._build_publish_artifact_continuity(
                        note=note,
                        comparison_record=comparison_record,
                        current_project=lead_project,
                        previous_project=previous_project,
                    ),
                )
            )
        if artifacts and all(not item.is_selected for item in artifacts):
            artifacts[0] = artifacts[0].model_copy(update={"is_selected": True})
        return artifacts

    def _build_publish_history(
        self,
        history: list[ExportRecord],
        *,
        focus_project: ProjectSnapshot | None,
        selected_artifact: PublishArtifactView | None,
    ) -> list[PublishHistoryItem]:
        items: list[PublishHistoryItem] = []
        latest_run_id = history[0].run_id if history else None
        for record in history:
            issue_state_label, _issue_state_class, _authority_label = self._publish_issue_state(
                is_latest=record.run_id == latest_run_id,
                preview_only=record.preview_only,
            )
            selected_project = (
                self._publish_record_project(record, focus_project.canonical_project_code)
                if focus_project
                else (record.project_snapshots[0] if record.project_snapshots else None)
            )
            focused_artifact_id = self._publish_context_artifact_id(
                record,
                note_kind=selected_artifact.note_kind if selected_artifact else None,
                project_code=selected_project.canonical_project_code if selected_project else None,
            )
            default_artifact_id = self._default_publish_artifact_id(
                record,
                selected_project or (record.project_snapshots[0] if record.project_snapshots else None),
            )
            items.append(
                PublishHistoryItem(
                    run_id=record.run_id,
                    generated_at=record.generated_at,
                    status=record.status,
                    preview_only=record.preview_only,
                    is_latest=record.run_id == latest_run_id,
                    issue_state_label=issue_state_label,
                    focus_project_name=selected_project.project_name if selected_project else "Portfolio",
                    focus_project_code=selected_project.canonical_project_code if selected_project else None,
                    artifact_availability=self._publish_history_availability(record),
                    open_path=self._publish_surface_path(
                        record.run_id,
                        default_artifact_id,
                        project_code=selected_project.canonical_project_code if selected_project else None,
                    ),
                    latest_artifact_path=self._publish_surface_path(record.run_id, default_artifact_id) if default_artifact_id else None,
                    open_output_path=(
                        self._publish_surface_path(
                            record.run_id,
                            focused_artifact_id or default_artifact_id,
                            project_code=selected_project.canonical_project_code if selected_project else None,
                        )
                        if (focused_artifact_id or default_artifact_id)
                        else None
                    ),
                )
            )
        return items

    def _build_publish_project_switches(
        self,
        record: ExportRecord,
        selected_project: ProjectSnapshot | None,
        selected_artifact: PublishArtifactView | None,
    ) -> list[PublishProjectOption]:
        switches: list[PublishProjectOption] = []
        for project in record.project_snapshots:
            switches.append(
                PublishProjectOption(
                    canonical_project_code=project.canonical_project_code,
                    project_name=project.project_name,
                    is_selected=selected_project is not None
                    and project.canonical_project_code == selected_project.canonical_project_code,
                    open_path=self._publish_surface_path(
                        record.run_id,
                        selected_artifact.artifact_id if selected_artifact else None,
                        project_code=project.canonical_project_code,
                    ),
                )
            )
        return switches

    def _publish_command_status(self, command_brief: ProjectCommandView | None) -> tuple[str, str]:
        if command_brief is None or command_brief.movement_days is None:
            return ("DELTA UNAVAILABLE", "unknown")
        if command_brief.movement_days > 0:
            return ("SLIPPING", "slipping")
        if command_brief.movement_days < 0:
            return ("RECOVERING", "recovering")
        return ("ON TRACK", "on-track")

    def _publish_comparison_record(self, selected_record: ExportRecord, history: list[ExportRecord]) -> ExportRecord | None:
        if selected_record.previous_run_id:
            matched = next((record for record in history if record.run_id == selected_record.previous_run_id), None)
            if matched is not None:
                return matched
        for record in history:
            if record.run_id != selected_record.run_id:
                return record
        return None

    def _publish_record_project(self, record: ExportRecord | None, canonical_project_code: str) -> ProjectSnapshot | None:
        if record is None:
            return None
        return next(
            (project for project in record.project_snapshots if project.canonical_project_code == canonical_project_code),
            None,
        )

    def _build_publish_comparison_summary(
        self,
        current_project: ProjectSnapshot | None,
        previous_project: ProjectSnapshot | None,
    ) -> list[str]:
        if current_project is None or previous_project is None:
            return ["Current issued brief stands without a prior deterministic baseline."]
        return [
            self._publish_finish_change_line(current_project, previous_project),
            self._publish_driver_change_line(current_project, previous_project),
            self._publish_risk_change_line(current_project, previous_project),
            self._publish_confidence_change_line(current_project, previous_project),
        ]

    def _build_publish_continuity(
        self,
        current_project: ProjectSnapshot | None,
        previous_project: ProjectSnapshot | None,
        comparison_record: ExportRecord | None,
    ) -> PublishContinuityView:
        if current_project is None or previous_project is None or comparison_record is None:
            return PublishContinuityView(
                status="unavailable",
                status_label="Prior issued output unavailable",
                summary="No prior issued brief is available for deterministic comparison.",
                detail_lines=["Current issued brief stands without a prior deterministic baseline."],
                prior_run_id=comparison_record.run_id if comparison_record else None,
                prior_generated_at=comparison_record.generated_at if comparison_record else None,
                compare_label="Previous issued run unavailable",
            )

        finish_line = self._publish_finish_change_line(current_project, previous_project)
        driver_line = self._publish_driver_change_line(current_project, previous_project)
        risk_line = self._publish_risk_change_line(current_project, previous_project)
        confidence_line = self._publish_confidence_change_line(current_project, previous_project)
        detail_lines = [finish_line, driver_line, risk_line]
        if confidence_line != "Confidence unchanged.":
            detail_lines.append(confidence_line)

        finish_changed = finish_line != "Finish unchanged."
        driver_changed = driver_line not in {"Driver unchanged.", "Driver comparison unavailable."}
        risk_changed = risk_line != "Risk posture unchanged."

        if finish_changed or driver_changed or risk_changed:
            summary_parts: list[str] = []
            if finish_changed:
                summary_parts.append(finish_line.rstrip("."))
            else:
                summary_parts.append("Finish unchanged")
            if driver_changed:
                summary_parts.append(driver_line.rstrip("."))
            if risk_changed:
                summary_parts.append(risk_line.rstrip("."))
            return PublishContinuityView(
                status="material_change",
                status_label="Material change since prior issued brief",
                summary="; ".join(summary_parts) + ".",
                detail_lines=detail_lines,
                prior_run_id=comparison_record.run_id,
                prior_generated_at=comparison_record.generated_at,
                compare_label=f"Previous issued run {comparison_record.run_id}",
            )

        return PublishContinuityView(
            status="no_material_change",
            status_label="No material change",
            summary="No material change from prior issued brief.",
            detail_lines=detail_lines,
            prior_run_id=comparison_record.run_id,
            prior_generated_at=comparison_record.generated_at,
            compare_label=f"Previous issued run {comparison_record.run_id}",
        )

    def _build_publish_artifact_continuity(
        self,
        *,
        note,
        comparison_record: ExportRecord | None,
        current_project: ProjectSnapshot | None,
        previous_project: ProjectSnapshot | None,
    ) -> PublishContinuityView:
        label = self._publish_note_kind_label(note.note_kind).lower()
        if comparison_record is None:
            return PublishContinuityView(
                status="unavailable",
                status_label="Prior issued output unavailable",
                summary=f"No prior issued {label} is available for deterministic comparison.",
                prior_run_id=None,
                prior_generated_at=None,
                compare_label="Previous issued run unavailable",
            )

        prior_note = self._publish_record_note(
            comparison_record,
            note_kind=note.note_kind,
            project_code=note.canonical_project_code,
            title=note.title,
        )
        if prior_note is None:
            return PublishContinuityView(
                status="unavailable",
                status_label="Prior issued output unavailable",
                summary=f"No prior issued {label} is available for deterministic comparison.",
                prior_run_id=comparison_record.run_id,
                prior_generated_at=comparison_record.generated_at,
                compare_label=f"Previous issued run {comparison_record.run_id}",
            )

        if (
            note.canonical_project_code
            and current_project is not None
            and previous_project is not None
            and note.canonical_project_code == current_project.canonical_project_code
        ):
            return self._build_publish_continuity(current_project, previous_project, comparison_record)

        current_markdown = publishable_markdown(note.body).strip()
        prior_markdown = publishable_markdown(prior_note.body).strip()
        if current_markdown == prior_markdown:
            return PublishContinuityView(
                status="no_material_change",
                status_label="No material change",
                summary=f"No material change from prior issued {label}.",
                prior_run_id=comparison_record.run_id,
                prior_generated_at=comparison_record.generated_at,
                compare_label=f"Previous issued run {comparison_record.run_id}",
            )

        return PublishContinuityView(
            status="material_change",
            status_label="Updated since prior issued output",
            summary=f"{self._publish_note_kind_label(note.note_kind)} content changed since the prior issued output.",
            detail_lines=["This issued document differs from the prior run artifact."],
            prior_run_id=comparison_record.run_id,
            prior_generated_at=comparison_record.generated_at,
            compare_label=f"Previous issued run {comparison_record.run_id}",
        )

    def _publish_finish_change_line(self, current_project: ProjectSnapshot, previous_project: ProjectSnapshot) -> str:
        current_finish = self._projected_finish_label(current_project)
        previous_finish = self._projected_finish_label(previous_project)
        if current_finish == previous_finish:
            return "Finish unchanged."
        return f"Finish changed: {previous_finish} -> {current_finish}."

    def _publish_driver_change_line(self, current_project: ProjectSnapshot, previous_project: ProjectSnapshot) -> str:
        current_driver = self._publish_driver_label(current_project)
        previous_driver = self._publish_driver_label(previous_project)
        if not current_driver or not previous_driver:
            return "Driver comparison unavailable."
        if current_driver == previous_driver:
            return "Driver unchanged."
        return f"Driver changed: {previous_driver} -> {current_driver}."

    def _publish_driver_label(self, project: ProjectSnapshot) -> str:
        driver = project.finish_driver.controlling_driver
        if not driver or driver == "Driver unavailable":
            return ""
        return self.execution_brief_service._short_driver_label(driver)

    def _publish_risk_change_line(self, current_project: ProjectSnapshot, previous_project: ProjectSnapshot) -> str:
        current_schedule = current_project.schedule
        previous_schedule = previous_project.schedule
        current_open_ends = ((current_schedule.open_start_count or 0) + (current_schedule.open_finish_count or 0)) if current_schedule else 0
        previous_open_ends = ((previous_schedule.open_start_count or 0) + (previous_schedule.open_finish_count or 0)) if previous_schedule else 0
        open_end_delta = current_open_ends - previous_open_ends
        if open_end_delta != 0:
            direction = "worsened" if open_end_delta > 0 else "improved"
            return f"Risk posture {direction}: open ends {open_end_delta:+d}."

        current_cycles = (current_schedule.cycle_count or 0) if current_schedule else 0
        previous_cycles = (previous_schedule.cycle_count or 0) if previous_schedule else 0
        cycle_delta = current_cycles - previous_cycles
        if cycle_delta != 0:
            direction = "worsened" if cycle_delta > 0 else "improved"
            return f"Risk posture {direction}: cycle {cycle_delta:+d}."

        current_negative_float = (current_schedule.negative_float_count or 0) if current_schedule else 0
        previous_negative_float = (previous_schedule.negative_float_count or 0) if previous_schedule else 0
        negative_float_delta = current_negative_float - previous_negative_float
        if negative_float_delta != 0:
            direction = "worsened" if negative_float_delta > 0 else "improved"
            return f"Risk posture {direction}: negative float {negative_float_delta:+d}."

        if current_project.health.risk_level != previous_project.health.risk_level:
            current_rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(current_project.health.risk_level, 0)
            previous_rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(previous_project.health.risk_level, 0)
            direction = "worsened" if current_rank > previous_rank else "improved"
            return f"Risk posture {direction}: {previous_project.health.risk_level} -> {current_project.health.risk_level}."
        return "Risk posture unchanged."

    def _publish_confidence_change_line(self, current_project: ProjectSnapshot, previous_project: ProjectSnapshot) -> str:
        current_confidence = self.execution_brief_service._confidence_label(current_project)
        previous_confidence = self.execution_brief_service._confidence_label(previous_project)
        if current_confidence == previous_confidence:
            return "Confidence unchanged."
        return f"Confidence changed: {previous_confidence} -> {current_confidence}."

    def _publish_brief_copy_text(self, command_brief: ProjectCommandView | None) -> str:
        if command_brief is None:
            return ""
        paragraphs = [line for section in command_brief.execution_brief.sections for line in section.lines]
        return "\n\n".join([command_brief.project_name, *paragraphs])

    def _publish_arena_path(self, command_brief: ProjectCommandView | None) -> str:
        if command_brief is None:
            return "/arena"
        return self._arena_path([command_brief.canonical_project_code])

    def _publish_present_path(self, run_id: str, project_code: str | None = None) -> str:
        params = [("run", run_id)]
        if project_code:
            params.append(("project", project_code))
        return "/publish/present?" + urlencode(params)

    def _publish_issue_state(self, *, is_latest: bool, preview_only: bool) -> tuple[str, str, str]:
        if is_latest and not preview_only:
            return ("Current authoritative output", "current", "Authoritative issued document")
        if is_latest and preview_only:
            return ("Current preview output", "preview", "Preview document")
        return ("Prior issued output", "historical", "Historical issued document")

    def _publish_history_availability(self, record: ExportRecord) -> list[PublishArtifactAvailability]:
        counts = {note_kind: 0 for note_kind in ("project_weekly_brief", "project_dossier", "portfolio_weekly_summary")}
        for note in record.notes:
            counts[note.note_kind] = counts.get(note.note_kind, 0) + 1
        return [
            PublishArtifactAvailability(
                key=note_kind,  # type: ignore[arg-type]
                label=self._publish_note_kind_label(note_kind),  # type: ignore[arg-type]
                available=counts[note_kind] > 0,
                count=counts[note_kind],
            )
            for note_kind in ("project_weekly_brief", "project_dossier", "portfolio_weekly_summary")
        ]

    def _default_publish_artifact_id(self, record: ExportRecord, lead_project: ProjectSnapshot | None) -> str | None:
        preferred_codes = [lead_project.canonical_project_code] if lead_project else []
        for note_kind in ("project_weekly_brief", "project_dossier", "portfolio_weekly_summary"):
            for preferred_code in preferred_codes + [None]:
                note = next(
                    (
                        item
                        for item in record.notes
                        if item.note_kind == note_kind and item.canonical_project_code == preferred_code
                    ),
                    None,
                )
                if note is not None:
                    return self._publish_artifact_id(note.note_kind, note.canonical_project_code, note.title)
        if not record.notes:
            return None
        first = record.notes[0]
        return self._publish_artifact_id(first.note_kind, first.canonical_project_code, first.title)

    def _publish_note_priority(self, note_kind: str, is_lead_project: bool) -> tuple[int, int]:
        priority = {
            "project_weekly_brief": 0,
            "project_dossier": 1,
            "portfolio_weekly_summary": 2,
        }.get(note_kind, 9)
        return (priority, 0 if is_lead_project else 1)

    def _publish_note_kind_label(self, note_kind: str) -> str:
        labels = {
            "project_weekly_brief": "Weekly Brief",
            "project_dossier": "Project Dossier",
            "portfolio_weekly_summary": "Portfolio Summary",
        }
        return labels.get(note_kind, note_kind.replace("_", " ").title())

    def _publish_artifact_summary(self, markdown: str) -> str:
        lines = [line.strip() for line in markdown.splitlines() if line.strip()]
        for line in lines:
            if not line.startswith("#") and not line.startswith("[["):
                return self._brief_statement(line.lstrip("- ").strip(), max_words=18)
        return "Open artifact preview"

    def _build_publish_artifact_preview_metadata(
        self,
        *,
        note_title: str,
        project_code: str | None,
        generated_at: str,
        frontmatter: dict[str, object],
    ) -> PublishArtifactPreviewMetadata:
        preview_generated_at = self._frontmatter_text(frontmatter.get("generated_at")) or generated_at
        return PublishArtifactPreviewMetadata(
            title=self._frontmatter_text(frontmatter.get("title")) or note_title,
            project_name=self._frontmatter_text(frontmatter.get("project_name")) or self._project_name_from_title(note_title),
            project_code=self._frontmatter_text(frontmatter.get("project_code")) or project_code,
            run_date=self._frontmatter_text(frontmatter.get("run_date"))
            or (preview_generated_at[:10] if preview_generated_at else None),
            generated_at=preview_generated_at,
            health_tier=self._frontmatter_label(frontmatter.get("health_tier")),
            risk_level=self._frontmatter_text(frontmatter.get("risk_level")),
            health_score=self._frontmatter_score(frontmatter.get("health_score")),
        )

    def _frontmatter_text(self, value: object | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _frontmatter_label(self, value: object | None) -> str | None:
        text = self._frontmatter_text(value)
        if not text:
            return None
        return text.replace("_", " ").title()

    def _frontmatter_score(self, value: object | None) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return f"{float(value):.1f}"
        text = self._frontmatter_text(value)
        if not text:
            return None
        try:
            return f"{float(text):.1f}"
        except ValueError:
            return text

    def _project_name_from_title(self, title: str) -> str | None:
        if " - " not in title:
            return None
        return title.split(" - ", 1)[0].strip() or None

    def _publish_artifact_id(self, note_kind: str, project_code: str | None, title: str) -> str:
        title_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        code_slug = re.sub(r"[^a-z0-9]+", "-", (project_code or "portfolio").lower()).strip("-")
        return f"{note_kind}-{code_slug}-{title_slug}"

    def _publish_context_artifact_id(
        self,
        record: ExportRecord,
        *,
        note_kind: str | None,
        project_code: str | None,
    ) -> str | None:
        if note_kind:
            note = self._publish_record_note(record, note_kind=note_kind, project_code=project_code)
            if note is not None:
                return self._publish_artifact_id(note.note_kind, note.canonical_project_code, note.title)
        return self._default_publish_artifact_id(
            record,
            self._publish_record_project(record, project_code) if project_code else None,
        )

    def _publish_record_note(
        self,
        record: ExportRecord,
        *,
        note_kind: str,
        project_code: str | None,
        title: str | None = None,
    ):
        matching = [
            note
            for note in record.notes
            if note.note_kind == note_kind and note.canonical_project_code == project_code
        ]
        if title:
            titled = next((note for note in matching if note.title == title), None)
            if titled is not None:
                return titled
        if matching:
            return matching[0]
        if project_code is not None:
            fallback = [note for note in record.notes if note.note_kind == note_kind]
            if title:
                titled = next((note for note in fallback if note.title == title), None)
                if titled is not None:
                    return titled
            if fallback:
                return fallback[0]
        return None

    def _publish_surface_path(
        self,
        run_id: str,
        artifact_id: str | None = None,
        *,
        print_mode: bool = False,
        project_code: str | None = None,
    ) -> str:
        params = [("run", run_id)]
        if project_code:
            params.append(("project", project_code))
        if artifact_id:
            params.append(("artifact", artifact_id))
        if print_mode:
            params.append(("print", "1"))
        return "/publish?" + urlencode(params)

    def _publish_source_path(self, run_id: str, artifact_id: str) -> str:
        return f"/exports/source/{quote(run_id, safe='')}/{quote(artifact_id, safe='')}"

    def _publish_obsidian_url(self, relative_path: str) -> str:
        vault_name = self.config.obsidian.vault_root.name
        return (
            "obsidian://open?vault="
            + quote(vault_name, safe="")
            + "&file="
            + quote(relative_path.replace("\\", "/"), safe="/")
        )

    def _build_attention_item(
        self,
        project: ProjectSnapshot,
        selected_codes: list[str],
        comparison_trust: ComparisonTrust,
    ) -> ControlTowerAttentionItem:
        why_it_matters = self._project_why(project)
        required_action = self._project_action(project)
        action_owner = self._project_action_owner(project)
        command_view = self.build_project_command_view(project, comparison_trust)
        return ControlTowerAttentionItem(
            canonical_project_code=project.canonical_project_code,
            project_name=project.project_name,
            domain=project.domain,
            posture=project.executive_summary,
            risk_level=project.health.risk_level,
            tier=project.health.tier,
            health_score=project.health.health_score,
            what_changed=self._project_change(project, comparison_trust),
            why_it_matters=why_it_matters,
            required_action=required_action,
            action_owner=action_owner,
            action_timing=self._project_action_timing(project),
            cause=self._project_cause(project),
            impact=self._project_impact(project, comparison_trust),
            schedule_signal=self._project_schedule_signal(project, comparison_trust),
            current_finish_date=project.delta.schedule.current_finish_date or (project.schedule.finish_date if project.schedule else None),
            finish_delta_days=project.delta.schedule.finish_date_movement_days,
            finish_statement=self._project_finish_statement(project),
            delta_statement=self._project_delta_statement(project),
            finish_authority_state=command_view.finish_authority_state,
            finish_source_label=command_view.finish_source_label,
            finish_source_detail=command_view.finish_source_detail,
            ranking_reason=self._ranking_reason(project),
            trust_status=project.trust_indicator.status,
            comparison_label=self._comparison_label_for_project(project),
            comparison_detail=self._project_comparison_detail(project, comparison_trust),
            drilldown_path=f"/projects/{project.canonical_project_code}",
            compare_path=f"/projects/{project.canonical_project_code}/compare",
            arena_add_path=self._arena_path(selected_codes + [project.canonical_project_code]),
            arena_remove_path=self._arena_path([code for code in selected_codes if code != project.canonical_project_code]),
            arena_promoted=project.canonical_project_code in selected_codes,
            arena_group="Professional Portfolio" if project.domain == "professional" else "Personal Operating Items",
        )

    def _build_narrative_section(
        self,
        *,
        key: str,
        label: str,
        title: str,
        items: list[NarrativeBullet],
        empty_summary: str,
        default_open: bool = False,
    ) -> NarrativeSection:
        if not items:
            return NarrativeSection(
                key=key,
                label=label,
                title=title,
                summary=empty_summary,
                item_count=0,
                lead_project_code=None,
                default_open=default_open,
                items=[],
            )
        lead = items[0]
        summary = f"{lead.who}: {self._brief_statement(lead.what, max_words=18)}"
        return NarrativeSection(
            key=key,
            label=label,
            title=title,
            summary=summary,
            item_count=len(items),
            lead_project_code=lead.canonical_project_code,
            default_open=default_open,
            items=items,
        )

    def _build_control_tower_scan_cards(
        self,
        *,
        headline: ControlTowerHeadline,
        comparison_trust: ComparisonTrust,
        material_changes: NarrativeSection,
        required_actions: NarrativeSection,
        rising_risks: NarrativeSection,
        watch_items: NarrativeSection,
    ) -> list[SurfaceScanCard]:
        return [
            SurfaceScanCard(
                key="posture",
                label="Overall posture",
                summary=headline.overall_posture,
                detail=f"Release {headline.readiness_status.replace('_', ' ')}. {comparison_trust.baseline_label}.",
                item_count=headline.intervention_count,
            ),
            SurfaceScanCard(
                key="change",
                label="What changed materially",
                summary=(
                    self._brief_statement(f"{material_changes.items[0].who}: {material_changes.items[0].what}", max_words=18)
                    if material_changes.items
                    else self._brief_statement(material_changes.summary, max_words=18)
                ),
                detail=(
                    self._brief_statement(material_changes.items[0].impact, max_words=18)
                    if material_changes.items
                    else self._brief_statement(comparison_trust.ranking_detail, max_words=18)
                ),
                item_count=material_changes.item_count,
                project_code=material_changes.lead_project_code,
            ),
            SurfaceScanCard(
                key="action",
                label="What requires action or decision now",
                summary=(
                    self._brief_statement(f"{required_actions.items[0].who}: {required_actions.items[0].action}", max_words=18)
                    if required_actions.items
                    else self._brief_statement(required_actions.summary, max_words=18)
                ),
                detail=(
                    self._brief_statement(required_actions.items[0].timing or required_actions.items[0].impact, max_words=18)
                    if required_actions.items
                    else self._brief_statement(headline.readiness_summary, max_words=18)
                ),
                item_count=required_actions.item_count,
                project_code=required_actions.lead_project_code,
            ),
            SurfaceScanCard(
                key="risk",
                label="Where risk is rising",
                summary=(
                    self._brief_statement(f"{rising_risks.items[0].who}: {rising_risks.items[0].why}", max_words=18)
                    if rising_risks.items
                    else self._brief_statement(rising_risks.summary, max_words=18)
                ),
                detail=(
                    self._brief_statement(rising_risks.items[0].action, max_words=18)
                    if rising_risks.items
                    else self._brief_statement(watch_items.summary, max_words=18)
                ),
                item_count=rising_risks.item_count,
                project_code=rising_risks.lead_project_code,
            ),
        ]

    def _build_arena_scan_cards(
        self,
        *,
        headline_posture: str,
        material_changes: NarrativeSection,
        why_it_matters: NarrativeSection,
        required_actions: NarrativeSection,
        rising_risks: NarrativeSection,
    ) -> list[SurfaceScanCard]:
        return [
            SurfaceScanCard(
                key="headline",
                label="Headline posture",
                summary=headline_posture,
                detail="Lead with posture and decision. Expand only if challenged.",
                item_count=0,
            ),
            SurfaceScanCard(
                key="change",
                label="What changed",
                summary=(
                    self._brief_statement(f"{material_changes.items[0].who}: {material_changes.items[0].what}", max_words=18)
                    if material_changes.items
                    else self._brief_statement(material_changes.summary, max_words=18)
                ),
                detail=(
                    self._brief_statement(material_changes.items[0].impact, max_words=18)
                    if material_changes.items
                    else ""
                ),
                item_count=material_changes.item_count,
                project_code=material_changes.lead_project_code,
            ),
            SurfaceScanCard(
                key="impact",
                label="Why it matters",
                summary=(
                    self._brief_statement(f"{why_it_matters.items[0].who}: {why_it_matters.items[0].why}", max_words=18)
                    if why_it_matters.items
                    else self._brief_statement(why_it_matters.summary, max_words=18)
                ),
                detail=(
                    self._brief_statement(why_it_matters.items[0].impact, max_words=18)
                    if why_it_matters.items
                    else ""
                ),
                item_count=why_it_matters.item_count,
                project_code=why_it_matters.lead_project_code,
            ),
            SurfaceScanCard(
                key="decision",
                label="What needs decision",
                summary=(
                    self._brief_statement(f"{required_actions.items[0].who}: {required_actions.items[0].action}", max_words=18)
                    if required_actions.items
                    else self._brief_statement(required_actions.summary, max_words=18)
                ),
                detail=(
                    self._brief_statement(required_actions.items[0].timing or required_actions.items[0].impact, max_words=18)
                    if required_actions.items
                    else self._brief_statement(rising_risks.summary, max_words=18)
                ),
                item_count=required_actions.item_count,
                project_code=required_actions.lead_project_code,
            ),
        ]

    def _change_bullet(self, item: ControlTowerAttentionItem) -> NarrativeBullet:
        return NarrativeBullet(
            canonical_project_code=item.canonical_project_code,
            project_name=item.project_name,
            who=item.canonical_project_code,
            finish=item.finish_statement,
            delta=item.delta_statement,
            what=item.what_changed,
            why=item.why_it_matters,
            action=f"{item.action_owner}: {item.required_action}",
            summary=item.what_changed,
            detail=item.impact,
            cause=item.cause,
            impact=item.impact,
            timing=item.action_timing,
            owner=item.action_owner,
            current_finish_date=item.current_finish_date,
            finish_delta_days=item.finish_delta_days,
        )

    def _action_bullet(self, item: ControlTowerAttentionItem) -> NarrativeBullet:
        return NarrativeBullet(
            canonical_project_code=item.canonical_project_code,
            project_name=item.project_name,
            who=item.canonical_project_code,
            finish=item.finish_statement,
            delta=item.delta_statement,
            what=item.what_changed,
            why=item.why_it_matters,
            action=f"{item.action_owner}: {item.required_action}",
            summary=f"{item.action_owner}: {item.required_action}",
            detail=item.impact,
            cause=item.cause,
            impact=item.impact,
            timing=item.action_timing,
            owner=item.action_owner,
            current_finish_date=item.current_finish_date,
            finish_delta_days=item.finish_delta_days,
        )

    def _risk_bullet(self, item: ControlTowerAttentionItem) -> NarrativeBullet:
        return NarrativeBullet(
            canonical_project_code=item.canonical_project_code,
            project_name=item.project_name,
            who=item.canonical_project_code,
            finish=item.finish_statement,
            delta=item.delta_statement,
            what=item.what_changed,
            why=item.why_it_matters,
            action=f"{item.action_owner}: {item.required_action}",
            summary=item.why_it_matters,
            detail=item.impact,
            cause=item.cause,
            impact=item.impact,
            timing=item.action_timing,
            owner=item.action_owner,
            current_finish_date=item.current_finish_date,
            finish_delta_days=item.finish_delta_days,
        )

    def _arena_change_bullet(self, item: ArenaItem) -> NarrativeBullet:
        return NarrativeBullet(
            canonical_project_code=item.canonical_project_code,
            project_name=item.project_name,
            who=item.canonical_project_code,
            finish=item.finish_statement,
            delta=item.delta_statement,
            what=item.change_statement,
            why=item.why_it_matters_statement,
            action=item.action_statement,
            summary=item.change_statement,
            detail=item.impact_statement,
            cause=item.cause_statement,
            impact=item.impact_statement,
            timing=item.action_timing,
            current_finish_date=item.current_finish_date,
            finish_delta_days=item.finish_delta_days,
        )

    def _arena_impact_bullet(self, item: ArenaItem) -> NarrativeBullet:
        return NarrativeBullet(
            canonical_project_code=item.canonical_project_code,
            project_name=item.project_name,
            who=item.canonical_project_code,
            finish=item.finish_statement,
            delta=item.delta_statement,
            what=item.change_statement,
            why=item.why_it_matters_statement,
            action=item.action_statement,
            summary=item.why_it_matters_statement,
            detail=item.impact_statement,
            cause=item.cause_statement,
            impact=item.impact_statement,
            timing=item.action_timing,
            current_finish_date=item.current_finish_date,
            finish_delta_days=item.finish_delta_days,
        )

    def _arena_action_required_bullet(self, item: ArenaItem) -> NarrativeBullet:
        return NarrativeBullet(
            canonical_project_code=item.canonical_project_code,
            project_name=item.project_name,
            who=item.canonical_project_code,
            finish=item.finish_statement,
            delta=item.delta_statement,
            what=item.change_statement,
            why=item.why_it_matters_statement,
            action=item.action_statement,
            summary=item.action_statement,
            detail=item.impact_statement,
            cause=item.cause_statement,
            impact=item.impact_statement,
            timing=item.action_timing,
            current_finish_date=item.current_finish_date,
            finish_delta_days=item.finish_delta_days,
        )

    def _arena_risk_bullet(self, item: ArenaItem) -> NarrativeBullet:
        return NarrativeBullet(
            canonical_project_code=item.canonical_project_code,
            project_name=item.project_name,
            who=item.canonical_project_code,
            finish=item.finish_statement,
            delta=item.delta_statement,
            what=item.change_statement,
            why=item.risk_statement,
            action=item.action_statement,
            summary=item.risk_statement,
            detail=item.impact_statement,
            cause=item.cause_statement,
            impact=item.impact_statement,
            timing=item.action_timing,
            current_finish_date=item.current_finish_date,
            finish_delta_days=item.finish_delta_days,
        )

    def _attention_score(self, project: ProjectSnapshot, comparison_trust: ComparisonTrust) -> float:
        risk_weight = {"HIGH": 40.0, "MEDIUM": 18.0, "LOW": 0.0}[project.health.risk_level]
        tier_weight = {"critical": 22.0, "at_risk": 14.0, "watch": 6.0, "healthy": 0.0}[project.health.tier]
        action_weight = sum({"high": 9.0, "medium": 5.0, "low": 2.0}[action.priority] for action in project.health.required_actions[:3])
        trust_weight = {"missing": 10.0, "low": 9.0, "partial": 5.0, "high": 0.0}[project.trust_indicator.status]
        base_pressure = max(0.0, 100.0 - project.health.health_score)
        delta_weight = self._delta_attention_score(project) if comparison_trust.delta_ranking_enabled else 0.0
        return round(risk_weight + tier_weight + action_weight + trust_weight + base_pressure + delta_weight, 1)

    def _delta_attention_score(self, project: ProjectSnapshot) -> float:
        score = 0.0
        if project.delta.schedule.finish_date_movement_days and project.delta.schedule.finish_date_movement_days > 0:
            score += min(18.0, float(project.delta.schedule.finish_date_movement_days) * 2.0)
        if project.delta.schedule.float_movement_days and project.delta.schedule.float_movement_days < 0:
            score += min(14.0, abs(project.delta.schedule.float_movement_days) * 3.0)
        if project.delta.financial.margin_movement and project.delta.financial.margin_movement < 0:
            score += min(12.0, abs(project.delta.financial.margin_movement) * 2.0)
        if project.delta.financial.cost_variance_change and project.delta.financial.cost_variance_change > 0:
            score += min(12.0, project.delta.financial.cost_variance_change / 10000.0)
        score += min(10.0, float(len(project.delta.risk.new_risks)) * 3.0)
        score += min(8.0, float(len(project.delta.risk.worsening_signals)) * 4.0)
        if project.delta.schedule.critical_path_changed:
            score += 5.0
        return round(score, 1)

    def _ranking_reason(self, project: ProjectSnapshot) -> str:
        reasons: list[str] = []
        if project.health.risk_level == "HIGH":
            reasons.append("high risk posture")
        if any(action.priority == "high" for action in project.health.required_actions):
            reasons.append("immediate action required")
        if project.trust_indicator.status != "high":
            reasons.append("trust-limited signals")
        if project.comparison_status == "trusted" and self._delta_attention_score(project) > 0:
            reasons.append("meaningful change since the prior trusted run")
        return ", ".join(reasons) if reasons else "steady but still tracked"

    def _current_finish_date(self, project: ProjectSnapshot) -> str | None:
        return project.delta.schedule.current_finish_date or (project.schedule.finish_date if project.schedule else None)

    def _projected_finish_reason(self, project: ProjectSnapshot) -> str | None:
        current_finish = self._current_finish_date(project)
        if current_finish:
            return None
        if project.schedule is None:
            return "No published schedule artifact is available for this project."
        detail = str(project.schedule.finish_detail or "").strip()
        return detail or "No finish milestone/date was found in the published schedule artifact."

    def _projected_finish_label(self, project: ProjectSnapshot) -> str:
        return self._current_finish_date(project) or "unavailable"

    def _project_finish_statement(self, project: ProjectSnapshot) -> str:
        current_finish = self._current_finish_date(project)
        if current_finish:
            return f"Projected finish: {current_finish}"
        return f"Projected finish unavailable. Reason: {self._projected_finish_reason(project)}"

    def _project_delta_reason(self, project: ProjectSnapshot) -> str | None:
        if project.delta.schedule.finish_date_movement_days is not None:
            return None
        detail = str(project.delta.schedule.finish_date_movement_reason or "").strip()
        if detail:
            return detail
        if self._current_finish_date(project):
            return "A finish date exists for the current run, but no trusted prior baseline exists for comparison."
        return "Projected finish is unavailable for the current run, so movement versus the prior trusted run cannot be computed."

    def _project_delta_label(self, project: ProjectSnapshot) -> str:
        movement = project.delta.schedule.finish_date_movement_days
        if movement is None:
            return "unavailable"
        if movement > 0:
            return f"+{movement} days"
        if movement < 0:
            return f"-{abs(movement)} days"
        return "0 days"

    def _project_delta_statement(self, project: ProjectSnapshot) -> str:
        movement = project.delta.schedule.finish_date_movement_days
        if movement is not None:
            return f"Movement vs prior trusted run: {self._project_delta_label(project)}"
        return f"Movement vs prior trusted run unavailable. Reason: {self._project_delta_reason(project)}"

    def _finish_authority_state(self, project: ProjectSnapshot) -> str:
        if project.delta.schedule.finish_date_movement_days is not None and project.comparison_status == "trusted":
            return "trusted comparison"
        if self._current_finish_date(project) and project.comparison_status == "trusted":
            return "trusted baseline, finish delta unavailable"
        if self._current_finish_date(project):
            return "current artifact only"
        return "finish unavailable"

    def _project_finish_source_detail(self, project: ProjectSnapshot) -> str:
        if project.schedule is None:
            return "No published schedule artifact is available for this project."
        detail = str(project.schedule.finish_detail or "").strip()
        return detail or "No finish milestone/date was found in the published schedule artifact."

    def _project_change(self, project: ProjectSnapshot, comparison_trust: ComparisonTrust) -> str:
        schedule = project.schedule
        open_ends = ((schedule.open_start_count or 0) + (schedule.open_finish_count or 0)) if schedule else 0
        parts: list[str] = []
        if project.comparison_status == "trusted":
            finish_delta = project.delta.schedule.finish_date_movement_days
            if finish_delta is not None:
                if finish_delta > 0:
                    parts.append(f"finish slipped {finish_delta} day(s) versus the prior run")
                elif finish_delta < 0:
                    parts.append(f"finish improved {abs(finish_delta)} day(s) versus the prior run")
                else:
                    parts.append("no date movement versus the prior run")
            for signal in project.delta.risk.worsening_signals[:2]:
                parts.append(signal.rstrip(".").lower())
            if project.delta.schedule.float_movement_days is not None and project.delta.schedule.float_movement_days < 0:
                parts.append(f"float compressed {abs(project.delta.schedule.float_movement_days):.1f} day(s)")
            if project.delta.financial.margin_movement is not None and project.delta.financial.margin_movement < 0:
                parts.append(f"margin moved down {abs(project.delta.financial.margin_movement):.2f} pts")
            if project.delta.financial.cost_variance_change is not None and project.delta.financial.cost_variance_change > 0:
                parts.append(f"cost variance worsened by ${project.delta.financial.cost_variance_change:,.0f}")
            if project.delta.risk.new_risks:
                parts.append("new risks: " + ", ".join(risk.replace("_", " ") for risk in project.delta.risk.new_risks[:3]))
        else:
            current_finish = self._current_finish_date(project)
            if current_finish:
                parts.append(f"projected finish is {current_finish}")
            else:
                parts.append("projected finish unavailable")
                parts.append(self._projected_finish_reason(project))
            parts.append(self._project_delta_reason(project))
            if schedule and (schedule.cycle_count or 0) > 0:
                parts.append(f"{schedule.cycle_count} schedule cycle(s) remain")
            if open_ends > 0:
                parts.append(f"{open_ends} open-end condition(s) remain")
            if schedule and (schedule.negative_float_count or 0) > 0:
                parts.append(f"{schedule.negative_float_count} activity(ies) still carry negative float")
        if not parts:
            return "No material change surfaced from the currently trusted signals."
        return self._sentence_from_parts(parts)

    def _project_why(self, project: ProjectSnapshot) -> str:
        if project.top_issues:
            return project.top_issues[0].detail
        if project.trust_indicator.status != "high" and project.trust_indicator.rationale:
            return project.trust_indicator.rationale[0]
        return project.executive_summary

    def _project_cause(self, project: ProjectSnapshot) -> str:
        if project.delta.risk.worsening_signals:
            return project.delta.risk.worsening_signals[0]
        if project.schedule and project.schedule.top_drivers:
            driver = project.schedule.top_drivers[0]
            if driver.rationale:
                return f"Top schedule driver {driver.label}: {driver.rationale}."
            return f"Top schedule driver {driver.label}."
        if project.financial and project.financial.key_findings:
            return project.financial.key_findings[0]
        return "cause not yet identified"

    def _project_action(self, project: ProjectSnapshot) -> str:
        if project.health.required_actions:
            return project.health.required_actions[0].action
        return "Validate the current signals and confirm the next source publication."

    def _project_action_owner(self, project: ProjectSnapshot) -> str:
        if project.health.required_actions:
            return project.health.required_actions[0].owner_hint
        return "PM"

    def _action_timing_from_text(self, action_text: str, priority: str | None = None) -> str:
        lowered = action_text.lower()
        if "before the next publish" in lowered:
            return "before next publish"
        if "before the next update cycle" in lowered:
            return "before next update cycle"
        if "before the next leadership review" in lowered:
            return "before next leadership review"
        if "before the next forecast review" in lowered:
            return "before next forecast review"
        if "before the next cost review" in lowered:
            return "before next cost review"
        if "before the next weekly review" in lowered:
            return "before next weekly review"
        if "this week" in lowered:
            return "this week"
        if any(token in lowered for token in ("now", "immediate", "immediately")):
            return "now"
        if priority == "high":
            return "now"
        return "before next update cycle"

    def _project_action_timing(self, project: ProjectSnapshot) -> str:
        action = self._project_action(project)
        priority = project.health.required_actions[0].priority if project.health.required_actions else None
        return self._action_timing_from_text(action, priority)

    def _project_schedule_signal(self, project: ProjectSnapshot, comparison_trust: ComparisonTrust) -> str:
        return f"{self._project_finish_statement(project)}. {self._project_delta_statement(project)}."

    def _project_impact(self, project: ProjectSnapshot, comparison_trust: ComparisonTrust) -> str:
        parts = [self._project_finish_statement(project) + ".", self._project_delta_statement(project) + "."]
        if project.delta.schedule.float_movement_days is not None:
            if project.delta.schedule.float_movement_days < 0:
                parts.append(f"Float compressed by {abs(project.delta.schedule.float_movement_days):.1f} day(s).")
            elif project.delta.schedule.float_movement_days > 0:
                parts.append(f"Float expanded by {project.delta.schedule.float_movement_days:.1f} day(s).")
        if project.delta.financial.margin_movement is not None and project.delta.financial.margin_movement < 0:
            parts.append(f"Margin moved down {abs(project.delta.financial.margin_movement):.2f} pts.")
        if project.delta.financial.cost_variance_change is not None and project.delta.financial.cost_variance_change > 0:
            parts.append(f"Cost variance worsened by ${project.delta.financial.cost_variance_change:,.0f}.")
        if project.health.risk_level == "HIGH":
            parts.append("Risk level remains HIGH.")
        return " ".join(part.strip() for part in parts if part.strip())

    def _portfolio_action_line(self, project: ProjectSnapshot, comparison_trust: ComparisonTrust) -> str:
        return (
            f"{project.canonical_project_code}: {self._project_action_owner(project)} to {self._project_action(project)} "
            f"Timing: {self._project_action_timing(project)}. Impact: {self._project_impact(project, comparison_trust)}"
        )

    def _change_summary(self, project: ProjectSnapshot, comparison_trust: ComparisonTrust) -> str:
        return self._project_change(project, comparison_trust)

    def _classify_domain(self, source_keys: list[str]) -> str:
        lowered = {item.split(":", 1)[0].lower() for item in source_keys}
        if lowered.intersection({"personal", "family", "life", "household", "reminder"}):
            return "personal"
        return "professional"

    def _normalize_selection(self, selected_codes: list[str] | None, projects: list[ProjectSnapshot]) -> list[str]:
        available_codes = {project.canonical_project_code for project in projects}
        result: list[str] = []
        for code in selected_codes or []:
            cleaned = str(code).strip()
            if cleaned and cleaned in available_codes and cleaned not in result:
                result.append(cleaned)
        return result

    def _arena_path(self, selected_codes: list[str], *, export_mode: bool = False) -> str:
        path = "/arena/export" if export_mode else "/arena"
        if not selected_codes:
            return path
        return f"{path}?{urlencode([('selected', code) for code in selected_codes], doseq=True)}"

    def _arena_artifact_path(self, selected_codes: list[str]) -> str:
        path = "/arena/export/artifact.md"
        if not selected_codes:
            return path
        return f"{path}?{urlencode([('selected', code) for code in selected_codes], doseq=True)}"

    def _move_selection(self, selected_codes: list[str], code: str, direction: int) -> list[str]:
        result = list(selected_codes)
        if code not in result:
            return result
        index = result.index(code)
        target = index + direction
        if target < 0 or target >= len(result):
            return result
        result[index], result[target] = result[target], result[index]
        return result

    def _latest_release_posture(self) -> tuple[str, str]:
        latest_release = read_json(Path(self.config.runtime.state_root) / RELEASE_ROOT_NAME / LATEST_RELEASE_JSON)
        if latest_release is None:
            return ("not_run", "No release readiness artifact has been recorded in the local runtime yet.")
        verdict = latest_release.get("verdict") or {}
        return (str(verdict.get("status") or "not_run"), str(verdict.get("summary") or "No release readiness summary recorded."))

    def _arena_headline(self, project: ProjectSnapshot, comparison_trust: ComparisonTrust) -> str:
        return f"{project.canonical_project_code}: {self._brief_statement(self._project_change(project, comparison_trust), max_words=18)}"

    def _arena_risk_statement(self, project: ProjectSnapshot) -> str:
        if project.top_issues:
            return project.top_issues[0].detail
        if project.trust_indicator.status != "high":
            return project.trust_indicator.rationale[0]
        return "cause not yet identified"

    def _arena_why_it_matters(self, project: ProjectSnapshot) -> str:
        return self._project_why(project)

    def _arena_action_statement(self, project: ProjectSnapshot) -> str:
        return f"{self._project_action_owner(project)}: {self._project_action(project)}"

    def _arena_change_statement(self, project: ProjectSnapshot, comparison_trust: ComparisonTrust) -> str:
        return self._project_change(project, comparison_trust)

    def _arena_metrics(self, project: ProjectSnapshot) -> list[ArenaMetric]:
        metrics = [
            ArenaMetric(label="Health", value=f"{project.health.health_score:.1f}"),
            ArenaMetric(label="Risk", value=project.health.risk_level),
            ArenaMetric(label="Domain", value=project.domain.title()),
        ]
        metrics.append(ArenaMetric(label="Finish", value=self._projected_finish_label(project)))
        if project.delta.schedule.finish_date_movement_days is not None:
            metrics.append(ArenaMetric(label="Finish Move", value=self._project_delta_label(project)))
        if project.financial and project.financial.metrics.get("margin_percent") is not None:
            metrics.append(ArenaMetric(label="Margin", value=f"{project.financial.metrics['margin_percent']:.1f}%"))
        return metrics[:5]

    def _arena_evidence(self, project: ProjectSnapshot) -> list[str]:
        evidence = [issue.label + ": " + issue.detail for issue in project.top_issues[:3]]
        evidence.extend(change.summary for change in project.latest_notable_changes[:3])
        evidence.extend(project.trust_indicator.rationale[:2])
        return evidence[:6]

    def _comparison_label_for_project(self, project: ProjectSnapshot) -> str:
        if project.comparison_status == "trusted":
            return "Authoritative delta-driven ranking"
        if project.comparison_status == "contained":
            return "Trust-bounded ranking"
        return "Current-run-only ranking"

    def _project_comparison_detail(self, project: ProjectSnapshot, comparison_trust: ComparisonTrust) -> str:
        if project.comparison_status == "trusted":
            run_id = project.comparison_run_id or comparison_trust.comparison_run_id or "prior distinct run"
            return f"Delta-sensitive comparison is authoritative against {run_id}."
        if project.comparison_status == "contained":
            return f"{comparison_trust.baseline_label}. {comparison_trust.ranking_detail}"
        return f"{comparison_trust.baseline_label}. {comparison_trust.ranking_detail}"

    def _arena_scope_summary(self, selected_codes: list[str], *, fallback_to_current_lead: bool = False) -> str:
        if not selected_codes:
            return "No promoted projects are in the current meeting slate."
        if fallback_to_current_lead:
            return "Fallback review slate: " + ", ".join(selected_codes)
        return "Meeting slate: " + ", ".join(selected_codes)

    def _arena_selection_summary(self, selected_codes: list[str], *, fallback_to_current_lead: bool = False) -> str:
        if not selected_codes:
            return "No promoted items are currently selected."
        if fallback_to_current_lead:
            return "Showing current Control Tower lead: " + ", ".join(selected_codes)
        return "Agenda order: " + ", ".join(selected_codes)

    def _arena_artifact_filename(self, selected_codes: list[str]) -> str:
        suffix = "-".join(selected_codes) if selected_codes else "no-selection"
        return f"arena-executive-handoff-{suffix}.md"

    def _brief_statement(self, text: str, *, max_words: int) -> str:
        cleaned = " ".join(str(text).split()).strip()
        if not cleaned:
            return ""
        first_sentence = cleaned.split(". ", 1)[0].strip()
        words = first_sentence.rstrip(".!?").split()
        if len(words) > max_words:
            clipped = " ".join(words[:max_words]).rstrip(",;:")
            return clipped + "..."
        if first_sentence.endswith(("...", ".", "!", "?")):
            return first_sentence
        return first_sentence + "."

    def _count_phrase(self, count: int) -> str:
        noun = "item" if count == 1 else "items"
        return f"{count} {noun}"

    def _sentence_from_parts(self, parts: list[str]) -> str:
        cleaned = [str(part).strip().rstrip(".") for part in parts if str(part).strip()]
        if not cleaned:
            return ""
        sentence = "; ".join(cleaned)
        return sentence + "."


def _merge_identity(left: ProjectIdentity, right: ProjectIdentity) -> ProjectIdentity:
    method_rank = {"manual_override": 3, "raw_match": 2, "fuzzy_match": 1}
    winner = left if method_rank[left.match_method] >= method_rank[right.match_method] else right
    aliases = sorted({*left.aliases, *right.aliases})
    source_keys = sorted({*left.source_keys, *right.source_keys})
    return winner.model_copy(update={"aliases": aliases, "source_keys": source_keys})


def _dedupe_provenance(values: list[SourceArtifactRef]) -> list[SourceArtifactRef]:
    result: list[SourceArtifactRef] = []
    seen: set[tuple[str, str, str]] = set()
    for value in values:
        key = (value.source_system, value.artifact_type, value.path)
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result

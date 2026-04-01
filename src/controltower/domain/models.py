from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


HealthTier = Literal["healthy", "watch", "at_risk", "critical"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]
MatchMethod = Literal["manual_override", "fuzzy_match", "raw_match"]
NoteKind = Literal["project_dossier", "project_weekly_brief", "portfolio_weekly_summary"]
SurfaceDomain = Literal["professional", "personal"]
ComparisonTrustStatus = Literal["trusted", "contained", "unavailable"]
ComparisonAuthority = Literal["authoritative", "trust_bounded", "unavailable"]
FinishDriverType = Literal["activity", "milestone", "cycle", "open_end", "float_issue", "unknown"]
DriverComparisonState = Literal["same", "changed", "unavailable"]
DeterministicComparisonState = Literal["changed", "unchanged", "unavailable"]
ActionContinuityState = Literal["new_this_run", "carry_forward", "comparison_unavailable"]
ContinuityResolvedType = Literal["issue", "action"]
ReviewRunState = Literal["pending_review", "approved", "triggered", "rejected", "failed", "escalated"]
NotificationDeliveryStatus = Literal["sent", "failed", "not_configured", "suppressed"]
ReviewDecision = Literal["approved", "rejected"]
ReviewTriggerProvider = Literal["file", "webhook", "stub", "none"]
ReviewTriggerStatus = Literal[
    "not_started",
    "pending",
    "emitted",
    "skipped",
    "failed",
    "retryable",
    "blocked",
    "validation_failed",
]
ReviewPolicyRiskLevel = Literal["low", "medium", "high", "critical"]
ReviewDecisionMode = Literal["auto_approve", "manual_review", "escalate"]
NotificationSignalLevel = Literal["quiet", "normal", "high"]
ExecutionPackType = Literal[
    "deploy_pack",
    "smoke_pack",
    "release_readiness_pack",
    "report_pack",
    "continuity_pack",
    "noop_pack",
]
ExecutionAttemptStatus = Literal["succeeded", "failed"]
ExecutionAttemptFailureClass = Literal["retryable", "permanent"]
ExecutionLifecycleStatus = Literal["not_started", "queued", "succeeded", "failed", "partial"]
ExecutionDeliveryStatus = Literal["queued", "dispatching", "dispatched", "acknowledged", "failed", "dead_lettered"]
ExecutionCloseoutStatus = Literal["pending", "succeeded", "failed", "partial"]
ExecutionPackGuard = Literal["open", "guarded", "blocked"]
ExecutionPackValidationStatus = Literal["valid", "invalid"]


class SourceArtifactRef(BaseModel):
    source_system: Literal["schedulelab", "profitintel", "controltower"]
    artifact_type: str
    path: str
    relative_path: str | None = None
    run_timestamp: str | None = None
    status: Literal["resolved", "missing", "derived"] = "resolved"
    notes: str | None = None


class TrustIndicator(BaseModel):
    status: Literal["high", "partial", "low", "missing"]
    rationale: list[str] = Field(default_factory=list)
    missing_data_flags: list[str] = Field(default_factory=list)


class ComparisonTrust(BaseModel):
    status: ComparisonTrustStatus
    label: str
    detail: str
    comparison_run_id: str | None = None
    delta_ranking_enabled: bool = False
    reason_code: str = "no_prior_run"
    ranking_authority: ComparisonAuthority = "unavailable"
    ranking_label: str = "Change-sensitive ranking unavailable"
    ranking_detail: str = "A trusted prior comparison run is not available, so delta-driven ranking is not authoritative."
    baseline_label: str = "No comparison baseline"
    baseline_detail: str = "No trusted prior comparison baseline is available for this surface."


class DomainCoverage(BaseModel):
    domain: SurfaceDomain
    label: str
    available: bool
    item_count: int
    detail: str


class ProjectIdentity(BaseModel):
    canonical_project_id: str
    canonical_project_code: str
    project_name: str
    source_keys: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    match_method: MatchMethod = "raw_match"
    matched_on: str | None = None


class ScheduleDriver(BaseModel):
    label: str
    activity_id: str | None = None
    activity_name: str | None = None
    score: float | None = None
    rationale: str | None = None


class IssueDriver(BaseModel):
    source: Literal["schedule", "financial", "cross_source"]
    severity: Literal["high", "medium", "low"]
    label: str
    detail: str


class RecommendedAction(BaseModel):
    priority: Literal["high", "medium", "low"]
    owner_hint: str
    action: str


class ScheduleSummary(BaseModel):
    project_code: str
    project_name: str
    run_timestamp: str | None = None
    schedule_date: str | None = None
    finish_date: str | None = None
    finish_source: str | None = None
    finish_source_label: str = "Finish signal unavailable"
    finish_detail: str = "No finish milestone/date was found in the published schedule artifact."
    finish_artifact_path: str | None = None
    finish_activity_id: str | None = None
    finish_activity_name: str | None = None
    health_score: float | None = None
    issues_total: int | None = None
    activity_count: int | None = None
    relationship_count: int | None = None
    negative_float_count: int | None = None
    open_start_count: int | None = None
    open_finish_count: int | None = None
    cycle_count: int | None = None
    top_driver_count: int | None = None
    risk_path_count: int | None = None
    milestone_count: int | None = None
    recovery_lever_count: int | None = None
    field_question_count: int | None = None
    parser_warning_count: int | None = None
    rows_dropped_or_skipped: int | None = None
    total_float_days: float | None = None
    critical_path_activity_count: int | None = None
    risk_flags: list[str] = Field(default_factory=list)
    top_drivers: list[ScheduleDriver] = Field(default_factory=list)
    source_file: str | None = None
    trust: TrustIndicator
    provenance: list[SourceArtifactRef] = Field(default_factory=list)


class MetricVariance(BaseModel):
    metric_name: str
    current_value: float | None = None
    comparison_value: float | None = None
    absolute_change: float | None = None
    percent_change: float | None = None
    trend_direction: Literal["up", "down", "flat"] = "flat"


class FinancialSummary(BaseModel):
    project_slug: str
    report_month: str | None = None
    comparison_month: str | None = None
    snapshot_timestamp: str | None = None
    snapshot_id: int | None = None
    snapshot_version: int | None = None
    parse_status: str | None = None
    completeness_score: float | None = None
    completeness_label: str | None = None
    trusted: bool = False
    comparison_eligible: bool = False
    trust_tier: Literal["high", "partial", "low", "missing"] = "missing"
    trust_reasons: list[str] = Field(default_factory=list)
    metrics: dict[str, float | None] = Field(default_factory=dict)
    variances: list[MetricVariance] = Field(default_factory=list)
    executive_summary: str = ""
    key_findings: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    trust: TrustIndicator
    source_file_name: str | None = None
    source_file_path: str | None = None
    provenance: list[SourceArtifactRef] = Field(default_factory=list)


class ScheduleDelta(BaseModel):
    current_finish_date: str | None = None
    previous_finish_date: str | None = None
    finish_date_movement_days: int | None = None
    finish_date_movement_reason: str | None = None
    current_float_days: float | None = None
    previous_float_days: float | None = None
    float_movement_days: float | None = None
    float_direction: Literal["compression", "expansion", "flat", "unknown"] = "unknown"
    critical_path_changed: bool = False
    current_critical_path_activity_count: int | None = None
    previous_critical_path_activity_count: int | None = None
    summary: str = ""


class FinancialDelta(BaseModel):
    current_cost_variance: float | None = None
    previous_cost_variance: float | None = None
    cost_variance_change: float | None = None
    current_margin_percent: float | None = None
    previous_margin_percent: float | None = None
    margin_movement: float | None = None
    summary: str = ""


class RiskDelta(BaseModel):
    new_risks: list[str] = Field(default_factory=list)
    resolved_risks: list[str] = Field(default_factory=list)
    worsening_signals: list[str] = Field(default_factory=list)
    summary: str = ""


class ProjectDeltaDetails(BaseModel):
    schedule: ScheduleDelta = Field(default_factory=ScheduleDelta)
    financial: FinancialDelta = Field(default_factory=FinancialDelta)
    risk: RiskDelta = Field(default_factory=RiskDelta)
    summary: str = ""


class HealthAssessment(BaseModel):
    health_score: float
    risk_level: RiskLevel
    score: float
    tier: HealthTier
    rationale: list[str]
    required_actions: list[RecommendedAction]
    recommended_actions: list[RecommendedAction]


class ChangeNote(BaseModel):
    source: Literal["schedule", "financial", "cross_source"]
    summary: str


class FinishDriverSummary(BaseModel):
    controlling_driver: str = "Driver unavailable"
    driver_type: FinishDriverType = "unknown"
    why_it_matters: str = "No published finish-driver signal is available for this project."
    comparison_state: DriverComparisonState = "unavailable"
    comparison_label: str = "No trusted prior driver comparison available"
    comparison_detail: str = "No trusted prior driver comparison is available for this project."
    previous_driver: str | None = None


class DeterministicPanelValue(BaseModel):
    value: str = "not available"
    available: bool = False
    reason: str | None = None


class FinishDriverDetail(BaseModel):
    driver_label: str = "Driver unavailable"
    driver_type: FinishDriverType = "unknown"
    activity_id: DeterministicPanelValue = Field(default_factory=DeterministicPanelValue)
    activity_name: DeterministicPanelValue = Field(default_factory=DeterministicPanelValue)
    why_controlling_finish: str = "No published finish-driver signal is available for this project."
    float_signal: DeterministicPanelValue = Field(default_factory=DeterministicPanelValue)
    constraint_signal: DeterministicPanelValue = Field(default_factory=DeterministicPanelValue)
    sequence_context: DeterministicPanelValue = Field(default_factory=DeterministicPanelValue)


class FinishDriverInvestigation(BaseModel):
    current_driver: FinishDriverDetail = Field(default_factory=FinishDriverDetail)
    prior_driver_presence: DeterministicPanelValue = Field(default_factory=DeterministicPanelValue)
    replacement_detail: DeterministicPanelValue = Field(default_factory=DeterministicPanelValue)
    comparison_summary: str = "No trusted prior driver comparison is available for this project."


class DriverChangeInvestigation(BaseModel):
    available: bool = False
    reason: str = "Driver change exploration is not available."
    difference_summary: str = "No deterministic driver change summary is available."
    current_driver: FinishDriverDetail = Field(default_factory=FinishDriverDetail)
    prior_driver: FinishDriverDetail = Field(default_factory=FinishDriverDetail)


class ChangeAnswer(BaseModel):
    state: DeterministicComparisonState = "unavailable"
    label: str
    detail: str


class ChangeIntelligenceSummary(BaseModel):
    finish: ChangeAnswer = Field(
        default_factory=lambda: ChangeAnswer(
            label="Finish movement unavailable",
            detail="No trusted prior finish baseline is available.",
        )
    )
    driver: ChangeAnswer = Field(
        default_factory=lambda: ChangeAnswer(
            label="Driver comparison unavailable",
            detail="No trusted prior driver comparison is available.",
        )
    )
    risk: ChangeAnswer = Field(
        default_factory=lambda: ChangeAnswer(
            label="New risk comparison unavailable",
            detail="No trusted prior risk comparison is available.",
        )
    )
    action: ChangeAnswer = Field(
        default_factory=lambda: ChangeAnswer(
            label="Action comparison unavailable",
            detail="No trusted prior action comparison is available.",
        )
    )


class MeetingPacketItem(BaseModel):
    canonical_project_code: str = ""
    project_name: str = ""
    finish_statement: str = "Projected finish unavailable."
    delta_statement: str = "Movement vs prior trusted run unavailable."
    status_label: str = "DELTA UNAVAILABLE"
    status_detail: str = "No trusted prior baseline is available."
    controlling_driver: str = "Driver unavailable"
    driver_reason: str = "No published finish-driver signal is available for this project."
    what_changed: list[str] = Field(default_factory=list)
    challenge_next: str = "None emitted from deterministic signals."
    required_actions: list[str] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    trust_posture: str = "Current-run-only ranking"
    baseline_posture: str = "No comparison baseline"
    drilldown_path: str = ""
    compare_path: str = ""


class ActionQueueItem(BaseModel):
    queue_id: str
    canonical_project_code: str
    project_name: str
    owner_role: str
    action_text: str
    timing: str
    reason_source_signal: str
    priority: Literal["high", "medium", "low"] | None = None
    priority_basis: str | None = None
    continuity_state: ActionContinuityState = "comparison_unavailable"
    continuity_label: str = "Continuity unavailable"
    continuity_detail: str = "No trusted prior action comparison is available."
    drilldown_path: str = ""
    compare_path: str = ""


class ActionQueueGroup(BaseModel):
    key: str
    label: str
    summary: str
    item_count: int
    items: list[ActionQueueItem] = Field(default_factory=list)


class ActionQueueView(BaseModel):
    title: str = "Action Queue"
    summary: str = "No trackable actions were emitted from the current deterministic signals."
    item_count: int = 0
    groups: list[ActionQueueGroup] = Field(default_factory=list)


class ContinuityResolvedItem(BaseModel):
    canonical_project_code: str
    project_name: str
    item_type: ContinuityResolvedType = "issue"
    summary: str
    detail: str
    resolution_basis: str
    compare_path: str = ""


class ProjectContinuitySummary(BaseModel):
    comparison_state: ComparisonTrustStatus = "unavailable"
    comparison_label: str = "Continuity unavailable"
    comparison_detail: str = "No trusted prior continuity baseline is available."
    new_action_count: int = 0
    carry_forward_action_count: int = 0
    resolved_item_count: int = 0
    resolved_items: list[ContinuityResolvedItem] = Field(default_factory=list)
    summary: str = "No trusted prior continuity baseline is available."


class ContinuityView(BaseModel):
    title: str = "Continuity"
    summary: str = "No trusted prior continuity baseline is available."
    comparison_label: str = "Continuity unavailable"
    comparison_detail: str = "No trusted prior continuity baseline is available."
    new_action_count: int = 0
    carry_forward_action_count: int = 0
    resolved_item_count: int = 0
    resolved_items: list[ContinuityResolvedItem] = Field(default_factory=list)


class MeetingPacketView(BaseModel):
    title: str = "Meeting Packet"
    summary: str = "No meeting packet items are currently in scope."
    item_count: int = 0
    items: list[MeetingPacketItem] = Field(default_factory=list)


class ProjectSnapshot(BaseModel):
    identity: ProjectIdentity
    canonical_project_id: str
    canonical_project_code: str
    project_name: str
    domain: SurfaceDomain = "professional"
    source_keys: list[str] = Field(default_factory=list)
    source_project_keys: dict[str, str] = Field(default_factory=dict)
    snapshot_timestamp: str
    schedule: ScheduleSummary | None = None
    financial: FinancialSummary | None = None
    delta: ProjectDeltaDetails = Field(default_factory=ProjectDeltaDetails)
    health: HealthAssessment
    top_issues: list[IssueDriver] = Field(default_factory=list)
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)
    latest_notable_changes: list[ChangeNote] = Field(default_factory=list)
    executive_summary: str
    provenance: list[SourceArtifactRef] = Field(default_factory=list)
    missing_data_flags: list[str] = Field(default_factory=list)
    trust_indicator: TrustIndicator
    comparison_status: ComparisonTrustStatus = "unavailable"
    comparison_run_id: str | None = None
    finish_driver: FinishDriverSummary = Field(default_factory=FinishDriverSummary)
    finish_driver_investigation: FinishDriverInvestigation = Field(default_factory=FinishDriverInvestigation)
    driver_change_investigation: DriverChangeInvestigation = Field(default_factory=DriverChangeInvestigation)
    change_intelligence: ChangeIntelligenceSummary = Field(default_factory=ChangeIntelligenceSummary)
    challenge_next: str | None = None
    meeting_packet: MeetingPacketItem = Field(default_factory=MeetingPacketItem)
    action_queue: list[ActionQueueItem] = Field(default_factory=list)
    continuity: ProjectContinuitySummary = Field(default_factory=ProjectContinuitySummary)
    attention_rank: int | None = None
    attention_score: float | None = None


class PortfolioSummary(BaseModel):
    generated_at: str
    project_count: int
    active_project_count: int
    tier_counts: dict[str, int]
    average_health_score: float | None = None
    overall_posture: str
    risk_distribution: dict[str, int] = Field(default_factory=dict)
    top_at_risk_projects: list[str] = Field(default_factory=list)
    top_5_at_risk_projects: list[str] = Field(default_factory=list)
    cross_project_risk_themes: list[str] = Field(default_factory=list)
    biggest_movers: list[str] = Field(default_factory=list)
    key_actions_this_week: list[str] = Field(default_factory=list)
    portfolio_changes: list[str] = Field(default_factory=list)
    project_rankings: list[ProjectSnapshot] = Field(default_factory=list)
    provenance: list[SourceArtifactRef] = Field(default_factory=list)
    comparison_trust: ComparisonTrust = Field(
        default_factory=lambda: ComparisonTrust(
            status="unavailable",
            label="Delta baseline unavailable",
            detail="No prior distinct run is available yet, so change-sensitive ranking is suppressed.",
            delta_ranking_enabled=False,
            reason_code="no_prior_run",
            ranking_authority="trust_bounded",
            ranking_label="Trust-bounded ranking",
            ranking_detail="Current-run risk, health, and trust signals are visible, but delta-driven ranking is not authoritative yet.",
            baseline_label="No prior comparison baseline",
            baseline_detail="No trusted prior comparison run is available yet, so change-sensitive ranking is suppressed.",
        )
    )
    domain_coverage: list[DomainCoverage] = Field(default_factory=list)


class ControlTowerHeadline(BaseModel):
    overall_posture: str
    intervention_count: int
    high_risk_count: int
    immediate_action_count: int
    readiness_status: str
    readiness_summary: str
    arena_candidate_count: int


class ControlTowerAttentionItem(BaseModel):
    canonical_project_code: str
    project_name: str
    domain: SurfaceDomain
    posture: str
    risk_level: RiskLevel
    tier: HealthTier
    health_score: float
    what_changed: str
    why_it_matters: str
    required_action: str
    action_owner: str
    action_timing: str
    cause: str
    impact: str
    schedule_signal: str
    current_finish_date: str | None = None
    finish_delta_days: int | None = None
    finish_statement: str = ""
    delta_statement: str = ""
    finish_authority_state: str = ""
    finish_source_label: str = ""
    finish_source_detail: str = ""
    ranking_reason: str
    trust_status: Literal["high", "partial", "low", "missing"]
    comparison_label: str = ""
    comparison_detail: str = ""
    drilldown_path: str
    compare_path: str
    arena_add_path: str
    arena_remove_path: str
    arena_promoted: bool = False
    arena_group: str = "Operational Priorities"


class SecondarySurfaceLink(BaseModel):
    label: str
    path: str
    detail: str


class ExecutionBriefSection(BaseModel):
    key: str
    label: str
    lines: list[str] = Field(default_factory=list)


class ExecutionBrief(BaseModel):
    finish_summary: ExecutionBriefSection
    driver_statement: ExecutionBriefSection
    risks_list: ExecutionBriefSection
    need_statement: ExecutionBriefSection
    doing_statement: ExecutionBriefSection

    @property
    def sections(self) -> tuple[ExecutionBriefSection, ...]:
        return (
            self.finish_summary,
            self.driver_statement,
            self.risks_list,
            self.need_statement,
            self.doing_statement,
        )


class SurfaceScanCard(BaseModel):
    key: str
    label: str
    summary: str
    detail: str = ""
    item_count: int = 0
    project_code: str | None = None


class ProjectCommandView(BaseModel):
    canonical_project_code: str
    project_name: str
    projected_finish_date: str | None = None
    projected_finish_label: str
    projected_finish_reason: str | None = None
    movement_days: int | None = None
    movement_label: str
    movement_reason: str | None = None
    risk_level: RiskLevel
    finish_authority_state: str
    finish_source_label: str = ""
    finish_source_detail: str = ""
    primary_issue: str
    action_owner: str
    action_summary: str
    required_action: str
    action_timing: str
    trust_label: str
    trust_detail: str
    finish_driver: FinishDriverSummary = Field(default_factory=FinishDriverSummary)
    finish_driver_investigation: FinishDriverInvestigation = Field(default_factory=FinishDriverInvestigation)
    driver_change_investigation: DriverChangeInvestigation = Field(default_factory=DriverChangeInvestigation)
    change_intelligence: ChangeIntelligenceSummary = Field(default_factory=ChangeIntelligenceSummary)
    execution_brief: ExecutionBrief
    challenge_next: str | None = None
    drilldown_path: str = ""


class NarrativeBullet(BaseModel):
    canonical_project_code: str | None = None
    project_name: str
    who: str
    finish: str
    delta: str
    what: str
    why: str
    action: str
    summary: str
    detail: str = ""
    cause: str = ""
    impact: str = ""
    timing: str = ""
    owner: str | None = None
    current_finish_date: str | None = None
    finish_delta_days: int | None = None

    def model_post_init(self, __context: Any) -> None:
        missing = [
            field_name.upper()
            for field_name, value in (
                ("who", self.who),
                ("finish", self.finish),
                ("delta", self.delta),
                ("what", self.what),
                ("why", self.why),
                ("action", self.action),
            )
            if not str(value or "").strip()
        ]
        if missing:
            raise ValueError(f"Narrative contract incomplete for {self.project_name}: missing {', '.join(missing)}")


class NarrativeSection(BaseModel):
    key: str
    label: str
    title: str
    summary: str
    item_count: int
    lead_project_code: str | None = None
    default_open: bool = False
    items: list[NarrativeBullet] = Field(default_factory=list)


class ControlTowerView(BaseModel):
    generated_at: str
    headline: ControlTowerHeadline
    comparison_trust: ComparisonTrust
    primary_project_answer: ProjectCommandView | None = None
    executive_scan: list[SurfaceScanCard] = Field(default_factory=list)
    material_changes_section: NarrativeSection
    required_actions_section: NarrativeSection
    rising_risks_section: NarrativeSection
    watch_items_section: NarrativeSection
    domain_coverage: list[DomainCoverage] = Field(default_factory=list)
    top_attention: list[ControlTowerAttentionItem] = Field(default_factory=list)
    intervention_required: list[ControlTowerAttentionItem] = Field(default_factory=list)
    arena_candidates: list[ControlTowerAttentionItem] = Field(default_factory=list)
    selected_arena_codes: list[str] = Field(default_factory=list)
    arena_path: str = "/arena"
    arena_export_path: str = "/arena/export"
    arena_artifact_path: str = "/arena/export/artifact.md"
    meeting_packet: MeetingPacketView = Field(default_factory=MeetingPacketView)
    action_queue: ActionQueueView = Field(default_factory=ActionQueueView)
    continuity: ContinuityView = Field(default_factory=ContinuityView)
    secondary_links: list[SecondarySurfaceLink] = Field(default_factory=list)


class ArenaMetric(BaseModel):
    label: str
    value: str


class ArenaItem(BaseModel):
    canonical_project_code: str
    project_name: str
    domain: SurfaceDomain
    group: str
    posture: str
    headline: str
    risk_statement: str
    why_it_matters_statement: str = ""
    action_statement: str
    change_statement: str
    cause_statement: str = ""
    impact_statement: str = ""
    action_timing: str = ""
    schedule_signal: str = ""
    current_finish_date: str | None = None
    finish_delta_days: int | None = None
    finish_statement: str = ""
    delta_statement: str = ""
    finish_authority_state: str = ""
    finish_source_label: str = ""
    finish_source_detail: str = ""
    comparison_label: str = ""
    comparison_detail: str = ""
    finish_driver: FinishDriverSummary = Field(default_factory=FinishDriverSummary)
    change_intelligence: ChangeIntelligenceSummary = Field(default_factory=ChangeIntelligenceSummary)
    challenge_next: str | None = None
    metrics: list[ArenaMetric] = Field(default_factory=list)
    evidence_points: list[str] = Field(default_factory=list)
    move_up_path: str | None = None
    move_down_path: str | None = None
    remove_path: str
    drilldown_path: str
    compare_path: str


class ArenaView(BaseModel):
    generated_at: str
    title: str
    subtitle: str
    export_title: str
    export_path: str
    artifact_title: str = "Arena Executive Handoff"
    artifact_path: str = "/arena/export/artifact.md"
    scope_summary: str = ""
    selection_summary: str = ""
    promotion_summary: str = ""
    headline_posture: str = ""
    project_answers: list[ProjectCommandView] = Field(default_factory=list)
    executive_scan: list[SurfaceScanCard] = Field(default_factory=list)
    material_changes_section: NarrativeSection
    why_it_matters_section: NarrativeSection
    required_actions_section: NarrativeSection
    rising_risks_section: NarrativeSection
    comparison_trust: ComparisonTrust
    items: list[ArenaItem] = Field(default_factory=list)
    selected_arena_codes: list[str] = Field(default_factory=list)
    meeting_packet: MeetingPacketView = Field(default_factory=MeetingPacketView)
    action_queue: ActionQueueView = Field(default_factory=ActionQueueView)
    continuity: ContinuityView = Field(default_factory=ContinuityView)
    empty_state: str


class GeneratedNote(BaseModel):
    note_kind: NoteKind
    canonical_project_code: str | None = None
    title: str
    frontmatter: dict[str, Any]
    body: str
    output_path: Path
    preview_path: Path | None = None
    versioned_output_paths: list[Path] = Field(default_factory=list)
    wikilinks: list[str] = Field(default_factory=list)

    def full_markdown(self) -> str:
        return self.body


class ProjectDelta(BaseModel):
    project_id: str
    delta: ProjectDeltaDetails


class ExportRecord(BaseModel):
    run_id: str
    generated_at: str
    preview_only: bool
    notes: list[GeneratedNote]
    vault_root: str
    status: Literal["success", "partial", "failed"]
    issues: list[str] = Field(default_factory=list)
    source_artifacts: list[SourceArtifactRef] = Field(default_factory=list)
    previous_run_id: str | None = None
    portfolio_snapshot: PortfolioSummary | None = None
    project_snapshots: list[ProjectSnapshot] = Field(default_factory=list)
    project_deltas: list[ProjectDelta] = Field(default_factory=list)


class PublishContinuityView(BaseModel):
    status: Literal["material_change", "no_material_change", "unavailable"] = "unavailable"
    status_label: str = "Prior issued output unavailable"
    summary: str = "No prior issued output is available for deterministic comparison."
    detail_lines: list[str] = Field(default_factory=list)
    prior_run_id: str | None = None
    prior_generated_at: str | None = None
    compare_label: str = "Previous issued run unavailable"


class PublishArtifactAvailability(BaseModel):
    key: NoteKind
    label: str
    available: bool
    count: int = 0


class PublishArtifactPreviewMetadata(BaseModel):
    title: str | None = None
    project_name: str | None = None
    project_code: str | None = None
    run_date: str | None = None
    generated_at: str | None = None
    health_tier: str | None = None
    risk_level: str | None = None
    health_score: str | None = None


class PublishArtifactView(BaseModel):
    artifact_id: str
    note_kind: NoteKind
    artifact_type_label: str
    title: str
    project_name: str | None = None
    project_code: str | None = None
    generated_at: str
    is_latest: bool = False
    is_selected: bool = False
    issue_state_label: str = "Historical output"
    issue_state_class: str = "historical"
    authority_label: str = "Issued document"
    source_run_id: str = ""
    preview_metadata: PublishArtifactPreviewMetadata = Field(default_factory=PublishArtifactPreviewMetadata)
    preview_html: str = ""
    preview_summary: str = ""
    copy_text: str = ""
    open_path: str
    print_path: str
    source_path: str
    obsidian_url: str | None = None
    continuity: PublishContinuityView = Field(default_factory=PublishContinuityView)


class PublishHistoryItem(BaseModel):
    run_id: str
    generated_at: str
    status: Literal["success", "partial", "failed"]
    preview_only: bool
    is_latest: bool = False
    issue_state_label: str = "Historical output"
    focus_project_name: str | None = None
    focus_project_code: str | None = None
    artifact_availability: list[PublishArtifactAvailability] = Field(default_factory=list)
    open_path: str
    latest_artifact_path: str | None = None
    open_output_path: str | None = None


class PublishProjectOption(BaseModel):
    canonical_project_code: str
    project_name: str
    is_selected: bool = False
    open_path: str


class PublishView(BaseModel):
    available: bool = False
    run_id: str | None = None
    generated_at: str | None = None
    status: Literal["success", "partial", "failed"] | None = None
    preview_only: bool = False
    command_brief: ProjectCommandView | None = None
    command_status_label: str = "DELTA UNAVAILABLE"
    command_status_class: str = "unknown"
    command_brief_copy_text: str = ""
    comparison_summary_lines: list[str] = Field(default_factory=list)
    continuity: PublishContinuityView = Field(default_factory=PublishContinuityView)
    arena_path: str = "/arena"
    present_path: str = "/publish/present"
    print_path: str = "/publish?print=1"
    latest_artifact_path: str | None = None
    obsidian_artifact_path: str | None = None
    exports_debug_path: str = "/exports/latest"
    selected_artifact: PublishArtifactView | None = None
    artifacts: list[PublishArtifactView] = Field(default_factory=list)
    project_switches: list[PublishProjectOption] = Field(default_factory=list)
    history: list[PublishHistoryItem] = Field(default_factory=list)


class ReviewArtifactRef(BaseModel):
    label: str
    file_name: str
    path: str
    source_path: str | None = None
    content_type: str = "application/octet-stream"
    size_bytes: int | None = None
    download_path: str = ""


class ReviewNotification(BaseModel):
    provider: str = "runtime_log"
    status: NotificationDeliveryStatus = "not_configured"
    signal_level: NotificationSignalLevel = "normal"
    title: str = ""
    body: str = ""
    notification_id: str | None = None
    sent_at: str | None = None
    record_path: str | None = None


class ReviewDecisionMetadata(BaseModel):
    reviewed_at: str | None = None
    reviewer_action: ReviewDecision | None = None
    approved_next_prompt: str | None = None
    rejection_note: str | None = None
    reviewer_identity: str | None = None
    auth_mode: str | None = None
    source_ip: str | None = None
    forwarded_for: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    correlation_id: str | None = None


class ReviewAuditEntry(BaseModel):
    event_id: str
    recorded_at: str
    event_type: str
    state: ReviewRunState
    message: str
    request_id: str | None = None
    correlation_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    record_path: str | None = None


class ReviewFailure(BaseModel):
    recorded_at: str
    phase: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ExecutionPackRecord(BaseModel):
    pack_id: str = "pack_noop_v1"
    pack_type: ExecutionPackType = "noop_pack"
    selected_at: str | None = None
    selected_by: str = "deterministic_rules_v1"
    selection_reason: str = "No execution pack has been selected yet."
    matched_keywords: list[str] = Field(default_factory=list)
    trigger_conditions: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)
    execution_mode: str = "operator_visible_noop"
    downstream_target: str = "operator_visibility_only"
    expected_outputs: list[str] = Field(default_factory=list)
    timeout_seconds: int = 300
    retry_limit: int = 0
    retry_posture: str = "No downstream retries are configured for this pack."
    pack_guard: ExecutionPackGuard = "open"
    guard_reasons: list[str] = Field(default_factory=list)
    guard_evaluated_at: str | None = None
    validation_status: ExecutionPackValidationStatus = "valid"
    validation_errors: list[str] = Field(default_factory=list)
    validated_at: str | None = None


class ExecutionEventArtifact(BaseModel):
    label: str
    file_name: str
    path: str
    source_path: str | None = None
    download_path: str | None = None


class ExecutionEventRecord(BaseModel):
    event_type: str = "codex_run.approved"
    event_version: str = "v1"
    event_id: str | None = None
    trigger_id: str | None = None
    run_id: str | None = None
    workspace: str | None = None
    title: str | None = None
    risk_level: ReviewPolicyRiskLevel | None = None
    decision_mode: ReviewDecisionMode | None = None
    decision_reasons: list[str] = Field(default_factory=list)
    approved_at: str | None = None
    approved_by: str | None = None
    approved_next_prompt: str | None = None
    review_url: str | None = None
    artifacts: list[ExecutionEventArtifact] = Field(default_factory=list)
    source: str = "controltower_orchestration"
    pack_hint: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None


class ExecutionEmissionAttempt(BaseModel):
    attempt_number: int
    attempted_at: str
    provider: ReviewTriggerProvider
    target: str | None = None
    status: ExecutionAttemptStatus
    failure_class: ExecutionAttemptFailureClass | None = None
    retryable: bool = False
    backoff_ms: int | None = None
    response_status: int | None = None
    response_excerpt: str | None = None
    error_message: str | None = None
    result_path: str | None = None
    dead_letter_path: str | None = None


class ExecutionResultArtifact(BaseModel):
    label: str
    path: str
    content_type: str | None = None
    external_url: str | None = None


class ExecutionResultRecord(BaseModel):
    event_id: str | None = None
    run_id: str | None = None
    pack_id: str | None = None
    pack_type: ExecutionPackType | None = None
    status: ExecutionLifecycleStatus = "not_started"
    summary: str | None = None
    output_artifacts: list[ExecutionResultArtifact] = Field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    external_reference: str | None = None
    logs_excerpt: str | None = None
    result_path: str | None = None
    recorded_at: str | None = None
    closeout_status: ExecutionCloseoutStatus = "pending"
    closeout_recorded_at: str | None = None
    closeout_json_path: str | None = None
    closeout_markdown_path: str | None = None
    closeout_summary: str | None = None


class ReviewTriggerRecord(BaseModel):
    provider: ReviewTriggerProvider = "none"
    execution_event_id: str | None = None
    trigger_id: str | None = None
    event_id: str | None = None
    pack_id: str | None = None
    pack_type: ExecutionPackType | None = None
    event_version: str | None = None
    status: ReviewTriggerStatus = "not_started"
    delivery_status: ExecutionDeliveryStatus | None = None
    requested_at: str | None = None
    first_attempted_at: str | None = None
    last_attempt_at: str | None = None
    last_attempted_at: str | None = None
    emitted_at: str | None = None
    attempt_count: int = 0
    target: str | None = None
    payload_path: str | None = None
    result_path: str | None = None
    response_status: int | None = None
    response_excerpt: str | None = None
    error_message: str | None = None
    last_error: str | None = None
    dead_letter_path: str | None = None
    downstream_reference: str | None = None
    closeout_status: ExecutionCloseoutStatus = "pending"
    closeout_recorded_at: str | None = None
    attempts: list[ExecutionEmissionAttempt] = Field(default_factory=list)


class ReviewContinuityRecord(BaseModel):
    written_at: str | None = None
    runtime_markdown_path: str | None = None
    vault_markdown_path: str | None = None
    strategic_checkin_written_at: str | None = None
    session_log_note_path: str | None = None
    active_control_note_path: str | None = None


class ReviewRun(BaseModel):
    run_id: str
    title: str
    workspace: str
    summary: str
    raw_output_excerpt: list[str] = Field(default_factory=list)
    proposed_next_prompt: str
    state: ReviewRunState = "pending_review"
    created_at: str
    review_url: str
    detail_path: str
    approve_path: str
    reject_path: str
    source_operation_id: str | None = None
    release_generated_at: str | None = None
    artifacts: list[ReviewArtifactRef] = Field(default_factory=list)
    decision_artifacts: list[ReviewArtifactRef] = Field(default_factory=list)
    risk_level: ReviewPolicyRiskLevel = "medium"
    decision_mode: ReviewDecisionMode = "manual_review"
    decision_reasons: list[str] = Field(default_factory=lambda: ["Policy metadata unavailable for this persisted run."])
    policy_version: str = "legacy"
    auto_approved_at: str | None = None
    escalated_at: str | None = None
    policy_evaluated_at: str = Field(default_factory=lambda: utc_now_iso())
    notification: ReviewNotification = Field(default_factory=ReviewNotification)
    reviewer: ReviewDecisionMetadata = Field(default_factory=ReviewDecisionMetadata)
    audit_trail: list[ReviewAuditEntry] = Field(default_factory=list)
    trigger: ReviewTriggerRecord = Field(default_factory=ReviewTriggerRecord)
    execution_pack: ExecutionPackRecord = Field(default_factory=ExecutionPackRecord)
    execution_event: ExecutionEventRecord = Field(default_factory=ExecutionEventRecord)
    execution_result: ExecutionResultRecord = Field(default_factory=ExecutionResultRecord)
    continuity: ReviewContinuityRecord = Field(default_factory=ReviewContinuityRecord)
    last_error: ReviewFailure | None = None


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

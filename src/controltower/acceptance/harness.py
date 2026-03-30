from __future__ import annotations

import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
import yaml

from controltower.api.app import create_app
from controltower.config import ControlTowerConfig
from controltower.domain.models import utc_now_iso
from controltower.services.controltower import ControlTowerService
from controltower.services.meeting_readiness import verify_meeting_readiness


def run_acceptance(config: ControlTowerConfig) -> dict:
    with TemporaryDirectory(prefix="controltower-acceptance-") as tmp_dir:
        temp_root = Path(tmp_dir)
        effective_config = config.model_copy(
            deep=True,
            update={
                "obsidian": config.obsidian.model_copy(update={"vault_root": temp_root / "vault"}),
                "runtime": config.runtime.model_copy(update={"state_root": temp_root / "state"}),
            },
        )
        config_path = temp_root / "acceptance_config.yaml"
        config_path.write_text(yaml.safe_dump(effective_config.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
        service = ControlTowerService(effective_config)
        validation_issues = service.validate_sources()

        seed_record = service.export_notes(preview_only=False)
        contained_client = TestClient(create_app(str(config_path)))
        contained_selected_code = None
        contained_export_context_rendered = False
        no_distinct_prior_is_contained = False
        if seed_record.project_snapshots:
            contained_selected_code = seed_record.project_snapshots[0].canonical_project_code
            contained_arena_view = service.build_arena([contained_selected_code])
            contained_artifact_response = contained_client.get(f"/arena/export/artifact.md?selected={contained_selected_code}")
            contained_export_context_rendered = all(
                snippet in contained_artifact_response.text
                for snippet in (
                    contained_arena_view.scope_summary,
                    contained_arena_view.selection_summary,
                    contained_arena_view.promotion_summary,
                    contained_arena_view.comparison_trust.ranking_label,
                    contained_arena_view.comparison_trust.baseline_label,
                )
            ) and "Generated at:" in contained_artifact_response.text
            no_distinct_prior_is_contained = (
                contained_arena_view.comparison_trust.reason_code == "no_distinct_prior_run"
                and contained_arena_view.comparison_trust.ranking_authority == "trust_bounded"
                and "No distinct trusted prior baseline" in contained_artifact_response.text
            )
        time.sleep(1.1)
        record = service.export_notes(preview_only=False)
        app = create_app(str(config_path))
        client = TestClient(app)

        portfolio_response = client.get("/api/portfolio")
        projects_response = client.get("/projects")
        arena_response = client.get("/arena")
        export_response = client.get("/exports/latest")
        runs_response = client.get("/runs")
        diagnostics_response = client.get("/diagnostics")
        diagnostics_api_response = client.get("/api/diagnostics")
        diagnostics_payload = diagnostics_api_response.json() if diagnostics_api_response.status_code == 200 else {}
        runtime_coherence = service.build_runtime_coherence_snapshot()
        meeting_readiness = verify_meeting_readiness(effective_config)

        project_ids = [project.canonical_project_id for project in record.project_snapshots]
        zero_duplicates = len(project_ids) == len(set(project_ids))
        delta_complete = len(record.project_deltas) == len(record.project_snapshots) and all(
            project.delta.summary for project in record.project_snapshots
        )
        required_actions_complete = all(
            project.health.required_actions for project in record.project_snapshots if project.health.tier != "healthy"
        )
        weekly_note = next((note for note in record.notes if note.note_kind == "project_weekly_brief"), None)
        portfolio_note = next((note for note in record.notes if note.note_kind == "portfolio_weekly_summary"), None)
        markdown_sections_present = bool(
            weekly_note
            and portfolio_note
            and "## What Changed This Week" in weekly_note.body
            and "## Top Risks" in weekly_note.body
            and "## Required Actions" in weekly_note.body
            and "## Key Metrics" in weekly_note.body
            and "## Portfolio Risk Ranking" in portfolio_note.body
        )
        compare_status = 404
        arena_selected_status = arena_response.status_code
        arena_export_status = client.get("/arena/export").status_code
        arena_artifact_status = client.get("/arena/export/artifact.md").status_code
        arena_artifact_body = client.get("/arena/export/artifact.md").text
        root_redirects_to_publish = False
        root_publish_rendered = False
        legacy_control_available = False
        arena_trust_rendered = False
        export_context_rendered = False
        diagnostics_match_runtime = False
        if record.project_snapshots:
            compare_status = client.get(f"/projects/{record.project_snapshots[0].canonical_project_code}/compare").status_code
            selected_code = record.project_snapshots[0].canonical_project_code
            selected_arena_response = client.get(
                f"/arena?selected={record.project_snapshots[0].canonical_project_code}"
            )
            selected_artifact_response = client.get(
                f"/arena/export/artifact.md?selected={record.project_snapshots[0].canonical_project_code}"
            )
            root_redirect_response = client.get("/", follow_redirects=False)
            home_response = client.get("/")
            control_response = client.get("/control")
            arena_selected_status = selected_arena_response.status_code
            arena_export_status = client.get(
                f"/arena/export?selected={record.project_snapshots[0].canonical_project_code}"
            ).status_code
            arena_artifact_status = selected_artifact_response.status_code
            arena_artifact_body = selected_artifact_response.text
            arena_view = service.build_arena([selected_code])
            root_redirects_to_publish = root_redirect_response.status_code == 307 and root_redirect_response.headers.get(
                "location", ""
            ).endswith("/publish")
            root_publish_rendered = (
                'id="publish-command-sheet"' in home_response.text
                and 'id="publish-latest-brief"' in home_response.text
                and 'aria-current="page">Publish</a>' in home_response.text
                and 'id="root-primary-workspace"' not in home_response.text
            )
            legacy_control_available = (
                control_response.status_code == 200
                and 'id="root-primary-workspace"' in control_response.text
            )
            arena_trust_rendered = (
                arena_view.comparison_trust.ranking_label in selected_arena_response.text
                and arena_view.comparison_trust.baseline_label in selected_arena_response.text
            )
            export_context_rendered = all(
                snippet in selected_artifact_response.text
                for snippet in (
                    arena_view.scope_summary,
                    arena_view.selection_summary,
                    arena_view.promotion_summary,
                    arena_view.comparison_trust.ranking_label,
                    arena_view.comparison_trust.baseline_label,
                )
            ) and "Generated at:" in selected_artifact_response.text
            diagnostics_runtime = diagnostics_payload.get("comparison_runtime") or {}
            diagnostics_match_runtime = (
                diagnostics_runtime.get("comparison_run_id") == runtime_coherence["comparison_run_id"]
                and diagnostics_runtime.get("ranking_authority") == runtime_coherence["ranking_authority"]
                and diagnostics_runtime.get("comparison_trust", {}).get("reason_code")
                == runtime_coherence["comparison_trust"]["reason_code"]
            )
        versioned_note_count = sum(len(note.versioned_output_paths) for note in record.notes)
        versioned_notes_created = versioned_note_count > 0 and all(
            path.exists() for note in record.notes for path in note.versioned_output_paths
        )
        risk_ranking_present = bool(
            record.portfolio_snapshot and record.portfolio_snapshot.top_5_at_risk_projects == record.portfolio_snapshot.top_at_risk_projects
        )
        portfolio_markdown_rendered = bool(
            portfolio_note and portfolio_note.body.startswith("---\n") and "## Portfolio Risk Ranking" in portfolio_note.body
        )
        project_weekly_briefs_rendered = bool(
            weekly_note and weekly_note.body.startswith("---\n") and "## What Changed This Week" in weekly_note.body
        )
        note_paths = [str(note.output_path) for note in record.notes]
        obsidian_outputs_written = all(Path(path).exists() for path in note_paths)
        existing_paths = [path for path in note_paths if Path(path).exists()]
        route_checks = {
            "portfolio_api": portfolio_response.status_code,
            "projects_page": projects_response.status_code,
            "arena_page": arena_selected_status,
            "arena_export_page": arena_export_status,
            "arena_artifact_route": arena_artifact_status,
            "exports_page": export_response.status_code,
            "runs_page": runs_response.status_code,
            "compare_page": compare_status,
            "diagnostics_page": diagnostics_response.status_code,
            "diagnostics_api": diagnostics_api_response.status_code,
        }
        export_checks = {
            "portfolio_markdown_rendered": portfolio_markdown_rendered,
            "project_weekly_briefs_rendered": project_weekly_briefs_rendered,
            "obsidian_versioned_exports_written": versioned_notes_created,
            "obsidian_outputs_written": obsidian_outputs_written,
            "arena_artifact_present": arena_artifact_status == 200,
            "arena_artifact_contains_context": contained_export_context_rendered and export_context_rendered,
            "arena_artifact_contains_meeting_packet_contract": all(
                snippet in arena_artifact_body
                for snippet in (
                    "## Meeting Packet",
                    "## Action Queue",
                    "## Continuity",
                    "- Controlling driver:",
                    "- What changed since prior run:",
                    "- Required action(s):",
                    "- Supporting evidence / signals:",
                )
            ),
        }
        coherence_checks = {
            "baseline_selection_matches_runtime": bool(runtime_coherence["comparison_run_matches_surface"]),
            "delta_ranking_matches_baseline": bool(runtime_coherence["delta_ranking_consistent_with_baseline"]),
            "root_redirects_to_publish": root_redirects_to_publish,
            "root_publish_surface_visible": root_publish_rendered,
            "legacy_control_available": legacy_control_available,
            "trust_state_visible_on_arena": arena_trust_rendered,
            "diagnostics_match_runtime": diagnostics_match_runtime,
            "no_distinct_prior_is_contained": no_distinct_prior_is_contained,
            "contained_blocks_authoritative_delta": bool(runtime_coherence["contained_blocks_authoritative_delta"]),
            "meeting_readiness_contract_passes": meeting_readiness["status"] == "pass",
            "driver_change_contract_passes": meeting_readiness["checks"].get("cross_surface_finish_driver_semantics_align") is True,
        }
        status = "pass"
        if not all(
            [
                all(code == 200 for code in route_checks.values()),
                zero_duplicates,
                delta_complete,
                required_actions_complete,
                markdown_sections_present,
                versioned_notes_created,
                risk_ranking_present,
                all(export_checks.values()),
                all(coherence_checks.values()),
            ]
        ):
            status = "fail"

        result = {
            "executed_at": utc_now_iso(),
            "status": status,
            "validation_issues": validation_issues,
            "note_count": len(record.notes),
            "written_note_count": len(existing_paths),
            "portfolio_status_code": portfolio_response.status_code,
            "projects_status_code": projects_response.status_code,
            "exports_status_code": export_response.status_code,
            "runs_status_code": runs_response.status_code,
            "compare_status_code": compare_status,
            "zero_duplicates": zero_duplicates,
            "delta_complete": delta_complete,
            "required_actions_complete": required_actions_complete,
            "markdown_sections_present": markdown_sections_present,
            "versioned_notes_created": versioned_notes_created,
            "risk_ranking_present": risk_ranking_present,
            "route_checks": route_checks,
            "export_checks": export_checks,
            "coherence_checks": coherence_checks,
            "meeting_readiness": meeting_readiness,
            "runtime_coherence": runtime_coherence,
            "vault_root": str(effective_config.obsidian.vault_root),
            "state_root": str(effective_config.runtime.state_root),
            "note_paths": note_paths,
            "seed_run_id": seed_record.run_id,
            "run_id": record.run_id,
            "arena_artifact_excerpt": arena_artifact_body.splitlines()[:20],
        }
        report_path = effective_config.runtime.state_root / "acceptance_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

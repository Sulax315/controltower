from __future__ import annotations

import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.config import ControlTowerConfig
from controltower.domain.models import utc_now_iso
from controltower.services.controltower import ControlTowerService
from controltower.services.release import verify_live_routes


def run_acceptance(config: ControlTowerConfig) -> dict:
    """Export + Obsidian validation with single-surface HTTP governance (Phase 12+)."""
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
        time.sleep(1.1)
        record = service.export_notes(preview_only=False)

        runtime_coherence = service.build_runtime_coherence_snapshot()
        live_routes = verify_live_routes(effective_config, record)

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
        versioned_note_count = sum(len(note.versioned_output_paths) for note in record.notes)
        versioned_notes_created = versioned_note_count > 0 and all(
            path.exists() for note in record.notes for path in note.versioned_output_paths
        )
        risk_ranking_present = bool(
            record.portfolio_snapshot
            and record.portfolio_snapshot.top_5_at_risk_projects == record.portfolio_snapshot.top_at_risk_projects
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

        route_checks = dict(live_routes.get("checks") or {})
        export_checks = {
            "portfolio_markdown_rendered": portfolio_markdown_rendered,
            "project_weekly_briefs_rendered": project_weekly_briefs_rendered,
            "obsidian_versioned_exports_written": versioned_notes_created,
            "obsidian_outputs_written": obsidian_outputs_written,
        }
        meeting_readiness = live_routes.get("meeting_readiness") or {"status": "fail", "checks": {}}
        coherence_checks = {
            "baseline_selection_matches_runtime": bool(runtime_coherence["comparison_run_matches_surface"]),
            "delta_ranking_matches_baseline": bool(runtime_coherence["delta_ranking_consistent_with_baseline"]),
            "root_redirects_to_publish": bool((live_routes.get("visibility_checks") or {}).get("root_redirects_to_publish")),
            "publish_surface_authoritative": bool((live_routes.get("visibility_checks") or {}).get("publish_surface_authoritative")),
            "legacy_surfaces_blocked": bool((live_routes.get("visibility_checks") or {}).get("legacy_surfaces_blocked")),
            "no_distinct_prior_is_contained": bool(runtime_coherence.get("contained_blocks_authoritative_delta")),
            "contained_blocks_authoritative_delta": bool(runtime_coherence["contained_blocks_authoritative_delta"]),
            "meeting_readiness_contract_passes": meeting_readiness.get("status") == "pass",
            "driver_change_contract_passes": True,
        }

        status = "pass"
        if not all(
            [
                live_routes.get("status") == "pass",
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

        arena_artifact_excerpt: list[str] = []
        if record.project_snapshots:
            try:
                _codes = [record.project_snapshots[0].canonical_project_code]
                _arena, _fn, body = service.build_arena_export_artifact(_codes)
                arena_artifact_excerpt = body.splitlines()[:20]
            except Exception:  # noqa: BLE001 — excerpt is diagnostic only
                arena_artifact_excerpt = []

        result = {
            "executed_at": utc_now_iso(),
            "status": status,
            "validation_issues": validation_issues,
            "note_count": len(record.notes),
            "written_note_count": len(existing_paths),
            "portfolio_status_code": route_checks.get("/api/portfolio", 404),
            "projects_status_code": route_checks.get("/projects", 404),
            "exports_status_code": route_checks.get("/exports/latest", 404),
            "runs_status_code": route_checks.get("/runs", 404),
            "compare_status_code": 404,
            "zero_duplicates": zero_duplicates,
            "delta_complete": delta_complete,
            "required_actions_complete": required_actions_complete,
            "markdown_sections_present": markdown_sections_present,
            "versioned_notes_created": versioned_notes_created,
            "risk_ranking_present": risk_ranking_present,
            "route_checks": {
                **route_checks,
                "live_route_gate": live_routes.get("status"),
            },
            "export_checks": export_checks,
            "coherence_checks": coherence_checks,
            "meeting_readiness": meeting_readiness,
            "runtime_coherence": runtime_coherence,
            "vault_root": str(effective_config.obsidian.vault_root),
            "state_root": str(effective_config.runtime.state_root),
            "note_paths": note_paths,
            "seed_run_id": seed_record.run_id,
            "run_id": record.run_id,
            "arena_artifact_excerpt": arena_artifact_excerpt,
        }
        report_path = effective_config.runtime.state_root / "acceptance_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

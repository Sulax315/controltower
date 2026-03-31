from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from controltower.config import ControlTowerConfig
from controltower.domain.models import ExportRecord, utc_now_iso
from controltower.obsidian.exporter import load_latest_export
from controltower.render.markdown import REQUIRED_MARKDOWN_TEMPLATES, validate_markdown_templates
from controltower.services.approval_ingest import sync_pending_release_approval
from controltower.services.build_info import current_build_info, workspace_root
from controltower.services.controltower import ControlTowerService
from controltower.services.identity_reconciliation import RegistryDocument
from controltower.services.meeting_readiness import verify_meeting_readiness
from controltower.services.runtime_state import (
    ACCEPTANCE_REPORT_NAME,
    ARTIFACT_INDEX_NAME,
    LATEST_DIAGNOSTICS_NAME,
    LATEST_RELEASE_JSON,
    LATEST_RELEASE_MD,
    RELEASE_ROOT_NAME,
    ensure_runtime_layout,
    read_json,
    refresh_artifact_index,
    write_diagnostics_snapshot,
)
from controltower.services.test_auth import app_auth_required, build_authenticated_test_client


RELEASE_SCHEMA_VERSION = "2026-03-27"


def collect_operator_diagnostics(
    config: ControlTowerConfig,
    *,
    latest_release_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_runtime_layout(config.runtime.state_root)
    build_info = current_build_info()
    config_status = {
        "status": "loaded",
        "registry_path": str(config.identity.registry_path),
        "vault_root": str(config.obsidian.vault_root),
        "state_root": str(config.runtime.state_root),
        "ui_host": config.ui.host,
        "ui_port": config.ui.port,
        "public_base_url": config.app.public_base_url,
        "auth_mode": config.auth.mode,
    }
    markdown_template_status = _markdown_template_status()
    ui_template_status = _ui_template_status()
    registry_status = _registry_status(config)
    latest_export = load_latest_export(config.runtime.state_root)
    acceptance = _load_json(Path(config.runtime.state_root) / ACCEPTANCE_REPORT_NAME)
    latest_release = latest_release_override or load_latest_release_readiness(config.runtime.state_root)
    latest_live_deployment = _load_json(Path(config.runtime.state_root) / RELEASE_ROOT_NAME / "latest_live_deployment.json")
    artifact_index = _load_json(Path(config.runtime.state_root) / ARTIFACT_INDEX_NAME)
    latest_operation = _latest_operation_summary(config.runtime.state_root)
    diagnostics_snapshot = _load_json(Path(config.runtime.state_root) / "diagnostics" / LATEST_DIAGNOSTICS_NAME)

    service_available = markdown_template_status["status"] == "ok" and registry_status["status"] == "loaded"
    source_validation_status = {"status": "unavailable", "issues": ["Control Tower service did not initialize."]}
    portfolio_status = {
        "project_count": 0,
        "average_health_score": None,
        "overall_posture": "Unavailable because the service could not initialize.",
        "tier_counts": {},
        "risk_distribution": {},
    }
    comparison_runtime = {
        "generated_at": None,
        "comparison_trust": None,
        "comparison_run_id": None,
        "comparison_run_matches_surface": False,
        "delta_ranking_consistent_with_baseline": False,
        "latest_run_id": None,
        "latest_run_matches_current": False,
        "no_distinct_prior_baseline": False,
        "contained_blocks_authoritative_delta": True,
        "ranking_authority": "unavailable",
        "selected_arena_codes": [],
        "arena_item_codes": [],
        "arena_export_path": "/arena/export",
        "arena_artifact_path": "/arena/export/artifact.md",
        "project_comparison_status_counts": {},
    }
    latest_export_notes: list[dict[str, Any]] = latest_export.get("notes", []) if isinstance(latest_export, dict) else []

    if service_available:
        service = ControlTowerService(config)
        portfolio = service.build_portfolio()
        source_validation_issues = service.validate_sources()
        source_validation_status = {
            "status": "ok" if not source_validation_issues else "issues",
            "issues": source_validation_issues,
        }
        portfolio_status = {
            "project_count": portfolio.project_count,
            "average_health_score": portfolio.average_health_score,
            "overall_posture": portfolio.overall_posture,
            "tier_counts": dict(portfolio.tier_counts),
            "risk_distribution": dict(portfolio.risk_distribution),
        }
        comparison_runtime = service.build_runtime_coherence_snapshot()

    latest_export_versioned_count = sum(
        len(note.get("versioned_output_paths", []))
        for note in latest_export_notes
        if isinstance(note, dict)
    )

    return {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "captured_at": utc_now_iso(),
        "product": {
            "name": config.app.product_name,
            "environment": config.app.environment,
            "version": build_info["version"],
            "build_metadata": {
                "git_commit": build_info["git_commit"] or "unavailable",
                "git_commit_available": build_info["git_commit_available"],
                "git_commit_short": build_info["git_commit_short"],
                "asset_version": build_info["asset_version"],
                "python_version": build_info["python_version"],
            },
        },
        "config": config_status,
        "templates": {
            "markdown": markdown_template_status,
            "ui": ui_template_status,
        },
        "registry": registry_status,
        "source_validation": source_validation_status,
        "release": {
            "generated_at": latest_release.get("generated_at") if latest_release else None,
            "status": (latest_release.get("verdict") or {}).get("status") if latest_release else "not_run",
            "summary": (latest_release.get("verdict") or {}).get("summary") if latest_release else "No release readiness artifact recorded yet.",
            "json_path": str(_release_root(config.runtime.state_root) / LATEST_RELEASE_JSON),
            "markdown_path": str(_release_root(config.runtime.state_root) / LATEST_RELEASE_MD),
            "live_deployment_path": str(_release_root(config.runtime.state_root) / "latest_live_deployment.json"),
            "live_deployment_present": latest_live_deployment is not None,
            "live_git_commit": latest_live_deployment.get("git_commit") if latest_live_deployment else None,
            "live_deployed_at": latest_live_deployment.get("deployed_at") if latest_live_deployment else None,
        },
        "acceptance": {
            "last_run_at": acceptance.get("executed_at") if acceptance else None,
            "last_status": acceptance.get("status") if acceptance else "not_run",
            "last_successful_run_at": acceptance.get("executed_at") if acceptance and acceptance.get("status") == "pass" else None,
            "report_path": str(Path(config.runtime.state_root) / ACCEPTANCE_REPORT_NAME),
            "report_present": acceptance is not None,
        },
        "latest_run": {
            "run_id": latest_export.get("run_id") if isinstance(latest_export, dict) else None,
            "generated_at": latest_export.get("generated_at") if isinstance(latest_export, dict) else None,
            "status": latest_export.get("status") if isinstance(latest_export, dict) else "not_run",
            "success": latest_export.get("status") == "success" if isinstance(latest_export, dict) else False,
            "latest_run_path": str(Path(config.runtime.state_root) / "latest_run.json"),
        },
        "operations": {
            "latest_run_timestamp": latest_operation.get("completed_at") if latest_operation else None,
            "latest_run_success": latest_operation.get("status") == "success" if latest_operation else None,
            "latest_run_status": latest_operation.get("status") if latest_operation else "not_run",
            "latest_run_type": latest_operation.get("operation_type") if latest_operation else None,
            "latest_run_summary_path": latest_operation.get("_summary_path") if latest_operation else None,
        },
        "artifacts": {
            "artifact_index_path": str(Path(config.runtime.state_root) / ARTIFACT_INDEX_NAME),
            "artifact_index_present": artifact_index is not None,
            "latest_diagnostics_path": str(Path(config.runtime.state_root) / "diagnostics" / LATEST_DIAGNOSTICS_NAME),
            "latest_diagnostics_present": diagnostics_snapshot is not None,
            "latest_export_run_id": latest_export.get("run_id") if isinstance(latest_export, dict) else None,
            "latest_export_status": latest_export.get("status") if isinstance(latest_export, dict) else "not_run",
            "latest_export_note_count": len(latest_export_notes),
            "latest_export_versioned_note_count": latest_export_versioned_count,
            "presence_checks": _artifact_presence_checks(config),
            "recent_history_file_count": len(list((Path(config.runtime.state_root) / "history").glob("*.json"))),
            "recent_operation_file_count": len(list((Path(config.runtime.state_root) / "operations" / "history").glob("*.json"))),
            "recent_release_file_count": len(list((_release_root(config.runtime.state_root)).glob("release_readiness_*.json"))),
            "recent_diagnostics_file_count": len(list((Path(config.runtime.state_root) / "diagnostics").glob("diagnostics_*.json"))),
            "log_file_count": len(list((Path(config.runtime.state_root) / "logs").glob("*"))),
        },
        "portfolio": portfolio_status,
        "comparison_runtime": comparison_runtime,
    }


def build_release_readiness(
    config: ControlTowerConfig,
    *,
    run_pytest: bool = False,
    run_acceptance_check: bool = False,
    pytest_result: dict[str, Any] | None = None,
    acceptance_result: dict[str, Any] | None = None,
    export_record: ExportRecord | None = None,
    release_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    service = ControlTowerService(config)
    validation_issues = service.validate_sources()
    export_record = export_record or service.export_notes(preview_only=False)

    if pytest_result is None:
        pytest_result = run_pytest_suite() if run_pytest else {"status": "not_run", "command": "pytest -q", "exit_code": None}
    if acceptance_result is None:
        if run_acceptance_check:
            from controltower.acceptance.harness import run_acceptance

            acceptance_result = run_acceptance(config)
        else:
            acceptance_result = _load_json(Path(config.runtime.state_root) / ACCEPTANCE_REPORT_NAME) or {"status": "not_run"}
    if acceptance_result.get("status") != "not_run":
        acceptance_report_path = Path(config.runtime.state_root) / ACCEPTANCE_REPORT_NAME
        acceptance_report_path.parent.mkdir(parents=True, exist_ok=True)
        acceptance_report_path.write_text(json.dumps(acceptance_result, indent=2), encoding="utf-8")

    route_checks = verify_live_routes(config, export_record)
    export_checks = verify_export_record(export_record)
    generated_at = utc_now_iso()
    build_info = current_build_info()
    release_trace_payload = _normalize_release_trace(
        release_trace,
        generated_at=generated_at,
        deployed_git_commit=build_info["git_commit"],
    )

    gate_results = {
        "pytest": pytest_result,
        "acceptance": acceptance_result,
        "route_checks": route_checks,
        "export_checks": export_checks,
        "source_validation": {
            "status": "pass" if not validation_issues else "fail",
            "issues": validation_issues,
        },
    }
    failing_checks = _failing_gate_checks(gate_results)
    ready = not failing_checks
    stage_results = _build_stage_results(gate_results, ready=ready)
    remaining_risks = list(validation_issues)
    if pytest_result.get("status") not in {"pass", "not_run"}:
        remaining_risks.append("Pytest did not pass in the release-readiness run.")
    if acceptance_result.get("status") not in {"pass", "not_run"}:
        remaining_risks.append("Acceptance harness did not pass in the release-readiness run.")
    if route_checks.get("status") != "pass":
        remaining_risks.append("One or more live route checks failed.")
    if export_checks.get("status") != "pass":
        remaining_risks.append("One or more export verification checks failed.")

    operator_recommendation = (
        "Proceed with live daily/weekly operation; continue monitoring diagnostics and scheduled summaries."
        if ready
        else "Do not proceed with live operation changes until the failing gates and remaining risks are resolved."
    )
    awaiting_approval = ready
    next_recommended_action = (
        "Approve next Codex lane"
        if awaiting_approval
        else "Check latest_release_readiness.md"
    )
    verdict = {
        "status": "ready" if ready else "not_ready",
        "ready_for_live_operations": ready,
        "summary": (
            "Control Tower v2 is ready for live daily/weekly operation."
            if ready
            else "Control Tower v2 is not ready for live daily/weekly operation."
        ),
        "remaining_risks": remaining_risks,
        "failing_checks": failing_checks,
        "operator_recommendation": operator_recommendation,
    }

    artifact = {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "generated_at": generated_at,
        "product": {
            "name": config.app.product_name,
            "environment": config.app.environment,
            "version": build_info["version"],
            "git_commit": build_info["git_commit"],
            "git_commit_available": build_info["git_commit_available"],
        },
        "config": {
            "registry_path": str(config.identity.registry_path),
            "vault_root": str(config.obsidian.vault_root),
            "state_root": str(config.runtime.state_root),
            "public_base_url": config.app.public_base_url,
        },
        "gate_results": gate_results,
        "stage_results": stage_results,
        "pytest": pytest_result,
        "acceptance": acceptance_result,
        "route_checks": route_checks,
        "export_checks": export_checks,
        "source_validation": gate_results["source_validation"],
        "failure_reason": _notification_failure_reason(gate_results, failing_checks),
        "next_recommended_action": next_recommended_action,
        "awaiting_approval": awaiting_approval,
        "latest_export": {
            "run_id": export_record.run_id,
            "status": export_record.status,
            "note_count": len(export_record.notes),
            "previous_run_id": export_record.previous_run_id,
            "manifest_path": str(Path(config.runtime.state_root) / "runs" / export_record.run_id / "manifest.json"),
        },
        "latest_evidence": {
            "acceptance_report_path": str(Path(config.runtime.state_root) / ACCEPTANCE_REPORT_NAME),
            "diagnostics_snapshot_path": None,
            "latest_diagnostics_path": None,
            "latest_run_path": str(Path(config.runtime.state_root) / "latest_run.json"),
            "artifact_index_path": str(Path(config.runtime.state_root) / ARTIFACT_INDEX_NAME),
        },
        "diagnostics_snapshot": None,
        "release_trace": release_trace_payload,
        "verdict": verdict,
    }

    diagnostics_snapshot = collect_operator_diagnostics(config, latest_release_override=artifact)
    diagnostics_history_path, diagnostics_latest_path = write_diagnostics_snapshot(config.runtime.state_root, diagnostics_snapshot)
    artifact["latest_evidence"]["diagnostics_snapshot_path"] = str(diagnostics_history_path)
    artifact["latest_evidence"]["latest_diagnostics_path"] = str(diagnostics_latest_path)
    artifact["diagnostics_snapshot"] = diagnostics_snapshot

    json_path, markdown_path = write_release_readiness_artifacts(config.runtime.state_root, artifact)
    artifact["artifact_paths"] = {
        "json": str(json_path),
        "markdown": str(markdown_path),
        "latest_json": str(_release_root(config.runtime.state_root) / LATEST_RELEASE_JSON),
        "latest_markdown": str(_release_root(config.runtime.state_root) / LATEST_RELEASE_MD),
    }
    json_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    (_release_root(config.runtime.state_root) / LATEST_RELEASE_JSON).write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    refresh_artifact_index(config.runtime.state_root)
    _sync_release_approval_state(config.runtime.state_root)
    return artifact


def refresh_release_readiness_diagnostics(config: ControlTowerConfig) -> dict[str, Any] | None:
    artifact = load_latest_release_readiness(config.runtime.state_root)
    if artifact is None:
        return None

    diagnostics_snapshot = collect_operator_diagnostics(config, latest_release_override=artifact)
    diagnostics_history_path, diagnostics_latest_path = write_diagnostics_snapshot(config.runtime.state_root, diagnostics_snapshot)
    artifact["diagnostics_snapshot"] = diagnostics_snapshot
    latest_evidence = artifact.setdefault("latest_evidence", {})
    latest_evidence["diagnostics_snapshot_path"] = str(diagnostics_history_path)
    latest_evidence["latest_diagnostics_path"] = str(diagnostics_latest_path)
    json_path, markdown_path = write_release_readiness_artifacts(config.runtime.state_root, artifact)
    artifact["artifact_paths"] = {
        "json": str(json_path),
        "markdown": str(markdown_path),
        "latest_json": str(_release_root(config.runtime.state_root) / LATEST_RELEASE_JSON),
        "latest_markdown": str(_release_root(config.runtime.state_root) / LATEST_RELEASE_MD),
    }
    latest_json_path = _release_root(config.runtime.state_root) / LATEST_RELEASE_JSON
    latest_json_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    _sync_release_approval_state(config.runtime.state_root)
    return {
        "artifact": artifact,
        "diagnostics_snapshot_path": str(diagnostics_history_path),
        "latest_diagnostics_path": str(diagnostics_latest_path),
    }


def stamp_release_trace(state_root: Path, release_trace: dict[str, Any]) -> dict[str, Any] | None:
    latest_json_path = _release_root(state_root) / LATEST_RELEASE_JSON
    if not latest_json_path.exists():
        return None

    artifact = json.loads(latest_json_path.read_text(encoding="utf-8"))
    artifact["release_trace"] = _normalize_release_trace(
        release_trace,
        generated_at=artifact.get("generated_at"),
        deployed_git_commit=((artifact.get("product") or {}).get("git_commit")),
    )
    rendered = _render_release_summary(artifact)
    latest_markdown_path = _release_root(state_root) / LATEST_RELEASE_MD
    latest_json_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    latest_markdown_path.write_text(rendered, encoding="utf-8", newline="\n")

    generated_at = artifact.get("generated_at")
    if generated_at:
        safe_stamp = str(generated_at).replace(":", "-")
        history_json_path = _release_root(state_root) / f"release_readiness_{safe_stamp}.json"
        history_markdown_path = _release_root(state_root) / f"release_readiness_{safe_stamp}.md"
        if history_json_path.exists():
            history_json_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
        if history_markdown_path.exists():
            history_markdown_path.write_text(rendered, encoding="utf-8", newline="\n")

    refresh_artifact_index(state_root)
    _sync_release_approval_state(state_root)
    return artifact


def run_pytest_suite() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q"]
    completed = subprocess.run(
        command,
        cwd=str(_workspace_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "status": "pass" if completed.returncode == 0 else "fail",
        "command": " ".join(command[2:]) if len(command) > 2 else "pytest -q",
        "exit_code": completed.returncode,
        "stdout_tail": _tail_lines(completed.stdout),
        "stderr_tail": _tail_lines(completed.stderr),
    }


def verify_live_routes(config: ControlTowerConfig, export_record: ExportRecord) -> dict[str, Any]:
    from controltower.api.app import create_app_from_config

    app = create_app_from_config(config)
    anonymous_client = TestClient(app)
    client = build_authenticated_test_client(app, config)
    auth_required = app_auth_required(config)
    project_code = export_record.project_snapshots[0].canonical_project_code if export_record.project_snapshots else None
    service = ControlTowerService(config)
    selected_codes = [project_code] if project_code else []
    arena = service.build_arena(selected_codes)
    root_redirect_response = client.get("/", follow_redirects=False)
    home_response = client.get("/")
    publish_response = client.get("/publish")
    control_response = client.get("/control")
    arena_response = client.get(f"/arena?selected={project_code}") if project_code else client.get("/arena")
    artifact_response = (
        client.get(f"/arena/export/artifact.md?selected={project_code}")
        if project_code
        else client.get("/arena/export/artifact.md")
    )
    diagnostics_api_response = client.get("/api/diagnostics")
    auth_checks: dict[str, bool] = {}
    if auth_required:
        login_response = anonymous_client.get("/login?next_path=/publish", follow_redirects=False)
        anonymous_publish_response = anonymous_client.get("/publish", follow_redirects=False)
        anonymous_diagnostics_response = anonymous_client.get("/api/diagnostics", follow_redirects=False)
        auth_checks = {
            "login_returns_200": login_response.status_code == 200,
            "publish_requires_login": anonymous_publish_response.status_code == 303
            and anonymous_publish_response.headers.get("location", "").startswith("/login?next_path=/publish"),
            "api_requires_auth": anonymous_diagnostics_response.status_code == 401,
            "authenticated_publish_succeeds": publish_response.status_code == 200,
            "authenticated_api_succeeds": diagnostics_api_response.status_code == 200,
        }
    checks = {
        "/": home_response.status_code,
        "/publish": publish_response.status_code,
        "/control": control_response.status_code,
        "/arena": client.get("/arena").status_code,
        "/projects": client.get("/projects").status_code,
        "/runs": client.get("/runs").status_code,
        f"/runs/{export_record.run_id}": client.get(f"/runs/{export_record.run_id}").status_code,
        "/exports/latest": client.get("/exports/latest").status_code,
        "/diagnostics": client.get("/diagnostics").status_code,
        "/api/diagnostics": diagnostics_api_response.status_code,
        "/arena/export/artifact.md": artifact_response.status_code,
    }
    if project_code:
        checks[f"/projects/{project_code}/compare"] = client.get(f"/projects/{project_code}/compare").status_code
        checks[f"/arena?selected={project_code}"] = arena_response.status_code
        checks[f"/arena/export?selected={project_code}"] = client.get(f"/arena/export?selected={project_code}").status_code
        checks[f"/arena/export/artifact.md?selected={project_code}"] = artifact_response.status_code
    else:
        checks["/projects/{project_code}/compare"] = 404
        checks["/arena?selected={project_code}"] = client.get("/arena").status_code
        checks["/arena/export?selected={project_code}"] = client.get("/arena/export").status_code
        checks["/arena/export/artifact.md?selected={project_code}"] = artifact_response.status_code
    diagnostics_payload = diagnostics_api_response.json() if diagnostics_api_response.status_code == 200 else {}
    meeting_readiness = verify_meeting_readiness(config, selected_codes)
    visibility_checks = {
        "root_redirects_to_publish": root_redirect_response.status_code == 307
        and root_redirect_response.headers.get("location", "").endswith("/publish"),
        "root_renders_publish_surface": (
            'id="publish-command-sheet"' in home_response.text
            and 'id="publish-latest-brief"' in home_response.text
            and 'aria-current="page">Publish</a>' in home_response.text
            and 'id="root-primary-workspace"' not in home_response.text
        ),
        "legacy_control_is_available": (
            control_response.status_code == 200
            and 'id="root-primary-workspace"' in control_response.text
        ),
        "arena_renders_trust_posture": (
            arena.comparison_trust.ranking_label in arena_response.text
            and arena.comparison_trust.baseline_label in arena_response.text
        ),
        "artifact_renders_selection_context": (
            arena.selection_summary in artifact_response.text
            and arena.scope_summary in artifact_response.text
            and arena.promotion_summary in artifact_response.text
        ),
        "artifact_renders_timestamp_context": "Generated at:" in artifact_response.text and arena.generated_at[:10] in artifact_response.text,
        "artifact_renders_trust_state": (
            arena.comparison_trust.ranking_label in artifact_response.text
            and arena.comparison_trust.baseline_label in artifact_response.text
        ),
        "diagnostics_match_runtime_comparison": (
            (diagnostics_payload.get("comparison_runtime") or {}).get("comparison_run_id")
            == arena.comparison_trust.comparison_run_id
        )
        and (
            (diagnostics_payload.get("comparison_runtime") or {}).get("ranking_authority")
            == arena.comparison_trust.ranking_authority
        ),
    }
    return {
        "status": (
            "pass"
            if all(status_code == 200 for status_code in checks.values())
            and all(visibility_checks.values())
            and all(auth_checks.values())
            and meeting_readiness["status"] == "pass"
            else "fail"
        ),
        "checks": checks,
        "auth_checks": auth_checks,
        "visibility_checks": visibility_checks,
        "meeting_readiness": meeting_readiness,
    }


def verify_export_record(record: ExportRecord) -> dict[str, Any]:
    portfolio_notes = [note for note in record.notes if note.note_kind == "portfolio_weekly_summary"]
    weekly_briefs = [note for note in record.notes if note.note_kind == "project_weekly_brief"]
    preview_paths_exist = all(note.preview_path and Path(note.preview_path).exists() for note in record.notes)
    output_paths_exist = all(Path(note.output_path).exists() for note in record.notes)
    versioned_paths = [path for note in record.notes for path in note.versioned_output_paths]
    versioned_paths_exist = bool(versioned_paths) and all(Path(path).exists() for path in versioned_paths)
    portfolio_rendered = all(note.body.startswith("---\n") and "## Portfolio Risk Ranking" in note.body for note in portfolio_notes)
    briefs_rendered = all(note.body.startswith("---\n") and "## What Changed This Week" in note.body for note in weekly_briefs)

    checks = {
        "portfolio_markdown_rendered": bool(portfolio_notes) and portfolio_rendered,
        "project_weekly_briefs_rendered": bool(weekly_briefs) and briefs_rendered,
        "obsidian_outputs_written": output_paths_exist,
        "obsidian_versioned_exports_written": versioned_paths_exist,
        "preview_exports_written": preview_paths_exist,
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "note_count": len(record.notes),
        "versioned_output_count": len(versioned_paths),
        "checks": checks,
    }


def load_latest_release_readiness(state_root: Path) -> dict[str, Any] | None:
    latest_path = _release_root(state_root) / LATEST_RELEASE_JSON
    if not latest_path.exists():
        return None
    return json.loads(latest_path.read_text(encoding="utf-8"))


def write_release_readiness_artifacts(state_root: Path, artifact: dict[str, Any]) -> tuple[Path, Path]:
    release_root = _release_root(state_root)
    release_root.mkdir(parents=True, exist_ok=True)
    safe_stamp = artifact["generated_at"].replace(":", "-")
    json_path = release_root / f"release_readiness_{safe_stamp}.json"
    markdown_path = release_root / f"release_readiness_{safe_stamp}.md"
    json_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    markdown_path.write_text(_render_release_summary(artifact), encoding="utf-8", newline="\n")
    (release_root / LATEST_RELEASE_JSON).write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    (release_root / LATEST_RELEASE_MD).write_text(_render_release_summary(artifact), encoding="utf-8", newline="\n")
    refresh_artifact_index(state_root)
    return json_path, markdown_path


def _render_release_summary(artifact: dict[str, Any]) -> str:
    product = artifact["product"]
    verdict = artifact["verdict"]
    gates = artifact["gate_results"]
    latest_export = artifact["latest_export"]
    evidence = artifact["latest_evidence"]
    git_commit = product["git_commit"] or "unavailable"
    failing_checks = verdict["failing_checks"] or ["None."]
    remaining_risks = verdict["remaining_risks"] or ["None."]
    release_trace = _normalize_release_trace(
        artifact.get("release_trace"),
        generated_at=artifact.get("generated_at"),
        deployed_git_commit=product.get("git_commit"),
    )

    lines = [
        "# Control Tower Release Readiness",
        "",
        f"- Generated at: {artifact['generated_at']}",
        f"- Product: {product['name']} {product['version']}",
        f"- Environment: {product['environment']}",
        f"- Git commit: {git_commit}",
        f"- Overall verdict: {verdict['status'].upper()}",
        f"- Verdict summary: {verdict['summary']}",
        f"- Operator recommendation: {verdict['operator_recommendation']}",
        "",
        "## Gate Results",
        "",
        f"- Pytest: {gates['pytest'].get('status')}",
        f"- Acceptance: {gates['acceptance'].get('status')}",
        f"- Route checks: {gates['route_checks'].get('status')}",
        f"- Export checks: {gates['export_checks'].get('status')}",
        f"- Source validation: {gates['source_validation'].get('status')}",
        "",
        "## Failing Checks",
        "",
    ]
    lines.extend(f"- {item}" for item in failing_checks)
    lines.extend(
        [
            "",
            "## Latest Evidence References",
            "",
            f"- Latest export run: {latest_export['run_id']} ({latest_export['status']})",
            f"- Export manifest: {latest_export['manifest_path']}",
            f"- Acceptance report: {evidence['acceptance_report_path']}",
            f"- Diagnostics snapshot: {evidence['diagnostics_snapshot_path']}",
            f"- Latest diagnostics pointer: {evidence['latest_diagnostics_path']}",
            f"- Latest run pointer: {evidence['latest_run_path']}",
            f"- Artifact index: {evidence['artifact_index_path']}",
            "",
            "## Release Trace",
            "",
            f"- Trace generated at: {release_trace['generated_at']}",
            f"- Local HEAD commit: {release_trace['local_head_commit']}",
            f"- Remote origin/main commit: {release_trace['remote_origin_main_commit']}",
            f"- Deployed GIT_COMMIT: {release_trace['deployed_git_commit']}",
            f"- Verification status: {release_trace['verification_status']}",
            "",
            "## Remaining Risks",
            "",
        ]
    )
    lines.extend(f"- {risk}" for risk in remaining_risks)
    return "\n".join(lines) + "\n"


def _normalize_release_trace(
    payload: dict[str, Any] | None,
    *,
    generated_at: str | None,
    deployed_git_commit: str | None,
) -> dict[str, Any]:
    payload = payload or {}
    return {
        "generated_at": payload.get("generated_at") or generated_at or "unavailable",
        "local_head_commit": payload.get("local_head_commit") or "unavailable",
        "remote_origin_main_commit": payload.get("remote_origin_main_commit") or "unavailable",
        "deployed_git_commit": payload.get("deployed_git_commit") or deployed_git_commit or "unavailable",
        "verification_status": payload.get("verification_status") or "not_run",
        "push_status": payload.get("push_status") or "unknown",
        "source_trace_path": payload.get("source_trace_path"),
    }


def _release_root(state_root: Path) -> Path:
    return Path(state_root) / RELEASE_ROOT_NAME


def _sync_release_approval_state(state_root: Path) -> None:
    latest_json_path = _release_root(state_root) / LATEST_RELEASE_JSON
    if not latest_json_path.exists():
        return
    orchestration_root = Path(state_root).resolve().parent / "ops" / "orchestration"
    sync_pending_release_approval(latest_json_path, orchestration_root=orchestration_root)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))

def _tail_lines(text: str, count: int = 20) -> list[str]:
    return [line for line in text.splitlines()[-count:] if line.strip()]


def _workspace_root() -> Path:
    return workspace_root()


def _markdown_template_status() -> dict[str, Any]:
    try:
        validate_markdown_templates()
    except FileNotFoundError as exc:
        return {
            "status": "missing",
            "required_templates": list(REQUIRED_MARKDOWN_TEMPLATES),
            "detail": str(exc),
        }
    return {
        "status": "ok",
        "required_templates": list(REQUIRED_MARKDOWN_TEMPLATES),
        "template_root": str(Path(__file__).resolve().parents[1] / "render" / "templates"),
    }


def _ui_template_status() -> dict[str, Any]:
    from controltower.api.app import REQUIRED_UI_TEMPLATES, validate_ui_assets

    try:
        validate_ui_assets()
    except FileNotFoundError as exc:
        return {
            "status": "missing",
            "required_templates": list(REQUIRED_UI_TEMPLATES),
            "detail": str(exc),
        }
    return {
        "status": "ok",
        "required_templates": list(REQUIRED_UI_TEMPLATES),
        "template_root": str(Path(__file__).resolve().parents[1] / "api" / "templates"),
        "static_root": str(Path(__file__).resolve().parents[1] / "api" / "static"),
    }


def _registry_status(config: ControlTowerConfig) -> dict[str, Any]:
    try:
        document = RegistryDocument.load(config.identity.registry_path)
    except (FileNotFoundError, ValueError) as exc:
        return {
            "status": "error",
            "path": str(config.identity.registry_path),
            "project_count": 0,
            "detail": str(exc),
        }
    return {
        "status": "loaded",
        "path": str(config.identity.registry_path),
        "project_count": len(document.projects),
    }


def _artifact_presence_checks(config: ControlTowerConfig) -> dict[str, bool]:
    state_root = Path(config.runtime.state_root)
    return {
        "latest_run_json": (state_root / "latest_run.json").exists(),
        "acceptance_report_json": (state_root / ACCEPTANCE_REPORT_NAME).exists(),
        "latest_release_json": (_release_root(state_root) / LATEST_RELEASE_JSON).exists(),
        "latest_release_markdown": (_release_root(state_root) / LATEST_RELEASE_MD).exists(),
        "artifact_index_json": (state_root / ARTIFACT_INDEX_NAME).exists(),
        "latest_diagnostics_json": (state_root / "diagnostics" / LATEST_DIAGNOSTICS_NAME).exists(),
        "runs_root": (state_root / "runs").exists(),
        "history_root": (state_root / "history").exists(),
        "logs_root": (state_root / "logs").exists(),
    }


def _latest_operation_summary(state_root: Path) -> dict[str, Any] | None:
    operations_root = Path(state_root) / "operations"
    latest_paths = sorted(operations_root.glob("latest_*.json"))
    entries: list[dict[str, Any]] = []
    for path in latest_paths:
        payload = read_json(path)
        if payload is None or path.name.startswith("latest_successful_"):
            continue
        payload["_summary_path"] = str(path)
        entries.append(payload)
    if not entries:
        return None
    return sorted(entries, key=lambda item: item.get("completed_at") or item.get("started_at") or "", reverse=True)[0]


def _failing_gate_checks(gate_results: dict[str, Any]) -> list[str]:
    failing: list[str] = []
    if gate_results["pytest"].get("status") not in {"pass", "not_run"}:
        failing.append("pytest")
    if gate_results["acceptance"].get("status") not in {"pass", "not_run"}:
        failing.append("acceptance")
    if gate_results["route_checks"].get("status") != "pass":
        failing.append("route_checks")
    if gate_results["export_checks"].get("status") != "pass":
        failing.append("export_checks")
    if gate_results["source_validation"].get("status") != "pass":
        failing.append("source_validation")
    return failing


def _build_stage_results(gate_results: dict[str, Any], *, ready: bool) -> dict[str, dict[str, str]]:
    stage_results: dict[str, dict[str, str]] = {
        "pytest": {"status": gate_results["pytest"].get("status") or "not_run"},
        "readiness": {"status": "pass" if ready else "fail"},
        "acceptance": {"status": gate_results["acceptance"].get("status") or "not_run"},
        "deploy": {"status": gate_results["route_checks"].get("status") or "not_run"},
    }
    if gate_results["export_checks"].get("status") != "pass":
        stage_results["export"] = {"status": gate_results["export_checks"].get("status") or "fail"}
    if gate_results["source_validation"].get("status") != "pass":
        stage_results["source_validation"] = {"status": gate_results["source_validation"].get("status") or "fail"}
    return stage_results


def _notification_failure_reason(gate_results: dict[str, Any], failing_checks: list[str]) -> str | None:
    if not failing_checks:
        return None
    failed_stage = failing_checks[0]
    if failed_stage == "pytest":
        return _tail_reason(gate_results["pytest"])
    if failed_stage == "acceptance":
        return _tail_reason(gate_results["acceptance"])
    if failed_stage == "route_checks":
        return _route_failure_reason(gate_results["route_checks"])
    if failed_stage == "export_checks":
        return _named_failure_reason(gate_results["export_checks"].get("checks"), prefix="Failed export check")
    if failed_stage == "source_validation":
        issues = gate_results["source_validation"].get("issues") or []
        return str(issues[0]) if issues else "Source validation failed."
    return "Release readiness failed."


def _tail_reason(result: dict[str, Any]) -> str:
    for key in ("stderr_tail", "stdout_tail"):
        tail = result.get(key) or []
        if tail:
            return str(tail[-1])
    if summary := result.get("summary"):
        return str(summary)
    return f"Stage reported status {result.get('status') or 'unknown'}."


def _route_failure_reason(route_checks: dict[str, Any]) -> str:
    for path, status_code in (route_checks.get("checks") or {}).items():
        if status_code != 200:
            return f"HTTP {status_code} from {path}"
    if reason := _named_failure_reason(route_checks.get("visibility_checks"), prefix="Failed visibility check"):
        return reason
    if reason := _named_failure_reason(route_checks.get("auth_checks"), prefix="Failed auth check"):
        return reason
    meeting_readiness = route_checks.get("meeting_readiness") or {}
    if meeting_readiness.get("status") != "pass":
        if reason := _named_failure_reason(meeting_readiness.get("checks"), prefix="Failed readiness check"):
            return reason
        return "Meeting readiness checks failed."
    return "Route checks failed."


def _named_failure_reason(checks: dict[str, Any] | None, *, prefix: str) -> str | None:
    if not checks:
        return None
    for name, value in checks.items():
        if value is not True:
            return f"{prefix}: {name}"
    return None

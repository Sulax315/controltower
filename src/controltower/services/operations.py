from __future__ import annotations

from pathlib import Path
from typing import Any

from controltower.config import ControlTowerConfig, load_config
from controltower.domain.models import ExportRecord, utc_now_iso
from controltower.render.markdown import validate_markdown_templates
from controltower.services.controltower import ControlTowerService
from controltower.services.delta import load_latest_run_record
from controltower.services.identity_reconciliation import RegistryDocument
from controltower.services.release import (
    build_release_readiness,
    collect_operator_diagnostics,
    refresh_release_readiness_diagnostics,
    verify_export_record,
    verify_live_routes,
)
from controltower.services.runtime_state import (
    ARTIFACT_INDEX_NAME,
    ensure_runtime_layout,
    prune_runtime_history,
    refresh_artifact_index,
    write_diagnostics_snapshot,
    write_operation_summary,
)


EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 10
EXIT_TEMPLATE_ERROR = 11
EXIT_REGISTRY_ERROR = 12
EXIT_SOURCE_ERROR = 13
EXIT_ROUTE_ERROR = 14
EXIT_EXPORT_ERROR = 15
EXIT_RELEASE_ERROR = 16
EXIT_RUNTIME_ERROR = 17
EXIT_UNEXPECTED_ERROR = 19


def run_preflight(
    *,
    config_path: Path | None = None,
    retention_dry_run: bool = False,
    stdout_log: str | None = None,
    stderr_log: str | None = None,
) -> dict[str, Any]:
    return _run_operation(
        "preflight",
        config_path=config_path,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        runner=lambda config: _preflight_operation(config, retention_dry_run=retention_dry_run),
    )


def run_daily(
    *,
    config_path: Path | None = None,
    retention_dry_run: bool = False,
    stdout_log: str | None = None,
    stderr_log: str | None = None,
) -> dict[str, Any]:
    return _run_operation(
        "daily",
        config_path=config_path,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        runner=lambda config: _daily_operation(config, retention_dry_run=retention_dry_run),
    )


def run_weekly(
    *,
    config_path: Path | None = None,
    retention_dry_run: bool = False,
    stdout_log: str | None = None,
    stderr_log: str | None = None,
) -> dict[str, Any]:
    return _run_operation(
        "weekly",
        config_path=config_path,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        runner=lambda config: _weekly_operation(config, retention_dry_run=retention_dry_run),
    )


def run_smoke(
    *,
    config_path: Path | None = None,
    refresh_export: bool = False,
    stdout_log: str | None = None,
    stderr_log: str | None = None,
) -> dict[str, Any]:
    return _run_operation(
        "smoke",
        config_path=config_path,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        runner=lambda config: _smoke_operation(config, refresh_export=refresh_export),
    )


def run_diagnostics_snapshot(
    *,
    config_path: Path | None = None,
    stdout_log: str | None = None,
    stderr_log: str | None = None,
) -> dict[str, Any]:
    return _run_operation(
        "diagnostics_snapshot",
        config_path=config_path,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        runner=_diagnostics_snapshot_operation,
    )


def run_release_gate(
    *,
    config_path: Path | None = None,
    run_pytest: bool = True,
    run_acceptance: bool = True,
    stdout_log: str | None = None,
    stderr_log: str | None = None,
) -> dict[str, Any]:
    return _run_operation(
        "release_readiness",
        config_path=config_path,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        runner=lambda config: _release_gate_operation(config, run_pytest=run_pytest, run_acceptance=run_acceptance),
    )


def _run_operation(
    operation_type: str,
    *,
    config_path: Path | None,
    stdout_log: str | None,
    stderr_log: str | None,
    runner,
) -> dict[str, Any]:
    started_at = utc_now_iso()
    state_root = _default_state_root()
    summary = _base_summary(
        operation_type=operation_type,
        started_at=started_at,
        config_path=config_path,
        state_root=state_root,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
    )

    try:
        config = load_config(config_path)
        state_root = Path(config.runtime.state_root)
        ensure_runtime_layout(state_root)
        summary["config"] = {
            "config_path": str(Path(config_path).resolve()) if config_path else None,
            "registry_path": str(config.identity.registry_path),
            "vault_root": str(config.obsidian.vault_root),
            "state_root": str(config.runtime.state_root),
        }
        summary["artifacts"]["summary_json"] = str(_summary_path(state_root, summary["operation_id"]))
        result = runner(config)
        summary["status"] = result["status"]
        summary["exit_code"] = result["exit_code"]
        summary["summary"] = result["summary"]
        summary["checks"] = result.get("checks", {})
        summary["artifacts"] = {**summary["artifacts"], **result.get("artifacts", {})}
        summary["error"] = result.get("error")
        if "retention" in result:
            summary["retention"] = result["retention"]
        summary["completed_at"] = utc_now_iso()
        write_operation_summary(state_root, summary)
        if operation_type == "release_readiness":
            refreshed_release = refresh_release_readiness_diagnostics(config)
            if refreshed_release is not None:
                summary["artifacts"]["latest_diagnostics"] = refreshed_release["latest_diagnostics_path"]
                summary["artifacts"]["diagnostics_snapshot"] = refreshed_release["diagnostics_snapshot_path"]
                write_operation_summary(state_root, summary)
        return summary
    except Exception as exc:  # pragma: no cover - exercised via script subprocesses and negative tests
        exit_code, error_type, action = _classify_exception(exc)
        summary["status"] = "failed"
        summary["exit_code"] = exit_code
        summary["completed_at"] = utc_now_iso()
        summary["summary"] = str(exc)
        summary["error"] = {
            "type": error_type,
            "message": str(exc),
            "action": action,
        }
        ensure_runtime_layout(state_root)
        summary["artifacts"]["summary_json"] = str(_summary_path(state_root, summary["operation_id"]))
        write_operation_summary(state_root, summary)
        return summary


def _preflight_operation(config: ControlTowerConfig, *, retention_dry_run: bool) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    validate_markdown_templates()
    checks["markdown_templates"] = {"status": "ok"}
    registry_document = RegistryDocument.load(config.identity.registry_path)
    checks["registry"] = {"status": "loaded", "project_count": len(registry_document.projects)}

    from controltower.api.app import validate_ui_assets

    validate_ui_assets()
    checks["ui_assets"] = {"status": "ok"}
    service = ControlTowerService(config)
    source_issues = service.validate_sources()
    checks["source_validation"] = {"status": "ok" if not source_issues else "issues", "issues": source_issues}
    diagnostics = collect_operator_diagnostics(config)
    diagnostics_history_path, diagnostics_latest_path = write_diagnostics_snapshot(config.runtime.state_root, diagnostics)
    prune_report = prune_runtime_history(config.runtime.state_root, config.runtime.retention, dry_run=retention_dry_run)
    artifact_index_path = refresh_artifact_index(config.runtime.state_root)

    if source_issues:
        return _failed_result(
            exit_code=EXIT_SOURCE_ERROR,
            message="Source validation failed during preflight.",
            action="Resolve missing or malformed ScheduleLab/ProfitIntel inputs before the next unattended run.",
            checks=checks,
            artifacts={
                "diagnostics_snapshot": str(diagnostics_history_path),
                "latest_diagnostics": str(diagnostics_latest_path),
                "artifact_index": str(artifact_index_path),
            },
            retention=prune_report,
        )
    return _successful_result(
        message="Preflight checks passed.",
        checks=checks,
        artifacts={
            "diagnostics_snapshot": str(diagnostics_history_path),
            "latest_diagnostics": str(diagnostics_latest_path),
            "artifact_index": str(artifact_index_path),
        },
        retention=prune_report,
    )


def _daily_operation(config: ControlTowerConfig, *, retention_dry_run: bool) -> dict[str, Any]:
    service = ControlTowerService(config)
    source_issues = service.validate_sources()
    if source_issues:
        return _failed_result(
            exit_code=EXIT_SOURCE_ERROR,
            message="Daily run blocked by source validation issues.",
            action="Run preflight and restore the missing ScheduleLab/ProfitIntel inputs before retrying the daily run.",
            checks={"source_validation": {"status": "issues", "issues": source_issues}},
        )

    export_record = service.export_notes(preview_only=False)
    diagnostics = collect_operator_diagnostics(config)
    diagnostics_history_path, diagnostics_latest_path = write_diagnostics_snapshot(config.runtime.state_root, diagnostics)
    prune_report = prune_runtime_history(config.runtime.state_root, config.runtime.retention, dry_run=retention_dry_run)
    artifact_index_path = refresh_artifact_index(config.runtime.state_root)

    return _successful_result(
        message=f"Daily run completed and wrote {len(export_record.notes)} notes.",
        checks={
            "source_validation": {"status": "ok", "issues": []},
            "export": {"status": export_record.status, "run_id": export_record.run_id, "note_count": len(export_record.notes)},
        },
        artifacts=_export_artifacts(config, export_record)
        | {
            "diagnostics_snapshot": str(diagnostics_history_path),
            "latest_diagnostics": str(diagnostics_latest_path),
            "artifact_index": str(artifact_index_path),
        },
        retention=prune_report,
    )


def _weekly_operation(config: ControlTowerConfig, *, retention_dry_run: bool) -> dict[str, Any]:
    service = ControlTowerService(config)
    source_issues = service.validate_sources()
    if source_issues:
        return _failed_result(
            exit_code=EXIT_SOURCE_ERROR,
            message="Weekly run blocked by source validation issues.",
            action="Resolve the source validation errors before retrying the weekly run.",
            checks={"source_validation": {"status": "issues", "issues": source_issues}},
        )

    export_record = service.export_notes(preview_only=False)
    smoke = _smoke_checks(config, export_record)
    release_artifact = build_release_readiness(
        config,
        run_pytest=True,
        run_acceptance_check=True,
        export_record=export_record,
    )
    prune_report = prune_runtime_history(config.runtime.state_root, config.runtime.retention, dry_run=retention_dry_run)
    artifact_index_path = refresh_artifact_index(config.runtime.state_root)

    if smoke["route_checks"]["status"] != "pass":
        return _failed_result(
            exit_code=EXIT_ROUTE_ERROR,
            message="Weekly run completed exports but live route smoke verification failed.",
            action="Inspect the route checks in the summary and repair the UI/API surface before the next unattended run.",
            checks=smoke,
            artifacts=_export_artifacts(config, export_record)
            | {
                "release_json": release_artifact["artifact_paths"]["json"],
                "release_markdown": release_artifact["artifact_paths"]["markdown"],
                "artifact_index": str(artifact_index_path),
            },
            retention=prune_report,
        )
    if release_artifact["verdict"]["ready_for_live_operations"] is not True:
        return _failed_result(
            exit_code=EXIT_RELEASE_ERROR,
            message="Weekly run finished but the release gate did not clear.",
            action="Review the release readiness markdown/json artifacts and resolve the failing gates before treating this run as healthy.",
            checks=smoke | {"release_verdict": release_artifact["verdict"]},
            artifacts=_export_artifacts(config, export_record)
            | {
                "release_json": release_artifact["artifact_paths"]["json"],
                "release_markdown": release_artifact["artifact_paths"]["markdown"],
                "artifact_index": str(artifact_index_path),
            },
            retention=prune_report,
        )
    return _successful_result(
        message="Weekly run completed, smoke verification passed, and release readiness stayed green.",
        checks=smoke | {"release_verdict": release_artifact["verdict"]},
        artifacts=_export_artifacts(config, export_record)
        | {
            "release_json": release_artifact["artifact_paths"]["json"],
            "release_markdown": release_artifact["artifact_paths"]["markdown"],
            "artifact_index": str(artifact_index_path),
        },
        retention=prune_report,
    )


def _smoke_operation(config: ControlTowerConfig, *, refresh_export: bool) -> dict[str, Any]:
    record = load_latest_run_record(config.runtime.state_root)
    service = ControlTowerService(config)
    if record is None or refresh_export:
        source_issues = service.validate_sources()
        if source_issues:
            return _failed_result(
                exit_code=EXIT_SOURCE_ERROR,
                message="Smoke verification could not build a fresh export because source validation failed.",
                action="Resolve the source inputs or rerun smoke without refresh after a healthy daily/weekly export exists.",
                checks={"source_validation": {"status": "issues", "issues": source_issues}},
            )
        record = service.export_notes(preview_only=False)

    smoke = _smoke_checks(config, record)
    diagnostics = collect_operator_diagnostics(config)
    diagnostics_history_path, diagnostics_latest_path = write_diagnostics_snapshot(config.runtime.state_root, diagnostics)
    artifact_index_path = refresh_artifact_index(config.runtime.state_root)

    if smoke["route_checks"]["status"] != "pass":
        return _failed_result(
            exit_code=EXIT_ROUTE_ERROR,
            message="Smoke verification failed route checks.",
            action="Inspect the route status map and restore the failing page/API before the next unattended run.",
            checks=smoke,
            artifacts=_export_artifacts(config, record)
            | {
                "diagnostics_snapshot": str(diagnostics_history_path),
                "latest_diagnostics": str(diagnostics_latest_path),
                "artifact_index": str(artifact_index_path),
            },
        )
    if smoke["export_checks"]["status"] != "pass":
        return _failed_result(
            exit_code=EXIT_EXPORT_ERROR,
            message="Smoke verification failed export checks.",
            action="Inspect the export checks in the summary and repair the missing markdown/output artifacts.",
            checks=smoke,
            artifacts=_export_artifacts(config, record)
            | {
                "diagnostics_snapshot": str(diagnostics_history_path),
                "latest_diagnostics": str(diagnostics_latest_path),
                "artifact_index": str(artifact_index_path),
            },
        )
    return _successful_result(
        message="Smoke verification passed against the live routes and latest export artifacts.",
        checks=smoke,
        artifacts=_export_artifacts(config, record)
        | {
            "diagnostics_snapshot": str(diagnostics_history_path),
            "latest_diagnostics": str(diagnostics_latest_path),
            "artifact_index": str(artifact_index_path),
        },
    )


def _diagnostics_snapshot_operation(config: ControlTowerConfig) -> dict[str, Any]:
    diagnostics = collect_operator_diagnostics(config)
    diagnostics_history_path, diagnostics_latest_path = write_diagnostics_snapshot(config.runtime.state_root, diagnostics)
    artifact_index_path = refresh_artifact_index(config.runtime.state_root)
    return _successful_result(
        message="Diagnostics snapshot captured.",
        checks={"diagnostics": {"status": "ok"}},
        artifacts={
            "diagnostics_snapshot": str(diagnostics_history_path),
            "latest_diagnostics": str(diagnostics_latest_path),
            "artifact_index": str(artifact_index_path),
        },
    )


def _release_gate_operation(config: ControlTowerConfig, *, run_pytest: bool, run_acceptance: bool) -> dict[str, Any]:
    release_artifact = build_release_readiness(
        config,
        run_pytest=run_pytest,
        run_acceptance_check=run_acceptance,
    )
    artifact_index_path = refresh_artifact_index(config.runtime.state_root)
    if release_artifact["verdict"]["ready_for_live_operations"] is not True:
        return _failed_result(
            exit_code=EXIT_RELEASE_ERROR,
            message="Release readiness failed.",
            action="Review the failing checks and remaining risks in the release artifacts before retrying.",
            checks={"release_verdict": release_artifact["verdict"], "gate_results": release_artifact["gate_results"]},
            artifacts={
                "release_json": release_artifact["artifact_paths"]["json"],
                "release_markdown": release_artifact["artifact_paths"]["markdown"],
                "artifact_index": str(artifact_index_path),
            },
        )
    return _successful_result(
        message="Release readiness passed.",
        checks={"release_verdict": release_artifact["verdict"], "gate_results": release_artifact["gate_results"]},
        artifacts={
            "release_json": release_artifact["artifact_paths"]["json"],
            "release_markdown": release_artifact["artifact_paths"]["markdown"],
            "artifact_index": str(artifact_index_path),
        },
    )


def _smoke_checks(config: ControlTowerConfig, export_record: ExportRecord) -> dict[str, Any]:
    return {
        "route_checks": verify_live_routes(config, export_record),
        "export_checks": verify_export_record(export_record),
    }


def _export_artifacts(config: ControlTowerConfig, record: ExportRecord) -> dict[str, str]:
    return {
        "latest_run_json": str(Path(config.runtime.state_root) / "latest_run.json"),
        "export_manifest": str(Path(config.runtime.state_root) / "runs" / record.run_id / "manifest.json"),
        "export_history": str(Path(config.runtime.state_root) / "history" / f"{record.run_id}.json"),
        "artifact_index": str(Path(config.runtime.state_root) / ARTIFACT_INDEX_NAME),
    }


def _base_summary(
    *,
    operation_type: str,
    started_at: str,
    config_path: Path | None,
    state_root: Path,
    stdout_log: str | None,
    stderr_log: str | None,
) -> dict[str, Any]:
    operation_id = f"{operation_type}_{started_at.replace(':', '-')}"
    return {
        "operation_id": operation_id,
        "operation_type": operation_type,
        "started_at": started_at,
        "completed_at": None,
        "status": "failed",
        "exit_code": EXIT_RUNTIME_ERROR,
        "summary": "",
        "config": {
            "config_path": str(Path(config_path).resolve()) if config_path else None,
            "state_root": str(state_root),
        },
        "checks": {},
        "artifacts": {
            "summary_json": str(_summary_path(state_root, operation_id)),
            "stdout_log": stdout_log,
            "stderr_log": stderr_log,
        },
        "error": None,
    }


def _successful_result(
    *,
    message: str,
    checks: dict[str, Any],
    artifacts: dict[str, str],
    retention: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "status": "success",
        "exit_code": EXIT_SUCCESS,
        "summary": message,
        "checks": checks,
        "artifacts": artifacts,
        "error": None,
    }
    if retention is not None:
        result["retention"] = retention
    return result


def _failed_result(
    *,
    exit_code: int,
    message: str,
    action: str,
    checks: dict[str, Any],
    artifacts: dict[str, str] | None = None,
    retention: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "status": "failed",
        "exit_code": exit_code,
        "summary": message,
        "checks": checks,
        "artifacts": artifacts or {},
        "error": {
            "type": "operation_failed",
            "message": message,
            "action": action,
        },
    }
    if retention is not None:
        result["retention"] = retention
    return result


def _classify_exception(exc: Exception) -> tuple[int, str, str]:
    message = str(exc)
    lowered = message.lower()
    if "config file" in lowered or "config root" in lowered or "runtime retention" in lowered:
        return (
            EXIT_CONFIG_ERROR,
            "config_error",
            "Validate the Control Tower config path and YAML contents before retrying.",
        )
    if "markdown templates" in lowered or "ui assets" in lowered:
        return (
            EXIT_TEMPLATE_ERROR,
            "template_error",
            "Restore the missing markdown/UI templates and rerun the operation.",
        )
    if "identity registry" in lowered or "ambiguous alias" in lowered:
        return (
            EXIT_REGISTRY_ERROR,
            "registry_error",
            "Repair the Control Tower identity registry and rerun the operation.",
        )
    return (
        EXIT_UNEXPECTED_ERROR,
        "unexpected_error",
        "Inspect the summary JSON and stack context, then retry once the underlying runtime error is resolved.",
    )


def _summary_path(state_root: Path, operation_id: str) -> Path:
    return Path(state_root) / "operations" / "history" / f"{operation_id}.json"


def _default_state_root() -> Path:
    return Path(__file__).resolve().parents[3] / ".controltower_runtime"

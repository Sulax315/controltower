from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from controltower.domain.models import utc_now_iso


RELEASE_ROOT_NAME = "release"
OPERATIONS_ROOT_NAME = "operations"
DIAGNOSTICS_ROOT_NAME = "diagnostics"
LOGS_ROOT_NAME = "logs"
HISTORY_ROOT_NAME = "history"
RUNS_ROOT_NAME = "runs"
LATEST_RUN_NAME = "latest_run.json"
ACCEPTANCE_REPORT_NAME = "acceptance_report.json"
ARTIFACT_INDEX_NAME = "artifact_index.json"
LATEST_RELEASE_JSON = "latest_release_readiness.json"
LATEST_RELEASE_MD = "latest_release_readiness.md"
LATEST_DIAGNOSTICS_NAME = "latest_diagnostics.json"


def ensure_runtime_layout(state_root: Path) -> dict[str, Path]:
    state_root = Path(state_root)
    paths = {
        "state_root": state_root,
        "runs_root": state_root / RUNS_ROOT_NAME,
        "history_root": state_root / HISTORY_ROOT_NAME,
        "release_root": state_root / RELEASE_ROOT_NAME,
        "operations_root": state_root / OPERATIONS_ROOT_NAME,
        "operations_history_root": state_root / OPERATIONS_ROOT_NAME / HISTORY_ROOT_NAME,
        "diagnostics_root": state_root / DIAGNOSTICS_ROOT_NAME,
        "logs_root": state_root / LOGS_ROOT_NAME,
    }
    for path in paths.values():
        if path.suffix:
            continue
        path.mkdir(parents=True, exist_ok=True)
    return paths


def read_json(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_operation_history(state_root: Path) -> list[dict[str, Any]]:
    history_root = ensure_runtime_layout(state_root)["operations_history_root"]
    entries: list[dict[str, Any]] = []
    for path in sorted(history_root.glob("*.json")):
        payload = read_json(path)
        if payload is None:
            continue
        payload["_summary_path"] = str(path)
        entries.append(payload)
    return sorted(entries, key=lambda item: item.get("completed_at") or item.get("started_at") or "", reverse=True)


def write_operation_summary(state_root: Path, summary: dict[str, Any]) -> Path:
    layout = ensure_runtime_layout(state_root)
    summary_path = layout["operations_history_root"] / f"{summary['operation_id']}.json"
    write_json(summary_path, summary)
    write_json(layout["operations_root"] / f"latest_{summary['operation_type']}.json", summary)
    if summary.get("status") == "success":
        write_json(layout["operations_root"] / f"latest_successful_{summary['operation_type']}.json", summary)
    refresh_artifact_index(state_root)
    return summary_path


def write_diagnostics_snapshot(state_root: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    diagnostics_root = ensure_runtime_layout(state_root)["diagnostics_root"]
    captured_at = payload.get("captured_at") or payload.get("generated_at") or utc_now_iso()
    safe_stamp = str(captured_at).replace(":", "-")
    history_path = diagnostics_root / f"diagnostics_{safe_stamp}.json"
    latest_path = diagnostics_root / LATEST_DIAGNOSTICS_NAME
    write_json(history_path, payload)
    write_json(latest_path, payload)
    refresh_artifact_index(state_root)
    return history_path, latest_path


def refresh_artifact_index(state_root: Path, *, recent_limit: int = 25) -> Path:
    layout = ensure_runtime_layout(state_root)
    state_root = layout["state_root"]
    latest_run = read_json(state_root / LATEST_RUN_NAME)
    acceptance = read_json(state_root / ACCEPTANCE_REPORT_NAME)
    latest_release = read_json(layout["release_root"] / LATEST_RELEASE_JSON)
    latest_diagnostics = read_json(layout["diagnostics_root"] / LATEST_DIAGNOSTICS_NAME)
    operations = load_operation_history(state_root)
    runs = _load_export_run_entries(state_root)[:recent_limit]
    releases = _load_release_entries(state_root)[:recent_limit]

    latest_operations: dict[str, dict[str, Any]] = {}
    for entry in operations:
        operation_type = entry.get("operation_type")
        if operation_type and operation_type not in latest_operations:
            latest_operations[operation_type] = {
                "operation_id": entry.get("operation_id"),
                "status": entry.get("status"),
                "completed_at": entry.get("completed_at"),
                "summary_path": entry.get("_summary_path"),
            }

    payload = {
        "generated_at": utc_now_iso(),
        "state_root": str(state_root),
        "latest": {
            "export_run": _latest_export_pointer(state_root, latest_run),
            "acceptance": _latest_acceptance_pointer(state_root, acceptance),
            "release_readiness": _latest_release_pointer(state_root, latest_release),
            "diagnostics": _latest_diagnostics_pointer(state_root, latest_diagnostics),
            "operations": latest_operations,
        },
        "recent_export_runs": runs,
        "recent_release_artifacts": releases,
        "recent_operations": [
            {
                "operation_id": entry.get("operation_id"),
                "operation_type": entry.get("operation_type"),
                "status": entry.get("status"),
                "started_at": entry.get("started_at"),
                "completed_at": entry.get("completed_at"),
                "exit_code": entry.get("exit_code"),
                "summary_path": entry.get("_summary_path"),
                "artifacts": entry.get("artifacts", {}),
            }
            for entry in operations[:recent_limit]
        ],
        "paths": {
            "latest_run_json": str(state_root / LATEST_RUN_NAME),
            "acceptance_report_json": str(state_root / ACCEPTANCE_REPORT_NAME),
            "latest_release_json": str(layout["release_root"] / LATEST_RELEASE_JSON),
            "latest_release_markdown": str(layout["release_root"] / LATEST_RELEASE_MD),
            "latest_diagnostics_json": str(layout["diagnostics_root"] / LATEST_DIAGNOSTICS_NAME),
            "operations_root": str(layout["operations_root"]),
            "logs_root": str(layout["logs_root"]),
        },
    }
    return write_json(state_root / ARTIFACT_INDEX_NAME, payload)


def prune_runtime_history(state_root: Path, retention: Any, *, dry_run: bool = False) -> dict[str, Any]:
    layout = ensure_runtime_layout(state_root)
    report = {
        "dry_run": dry_run,
        "generated_at": utc_now_iso(),
        "deleted_paths": [],
        "categories": {},
    }

    run_result = _prune_run_history(layout["state_root"], retention.run_history_limit, dry_run=dry_run)
    release_result = _prune_release_history(layout["state_root"], retention.release_history_limit, dry_run=dry_run)
    operation_result = _prune_operation_history(layout["state_root"], retention.operations_history_limit, dry_run=dry_run)
    diagnostics_result = _prune_diagnostics_history(layout["state_root"], retention.diagnostics_history_limit, dry_run=dry_run)
    log_result = _prune_logs(
        layout["state_root"],
        retention.log_file_limit,
        kept_operation_ids=set(operation_result["kept_ids"]),
        dry_run=dry_run,
    )

    report["categories"] = {
        "runs": run_result,
        "release": release_result,
        "operations": operation_result,
        "diagnostics": diagnostics_result,
        "logs": log_result,
    }
    for category in report["categories"].values():
        report["deleted_paths"].extend(category["deleted_paths"])

    if not dry_run:
        refresh_artifact_index(layout["state_root"])
    return report


def _load_export_run_entries(state_root: Path) -> list[dict[str, Any]]:
    state_root = Path(state_root)
    records: dict[str, dict[str, Any]] = {}
    for history_path in sorted((state_root / HISTORY_ROOT_NAME).glob("*.json")):
        payload = read_json(history_path)
        if payload is None or not payload.get("run_id"):
            continue
        run_id = payload["run_id"]
        records[run_id] = payload
        records[run_id]["_history_path"] = str(history_path)
    for manifest_path in sorted((state_root / RUNS_ROOT_NAME).glob("*/manifest.json")):
        payload = read_json(manifest_path)
        if payload is None or not payload.get("run_id"):
            continue
        run_id = payload["run_id"]
        records.setdefault(run_id, payload)
        records[run_id]["_manifest_path"] = str(manifest_path)
    latest = read_json(state_root / LATEST_RUN_NAME)
    if latest and latest.get("run_id"):
        run_id = latest["run_id"]
        records.setdefault(run_id, latest)
    entries: list[dict[str, Any]] = []
    for run_id, payload in records.items():
        notes = payload.get("notes", [])
        entries.append(
            {
                "run_id": run_id,
                "generated_at": payload.get("generated_at"),
                "status": payload.get("status"),
                "preview_only": payload.get("preview_only"),
                "manifest_path": payload.get("_manifest_path") or str(state_root / RUNS_ROOT_NAME / run_id / "manifest.json"),
                "history_path": payload.get("_history_path") or str(state_root / HISTORY_ROOT_NAME / f"{run_id}.json"),
                "run_root": str(state_root / RUNS_ROOT_NAME / run_id),
                "preview_root": str(state_root / RUNS_ROOT_NAME / run_id / "previews"),
                "note_count": len(notes),
                "portfolio_outputs": _portfolio_output_paths(notes),
                "project_outputs": _project_output_paths(notes),
            }
        )
    return sorted(entries, key=lambda item: item.get("generated_at") or "", reverse=True)


def _load_release_entries(state_root: Path) -> list[dict[str, Any]]:
    release_root = Path(state_root) / RELEASE_ROOT_NAME
    entries: list[dict[str, Any]] = []
    for json_path in sorted(release_root.glob("release_readiness_*.json")):
        payload = read_json(json_path)
        if payload is None:
            continue
        safe_stamp = json_path.stem.replace("release_readiness_", "")
        entries.append(
            {
                "generated_at": payload.get("generated_at"),
                "status": (payload.get("verdict") or {}).get("status"),
                "ready_for_live_operations": (payload.get("verdict") or {}).get("ready_for_live_operations"),
                "json_path": str(json_path),
                "markdown_path": str(release_root / f"release_readiness_{safe_stamp}.md"),
            }
        )
    return sorted(entries, key=lambda item: item.get("generated_at") or "", reverse=True)


def _latest_export_pointer(state_root: Path, latest_run: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "path": str(Path(state_root) / LATEST_RUN_NAME),
        "present": latest_run is not None,
        "run_id": latest_run.get("run_id") if latest_run else None,
        "generated_at": latest_run.get("generated_at") if latest_run else None,
        "status": latest_run.get("status") if latest_run else None,
    }


def _latest_acceptance_pointer(state_root: Path, acceptance: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "path": str(Path(state_root) / ACCEPTANCE_REPORT_NAME),
        "present": acceptance is not None,
        "executed_at": acceptance.get("executed_at") if acceptance else None,
        "status": acceptance.get("status") if acceptance else None,
    }


def _latest_release_pointer(state_root: Path, latest_release: dict[str, Any] | None) -> dict[str, Any]:
    release_root = Path(state_root) / RELEASE_ROOT_NAME
    return {
        "json_path": str(release_root / LATEST_RELEASE_JSON),
        "markdown_path": str(release_root / LATEST_RELEASE_MD),
        "present": latest_release is not None,
        "generated_at": latest_release.get("generated_at") if latest_release else None,
        "status": (latest_release.get("verdict") or {}).get("status") if latest_release else None,
    }


def _latest_diagnostics_pointer(state_root: Path, latest_diagnostics: dict[str, Any] | None) -> dict[str, Any]:
    diagnostics_root = Path(state_root) / DIAGNOSTICS_ROOT_NAME
    return {
        "path": str(diagnostics_root / LATEST_DIAGNOSTICS_NAME),
        "present": latest_diagnostics is not None,
        "captured_at": latest_diagnostics.get("captured_at") if latest_diagnostics else None,
    }


def _portfolio_output_paths(notes: list[dict[str, Any]]) -> list[str]:
    return [
        str(note.get("output_path"))
        for note in notes
        if note.get("note_kind") == "portfolio_weekly_summary" and note.get("output_path")
    ]


def _project_output_paths(notes: list[dict[str, Any]]) -> list[str]:
    return [
        str(note.get("output_path"))
        for note in notes
        if note.get("note_kind") in {"project_dossier", "project_weekly_brief"} and note.get("output_path")
    ]


def _prune_run_history(state_root: Path, limit: int, *, dry_run: bool) -> dict[str, Any]:
    entries = _load_export_run_entries(state_root)
    latest_run = read_json(Path(state_root) / LATEST_RUN_NAME)
    latest_run_id = latest_run.get("run_id") if latest_run else None
    latest_success_id = next((entry["run_id"] for entry in entries if entry.get("status") == "success"), None)
    keep_ids = {entry["run_id"] for entry in entries[:limit]}
    if latest_run_id:
        keep_ids.add(latest_run_id)
    if latest_success_id:
        keep_ids.add(latest_success_id)

    deleted_paths: list[str] = []
    for entry in entries:
        if entry["run_id"] in keep_ids:
            continue
        for path in (entry["history_path"], entry["run_root"]):
            deleted_paths.extend(_delete_path(Path(path), dry_run=dry_run))
    return {"kept_ids": sorted(keep_ids), "deleted_paths": deleted_paths}


def _prune_release_history(state_root: Path, limit: int, *, dry_run: bool) -> dict[str, Any]:
    entries = _load_release_entries(state_root)
    latest_release = read_json(Path(state_root) / RELEASE_ROOT_NAME / LATEST_RELEASE_JSON)
    latest_success_stem = None
    for entry in entries:
        if entry.get("ready_for_live_operations"):
            latest_success_stem = Path(entry["json_path"]).stem.replace("release_readiness_", "")
            break
    keep_stems = {
        Path(entry["json_path"]).stem.replace("release_readiness_", "")
        for entry in entries[:limit]
    }
    if latest_release and latest_release.get("generated_at"):
        keep_stems.add(str(latest_release["generated_at"]).replace(":", "-"))
    if latest_success_stem:
        keep_stems.add(latest_success_stem)

    deleted_paths: list[str] = []
    for entry in entries:
        stem = Path(entry["json_path"]).stem.replace("release_readiness_", "")
        if stem in keep_stems:
            continue
        deleted_paths.extend(_delete_path(Path(entry["json_path"]), dry_run=dry_run))
        deleted_paths.extend(_delete_path(Path(entry["markdown_path"]), dry_run=dry_run))
    return {"kept_ids": sorted(keep_stems), "deleted_paths": deleted_paths}


def _prune_operation_history(state_root: Path, limit: int, *, dry_run: bool) -> dict[str, Any]:
    entries = load_operation_history(state_root)
    keep_ids = {entry["operation_id"] for entry in entries[:limit] if entry.get("operation_id")}

    latest_per_type: dict[str, str] = {}
    latest_successful_per_type: dict[str, str] = {}
    for entry in entries:
        operation_type = entry.get("operation_type")
        operation_id = entry.get("operation_id")
        if not operation_type or not operation_id:
            continue
        latest_per_type.setdefault(operation_type, operation_id)
        if entry.get("status") == "success":
            latest_successful_per_type.setdefault(operation_type, operation_id)
    keep_ids.update(latest_per_type.values())
    keep_ids.update(latest_successful_per_type.values())

    deleted_paths: list[str] = []
    for entry in entries:
        operation_id = entry.get("operation_id")
        summary_path = entry.get("_summary_path")
        if not operation_id or not summary_path or operation_id in keep_ids:
            continue
        deleted_paths.extend(_delete_path(Path(summary_path), dry_run=dry_run))
    return {"kept_ids": sorted(keep_ids), "deleted_paths": deleted_paths}


def _prune_diagnostics_history(state_root: Path, limit: int, *, dry_run: bool) -> dict[str, Any]:
    diagnostics_root = Path(state_root) / DIAGNOSTICS_ROOT_NAME
    entries = sorted(diagnostics_root.glob("diagnostics_*.json"), reverse=True)
    keep_paths = {str(path) for path in entries[:limit]}
    deleted_paths: list[str] = []
    for path in entries:
        if str(path) in keep_paths:
            continue
        deleted_paths.extend(_delete_path(path, dry_run=dry_run))
    return {"kept_ids": sorted(keep_paths), "deleted_paths": deleted_paths}


def _prune_logs(state_root: Path, limit: int, *, kept_operation_ids: set[str], dry_run: bool) -> dict[str, Any]:
    logs_root = Path(state_root) / LOGS_ROOT_NAME
    log_files = sorted((path for path in logs_root.glob("*") if path.is_file()), key=lambda item: item.stat().st_mtime, reverse=True)
    keep_paths = {str(path) for path in log_files[:limit]}
    for entry in load_operation_history(state_root):
        if entry.get("operation_id") not in kept_operation_ids:
            continue
        artifacts = entry.get("artifacts", {})
        for key in ("stdout_log", "stderr_log"):
            value = artifacts.get(key)
            if value:
                keep_paths.add(str(Path(value)))

    deleted_paths: list[str] = []
    for path in log_files:
        if str(path) in keep_paths:
            continue
        deleted_paths.extend(_delete_path(path, dry_run=dry_run))
    return {"kept_ids": sorted(keep_paths), "deleted_paths": deleted_paths}


def _delete_path(path: Path, *, dry_run: bool) -> list[str]:
    path = Path(path)
    if not path.exists():
        return []
    deleted = [str(path)]
    if dry_run:
        return deleted
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return deleted

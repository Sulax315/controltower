from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from controltower.domain.models import utc_now_iso
from controltower.schedule_intake.export_artifacts import FILENAME_PUBLISH_PACKET

RUNS_DIRNAME = "runs"
REGISTRY_FILENAME = "registry.json"
RUN_METADATA_FILENAME = "run.json"
VALID_RUN_STATUSES = {"pending", "running", "completed", "failed"}


def create_run(
    state_root: Path,
    *,
    run_id: str,
    input_filename: str,
    input_path: Path,
    artifact_dir: Path,
    bundle_path: Path,
    manifest_path: Path,
    publish_packet_path: Path | None = None,
    status: str = "pending",
) -> dict[str, Any]:
    _validate_status(status)
    runs_root = _runs_root(state_root)
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "input").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    resolved_publish_path = (
        publish_packet_path if publish_packet_path is not None else artifact_dir / FILENAME_PUBLISH_PACKET
    )
    record = {
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "status": status,
        "input_filename": input_filename,
        "input_path": str(input_path),
        "artifact_dir": str(artifact_dir),
        "bundle_path": str(bundle_path),
        "manifest_path": str(manifest_path),
        "publish_packet_path": str(resolved_publish_path),
        "error_message": None,
    }
    _write_run_record(run_dir / RUN_METADATA_FILENAME, record)
    _upsert_registry_record(state_root, record)
    return record


def get_run(state_root: Path, run_id: str) -> dict[str, Any] | None:
    runs_root = _runs_root(state_root)
    path = runs_root / run_id / RUN_METADATA_FILENAME
    file_record = _read_json_safe(path)
    registry_record = _registry_record_by_id(state_root, run_id)
    if file_record is None and registry_record is None:
        return None
    merged = _merge_records(file_record=file_record, registry_record=registry_record, run_id=run_id)
    return _with_consistency_flags(merged)


def list_runs(state_root: Path) -> list[dict[str, Any]]:
    records_by_id: dict[str, dict[str, Any]] = {}
    registry = _read_registry(state_root)
    for record in registry.get("runs", []):
        if not isinstance(record, dict):
            continue
        run_id = str(record.get("run_id", "")).strip()
        if not run_id:
            continue
        records_by_id[run_id] = _with_consistency_flags(record)

    runs_root = _runs_root(state_root)
    for run_dir in runs_root.glob("run_*"):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        run_file = _read_json_safe(run_dir / RUN_METADATA_FILENAME)
        merged = _merge_records(file_record=run_file, registry_record=records_by_id.get(run_id), run_id=run_id)
        records_by_id[run_id] = _with_consistency_flags(merged)

    out = list(records_by_id.values())
    return sorted(out, key=lambda x: str(x.get("run_id", "")), reverse=True)


def update_run_status(
    state_root: Path,
    run_id: str,
    *,
    status: str,
    error_message: str | None = None,
) -> dict[str, Any]:
    _validate_status(status)
    run_path = _runs_root(state_root) / run_id / RUN_METADATA_FILENAME
    record = _read_json(run_path)
    record["status"] = status
    record["error_message"] = (error_message or None)
    _write_run_record(run_path, record)
    _upsert_registry_record(state_root, record)
    return record


def _runs_root(state_root: Path) -> Path:
    root = Path(state_root) / RUNS_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _registry_path(state_root: Path) -> Path:
    return _runs_root(state_root) / REGISTRY_FILENAME


def _read_registry(state_root: Path) -> dict[str, Any]:
    path = _registry_path(state_root)
    if not path.exists():
        return {"runs": []}
    payload = _read_json(path)
    if not isinstance(payload.get("runs"), list):
        return {"runs": []}
    return payload


def _upsert_registry_record(state_root: Path, record: dict[str, Any]) -> None:
    payload = _read_registry(state_root)
    records = payload["runs"]
    assert isinstance(records, list)
    run_id = str(record.get("run_id", ""))
    updated = False
    for idx, existing in enumerate(records):
        if isinstance(existing, dict) and str(existing.get("run_id", "")) == run_id:
            records[idx] = record
            updated = True
            break
    if not updated:
        records.append(record)
    records = sorted((x for x in records if isinstance(x, dict)), key=lambda x: str(x.get("run_id", "")), reverse=True)
    _write_json(_registry_path(state_root), {"runs": records})


def _validate_status(status: str) -> None:
    if status not in VALID_RUN_STATUSES:
        raise ValueError(f"Invalid run status: {status}")


def _write_run_record(path: Path, record: dict[str, Any]) -> None:
    _write_json(path, record)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _read_json_safe(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = _read_json(path)
    except Exception:
        return None
    return payload


def _registry_record_by_id(state_root: Path, run_id: str) -> dict[str, Any] | None:
    registry = _read_registry(state_root)
    for record in registry.get("runs", []):
        if isinstance(record, dict) and str(record.get("run_id", "")) == run_id:
            return record
    return None


def _merge_records(
    *,
    file_record: dict[str, Any] | None,
    registry_record: dict[str, Any] | None,
    run_id: str,
) -> dict[str, Any]:
    base = dict(registry_record or {})
    base.update(file_record or {})
    base["run_id"] = str(base.get("run_id") or run_id)
    base.setdefault("status", "failed")
    base.setdefault("created_at", utc_now_iso())
    base.setdefault("input_filename", "")
    base.setdefault("input_path", "")
    base.setdefault("artifact_dir", "")
    base.setdefault("bundle_path", "")
    base.setdefault("manifest_path", "")
    base.setdefault("publish_packet_path", "")
    base.setdefault("error_message", None)
    if file_record is None and registry_record is not None:
        base["consistency_state"] = "registry_only"
    elif file_record is not None and registry_record is None:
        base["consistency_state"] = "metadata_only"
    else:
        base["consistency_state"] = "consistent"
    return base


def _with_consistency_flags(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    bundle_raw = str(out.get("bundle_path") or "").strip()
    manifest_raw = str(out.get("manifest_path") or "").strip()
    artifact_raw = str(out.get("artifact_dir") or "").strip()
    input_raw = str(out.get("input_path") or "").strip()
    out["bundle_exists"] = Path(bundle_raw).is_file() if bundle_raw else False
    out["manifest_exists"] = Path(manifest_raw).is_file() if manifest_raw else False
    out["artifact_dir_exists"] = Path(artifact_raw).is_dir() if artifact_raw else False
    out["input_exists"] = Path(input_raw).is_file() if input_raw else False
    pp_raw = str(out.get("publish_packet_path") or "").strip()
    out["publish_packet_exists"] = Path(pp_raw).is_file() if pp_raw else False
    return out


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    path.write_text(text, encoding="utf-8")

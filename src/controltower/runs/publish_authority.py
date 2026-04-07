"""
Publish authority — explicit, deterministic criteria for operator-surface publishability.

A run is publishable only when registry state and on-disk export artifacts jointly satisfy
the same contracts used by execution (manifest + bundle validation + publish packet assembly).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from controltower.schedule_intake.publish_assembly import PublishPacket, build_publish_packet
from controltower.schedule_intake.verification import BundleValidationError, load_publish_bundle, validate_export_artifact_set

from controltower.runs.registry import list_runs


def load_publish_projection_from_bundle_path(bundle_path: str) -> PublishPacket:
    """Single server-side path from on-disk bundle JSON to the publish packet used for projection."""
    return build_publish_packet(load_publish_bundle(bundle_path))


def assess_run_publishability(state_root: Path, run: dict[str, Any]) -> tuple[bool, str | None]:
    """
    Return (True, None) if the run may be treated as authoritative for the publish operator projection.
    """
    state_root = Path(state_root).expanduser().resolve()
    run_id = str(run.get("run_id") or "").strip()
    if not run_id:
        return False, "run_id is missing."

    status = str(run.get("status") or "").strip().lower()
    if status != "completed":
        return False, f"run is not publishable: status is {status!r} (required completed)."

    bundle_path = str(run.get("bundle_path") or "").strip()
    if not bundle_path:
        return False, "Run bundle path is missing."
    bp = Path(bundle_path).expanduser().resolve()
    if not bp.is_file():
        return False, "Run bundle artifact is missing."

    artifact_dir = str(run.get("artifact_dir") or "").strip()
    if not artifact_dir:
        return False, "Run artifact directory is missing."
    ad = Path(artifact_dir).expanduser().resolve()
    if not ad.is_dir():
        return False, "Run artifact directory is missing."

    try:
        bp.relative_to(state_root)
        ad.relative_to(state_root)
    except ValueError:
        return False, "Run artifact paths must lie under the configured runtime state root."

    export_check = validate_export_artifact_set(ad)
    if not export_check.ok:
        return False, "Export artifact set is not publishable: " + "; ".join(export_check.errors)

    try:
        load_publish_projection_from_bundle_path(str(bp))
    except BundleValidationError as exc:
        return False, f"Bundle contract violation: {exc}"
    except Exception as exc:  # noqa: BLE001 — surface as non-publishable, not 500
        return False, f"Bundle could not be assembled for publish: {exc}"

    return True, None


def get_latest_publishable_run(state_root: Path) -> dict[str, Any] | None:
    """Latest publishable run by existing registry ordering (deterministic reverse run_id sort)."""
    for run in list_runs(state_root):
        ok, _ = assess_run_publishability(state_root, run)
        if ok:
            return run
    return None


def resolved_runtime_state_root(config_path: Path | None) -> Path:
    """
    Resolved ``runtime.state_root`` for a config file path.

    Used in tests and tooling to align CLI execution with UI config loading.
    """
    from controltower.config import load_config

    cfg = load_config(Path(config_path).resolve()) if config_path is not None else load_config()
    return Path(cfg.runtime.state_root).expanduser().resolve()

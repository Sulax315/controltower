"""
Control Tower → controltower_orchestrator_mcp durable substrate.

The orchestrator owns workflow and artifact state (JSON queues). This module only:
binds store paths from ``ControlTowerConfig``, imports the orchestrator orchestration package
in-process, and invokes the same read/mutation functions the MCP tools call.

Control Tower must not re-implement approvals, publish, release, or workflow projection logic.
"""

from __future__ import annotations

import sys
import threading
from typing import Any

from controltower.config import ControlTowerConfig, default_orchestrator_mcp_service_root

_lock = threading.Lock()
_bound_signature: str | None = None

SCHEDULE_PUBLISH_WORKFLOW_TYPE = "schedule_publish_workflow"

_SECRET_KEY_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "bearer",
    "authorization",
)


def substrate_unavailable_payload(*, code: str, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": {"code": code, "message": message},
        "source": "controltower_ui_substrate",
    }


def _strip_secrets_for_browser(obj: Any) -> Any:
    """Best-effort redaction for JSON placed in HTML data attributes (defense in depth)."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if any(fragment in lk for fragment in _SECRET_KEY_FRAGMENTS):
                out[k] = "[redacted]"
            else:
                out[k] = _strip_secrets_for_browser(v)
        return out
    if isinstance(obj, list):
        return [_strip_secrets_for_browser(i) for i in obj]
    return obj


def ensure_substrate_bound(config: ControlTowerConfig) -> str | None:
    """
    Bind orchestrator JSON paths. Returns an error message if substrate is disabled or invalid.
    Thread-safe; re-binds when service root or runtime dir changes.
    """
    if not config.orchestrator_substrate.enabled:
        return "orchestrator_substrate_disabled"

    root = config.orchestrator_substrate.mcp_service_root or default_orchestrator_mcp_service_root()
    root = root.resolve()
    if not root.is_dir():
        return f"orchestrator_mcp_service_root_missing:{root}"

    runtime_dir = config.orchestrator_substrate.runtime_dir or (root / "runtime")
    runtime_dir = runtime_dir.resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)

    signature = f"{root}|{runtime_dir}"
    global _bound_signature
    with _lock:
        if _bound_signature == signature:
            return None
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)

        import app.orchestration.approvals as orch_approvals  # noqa: PLC0415
        import app.orchestration.publish as orch_publish  # noqa: PLC0415
        import app.orchestration.release as orch_release  # noqa: PLC0415

        orch_approvals._QUEUE_JSON_PATH = runtime_dir / "approval_queue.json"
        orch_publish._PUBLISH_JSON_PATH = runtime_dir / "publish_packets.json"
        orch_release._RELEASE_JSON_PATH = runtime_dir / "release_requests.json"
        _bound_signature = signature
    return None


def list_approval_requests(
    config: ControlTowerConfig,
    *,
    state: str | None = None,
    approval_type: str | None = None,
    target_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    err = ensure_substrate_bound(config)
    if err:
        return substrate_unavailable_payload(code=err, message=err)
    from app.orchestration.approvals import list_approval_requests as fn  # noqa: PLC0415

    return fn(state=state, approval_type=approval_type, target_id=target_id, limit=limit)


def list_publish_packets(
    config: ControlTowerConfig,
    *,
    state: str | None = None,
    publish_target: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    err = ensure_substrate_bound(config)
    if err:
        return substrate_unavailable_payload(code=err, message=err)
    from app.orchestration.publish import list_publish_packets as fn  # noqa: PLC0415

    return fn(state=state, publish_target=publish_target, limit=limit)


def list_release_requests(
    config: ControlTowerConfig,
    *,
    state: str | None = None,
    target_env: str | None = None,
    release_type: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    err = ensure_substrate_bound(config)
    if err:
        return substrate_unavailable_payload(code=err, message=err)
    from app.orchestration.release import list_release_requests as fn  # noqa: PLC0415

    return fn(state=state, target_env=target_env, release_type=release_type, limit=limit)


def get_schedule_publish_workflow(config: ControlTowerConfig, workflow_id: str) -> dict[str, Any]:
    err = ensure_substrate_bound(config)
    if err:
        return substrate_unavailable_payload(code=err, message=err)
    from app.orchestration.schedule_publish_workflow import (  # noqa: PLC0415
        get_schedule_publish_workflow as fn,
    )

    return fn(workflow_id)


def approve_approval_request(
    config: ControlTowerConfig,
    *,
    approval_request_id: str,
    actor: str | None,
    reason: str | None,
) -> dict[str, Any]:
    err = ensure_substrate_bound(config)
    if err:
        return substrate_unavailable_payload(code=err, message=err)
    from app.orchestration.approvals import approve_approval_request as fn  # noqa: PLC0415

    return fn(approval_request_id, actor, reason)


def deny_approval_request(
    config: ControlTowerConfig,
    *,
    approval_request_id: str,
    actor: str | None,
    reason: str | None,
) -> dict[str, Any]:
    err = ensure_substrate_bound(config)
    if err:
        return substrate_unavailable_payload(code=err, message=err)
    from app.orchestration.approvals import deny_approval_request as fn  # noqa: PLC0415

    return fn(approval_request_id, actor, reason)


def promote_publish_packet(
    config: ControlTowerConfig,
    *,
    publish_request_id: str,
    actor: str | None,
    reason: str | None,
) -> dict[str, Any]:
    err = ensure_substrate_bound(config)
    if err:
        return substrate_unavailable_payload(code=err, message=err)
    from app.orchestration.publish import promote_publish_packet as fn  # noqa: PLC0415

    return fn(publish_request_id, actor, reason)


def execute_release_request(
    config: ControlTowerConfig,
    *,
    release_request_id: str,
    actor: str | None,
    reason: str | None,
) -> dict[str, Any]:
    err = ensure_substrate_bound(config)
    if err:
        return substrate_unavailable_payload(code=err, message=err)
    from app.orchestration.release import execute_release_request as fn  # noqa: PLC0415

    return fn(release_request_id, actor, reason)


def schedule_workflow_rows(config: ControlTowerConfig, *, limit: int = 80) -> list[dict[str, Any]]:
    """Approval queue rows whose payload marks a schedule_publish_workflow (for operator tables)."""
    raw = list_approval_requests(config, limit=min(limit, 500))
    if raw.get("status") != "ok":
        return []
    out: list[dict[str, Any]] = []
    for item in raw.get("items") or []:
        pl = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        if pl.get("workflow_type") == SCHEDULE_PUBLISH_WORKFLOW_TYPE and pl.get("workflow_id"):
            out.append(item)
    return out

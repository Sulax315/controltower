"""Server-side assembly of orchestrator substrate data for Control Tower publish / ops surfaces."""

from __future__ import annotations

from typing import Any

from controltower.config import ControlTowerConfig
from controltower.integrations import orchestrator_substrate as orch


def build_orchestrator_publish_panel(
    config: ControlTowerConfig,
    *,
    workflow_id: str | None = None,
    action_notice: str | None = None,
    action_error: str | None = None,
) -> dict[str, Any] | None:
    """
    Build a template-friendly payload for the publish-page execution band.

    Returns None when substrate integration is disabled (no UI section).
    """
    if not config.orchestrator_substrate.enabled:
        return None

    wf = (workflow_id or "").strip() or None
    schedule_rows = orch.schedule_workflow_rows(config, limit=80)
    approvals = orch.list_approval_requests(config, limit=80)
    packets = orch.list_publish_packets(config, limit=80)
    releases = orch.list_release_requests(config, limit=80)
    detail: dict[str, Any] | None = None
    if wf:
        raw_detail = orch.get_schedule_publish_workflow(config, wf)
        detail = raw_detail if isinstance(raw_detail, dict) else None

    return {
        "authority_note": (
            "Orchestrator durable stores are the source of truth; Control Tower only reads and "
            "forwards bounded mutations through the same seams as controltower_orchestrator_mcp."
        ),
        "schedule_workflow_rows": schedule_rows,
        "list_approvals": approvals,
        "list_publish": packets,
        "list_release": releases,
        "workflow_detail": detail,
        "selected_workflow_id": wf,
        "action_notice": action_notice,
        "action_error": action_error,
    }


def mutation_query_notices(result: dict[str, Any]) -> tuple[str, str | None]:
    """Map orchestrator mutation envelope to short query params for redirect UX."""
    status = str(result.get("status") or "")
    if status == "ok":
        return "ok", None
    err = result.get("error") if isinstance(result.get("error"), dict) else {}
    code = str(err.get("message") or err.get("code") or "mutation_failed")
    return "error", code[:512]

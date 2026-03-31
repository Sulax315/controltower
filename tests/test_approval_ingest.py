from __future__ import annotations

import json
from pathlib import Path

import pytest

from controltower.services.approval_ingest import ingest_approval_inbox, sync_pending_release_approval


def test_sync_pending_release_creates_awaiting_approval_state(tmp_path: Path):
    orchestration_root = tmp_path / "ops" / "orchestration"
    status_path = _write_release_status(tmp_path)

    result = sync_pending_release_approval(status_path, orchestration_root=orchestration_root)

    pending = json.loads((orchestration_root / "pending_approval.json").read_text(encoding="utf-8"))
    run_state = json.loads((orchestration_root / "run_state.json").read_text(encoding="utf-8"))
    next_prompt = (orchestration_root / "next_prompt.md").read_text(encoding="utf-8")
    trigger = json.loads((orchestration_root / "trigger_next_run.json").read_text(encoding="utf-8"))

    assert result["status"] == "awaiting_approval"
    assert pending["status"] == "awaiting_approval"
    assert pending["run_id"] == "release_review_run_2026_03_31"
    assert run_state["status"] == "awaiting_approval"
    assert run_state["pending_run_id"] == "release_review_run_2026_03_31"
    assert "Awaiting operator approval reply." in next_prompt
    assert trigger["ready_for_operator_launch"] is False


def test_ingest_approval_applies_approve_updates_state_and_notifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    orchestration_root = tmp_path / "ops" / "orchestration"
    status_path = _write_release_status(tmp_path)
    sync_pending_release_approval(status_path, orchestration_root=orchestration_root)
    (orchestration_root / "inbox" / "signal_approve.json").write_text(
        json.dumps({"source_channel": "signal", "message": "approve"}),
        encoding="utf-8-sig",
    )

    notifications: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(
        "controltower.services.approval_ingest.send_operator_notification",
        lambda message, status=None: notifications.append((message, status)),
    )

    result = ingest_approval_inbox(orchestration_root=orchestration_root)

    pending = json.loads((orchestration_root / "pending_approval.json").read_text(encoding="utf-8"))
    run_state = json.loads((orchestration_root / "run_state.json").read_text(encoding="utf-8"))
    next_prompt = (orchestration_root / "next_prompt.md").read_text(encoding="utf-8")
    trigger = json.loads((orchestration_root / "trigger_next_run.json").read_text(encoding="utf-8"))
    event_log = [
        json.loads(line)
        for line in (orchestration_root / "approval_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result["processed_file_count"] == 1
    assert result["events"][0]["normalized_command"] == "APPROVE"
    assert result["events"][0]["applied"] is True
    assert pending["status"] == "approved"
    assert pending["applied_command"] == "APPROVE"
    assert run_state["status"] == "approved"
    assert run_state["active_run_id"] == "release_review_run_2026_03_31"
    assert "Approved handoff for the next Codex lane:" in next_prompt
    assert trigger["command"] == "APPROVE"
    assert trigger["ready_for_operator_launch"] is True
    assert trigger["next_action"] == "launch_next_codex_lane"
    assert event_log[0]["parse_status"] == "parsed"
    assert event_log[0]["applied"] is True
    assert notifications
    assert "Approval applied" in notifications[0][0]
    assert (orchestration_root / "inbox" / "processed" / "signal_approve.json").exists()


def test_ingest_approval_rejects_mismatched_run_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    orchestration_root = tmp_path / "ops" / "orchestration"
    status_path = _write_release_status(tmp_path)
    sync_pending_release_approval(status_path, orchestration_root=orchestration_root)
    (orchestration_root / "inbox" / "signal_mismatch.json").write_text(
        json.dumps({"source_channel": "signal", "message": "APPROVE release_review_other"}),
        encoding="utf-8",
    )

    notifications: list[str] = []
    monkeypatch.setattr(
        "controltower.services.approval_ingest.send_operator_notification",
        lambda message, status=None: notifications.append(message),
    )

    result = ingest_approval_inbox(orchestration_root=orchestration_root)

    pending = json.loads((orchestration_root / "pending_approval.json").read_text(encoding="utf-8"))
    run_state = json.loads((orchestration_root / "run_state.json").read_text(encoding="utf-8"))
    next_prompt = (orchestration_root / "next_prompt.md").read_text(encoding="utf-8")
    trigger = json.loads((orchestration_root / "trigger_next_run.json").read_text(encoding="utf-8"))

    assert result["events"][0]["applied"] is False
    assert "does not match pending approval" in result["events"][0]["reason"]
    assert pending["status"] == "awaiting_approval"
    assert run_state["status"] == "awaiting_approval"
    assert "Status: approval_ignored" in next_prompt
    assert trigger["ready_for_operator_launch"] is False
    assert notifications
    assert "Approval ignored" in notifications[0]


def test_ingest_approval_rejects_when_no_pending_approval_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    orchestration_root = tmp_path / "ops" / "orchestration"
    (orchestration_root / "inbox").mkdir(parents=True, exist_ok=True)
    (orchestration_root / "inbox" / "signal_no_pending.json").write_text(
        json.dumps({"source_channel": "signal", "message": "APPROVE"}),
        encoding="utf-8",
    )

    notifications: list[str] = []
    monkeypatch.setattr(
        "controltower.services.approval_ingest.send_operator_notification",
        lambda message, status=None: notifications.append(message),
    )

    result = ingest_approval_inbox(orchestration_root=orchestration_root)

    pending = json.loads((orchestration_root / "pending_approval.json").read_text(encoding="utf-8"))
    run_state = json.loads((orchestration_root / "run_state.json").read_text(encoding="utf-8"))

    assert result["events"][0]["applied"] is False
    assert result["events"][0]["reason"] == "No matching pending approval exists."
    assert pending["status"] == "idle"
    assert run_state["status"] == "idle"
    assert notifications
    assert "Approval ignored" in notifications[0]


def test_hold_updates_state_and_preserves_non_launch_trigger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    orchestration_root = tmp_path / "ops" / "orchestration"
    status_path = _write_release_status(tmp_path)
    sync_pending_release_approval(status_path, orchestration_root=orchestration_root)
    (orchestration_root / "inbox" / "signal_hold.json").write_text(
        json.dumps({"source_channel": "signal", "message": "HOLD"}),
        encoding="utf-8",
    )
    monkeypatch.setattr("controltower.services.approval_ingest.send_operator_notification", lambda *args, **kwargs: None)

    ingest_approval_inbox(orchestration_root=orchestration_root)

    pending = json.loads((orchestration_root / "pending_approval.json").read_text(encoding="utf-8"))
    next_prompt = (orchestration_root / "next_prompt.md").read_text(encoding="utf-8")
    trigger = json.loads((orchestration_root / "trigger_next_run.json").read_text(encoding="utf-8"))

    assert pending["status"] == "held"
    assert "Operator hold is active." in next_prompt
    assert trigger["command"] == "HOLD"
    assert trigger["ready_for_operator_launch"] is False


def test_retry_creates_retry_prompt_and_trigger_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    orchestration_root = tmp_path / "ops" / "orchestration"
    status_path = _write_release_status(tmp_path)
    sync_pending_release_approval(status_path, orchestration_root=orchestration_root)
    (orchestration_root / "inbox" / "signal_retry.json").write_text(
        json.dumps({"source_channel": "signal", "message": "RETRY release_review_run_2026_03_31"}),
        encoding="utf-8",
    )
    monkeypatch.setattr("controltower.services.approval_ingest.send_operator_notification", lambda *args, **kwargs: None)

    ingest_approval_inbox(orchestration_root=orchestration_root)

    pending = json.loads((orchestration_root / "pending_approval.json").read_text(encoding="utf-8"))
    next_prompt = (orchestration_root / "next_prompt.md").read_text(encoding="utf-8")
    trigger = json.loads((orchestration_root / "trigger_next_run.json").read_text(encoding="utf-8"))

    assert pending["status"] == "retry_requested"
    assert "Retry handoff prepared." in next_prompt
    assert "Focus the next lane on rerunning or repairing stage: release_readiness" in next_prompt
    assert trigger["command"] == "RETRY"
    assert trigger["ready_for_operator_launch"] is True
    assert trigger["next_action"] == "rerun_release_lane"


def _write_release_status(tmp_path: Path) -> Path:
    release_root = tmp_path / "release"
    release_root.mkdir(parents=True, exist_ok=True)
    markdown_path = release_root / "latest_release_readiness.md"
    latest_json_path = release_root / "latest_release_readiness.json"
    diagnostics_path = tmp_path / "diagnostics" / "latest_diagnostics.json"
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_path.write_text("{}", encoding="utf-8")
    latest_run_path = tmp_path / "latest_run.json"
    latest_run_path.write_text("{}", encoding="utf-8")
    manifest_path = tmp_path / "runs" / "run_2026_03_31" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("{}", encoding="utf-8")
    markdown_path.write_text("# release\n", encoding="utf-8")

    payload = {
        "generated_at": "2026-03-31T12:34:56Z",
        "awaiting_approval": True,
        "next_recommended_action": "Approve next Codex lane",
        "failure_reason": None,
        "stage_results": {
            "pytest": {"status": "pass"},
            "readiness": {"status": "pass"},
            "acceptance": {"status": "pass"},
            "deploy": {"status": "pass"},
        },
        "latest_export": {
            "run_id": "run_2026_03_31",
            "manifest_path": str(manifest_path),
        },
        "latest_evidence": {
            "latest_diagnostics_path": str(diagnostics_path),
            "latest_run_path": str(latest_run_path),
        },
        "artifact_paths": {
            "json": str(latest_json_path),
            "latest_json": str(latest_json_path),
            "markdown": str(markdown_path),
            "latest_markdown": str(markdown_path),
        },
        "verdict": {
            "status": "ready",
            "summary": "Control Tower v2 is ready for live daily/weekly operation.",
            "operator_recommendation": "Proceed with live daily/weekly operation; continue monitoring diagnostics and scheduled summaries.",
            "ready_for_live_operations": True,
        },
    }
    latest_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return latest_json_path

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from controltower.domain.models import utc_now_iso
from controltower.services.notifications import send_operator_notification


APPROVAL_COMMANDS = {
    "APPROVE": "approved",
    "HOLD": "held",
    "RETRY": "retry_requested",
}
APPROVAL_EVENT_LOG_NAME = "approval_events.jsonl"
PENDING_APPROVAL_NAME = "pending_approval.json"
RUN_STATE_NAME = "run_state.json"
NEXT_PROMPT_NAME = "next_prompt.md"
TRIGGER_NEXT_RUN_NAME = "trigger_next_run.json"


def sync_pending_release_approval(
    status_path: Path | None = None,
    *,
    orchestration_root: Path | None = None,
) -> dict[str, Any]:
    paths = ensure_approval_layout(orchestration_root)
    resolved_status_path = Path(status_path) if status_path is not None else _default_release_status_path()
    status = json.loads(Path(resolved_status_path).read_text(encoding="utf-8"))
    now = utc_now_iso()

    if not bool(status.get("awaiting_approval")):
        pending = _base_pending_approval(now)
        pending.update(
            {
                "updated_at": now,
                "source_release_status_path": str(Path(resolved_status_path).resolve()),
                "reason": "Latest release artifact is not awaiting approval.",
            }
        )
        run_state = _base_run_state(now, orchestration_root=paths["root"])
        run_state.update(
            {
                "updated_at": now,
                "status": "idle",
                "source_release_status_path": str(Path(resolved_status_path).resolve()),
            }
        )
        _write_json(paths["pending_approval"], pending)
        _write_json(paths["run_state"], run_state)
        _write_text(paths["next_prompt"], _awaiting_prompt_markdown(pending, status=None))
        _write_json(paths["trigger_next_run"], _idle_trigger_payload(now, pending, orchestration_root=paths["root"]))
        return {
            "status": "no_pending_approval",
            "pending_approval_path": str(paths["pending_approval"]),
            "run_state_path": str(paths["run_state"]),
            "next_prompt_path": str(paths["next_prompt"]),
            "trigger_path": str(paths["trigger_next_run"]),
        }

    pending = _build_pending_approval(status, resolved_status_path, now=now)
    run_state = _build_run_state(pending, last_event=None, now=now, orchestration_root=paths["root"])
    _write_json(paths["pending_approval"], pending)
    _write_json(paths["run_state"], run_state)
    _write_text(paths["next_prompt"], _awaiting_prompt_markdown(pending, status=status))
    _write_json(paths["trigger_next_run"], _idle_trigger_payload(now, pending, orchestration_root=paths["root"]))
    return {
        "status": "awaiting_approval",
        "run_id": pending["run_id"],
        "pending_approval_path": str(paths["pending_approval"]),
        "run_state_path": str(paths["run_state"]),
        "next_prompt_path": str(paths["next_prompt"]),
        "trigger_path": str(paths["trigger_next_run"]),
    }


def ingest_approval_inbox(*, orchestration_root: Path | None = None) -> dict[str, Any]:
    paths = ensure_approval_layout(orchestration_root)
    inbox_files = sorted(path for path in paths["inbox"].glob("*.json") if path.is_file())
    results: list[dict[str, Any]] = []
    for inbox_file in inbox_files:
        results.append(_ingest_single_file(inbox_file, paths=paths))
    return {
        "status": "ok",
        "processed_file_count": len(results),
        "processed_files": [result["inbox_file"] for result in results],
        "events": results,
        "pending_approval_path": str(paths["pending_approval"]),
        "run_state_path": str(paths["run_state"]),
        "next_prompt_path": str(paths["next_prompt"]),
        "trigger_path": str(paths["trigger_next_run"]),
    }


def ensure_approval_layout(orchestration_root: Path | None = None) -> dict[str, Path]:
    root = Path(orchestration_root or _default_orchestration_root())
    paths = {
        "root": root,
        "inbox": root / "inbox",
        "processed_inbox": root / "inbox" / "processed",
        "approval_events": root / APPROVAL_EVENT_LOG_NAME,
        "pending_approval": root / PENDING_APPROVAL_NAME,
        "run_state": root / RUN_STATE_NAME,
        "next_prompt": root / NEXT_PROMPT_NAME,
        "trigger_next_run": root / TRIGGER_NEXT_RUN_NAME,
    }
    for key in ("root", "inbox", "processed_inbox"):
        paths[key].mkdir(parents=True, exist_ok=True)
    if not paths["approval_events"].exists():
        paths["approval_events"].write_text("", encoding="utf-8", newline="\n")
    if not paths["pending_approval"].exists():
        _write_json(paths["pending_approval"], _base_pending_approval(utc_now_iso()))
    if not paths["run_state"].exists():
        _write_json(paths["run_state"], _base_run_state(utc_now_iso(), orchestration_root=paths["root"]))
    if not paths["next_prompt"].exists():
        _write_text(paths["next_prompt"], "# Control Tower Next Prompt\n\nNo approval state has been recorded yet.\n")
    if not paths["trigger_next_run"].exists():
        _write_json(
            paths["trigger_next_run"],
            _idle_trigger_payload(
                utc_now_iso(),
                _base_pending_approval(utc_now_iso()),
                orchestration_root=paths["root"],
            ),
        )
    return paths


def _ingest_single_file(inbox_file: Path, *, paths: dict[str, Path]) -> dict[str, Any]:
    ingested_at = utc_now_iso()
    try:
        payload = json.loads(inbox_file.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        event = {
            "event_id": _event_id(ingested_at, inbox_file.stem),
            "timestamp": ingested_at,
            "ingested_at": ingested_at,
            "source_channel": "file",
            "raw_message": None,
            "normalized_command": None,
            "referenced_run_id": None,
            "parse_status": "invalid_payload",
            "applied": False,
            "reason": f"Unreadable inbound approval payload: {exc}",
            "inbox_file": str(inbox_file.resolve()),
        }
        _append_event(paths["approval_events"], event)
        _archive_inbox_file(inbox_file, paths["processed_inbox"])
        return event

    event = _parse_payload(payload, inbox_file=inbox_file, ingested_at=ingested_at)
    event = _apply_event(event, payload=payload, paths=paths)
    _append_event(paths["approval_events"], event)
    _archive_inbox_file(inbox_file, paths["processed_inbox"])

    if event["normalized_command"] in APPROVAL_COMMANDS:
        send_operator_notification(_notification_feedback_message(event), status={"approval_event": event})
    return event


def _parse_payload(payload: dict[str, Any], *, inbox_file: Path, ingested_at: str) -> dict[str, Any]:
    timestamp = _payload_text(payload, "timestamp", "received_at", "sent_at", "message_timestamp") or ingested_at
    raw_message = _payload_text(payload, "raw_message", "message", "text", "body", "content")
    source_channel = _payload_text(payload, "source_channel", "channel", "provider", "transport") or "file"
    normalized_text = _normalize_message(raw_message)
    command, referenced_run_id = _parse_command(normalized_text)
    parse_status = "parsed" if command else "unsupported_command"
    reason = None if command else "Message did not match APPROVE, HOLD, or RETRY."
    return {
        "event_id": _event_id(ingested_at, inbox_file.stem),
        "timestamp": timestamp,
        "ingested_at": ingested_at,
        "source_channel": source_channel,
        "raw_message": raw_message,
        "normalized_command": command,
        "referenced_run_id": referenced_run_id,
        "parse_status": parse_status,
        "applied": False,
        "reason": reason,
        "inbox_file": str(inbox_file.resolve()),
        "message_id": _payload_text(payload, "message_id", "id", "envelope_id"),
    }


def _apply_event(event: dict[str, Any], *, payload: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    if event["parse_status"] != "parsed":
        return event

    pending = _read_json(paths["pending_approval"]) or _base_pending_approval(event["ingested_at"])
    current_state = _read_json(paths["run_state"]) or _base_run_state(
        event["ingested_at"],
        orchestration_root=paths["root"],
    )
    status_path = pending.get("source_release_status_path")
    release_status = _load_release_status(Path(status_path)) if status_path else None

    if pending.get("status") != "awaiting_approval" or not pending.get("run_id"):
        event["reason"] = "No matching pending approval exists."
        return _write_current_state(current_state, pending, event, release_status, paths)

    if event["referenced_run_id"] and event["referenced_run_id"] != pending.get("run_id"):
        event["reason"] = f"Referenced run_id does not match pending approval {pending['run_id']}."
        return _write_current_state(current_state, pending, event, release_status, paths)

    command = event["normalized_command"]
    next_state = APPROVAL_COMMANDS[command]
    applied_at = event["timestamp"]
    pending.update(
        {
            "status": next_state,
            "updated_at": applied_at,
            "applied_command": command,
            "applied_at": applied_at,
            "applied_source_channel": event["source_channel"],
            "last_inbox_file": event["inbox_file"],
            "last_message_id": event.get("message_id"),
            "pending": False,
        }
    )
    event["applied"] = True
    event["reason"] = None
    event["applied_run_id"] = pending["run_id"]
    current_state = _build_run_state(pending, last_event=event, now=applied_at, orchestration_root=paths["root"])
    _write_json(paths["pending_approval"], pending)
    _write_json(paths["run_state"], current_state)
    _write_text(paths["next_prompt"], _decision_prompt_markdown(pending, release_status=release_status))
    _write_json(
        paths["trigger_next_run"],
        _trigger_payload(pending, release_status=release_status, orchestration_root=paths["root"]),
    )
    return event


def _write_current_state(
    current_state: dict[str, Any],
    pending: dict[str, Any],
    event: dict[str, Any],
    release_status: dict[str, Any] | None,
    paths: dict[str, Path],
) -> dict[str, Any]:
    current_state = dict(current_state)
    current_state["updated_at"] = event["ingested_at"]
    current_state["last_event"] = _event_summary(event)
    _write_json(paths["run_state"], current_state)
    _write_json(paths["pending_approval"], pending)
    _write_text(paths["next_prompt"], _ignored_prompt_markdown(pending, event, release_status=release_status))
    _write_json(
        paths["trigger_next_run"],
        _idle_trigger_payload(event["ingested_at"], pending, orchestration_root=paths["root"], event=event),
    )
    return event


def _build_pending_approval(status: dict[str, Any], status_path: Path, *, now: str) -> dict[str, Any]:
    latest_export = status.get("latest_export") or {}
    verdict = status.get("verdict") or {}
    artifact_paths = status.get("artifact_paths") or {}
    latest_evidence = status.get("latest_evidence") or {}
    generated_at = str(status.get("generated_at") or now)
    run_id = _release_run_id(status)
    return {
        "status": "awaiting_approval",
        "pending": True,
        "run_id": run_id,
        "created_at": now,
        "updated_at": now,
        "source_channel": "release_readiness",
        "source_release_status_path": str(Path(status_path).resolve()),
        "release_generated_at": generated_at,
        "release_verdict": verdict.get("status"),
        "release_summary": verdict.get("summary"),
        "operator_recommendation": verdict.get("operator_recommendation"),
        "next_recommended_action": status.get("next_recommended_action"),
        "latest_export_run_id": latest_export.get("run_id"),
        "latest_export_manifest_path": latest_export.get("manifest_path"),
        "latest_release_markdown_path": artifact_paths.get("latest_markdown") or artifact_paths.get("markdown"),
        "latest_release_json_path": artifact_paths.get("latest_json") or artifact_paths.get("json"),
        "latest_diagnostics_path": latest_evidence.get("latest_diagnostics_path"),
        "diagnostics_snapshot_path": latest_evidence.get("diagnostics_snapshot_path"),
        "latest_run_path": latest_evidence.get("latest_run_path"),
        "failure_reason": status.get("failure_reason"),
        "failed_stage": _first_failed_stage(status),
        "allowed_commands": sorted(APPROVAL_COMMANDS),
    }


def _build_run_state(
    pending: dict[str, Any],
    *,
    last_event: dict[str, Any] | None,
    now: str,
    orchestration_root: Path,
) -> dict[str, Any]:
    return {
        "updated_at": now,
        "status": pending.get("status") or "idle",
        "pending_run_id": pending.get("run_id") if pending.get("status") == "awaiting_approval" else None,
        "active_run_id": pending.get("run_id"),
        "latest_export_run_id": pending.get("latest_export_run_id"),
        "source_release_status_path": pending.get("source_release_status_path"),
        "next_prompt_path": str((orchestration_root / NEXT_PROMPT_NAME).resolve()),
        "trigger_path": str((orchestration_root / TRIGGER_NEXT_RUN_NAME).resolve()),
        "last_event": _event_summary(last_event) if last_event else None,
    }


def _base_pending_approval(now: str) -> dict[str, Any]:
    return {
        "status": "idle",
        "pending": False,
        "run_id": None,
        "created_at": now,
        "updated_at": now,
        "source_channel": None,
        "source_release_status_path": None,
        "release_generated_at": None,
        "release_verdict": None,
        "release_summary": None,
        "operator_recommendation": None,
        "next_recommended_action": None,
        "latest_export_run_id": None,
        "latest_export_manifest_path": None,
        "latest_release_markdown_path": None,
        "latest_release_json_path": None,
        "latest_diagnostics_path": None,
        "diagnostics_snapshot_path": None,
        "latest_run_path": None,
        "failure_reason": None,
        "failed_stage": None,
        "allowed_commands": sorted(APPROVAL_COMMANDS),
    }


def _base_run_state(now: str, *, orchestration_root: Path | None = None) -> dict[str, Any]:
    root = Path(orchestration_root or _default_orchestration_root())
    return {
        "updated_at": now,
        "status": "idle",
        "pending_run_id": None,
        "active_run_id": None,
        "latest_export_run_id": None,
        "source_release_status_path": None,
        "next_prompt_path": str(root / NEXT_PROMPT_NAME),
        "trigger_path": str(root / TRIGGER_NEXT_RUN_NAME),
        "last_event": None,
    }


def _awaiting_prompt_markdown(pending: dict[str, Any], *, status: dict[str, Any] | None) -> str:
    lines = [
        "# Control Tower Next Prompt",
        "",
        f"Status: {pending.get('status')}",
        f"Run ID: {pending.get('run_id') or 'none'}",
    ]
    if pending.get("status") != "awaiting_approval":
        lines.extend(
            [
                "",
                "No pending approval is currently active.",
            ]
        )
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            f"Release Generated At: {pending.get('release_generated_at') or 'unknown'}",
            f"Latest Export Run: {pending.get('latest_export_run_id') or 'unknown'}",
            "",
            "Awaiting operator approval reply.",
            "",
            "Accepted replies:",
            "- APPROVE",
            "- HOLD",
            "- RETRY",
            f"- APPROVE {pending['run_id']}",
            f"- RETRY {pending['run_id']}",
        ]
    )
    if status:
        lines.extend(
            [
                "",
                "Release Context:",
                f"- Verdict: {(status.get('verdict') or {}).get('status') or 'unknown'}",
                f"- Summary: {(status.get('verdict') or {}).get('summary') or 'No summary recorded.'}",
                f"- Next Recommended Action: {status.get('next_recommended_action') or 'Not provided.'}",
            ]
        )
    return "\n".join(lines) + "\n"


def _ignored_prompt_markdown(
    pending: dict[str, Any],
    event: dict[str, Any],
    *,
    release_status: dict[str, Any] | None,
) -> str:
    lines = [
        "# Control Tower Next Prompt",
        "",
        "Status: approval_ignored",
        f"Command: {event.get('normalized_command') or 'unparsed'}",
        f"Reason: {event.get('reason') or 'No reason recorded.'}",
        "",
        "Current Context:",
        f"- Pending Status: {pending.get('status') or 'idle'}",
        f"- Pending Run ID: {pending.get('run_id') or 'none'}",
        f"- Release Status Path: {pending.get('source_release_status_path') or 'unavailable'}",
    ]
    if release_status:
        lines.append(f"- Release Verdict: {(release_status.get('verdict') or {}).get('status') or 'unknown'}")
    return "\n".join(lines) + "\n"


def _decision_prompt_markdown(pending: dict[str, Any], *, release_status: dict[str, Any] | None) -> str:
    command = pending.get("applied_command") or "UNKNOWN"
    lines = [
        "# Control Tower Next Prompt",
        "",
        f"Status: {pending.get('status')}",
        f"Command: {command}",
        f"Run ID: {pending.get('run_id') or 'unknown'}",
        f"Applied At: {pending.get('applied_at') or pending.get('updated_at') or 'unknown'}",
        "",
        "Artifact Context:",
        f"- Release JSON: {pending.get('latest_release_json_path') or pending.get('source_release_status_path') or 'unavailable'}",
        f"- Release Markdown: {pending.get('latest_release_markdown_path') or 'unavailable'}",
        f"- Latest Diagnostics: {pending.get('latest_diagnostics_path') or 'unavailable'}",
        f"- Latest Run Pointer: {pending.get('latest_run_path') or 'unavailable'}",
        f"- Export Manifest: {pending.get('latest_export_manifest_path') or 'unavailable'}",
        "",
    ]
    if command == "APPROVE":
        lines.extend(_approve_prompt_body(pending, release_status=release_status))
    elif command == "HOLD":
        lines.extend(_hold_prompt_body(pending, release_status=release_status))
    else:
        lines.extend(_retry_prompt_body(pending, release_status=release_status))
    return "\n".join(lines) + "\n"


def _approve_prompt_body(pending: dict[str, Any], *, release_status: dict[str, Any] | None) -> list[str]:
    verdict = (release_status or {}).get("verdict") or {}
    return [
        "Approved handoff for the next Codex lane:",
        "",
        "Continue inside the existing Control Tower repository and build from the already validated release state.",
        f"Use release summary: {verdict.get('summary') or pending.get('release_summary') or 'No summary recorded.'}",
        f"Use next recommended action: {pending.get('next_recommended_action') or 'Approve next Codex lane'}",
        "Do not rework prior release or notification logic.",
        "Start from the artifacts listed above, confirm current state, and prepare the next operator-visible lane output only.",
    ]


def _hold_prompt_body(pending: dict[str, Any], *, release_status: dict[str, Any] | None) -> list[str]:
    verdict = (release_status or {}).get("verdict") or {}
    return [
        "Operator hold is active.",
        "",
        f"Preserve the current release context: {verdict.get('summary') or pending.get('release_summary') or 'No summary recorded.'}",
        "Do not launch the next lane.",
        "Wait for a later APPROVE or RETRY command before preparing operator launch artifacts.",
    ]


def _retry_prompt_body(pending: dict[str, Any], *, release_status: dict[str, Any] | None) -> list[str]:
    target_stage = pending.get("failed_stage") or _first_failed_stage(release_status) or "release_readiness"
    failure_reason = pending.get("failure_reason") or (release_status or {}).get("failure_reason") or "No failure reason recorded."
    return [
        "Retry handoff prepared.",
        "",
        f"Focus the next lane on rerunning or repairing stage: {target_stage}",
        f"Known failure reason: {failure_reason}",
        "Use the recorded release and diagnostics artifacts as the starting point.",
        "Re-establish a validated state before asking for another approval.",
    ]


def _trigger_payload(
    pending: dict[str, Any],
    *,
    release_status: dict[str, Any] | None,
    orchestration_root: Path,
) -> dict[str, Any]:
    command = pending.get("applied_command") or "UNKNOWN"
    ready = command in {"APPROVE", "RETRY"}
    next_action = "launch_next_codex_lane" if command == "APPROVE" else "rerun_release_lane" if command == "RETRY" else "hold"
    return {
        "approved_at": pending.get("applied_at"),
        "command": command,
        "target_run_id": pending.get("run_id"),
        "next_action": next_action,
        "next_prompt_path": str((orchestration_root / NEXT_PROMPT_NAME).resolve()),
        "ready_for_operator_launch": ready,
        "release_status_path": pending.get("source_release_status_path"),
        "release_generated_at": pending.get("release_generated_at"),
        "release_verdict": ((release_status or {}).get("verdict") or {}).get("status") or pending.get("release_verdict"),
        "latest_export_run_id": pending.get("latest_export_run_id"),
    }


def _idle_trigger_payload(
    now: str,
    pending: dict[str, Any],
    *,
    orchestration_root: Path,
    event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "approved_at": None,
        "command": event.get("normalized_command") if event else None,
        "target_run_id": pending.get("run_id"),
        "next_action": "await_operator_input",
        "next_prompt_path": str((orchestration_root / NEXT_PROMPT_NAME).resolve()),
        "ready_for_operator_launch": False,
        "release_status_path": pending.get("source_release_status_path"),
        "release_generated_at": pending.get("release_generated_at"),
        "updated_at": now,
        "reason": event.get("reason") if event else None,
    }


def _notification_feedback_message(event: dict[str, Any]) -> str:
    if event.get("applied"):
        return (
            "Approval applied\n"
            f"Command: {event['normalized_command']}\n"
            f"Run: {event.get('applied_run_id') or event.get('referenced_run_id') or 'pending'}\n"
            "Next: next_prompt.md updated"
        )
    return (
        "Approval ignored\n"
        f"Reason: {event.get('reason') or 'No reason recorded.'}\n"
        f"Command: {(event.get('raw_message') or '').strip() or event.get('normalized_command') or 'unparsed'}"
    )


def _event_summary(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        "event_id": event.get("event_id"),
        "timestamp": event.get("timestamp"),
        "source_channel": event.get("source_channel"),
        "raw_message": event.get("raw_message"),
        "normalized_command": event.get("normalized_command"),
        "referenced_run_id": event.get("referenced_run_id"),
        "parse_status": event.get("parse_status"),
        "applied": event.get("applied"),
        "reason": event.get("reason"),
    }


def _first_failed_stage(status: dict[str, Any] | None) -> str | None:
    if not status:
        return None
    for name, stage in (status.get("stage_results") or {}).items():
        state = ""
        if isinstance(stage, dict):
            state = str(stage.get("status") or "").strip().lower()
        else:
            state = str(stage or "").strip().lower()
        if state in {"fail", "failed", "error", "not_ready"}:
            return name
    return None


def _append_event(path: Path, event: dict[str, Any]) -> None:
    serialized = json.dumps(event, sort_keys=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(serialized)
        handle.write("\n")


def _archive_inbox_file(inbox_file: Path, processed_root: Path) -> None:
    processed_root.mkdir(parents=True, exist_ok=True)
    destination = processed_root / inbox_file.name
    if destination.exists():
        destination = processed_root / f"{inbox_file.stem}_{utc_now_iso().replace(':', '-')}{inbox_file.suffix}"
    shutil.move(str(inbox_file), str(destination))


def _default_orchestration_root() -> Path:
    return Path(__file__).resolve().parents[3] / "ops" / "orchestration"


def _default_release_status_path() -> Path:
    return Path(__file__).resolve().parents[3] / ".controltower_runtime" / "release" / "latest_release_readiness.json"


def _event_id(timestamp: str, suffix: str) -> str:
    safe_suffix = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in suffix)
    return f"approval_event_{timestamp.replace(':', '-')}_{safe_suffix}"


def _parse_command(message: str | None) -> tuple[str | None, str | None]:
    if not message:
        return None, None
    parts = message.split(" ", 1)
    command = parts[0].upper()
    if command not in APPROVAL_COMMANDS:
        return None, None
    run_id = parts[1].strip() if len(parts) > 1 else None
    return command, run_id or None


def _normalize_message(message: str | None) -> str | None:
    if message is None:
        return None
    normalized = " ".join(str(message).strip().split())
    return normalized or None


def _payload_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _release_run_id(status: dict[str, Any]) -> str:
    latest_export = status.get("latest_export") or {}
    if latest_export.get("run_id"):
        return f"release_review_{latest_export['run_id']}"
    generated_at = str(status.get("generated_at") or utc_now_iso())
    return f"release_review_{generated_at.replace(':', '-')}"


def _load_release_status(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")

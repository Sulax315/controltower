from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, MutableMapping

from controltower.domain.models import utc_now_iso
from controltower.services.notifications import (
    DEFAULT_SIGNAL_TIMEOUT_SECONDS,
    _mask_sensitive_text,
    delivery_artifact_path,
    dispatch_notification_message,
    load_notification_environment,
    selected_notification_channel,
    signal_cli_configuration,
)


def inspect_signal_transport(
    *,
    environ: MutableMapping[str, str] | None = None,
    env_file: Path | None = None,
    host_marker: str | None = None,
    send_test: bool = True,
    status_path: Path | None = None,
) -> dict[str, Any]:
    current_environ = os.environ if environ is None else environ
    loaded_env = load_notification_environment(current_environ, env_file=env_file)
    generated_at = utc_now_iso()
    command_path = _env_value(current_environ, "SIGNAL_CLI_PATH")
    sender = _env_value(current_environ, "SIGNAL_SENDER")
    recipient = _env_value(current_environ, "SIGNAL_RECIPIENT")
    signal_config = signal_cli_configuration(current_environ)
    artifact_path = delivery_artifact_path(current_environ, status_path=status_path)

    summary: dict[str, Any] = {
        "generated_at": generated_at,
        "status": "pending",
        "selected_channel": selected_notification_channel(current_environ),
        "env_file": str(Path(loaded_env).resolve()) if loaded_env is not None else None,
        "artifact_path": str(artifact_path.resolve()),
        "config": {
            "status": "pass" if signal_config["configuration_present"] else "fail",
            "missing_env": list(signal_config["missing_env"]),
            "command_path": signal_config["command_path"],
            "sender": signal_config["sender"],
            "recipient": signal_config["recipient"],
        },
        "executable": {
            "status": "pending",
            "requested_path": command_path,
            "resolved_path": None,
        },
        "registration": {
            "status": "pending",
            "sender": signal_config["sender"],
            "sender_registered": None,
            "registered_accounts": [],
            "command": None,
            "error": None,
        },
        "outbound_test": {
            "status": "not_run",
            "host_marker": (host_marker or platform.node() or "local").strip() or "local",
            "delivery_state": None,
            "failure_reason": None,
        },
        "latest_delivery_artifact": _load_artifact(artifact_path),
    }

    resolved_command = _resolve_signal_cli_path(command_path)
    summary["executable"]["resolved_path"] = resolved_command
    summary["executable"]["status"] = "pass" if resolved_command else "fail"

    if resolved_command and sender:
        summary["registration"] = inspect_signal_registration(
            resolved_command,
            sender=sender,
        )
    elif not sender:
        summary["registration"]["status"] = "blocked"
        summary["registration"]["error"] = "SIGNAL_SENDER is not configured."
    else:
        summary["registration"]["status"] = "blocked"
        summary["registration"]["error"] = "signal-cli executable is not available."

    if send_test:
        outbound = run_signal_delivery_test(
            environ=current_environ,
            host_marker=summary["outbound_test"]["host_marker"],
            status_path=status_path,
        )
        summary["outbound_test"] = outbound
        summary["latest_delivery_artifact"] = _load_artifact(artifact_path)
        summary["status"] = outbound["delivery_state"] or "send_failed"
        return summary

    summary["status"] = _precheck_state(summary)
    return summary


def inspect_signal_registration(
    resolved_command: str,
    *,
    sender: str,
    timeout_seconds: int = DEFAULT_SIGNAL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    command = [resolved_command, "-o", "json", "listAccounts"]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "signal-cli listAccounts exited non-zero.").strip()
        return {
            "status": "execution_failed",
            "sender": _mask_phone(sender),
            "sender_registered": None,
            "registered_accounts": [],
            "command": _display_command(command),
            "error": _mask_sensitive_text(detail),
        }

    accounts = _parse_list_accounts_output(completed.stdout)
    normalized_sender = _normalize_signal_account(sender)
    sender_registered = normalized_sender in {_normalize_signal_account(account) for account in accounts}
    return {
        "status": "pass" if sender_registered else "registration_missing",
        "sender": _mask_phone(sender),
        "sender_registered": sender_registered,
        "registered_accounts": [_mask_phone(account) for account in accounts],
        "command": _display_command(command),
        "error": None,
    }


def run_signal_delivery_test(
    *,
    environ: MutableMapping[str, str] | None = None,
    host_marker: str | None = None,
    status_path: Path | None = None,
) -> dict[str, Any]:
    current_environ = os.environ if environ is None else environ
    now = utc_now_iso()
    marker = (host_marker or platform.node() or "local").strip() or "local"
    message = (
        "Control Tower Signal Test\n"
        "Status: PASS\n"
        f"Host: {marker}\n"
        f"Time: {now}"
    )
    artifact_path = delivery_artifact_path(current_environ, status_path=status_path)

    try:
        dispatch_notification_message(
            message,
            status={"kind": "signal_test", "timestamp": now, "host": marker},
            environ=current_environ,
            require_channel="signal_cli",
            status_path=status_path,
        )
    except Exception:
        artifact = _load_artifact(artifact_path)
        return {
            "status": "fail",
            "host_marker": marker,
            "delivery_state": (artifact or {}).get("delivery_state"),
            "failure_reason": (artifact or {}).get("failure_reason"),
        }

    artifact = _load_artifact(artifact_path)
    return {
        "status": "pass",
        "host_marker": marker,
        "delivery_state": (artifact or {}).get("delivery_state"),
        "failure_reason": (artifact or {}).get("failure_reason"),
    }


def _precheck_state(summary: dict[str, Any]) -> str:
    if summary["config"]["status"] != "pass":
        return "config_missing"
    if summary["executable"]["status"] != "pass":
        return "executable_missing"

    registration = summary["registration"]
    if registration["status"] == "registration_missing":
        return "registration_missing"
    if registration["status"] == "execution_failed":
        return "send_failed"
    return "ready_to_send"


def _parse_list_accounts_output(stdout: str) -> list[str]:
    stripped = stdout.strip()
    if not stripped:
        return []

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return [line.strip() for line in stripped.splitlines() if line.strip()]

    if isinstance(parsed, list):
        return [_account_value(entry) for entry in parsed if _account_value(entry)]
    if isinstance(parsed, dict):
        for key in ("accounts", "results", "items"):
            value = parsed.get(key)
            if isinstance(value, list):
                return [_account_value(entry) for entry in value if _account_value(entry)]
    value = _account_value(parsed)
    return [value] if value else []


def _account_value(entry: Any) -> str | None:
    if isinstance(entry, str):
        stripped = entry.strip()
        return stripped or None
    if isinstance(entry, dict):
        for key in ("account", "number", "username"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _normalize_signal_account(value: str) -> str:
    trimmed = value.strip()
    digits = "".join(char for char in trimmed if char.isdigit())
    return f"+{digits}" if trimmed.startswith("+") or digits else trimmed


def _resolve_signal_cli_path(command_path: str | None) -> str | None:
    if not command_path:
        return None

    candidate = shutil.which(command_path)
    if candidate:
        return candidate

    expanded = Path(command_path).expanduser()
    if expanded.exists():
        return str(expanded)
    return None


def _env_value(environ: MutableMapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _display_command(command: list[str]) -> str:
    return " ".join(command)


def _load_artifact(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if isinstance(payload, dict):
        return payload
    return None


def _mask_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = [char for char in value if char.isdigit()]
    if len(digits) <= 4:
        return "***"
    prefix = "+" if value.strip().startswith("+") else ""
    return f"{prefix}***{''.join(digits[-4:])}"

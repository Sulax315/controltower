from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, MutableMapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from controltower.domain.models import utc_now_iso
from controltower.logging_utils import configure_logging, get_logger


LOGGER = get_logger(__name__)
DEFAULT_SIGNAL_TIMEOUT_SECONDS = 15
DEFAULT_WEBHOOK_TIMEOUT_SECONDS = 10
DEFAULT_ENV_FILE_NAME = "controltower.env"
DEFAULT_DELIVERY_ARTIFACT_NAME = "latest_delivery_attempt.json"


def send_release_notification(status: dict[str, Any], *, status_path: Path | None = None) -> None:
    message = format_release_message(status)
    try:
        dispatch_notification_message(message, status=status, status_path=status_path)
    except Exception as exc:  # pragma: no cover - defended by tests through call sites
        channel = _selected_channel(os.environ)
        LOGGER.warning("Release notification via %s failed: %s", channel, _mask_sensitive_text(str(exc)))


def format_release_message(status: dict[str, Any]) -> str:
    release_passed = _release_passed(status)
    title = "Control Tower Release PASS" if release_passed else "Control Tower Release FAIL"
    lines = [title]

    commit = _commit_from_status(status)
    if commit:
        lines.append(f"Commit: {commit}")

    branch = _branch_from_status(status)
    if branch:
        lines.append(f"Branch: {branch}")

    if release_passed:
        stages = _stage_rows(status)
        if stages:
            lines.extend(["", "Stages:"])
            lines.extend(f"- {name}: {_display_status(stage_status)}" for name, stage_status in stages)
        live_url = _live_url(status)
        if live_url:
            lines.extend(["", "Live:", live_url])
        if _awaiting_approval(status):
            lines.extend(["", "Awaiting approval before next step"])
        next_action = _next_action(status, release_passed=release_passed)
        if next_action:
            lines.extend(["", "Next:", next_action])
        return "\n".join(lines)

    failed_stage = _failed_stage(status)
    if failed_stage:
        lines.extend(["", "Failed Stage:", failed_stage])

    reason = _failure_reason(status)
    if reason:
        lines.extend(["", "Reason:", reason])

    if _awaiting_approval(status):
        lines.extend(["", "Awaiting approval before next step"])

    action = _next_action(status, release_passed=release_passed)
    if action:
        lines.extend(["", "Action:", action])

    return "\n".join(lines)


def notify_release_status_file(status_path: Path) -> None:
    path = Path(status_path)
    if not path.exists():
        LOGGER.warning("Release notification skipped because the status artifact is missing: %s", path)
        return
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Release notification skipped because the status artifact could not be read: %s", exc)
        return
    send_release_notification(status, status_path=path)


def send_operator_notification(message: str, *, status: dict[str, Any] | None = None) -> None:
    try:
        dispatch_notification_message(message, status=status)
    except Exception as exc:  # pragma: no cover - defended by higher-level service tests
        channel = _selected_channel(os.environ)
        LOGGER.warning("Operator notification via %s failed: %s", channel, _mask_sensitive_text(str(exc)))


def dispatch_notification_message(
    message: str,
    *,
    status: dict[str, Any] | None = None,
    environ: dict[str, str] | None = None,
    require_channel: str | None = None,
    status_path: Path | None = None,
) -> str:
    current_environ = os.environ if environ is None else environ
    if environ is None:
        load_notification_environment(current_environ)
    channel = _selected_channel(current_environ)
    signal_config = signal_cli_configuration(current_environ)
    attempt = _delivery_attempt_record(
        channel=channel,
        environ=current_environ,
        require_channel=require_channel,
        signal_config=signal_config,
    )
    LOGGER.info("Dispatching notification via %s.", channel)
    try:
        if require_channel == "signal_cli" and not signal_config["configuration_present"]:
            raise ValueError(_missing_signal_config_reason(signal_config["missing_env"]))
        if require_channel and channel != require_channel:
            raise RuntimeError(f"Selected notification channel is '{channel}', not '{require_channel}'.")
        if channel == "signal_cli":
            _send_signal_cli(message, current_environ)
        elif channel == "webhook":
            _send_webhook(message, status, current_environ)
        else:
            _send_console(message)
        attempt["success"] = True
        attempt["delivery_state"] = _success_delivery_state(attempt["selected_channel"])
        attempt["failure_reason"] = None
    except Exception as exc:
        attempt["success"] = False
        attempt["delivery_state"] = _failure_delivery_state(
            attempt["selected_channel"],
            exc,
            signal_config=signal_config,
        )
        attempt["failure_reason"] = _mask_sensitive_text(str(exc))
        _write_delivery_artifact(attempt, environ=current_environ, status_path=status_path)
        raise
    _write_delivery_artifact(attempt, environ=current_environ, status_path=status_path)
    return channel


def selected_notification_channel(environ: dict[str, str] | None = None) -> str:
    return _selected_channel(os.environ if environ is None else environ)


def signal_cli_configuration(environ: dict[str, str] | None = None) -> dict[str, Any]:
    current_environ = os.environ if environ is None else environ
    command_path = _env_value(current_environ, "SIGNAL_CLI_PATH")
    sender = _env_value(current_environ, "SIGNAL_SENDER")
    recipient = _env_value(current_environ, "SIGNAL_RECIPIENT")
    missing_env = [
        name
        for name, value in (
            ("SIGNAL_CLI_PATH", command_path),
            ("SIGNAL_SENDER", sender),
            ("SIGNAL_RECIPIENT", recipient),
        )
        if value is None
    ]
    resolved_command = _resolve_command_path(command_path)
    return {
        "configuration_present": not missing_env,
        "missing_env": missing_env,
        "command_path": resolved_command or command_path,
        "sender": _mask_phone_number(sender),
        "recipient": _mask_phone_number(recipient),
    }


def delivery_artifact_path(
    environ: dict[str, str] | None = None,
    *,
    status_path: Path | None = None,
) -> Path:
    current_environ = os.environ if environ is None else environ
    explicit = _env_value(current_environ, "CONTROLTOWER_NOTIFICATION_ARTIFACT_PATH")
    if explicit:
        return Path(explicit)

    runtime_root = _runtime_root_for_delivery(current_environ, status_path=status_path)
    return runtime_root / "notifications" / DEFAULT_DELIVERY_ARTIFACT_NAME


def load_notification_environment(
    environ: MutableMapping[str, str] | None = None,
    *,
    env_file: Path | None = None,
) -> Path | None:
    current_environ = os.environ if environ is None else environ
    candidate = _notification_env_path(env_file)
    if candidate is None or not candidate.exists():
        _load_windows_persistent_environment(current_environ)
        return None

    for line in candidate.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        name, value = stripped.split("=", 1)
        key = name.strip()
        if not key:
            continue
        current_environ.setdefault(key, value.strip().strip('"').strip("'"))
    _load_windows_persistent_environment(current_environ)
    return candidate


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="controltower.services.notifications")
    parser.add_argument(
        "--status-path",
        type=Path,
        default=_default_status_path(),
        help="Path to the latest release status artifact.",
    )
    args = parser.parse_args(argv)
    LOGGER.info("Notification attempt for release status artifact: %s", args.status_path)
    notify_release_status_file(args.status_path)
    return 0


def _selected_channel(environ: dict[str, str]) -> str:
    if _env_value(environ, "SIGNAL_CLI_PATH") and _env_value(environ, "SIGNAL_RECIPIENT"):
        return "signal_cli"
    if _env_value(environ, "NOTIFICATION_WEBHOOK_URL"):
        return "webhook"
    return "console"


def _send_signal_cli(message: str, environ: dict[str, str]) -> None:
    signal_cli_path = _env_value(environ, "SIGNAL_CLI_PATH")
    sender = _env_value(environ, "SIGNAL_SENDER")
    recipient = _env_value(environ, "SIGNAL_RECIPIENT")
    if not signal_cli_path or not recipient:
        raise ValueError("Signal delivery requires SIGNAL_CLI_PATH and SIGNAL_RECIPIENT.")
    if not sender:
        raise ValueError("Signal delivery requires SIGNAL_SENDER.")
    resolved_command = _resolve_command_path(signal_cli_path)
    if resolved_command is None:
        raise RuntimeError(f"signal-cli executable is not available: {signal_cli_path}")
    command, stdin_payload = _build_signal_send_command(
        resolved_command,
        sender=sender,
        recipient=recipient,
        message=message,
    )
    completed = subprocess.run(
        command,
        input=stdin_payload,
        capture_output=True,
        text=True,
        check=False,
        timeout=DEFAULT_SIGNAL_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "signal-cli exited non-zero.").strip()
        raise RuntimeError(detail)


def _send_webhook(message: str, status: dict[str, Any] | None, environ: dict[str, str]) -> None:
    webhook_url = _env_value(environ, "NOTIFICATION_WEBHOOK_URL")
    if not webhook_url:
        raise ValueError("Webhook delivery requires NOTIFICATION_WEBHOOK_URL.")
    payload = json.dumps({"message": message, "status": status or {}}).encode("utf-8")
    request = Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "controltower-release-notifier/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=DEFAULT_WEBHOOK_TIMEOUT_SECONDS):
            return
    except (HTTPError, URLError, OSError) as exc:
        raise RuntimeError(str(exc)) from exc


def _send_console(message: str) -> None:
    print(message)


def _release_passed(status: dict[str, Any]) -> bool:
    verdict = status.get("verdict") or {}
    if isinstance(verdict, dict):
        if verdict.get("ready_for_live_operations") is True:
            return True
        if _normalized_state(verdict.get("status")) == "pass":
            return True
    if _normalized_state(status.get("status")) == "pass":
        return True
    return False


def _stage_rows(status: dict[str, Any]) -> list[tuple[str, str]]:
    stages = status.get("stage_results")
    if isinstance(stages, dict) and stages:
        return [(name, _stage_status(stage)) for name, stage in stages.items()]

    gate_results = status.get("gate_results") or {}
    rows: list[tuple[str, str]] = []
    if "pytest" in gate_results:
        rows.append(("pytest", _stage_status(gate_results["pytest"])))
    rows.append(("readiness", "pass" if _release_passed(status) else "fail"))
    if "acceptance" in gate_results:
        rows.append(("acceptance", _stage_status(gate_results["acceptance"])))
    if "route_checks" in gate_results:
        rows.append(("deploy", _stage_status(gate_results["route_checks"])))
    if gate_results.get("export_checks", {}).get("status") not in {None, "pass"}:
        rows.append(("export", _stage_status(gate_results["export_checks"])))
    if gate_results.get("source_validation", {}).get("status") not in {None, "pass"}:
        rows.append(("source_validation", _stage_status(gate_results["source_validation"])))
    return rows


def _failed_stage(status: dict[str, Any]) -> str | None:
    stages = status.get("stage_results")
    gate_results = status.get("gate_results")
    failure = status.get("failure") or {}
    if not (isinstance(stages, dict) and stages) and not (isinstance(gate_results, dict) and gate_results):
        if isinstance(failure, dict) and failure.get("step"):
            return str(failure["step"])
    for name, stage_status in _stage_rows(status):
        if _normalized_state(stage_status) == "fail":
            return "post_deploy_smoke" if name == "deploy" else name
    if isinstance(failure, dict) and failure.get("step"):
        return str(failure["step"])
    verdict = status.get("verdict") or {}
    failing_checks = verdict.get("failing_checks") if isinstance(verdict, dict) else None
    if failing_checks:
        first = str(failing_checks[0])
        return "post_deploy_smoke" if first == "route_checks" else first
    return None


def _failure_reason(status: dict[str, Any]) -> str | None:
    if reason := status.get("failure_reason"):
        return str(reason)
    failure = status.get("failure") or {}
    if isinstance(failure, dict) and failure.get("reason"):
        return str(failure["reason"])
    error = status.get("error") or {}
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    return None


def _next_action(status: dict[str, Any], *, release_passed: bool) -> str | None:
    if action := status.get("next_recommended_action"):
        return str(action)
    failure = status.get("failure") or {}
    if not release_passed and isinstance(failure, dict) and failure.get("action"):
        return str(failure["action"])
    verdict = status.get("verdict") or {}
    if isinstance(verdict, dict) and verdict.get("operator_recommendation"):
        return str(verdict["operator_recommendation"])
    if release_passed:
        return "Approve next Codex lane"
    return None


def _awaiting_approval(status: dict[str, Any]) -> bool:
    return bool(status.get("awaiting_approval"))


def _commit_from_status(status: dict[str, Any]) -> str | None:
    product = status.get("product") or {}
    if isinstance(product, dict) and product.get("git_commit"):
        return str(product["git_commit"])[:7]
    if commit := status.get("intended_commit"):
        return str(commit)[:7]
    if commit := status.get("git_commit"):
        return str(commit)[:7]
    source_trace = status.get("source_trace") or {}
    if isinstance(source_trace, dict) and source_trace.get("local_head_commit"):
        return str(source_trace["local_head_commit"])[:7]
    git = status.get("git") or {}
    if isinstance(git, dict) and git.get("head_commit"):
        return str(git["head_commit"])[:7]
    release_trace = status.get("release_trace") or {}
    if isinstance(release_trace, dict) and release_trace.get("local_head_commit"):
        return str(release_trace["local_head_commit"])[:7]
    return None


def _branch_from_status(status: dict[str, Any]) -> str | None:
    for key in ("branch", "git_branch"):
        if value := status.get(key):
            return str(value)
    git = status.get("git") or {}
    if isinstance(git, dict) and git.get("branch"):
        return str(git["branch"])
    return None


def _live_url(status: dict[str, Any]) -> str | None:
    config = status.get("config") or {}
    if isinstance(config, dict) and config.get("public_base_url"):
        return str(config["public_base_url"])
    deployment = status.get("deployment_target") or {}
    if isinstance(deployment, dict) and deployment.get("public_base_url"):
        return str(deployment["public_base_url"])
    return None


def _stage_status(stage: Any) -> str:
    if isinstance(stage, dict):
        return str(stage.get("status") or "unknown")
    return str(stage or "unknown")


def _display_status(value: str) -> str:
    normalized = _normalized_state(value)
    if normalized == "pass":
        return "PASS"
    if normalized == "fail":
        return "FAIL"
    if normalized == "skip":
        return "SKIP"
    return str(value).upper()


def _normalized_state(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"pass", "passed", "ready", "success", "succeeded", "accepted", "ok"}:
        return "pass"
    if normalized in {"fail", "failed", "not_ready", "error"}:
        return "fail"
    if normalized in {"not_run", "skipped", "skip"}:
        return "skip"
    return normalized or "unknown"


def _env_value(environ: dict[str, str], name: str) -> str | None:
    value = environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _resolve_command_path(command_path: str | None) -> str | None:
    if not command_path:
        return None
    resolved = shutil.which(command_path)
    if resolved:
        return resolved
    candidate = Path(command_path).expanduser()
    if candidate.exists():
        return str(candidate)
    return None


def _build_signal_send_command(
    resolved_command: str,
    *,
    sender: str,
    recipient: str,
    message: str,
) -> tuple[list[str], str | None]:
    if _is_windows_batch_command(resolved_command):
        # Batch wrappers are parsed by cmd.exe, which truncates newline-bearing
        # `-m` arguments and drops the trailing recipient. Pipe the full message
        # over stdin instead so the recipient remains a separate argument.
        return [resolved_command, "-a", sender, "send", "--message-from-stdin", recipient], message
    return [resolved_command, "-u", sender, "send", "-m", message, recipient], None


def _is_windows_batch_command(command_path: str) -> bool:
    return Path(command_path).suffix.lower() in {".bat", ".cmd"}


def _missing_signal_config_reason(missing_env: list[str]) -> str:
    missing = ", ".join(missing_env) if missing_env else "unknown prerequisites"
    return f"Signal delivery is not configured. Missing: {missing}."


def _delivery_attempt_record(
    *,
    channel: str,
    environ: dict[str, str],
    require_channel: str | None,
    signal_config: dict[str, Any],
) -> dict[str, Any]:
    selected_channel = require_channel or channel
    configuration_present = False
    command_path = None
    sender = None
    recipient = None
    if selected_channel == "signal_cli":
        configuration_present = bool(signal_config["configuration_present"])
        command_path = signal_config["command_path"]
        sender = signal_config["sender"]
        recipient = signal_config["recipient"]
    elif selected_channel == "webhook":
        configuration_present = _env_value(environ, "NOTIFICATION_WEBHOOK_URL") is not None
    return {
        "attempted_at": utc_now_iso(),
        "selected_channel": selected_channel,
        "fallback_channel": channel,
        "required_channel": require_channel,
        "configuration_present": configuration_present,
        "command_path": command_path,
        "sender": sender,
        "recipient": recipient,
        "success": False,
        "delivery_state": "pending",
        "failure_reason": None,
    }


def _write_delivery_artifact(
    payload: dict[str, Any],
    *,
    environ: dict[str, str],
    status_path: Path | None,
) -> Path:
    artifact_path = delivery_artifact_path(environ, status_path=status_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return artifact_path


def _runtime_root_for_delivery(environ: dict[str, str], *, status_path: Path | None) -> Path:
    if status_path is not None:
        resolved_status_path = Path(status_path).resolve()
        if resolved_status_path.parent.name == "release":
            return resolved_status_path.parent.parent
    if release_status_path := _env_value(environ, "CONTROLTOWER_RELEASE_STATUS_PATH"):
        candidate = Path(release_status_path).resolve()
        if candidate.parent.name == "release":
            return candidate.parent.parent
    if runtime_root := _env_value(environ, "CONTROLTOWER_RUNTIME_ROOT"):
        return Path(runtime_root)
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / ".controltower_runtime"


def _mask_phone_number(value: str | None) -> str | None:
    if not value:
        return None
    trimmed = value.strip()
    digits = [char for char in trimmed if char.isdigit()]
    if len(digits) <= 4:
        return "***"
    suffix = "".join(digits[-4:])
    prefix = "+" if trimmed.startswith("+") else ""
    return f"{prefix}***{suffix}"


def _mask_sensitive_text(value: str) -> str:
    masked = value
    for match in re.findall(r"\+?\d[\d\s().-]{5,}\d", value):
        masked_number = _mask_phone_number(match)
        if masked_number:
            masked = masked.replace(match, masked_number)
    return masked


def _success_delivery_state(channel: str) -> str:
    if channel == "signal_cli":
        return "send_succeeded"
    if channel == "webhook":
        return "webhook_succeeded"
    return "console_only"


def _failure_delivery_state(
    channel: str,
    exc: Exception,
    *,
    signal_config: dict[str, Any],
) -> str:
    if channel != "signal_cli":
        if channel == "webhook":
            return "webhook_failed"
        return "send_failed"

    reason = str(exc)
    normalized = reason.strip().lower()
    if not signal_config["configuration_present"] or "signal delivery is not configured" in normalized:
        return "config_missing"
    if "requires signal_cli_path" in normalized or "requires signal_sender" in normalized:
        return "config_missing"
    if "signal-cli executable is not available" in normalized:
        return "executable_missing"
    if _looks_like_registration_failure(normalized):
        return "registration_missing"
    return "send_failed"


def _looks_like_registration_failure(message: str) -> bool:
    return any(
        token in message
        for token in (
            "not registered",
            "unregistered",
            "register the number",
            "register a new device",
            "linked device",
        )
    )


def _default_status_path() -> Path:
    if env_path := os.getenv("CONTROLTOWER_RELEASE_STATUS_PATH"):
        return Path(env_path)
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / ".controltower_runtime" / "release" / "latest_release_readiness.json"


def _notification_env_path(explicit_path: Path | None) -> Path | None:
    if explicit_path is not None:
        return Path(explicit_path)
    if env_path := os.getenv("CONTROLTOWER_ENV_FILE"):
        return Path(env_path)
    repo_root = Path(__file__).resolve().parents[3]
    candidate = repo_root / DEFAULT_ENV_FILE_NAME
    return candidate if candidate.exists() else None


def _load_windows_persistent_environment(environ: MutableMapping[str, str]) -> None:
    missing = [
        name
        for name in (
            "SIGNAL_CLI_PATH",
            "SIGNAL_SENDER",
            "SIGNAL_RECIPIENT",
            "NOTIFICATION_WEBHOOK_URL",
            "JAVA_HOME",
        )
        if _env_value(environ, name) is None
    ]
    if missing:
        for name, value in _windows_persistent_env_values(missing).items():
            environ.setdefault(name, value)
    _merge_windows_path_environment(environ, _windows_persistent_path_entries())


def _windows_persistent_env_values(names: list[str]) -> dict[str, str]:
    if os.name != "nt":
        return {}
    try:
        import winreg
    except ImportError:  # pragma: no cover - winreg is only available on Windows
        return {}

    values: dict[str, str] = {}
    registry_roots = (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    )
    for hive, subkey in registry_roots:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                for name in names:
                    if name in values:
                        continue
                    try:
                        value, _ = winreg.QueryValueEx(key, name)
                    except OSError:
                        continue
                    if isinstance(value, str):
                        stripped = value.strip()
                        if stripped:
                            values[name] = stripped
        except OSError:
            continue
    return values


def _windows_persistent_path_entries() -> list[str]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:  # pragma: no cover - winreg is only available on Windows
        return []

    entries: list[str] = []
    seen: set[str] = set()
    registry_roots = (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    )
    for hive, subkey in registry_roots:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                try:
                    value, _ = winreg.QueryValueEx(key, "Path")
                except OSError:
                    continue
        except OSError:
            continue
        if not isinstance(value, str):
            continue
        for entry in value.split(os.pathsep):
            stripped = entry.strip()
            normalized = stripped.lower()
            if not stripped or normalized in seen:
                continue
            seen.add(normalized)
            entries.append(stripped)
    return entries


def _merge_windows_path_environment(environ: MutableMapping[str, str], path_entries: list[str]) -> None:
    if not path_entries:
        return
    path_key = next((name for name in environ if name.lower() == "path"), "Path")
    current_value = str(environ.get(path_key, ""))
    current_entries = [entry.strip() for entry in current_value.split(os.pathsep) if entry.strip()]
    seen = {entry.lower() for entry in current_entries}
    additions = [entry for entry in path_entries if entry.lower() not in seen]
    if not additions:
        return
    combined = current_entries + additions if current_entries else additions
    environ[path_key] = os.pathsep.join(combined)


if __name__ == "__main__":
    raise SystemExit(main())

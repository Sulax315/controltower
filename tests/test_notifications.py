from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from controltower.services.notifications import (
    format_controltower_event_message,
    format_release_message,
    load_notification_environment,
    notify_controltower_event,
    send_release_notification,
)


@pytest.fixture
def sample_release_status() -> dict[str, object]:
    return {
        "product": {"git_commit": "875a092abcdef"},
        "branch": "main",
        "stage_results": {
            "pytest": {"status": "pass"},
            "readiness": {"status": "pass"},
            "acceptance": {"status": "pass"},
            "deploy": {"status": "pass"},
        },
        "config": {"public_base_url": "https://controltower.bratek.io"},
        "next_recommended_action": "Approve next Codex lane",
        "awaiting_approval": True,
        "verdict": {"ready_for_live_operations": True},
    }


@pytest.fixture(autouse=True)
def notification_artifact_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    artifact_path = tmp_path / "runtime" / "notifications" / "latest_delivery_attempt.json"
    monkeypatch.setenv("CONTROLTOWER_NOTIFICATION_ARTIFACT_PATH", str(artifact_path))
    return artifact_path


def test_format_release_message_success_is_operator_grade(sample_release_status: dict[str, object]):
    message = format_release_message(sample_release_status)

    assert message == (
        "[CONTROL TOWER]\n"
        "Event: RELEASE_SUCCESS\n"
        "Project: Control Tower\n"
        "Commit: 875a092\n"
        "Status: PASS\n"
        "Branch: main\n"
        "Live URL: https://controltower.bratek.io\n"
        "Next Action: Approve next Codex lane\n"
        "Approval State: awaiting_approval"
    )


def test_format_release_message_failure_highlights_stage_reason_and_action():
    status = {
        "product": {"git_commit": "875a092abcdef"},
        "stage_results": {
            "pytest": {"status": "pass"},
            "readiness": {"status": "fail"},
            "acceptance": {"status": "pass"},
            "deploy": {"status": "fail"},
        },
        "failure_reason": "HTTP 500 from /api/health",
        "next_recommended_action": "Check latest_release_log.txt",
        "verdict": {"ready_for_live_operations": False},
    }

    message = format_release_message(status)

    assert message == (
        "[CONTROL TOWER]\n"
        "Event: RELEASE_FAILURE\n"
        "Project: Control Tower\n"
        "Commit: 875a092\n"
        "Status: FAIL\n"
        "Error Summary: HTTP 500 from /api/health\n"
        "Failing Step: readiness\n"
        "Recommended Action: Check latest_release_log.txt"
    )


def test_format_release_message_handles_authoritative_release_failure_summary():
    status = {
        "status": "failed",
        "git": {"branch": "main"},
        "source_trace": {"local_head_commit": "f3ca503613f8e37943f5f6315eb689be5fd85a72"},
        "failure": {
            "step": "git_state",
            "reason": "Working tree is dirty.",
            "action": "Commit or stash local changes before running the authoritative release handoff.",
        },
        "deployment_target": {"public_base_url": "https://controltower.bratek.io"},
    }

    message = format_release_message(status)

    assert message == (
        "[CONTROL TOWER]\n"
        "Event: RELEASE_FAILURE\n"
        "Project: Control Tower\n"
        "Commit: f3ca503\n"
        "Status: FAIL\n"
        "Error Summary: Working tree is dirty.\n"
        "Failing Step: git_state\n"
        "Branch: main\n"
        "Recommended Action: Commit or stash local changes before running the authoritative release handoff."
    )


def test_send_release_notification_constructs_signal_command(
    monkeypatch: pytest.MonkeyPatch,
    sample_release_status: dict[str, object],
    notification_artifact_env: Path,
):
    captured: dict[str, object] = {}

    def _fake_run(command, input=None, capture_output=None, text=None, check=None, timeout=None):
        captured["command"] = command
        captured["input"] = input
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setenv("SIGNAL_CLI_PATH", "/usr/local/bin/signal-cli")
    monkeypatch.setenv("SIGNAL_SENDER", "+15551230000")
    monkeypatch.setenv("SIGNAL_RECIPIENT", "+15557654321")
    monkeypatch.delenv("NOTIFICATION_WEBHOOK_URL", raising=False)
    monkeypatch.setattr("controltower.services.notifications.subprocess.run", _fake_run)
    monkeypatch.setattr(
        "controltower.services.notifications._resolve_command_path",
        lambda command_path: command_path,
    )

    send_release_notification(sample_release_status)

    assert captured["command"] == [
        "/usr/local/bin/signal-cli",
        "-u",
        "+15551230000",
        "send",
        "-m",
        format_release_message(sample_release_status),
        "+15557654321",
    ]
    assert captured["input"] is None
    assert captured["timeout"] == 15
    artifact = json.loads(notification_artifact_env.read_text(encoding="utf-8"))
    assert artifact["selected_channel"] == "signal_cli"
    assert artifact["configuration_present"] is True
    assert artifact["command_path"] == "/usr/local/bin/signal-cli"
    assert artifact["sender"] == "+***0000"
    assert artifact["recipient"] == "+***4321"
    assert artifact["success"] is True
    assert artifact["delivery_state"] == "send_succeeded"
    assert artifact["failure_reason"] is None


def test_send_release_notification_loads_windows_persistent_signal_env(
    monkeypatch: pytest.MonkeyPatch,
    sample_release_status: dict[str, object],
    notification_artifact_env: Path,
):
    captured: dict[str, object] = {}

    def _fake_run(command, input=None, capture_output=None, text=None, check=None, timeout=None):
        captured["command"] = command
        captured["input"] = input
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.delenv("SIGNAL_CLI_PATH", raising=False)
    monkeypatch.delenv("SIGNAL_SENDER", raising=False)
    monkeypatch.delenv("SIGNAL_RECIPIENT", raising=False)
    monkeypatch.delenv("NOTIFICATION_WEBHOOK_URL", raising=False)
    monkeypatch.setattr("controltower.services.notifications.subprocess.run", _fake_run)
    monkeypatch.setattr(
        "controltower.services.notifications._resolve_command_path",
        lambda command_path: command_path,
    )
    monkeypatch.setattr(
        "controltower.services.notifications._windows_persistent_env_values",
        lambda names: {
            "SIGNAL_CLI_PATH": r"C:\Tools\signal-cli\signal-cli-0.14.1\bin\signal-cli.bat",
            "SIGNAL_SENDER": "+15551230000",
            "SIGNAL_RECIPIENT": "+15557654321",
        },
    )

    send_release_notification(sample_release_status)

    assert captured["command"] == [
        r"C:\Tools\signal-cli\signal-cli-0.14.1\bin\signal-cli.bat",
        "-a",
        "+15551230000",
        "send",
        "--message-from-stdin",
        "+15557654321",
    ]
    assert captured["input"] == format_release_message(sample_release_status)
    assert captured["timeout"] == 15
    artifact = json.loads(notification_artifact_env.read_text(encoding="utf-8"))
    assert artifact["selected_channel"] == "signal_cli"
    assert artifact["command_path"] == r"C:\Tools\signal-cli\signal-cli-0.14.1\bin\signal-cli.bat"
    assert artifact["success"] is True
    assert artifact["delivery_state"] == "send_succeeded"


def test_load_notification_environment_merges_windows_java_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    environ = {
        "Path": r"C:\Windows\system32;C:\Windows",
    }

    monkeypatch.setattr(
        "controltower.services.notifications._windows_persistent_env_values",
        lambda names: {
            "JAVA_HOME": r"C:\Users\JBratek\AppData\Local\Programs\Eclipse Adoptium\jdk-25.0.2.10-hotspot",
            "SIGNAL_CLI_PATH": r"C:\Tools\signal-cli\signal-cli-0.14.1\bin\signal-cli.bat",
        },
    )
    monkeypatch.setattr(
        "controltower.services.notifications._windows_persistent_path_entries",
        lambda: [r"C:\Users\JBratek\AppData\Local\Programs\Eclipse Adoptium\jdk-25.0.2.10-hotspot\bin"],
    )

    loaded_path = load_notification_environment(environ, env_file=tmp_path / "missing.env")

    assert loaded_path is None
    assert environ["JAVA_HOME"] == r"C:\Users\JBratek\AppData\Local\Programs\Eclipse Adoptium\jdk-25.0.2.10-hotspot"
    assert environ["SIGNAL_CLI_PATH"] == r"C:\Tools\signal-cli\signal-cli-0.14.1\bin\signal-cli.bat"
    assert (
        environ["Path"]
        == r"C:\Windows\system32;C:\Windows;C:\Users\JBratek\AppData\Local\Programs\Eclipse Adoptium\jdk-25.0.2.10-hotspot\bin"
    )


def test_send_release_notification_falls_back_to_console_without_config(
    monkeypatch: pytest.MonkeyPatch,
    sample_release_status: dict[str, object],
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.delenv("SIGNAL_CLI_PATH", raising=False)
    monkeypatch.delenv("SIGNAL_SENDER", raising=False)
    monkeypatch.delenv("SIGNAL_RECIPIENT", raising=False)
    monkeypatch.delenv("NOTIFICATION_WEBHOOK_URL", raising=False)
    monkeypatch.setattr("controltower.services.notifications._windows_persistent_env_values", lambda names: {})

    send_release_notification(sample_release_status)

    captured = capsys.readouterr()
    assert "Event: RELEASE_SUCCESS" in captured.out
    assert "Approve next Codex lane" in captured.out


def test_format_controltower_event_message_uses_strict_operator_shape():
    message = format_controltower_event_message(
        event="APPROVAL_REQUIRED",
        project="Control Tower",
        commit="875a092abcdef",
        status="action_required",
        instruction="Reply YES to approve or NO to reject",
    )

    assert message == (
        "[CONTROL TOWER]\n"
        "Event: APPROVAL_REQUIRED\n"
        "Project: Control Tower\n"
        "Commit: 875a092\n"
        "Status: ACTION_REQUIRED\n"
        "Instruction: Reply YES to approve or NO to reject"
    )


def test_notify_controltower_event_writes_delivery_artifact(
    monkeypatch: pytest.MonkeyPatch,
    notification_artifact_env: Path,
):
    captured: dict[str, object] = {}

    def _fake_run(command, input=None, capture_output=None, text=None, check=None, timeout=None):
        captured["command"] = command
        captured["input"] = input
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setenv("SIGNAL_CLI_PATH", "/usr/local/bin/signal-cli")
    monkeypatch.setenv("SIGNAL_SENDER", "+15551230000")
    monkeypatch.setenv("SIGNAL_RECIPIENT", "+15557654321")
    monkeypatch.setattr("controltower.services.notifications.subprocess.run", _fake_run)
    monkeypatch.setattr("controltower.services.notifications._resolve_command_path", lambda command_path: command_path)

    result = notify_controltower_event(
        "APPROVAL_REQUIRED",
        project="Control Tower",
        commit="875a092abcdef",
        status="ACTION_REQUIRED",
        instruction="Reply YES to approve or NO to reject",
    )

    assert captured["command"][0] == "/usr/local/bin/signal-cli"
    assert captured["command"][5].startswith("[CONTROL TOWER]\nEvent: APPROVAL_REQUIRED")
    artifact = json.loads(notification_artifact_env.read_text(encoding="utf-8"))
    assert artifact["event"] == "APPROVAL_REQUIRED"
    assert artifact["project"] == "Control Tower"
    assert artifact["notification_status"] == "ACTION_REQUIRED"
    assert artifact["success"] is True
    assert result["delivery"]["delivery_state"] == "send_succeeded"


def test_send_release_notification_does_not_raise_on_signal_failure(
    monkeypatch: pytest.MonkeyPatch,
    sample_release_status: dict[str, object],
    caplog: pytest.LogCaptureFixture,
    notification_artifact_env: Path,
):
    monkeypatch.setenv("SIGNAL_CLI_PATH", "/missing/signal-cli")
    monkeypatch.setenv("SIGNAL_SENDER", "+15551230000")
    monkeypatch.setenv("SIGNAL_RECIPIENT", "+15557654321")
    monkeypatch.delenv("NOTIFICATION_WEBHOOK_URL", raising=False)

    with caplog.at_level("WARNING"):
        send_release_notification(sample_release_status)

    assert "Release notification via signal_cli failed" in caplog.text
    artifact = json.loads(notification_artifact_env.read_text(encoding="utf-8"))
    assert artifact["selected_channel"] == "signal_cli"
    assert artifact["configuration_present"] is True
    assert artifact["success"] is False
    assert artifact["delivery_state"] == "executable_missing"
    assert "signal-cli executable is not available" in artifact["failure_reason"]


def test_send_release_notification_uses_webhook_when_signal_not_configured(
    monkeypatch: pytest.MonkeyPatch,
    sample_release_status: dict[str, object],
    notification_artifact_env: Path,
):
    captured: dict[str, object] = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse()

    monkeypatch.delenv("SIGNAL_CLI_PATH", raising=False)
    monkeypatch.delenv("SIGNAL_SENDER", raising=False)
    monkeypatch.delenv("SIGNAL_RECIPIENT", raising=False)
    monkeypatch.setenv("NOTIFICATION_WEBHOOK_URL", "https://example.test/hooks/release")
    monkeypatch.setattr("controltower.services.notifications._windows_persistent_env_values", lambda names: {})
    monkeypatch.setattr("controltower.services.notifications.urlopen", _fake_urlopen)

    send_release_notification(sample_release_status)

    assert captured["url"] == "https://example.test/hooks/release"
    assert captured["timeout"] == 10
    assert captured["payload"]["message"] == format_release_message(sample_release_status)
    assert captured["payload"]["status"]["next_recommended_action"] == "Approve next Codex lane"
    artifact = json.loads(notification_artifact_env.read_text(encoding="utf-8"))
    assert artifact["selected_channel"] == "webhook"
    assert artifact["configuration_present"] is True
    assert artifact["success"] is True
    assert artifact["delivery_state"] == "webhook_succeeded"


def test_missing_signal_config_writes_clear_failure_artifact(
    monkeypatch: pytest.MonkeyPatch,
    notification_artifact_env: Path,
):
    from controltower.services.notifications import dispatch_notification_message

    monkeypatch.delenv("SIGNAL_CLI_PATH", raising=False)
    monkeypatch.delenv("SIGNAL_SENDER", raising=False)
    monkeypatch.delenv("SIGNAL_RECIPIENT", raising=False)
    monkeypatch.delenv("NOTIFICATION_WEBHOOK_URL", raising=False)
    monkeypatch.setattr("controltower.services.notifications._windows_persistent_env_values", lambda names: {})

    with pytest.raises(ValueError, match="Signal delivery is not configured"):
        dispatch_notification_message("test", require_channel="signal_cli")

    artifact = json.loads(notification_artifact_env.read_text(encoding="utf-8"))
    assert artifact["selected_channel"] == "signal_cli"
    assert artifact["configuration_present"] is False
    assert artifact["command_path"] is None
    assert artifact["sender"] is None
    assert artifact["recipient"] is None
    assert artifact["success"] is False
    assert artifact["delivery_state"] == "config_missing"
    assert "SIGNAL_CLI_PATH, SIGNAL_SENDER, SIGNAL_RECIPIENT" in artifact["failure_reason"]


def test_signal_registration_failure_is_classified_and_masked(
    monkeypatch: pytest.MonkeyPatch,
    notification_artifact_env: Path,
):
    from controltower.services.notifications import dispatch_notification_message

    def _fake_run(command, input=None, capture_output=None, text=None, check=None, timeout=None):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="User +15551230000 is not registered.",
        )

    monkeypatch.setenv("SIGNAL_CLI_PATH", "/usr/local/bin/signal-cli")
    monkeypatch.setenv("SIGNAL_SENDER", "+15551230000")
    monkeypatch.setenv("SIGNAL_RECIPIENT", "+15557654321")
    monkeypatch.setattr("controltower.services.notifications.subprocess.run", _fake_run)
    monkeypatch.setattr(
        "controltower.services.notifications._resolve_command_path",
        lambda command_path: command_path,
    )

    with pytest.raises(RuntimeError, match="not registered"):
        dispatch_notification_message("test", require_channel="signal_cli")

    artifact = json.loads(notification_artifact_env.read_text(encoding="utf-8"))
    assert artifact["delivery_state"] == "registration_missing"
    assert artifact["failure_reason"] == "User +***0000 is not registered."


def test_send_release_notification_uses_stdin_for_windows_batch_signal_command(
    monkeypatch: pytest.MonkeyPatch,
    sample_release_status: dict[str, object],
    notification_artifact_env: Path,
):
    captured: dict[str, object] = {}

    def _fake_run(command, input=None, capture_output=None, text=None, check=None, timeout=None):
        captured["command"] = command
        captured["input"] = input
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    message = format_release_message(sample_release_status)
    signal_cli_bat = r"C:\Tools\signal-cli\signal-cli-0.14.1\bin\signal-cli.bat"
    monkeypatch.setenv("SIGNAL_CLI_PATH", signal_cli_bat)
    monkeypatch.setenv("SIGNAL_SENDER", "+15551230000")
    monkeypatch.setenv("SIGNAL_RECIPIENT", "+15557654321")
    monkeypatch.delenv("NOTIFICATION_WEBHOOK_URL", raising=False)
    monkeypatch.setattr("controltower.services.notifications.subprocess.run", _fake_run)
    monkeypatch.setattr(
        "controltower.services.notifications._resolve_command_path",
        lambda command_path: command_path,
    )

    send_release_notification(sample_release_status)

    assert captured["command"] == [
        signal_cli_bat,
        "-a",
        "+15551230000",
        "send",
        "--message-from-stdin",
        "+15557654321",
    ]
    assert captured["input"] == message
    assert captured["timeout"] == 15
    artifact = json.loads(notification_artifact_env.read_text(encoding="utf-8"))
    assert artifact["selected_channel"] == "signal_cli"
    assert artifact["command_path"] == signal_cli_bat
    assert artifact["success"] is True
    assert artifact["delivery_state"] == "send_succeeded"

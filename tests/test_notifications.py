from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from controltower.services.notifications import format_release_message, send_release_notification


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
        "Control Tower Release PASS\n"
        "Commit: 875a092\n"
        "Branch: main\n"
        "\n"
        "Stages:\n"
        "- pytest: PASS\n"
        "- readiness: PASS\n"
        "- acceptance: PASS\n"
        "- deploy: PASS\n"
        "\n"
        "Live:\n"
        "https://controltower.bratek.io\n"
        "\n"
        "Awaiting approval before next step\n"
        "\n"
        "Next:\n"
        "Approve next Codex lane"
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
        "Control Tower Release FAIL\n"
        "Commit: 875a092\n"
        "\n"
        "Failed Stage:\n"
        "readiness\n"
        "\n"
        "Reason:\n"
        "HTTP 500 from /api/health\n"
        "\n"
        "Action:\n"
        "Check latest_release_log.txt"
    )


def test_send_release_notification_constructs_signal_command(
    monkeypatch: pytest.MonkeyPatch,
    sample_release_status: dict[str, object],
    notification_artifact_env: Path,
):
    captured: dict[str, object] = {}

    def _fake_run(command, capture_output=None, text=None, check=None, timeout=None):
        captured["command"] = command
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
    assert captured["timeout"] == 15
    artifact = json.loads(notification_artifact_env.read_text(encoding="utf-8"))
    assert artifact["selected_channel"] == "signal_cli"
    assert artifact["configuration_present"] is True
    assert artifact["command_path"] == "/usr/local/bin/signal-cli"
    assert artifact["recipient"] == "+***4321"
    assert artifact["success"] is True
    assert artifact["failure_reason"] is None


def test_send_release_notification_falls_back_to_console_without_config(
    monkeypatch: pytest.MonkeyPatch,
    sample_release_status: dict[str, object],
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.delenv("SIGNAL_CLI_PATH", raising=False)
    monkeypatch.delenv("SIGNAL_SENDER", raising=False)
    monkeypatch.delenv("SIGNAL_RECIPIENT", raising=False)
    monkeypatch.delenv("NOTIFICATION_WEBHOOK_URL", raising=False)

    send_release_notification(sample_release_status)

    captured = capsys.readouterr()
    assert "Control Tower Release PASS" in captured.out
    assert "Approve next Codex lane" in captured.out


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


def test_missing_signal_config_writes_clear_failure_artifact(
    monkeypatch: pytest.MonkeyPatch,
    notification_artifact_env: Path,
):
    from controltower.services.notifications import dispatch_notification_message

    monkeypatch.delenv("SIGNAL_CLI_PATH", raising=False)
    monkeypatch.delenv("SIGNAL_SENDER", raising=False)
    monkeypatch.delenv("SIGNAL_RECIPIENT", raising=False)
    monkeypatch.delenv("NOTIFICATION_WEBHOOK_URL", raising=False)

    with pytest.raises(ValueError, match="Signal delivery is not configured"):
        dispatch_notification_message("test", require_channel="signal_cli")

    artifact = json.loads(notification_artifact_env.read_text(encoding="utf-8"))
    assert artifact["selected_channel"] == "signal_cli"
    assert artifact["configuration_present"] is False
    assert artifact["command_path"] is None
    assert artifact["recipient"] is None
    assert artifact["success"] is False
    assert "SIGNAL_CLI_PATH, SIGNAL_SENDER, SIGNAL_RECIPIENT" in artifact["failure_reason"]

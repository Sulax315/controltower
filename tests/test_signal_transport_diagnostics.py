from __future__ import annotations

import json
from pathlib import Path

import pytest

from controltower.services.signal_transport_diagnostics import inspect_signal_transport


@pytest.fixture
def artifact_path(tmp_path: Path) -> Path:
    return tmp_path / "runtime" / "notifications" / "latest_delivery_attempt.json"


def test_signal_transport_reports_missing_config(monkeypatch: pytest.MonkeyPatch, artifact_path: Path):
    monkeypatch.setenv("CONTROLTOWER_NOTIFICATION_ARTIFACT_PATH", str(artifact_path))
    monkeypatch.delenv("SIGNAL_CLI_PATH", raising=False)
    monkeypatch.delenv("SIGNAL_SENDER", raising=False)
    monkeypatch.delenv("SIGNAL_RECIPIENT", raising=False)

    summary = inspect_signal_transport(send_test=False)

    assert summary["status"] == "config_missing"
    assert summary["config"]["missing_env"] == ["SIGNAL_CLI_PATH", "SIGNAL_SENDER", "SIGNAL_RECIPIENT"]
    assert summary["executable"]["status"] == "fail"


def test_signal_transport_reports_missing_executable(monkeypatch: pytest.MonkeyPatch, artifact_path: Path):
    monkeypatch.setenv("CONTROLTOWER_NOTIFICATION_ARTIFACT_PATH", str(artifact_path))
    monkeypatch.setenv("SIGNAL_CLI_PATH", "/missing/signal-cli")
    monkeypatch.setenv("SIGNAL_SENDER", "+15551230000")
    monkeypatch.setenv("SIGNAL_RECIPIENT", "+15557654321")

    summary = inspect_signal_transport(send_test=False)

    assert summary["status"] == "executable_missing"
    assert summary["config"]["status"] == "pass"
    assert summary["registration"]["status"] == "blocked"


def test_signal_transport_reports_registration_missing(
    monkeypatch: pytest.MonkeyPatch,
    artifact_path: Path,
):
    def _fake_run(command, capture_output=None, text=None, check=None, timeout=None):
        return __import__("subprocess").CompletedProcess(command, 0, stdout=json.dumps(["+15550001111"]), stderr="")

    monkeypatch.setenv("CONTROLTOWER_NOTIFICATION_ARTIFACT_PATH", str(artifact_path))
    monkeypatch.setenv("SIGNAL_CLI_PATH", "/usr/local/bin/signal-cli")
    monkeypatch.setenv("SIGNAL_SENDER", "+15551230000")
    monkeypatch.setenv("SIGNAL_RECIPIENT", "+15557654321")
    monkeypatch.setattr("controltower.services.signal_transport_diagnostics.shutil.which", lambda path: path)
    monkeypatch.setattr("controltower.services.signal_transport_diagnostics.subprocess.run", _fake_run)

    summary = inspect_signal_transport(send_test=False)

    assert summary["status"] == "registration_missing"
    assert summary["registration"]["sender_registered"] is False
    assert summary["registration"]["registered_accounts"] == ["+***1111"]


def test_signal_transport_uses_delivery_artifact_for_outbound_state(
    monkeypatch: pytest.MonkeyPatch,
    artifact_path: Path,
):
    monkeypatch.setenv("CONTROLTOWER_NOTIFICATION_ARTIFACT_PATH", str(artifact_path))
    monkeypatch.setenv("SIGNAL_CLI_PATH", "/usr/local/bin/signal-cli")
    monkeypatch.setenv("SIGNAL_SENDER", "+15551230000")
    monkeypatch.setenv("SIGNAL_RECIPIENT", "+15557654321")
    monkeypatch.setattr("controltower.services.signal_transport_diagnostics.shutil.which", lambda path: path)
    monkeypatch.setattr(
        "controltower.services.signal_transport_diagnostics.inspect_signal_registration",
        lambda *args, **kwargs: {
            "status": "pass",
            "sender": "+***0000",
            "sender_registered": True,
            "registered_accounts": ["+***0000"],
            "command": "signal-cli -o json listAccounts",
            "error": None,
        },
    )

    def _fake_dispatch(*args, **kwargs):
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(
                {
                    "delivery_state": "send_succeeded",
                    "failure_reason": None,
                    "sender": "+***0000",
                    "recipient": "+***4321",
                }
            ),
            encoding="utf-8",
        )
        return "signal_cli"

    monkeypatch.setattr("controltower.services.signal_transport_diagnostics.dispatch_notification_message", _fake_dispatch)

    summary = inspect_signal_transport(send_test=True, host_marker="droplet-a")

    assert summary["status"] == "send_succeeded"
    assert summary["outbound_test"]["status"] == "pass"
    assert summary["outbound_test"]["delivery_state"] == "send_succeeded"
    assert summary["latest_delivery_artifact"]["sender"] == "+***0000"

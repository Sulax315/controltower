from __future__ import annotations

import json
import sys

from controltower.cli import main


def test_cli_execution_demo_flow(sample_config_path, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controltower",
            "--config",
            str(sample_config_path),
            "execution-simulate",
            "--profile",
            "medium",
            "--provider",
            "file",
        ],
    )
    assert main() == 0
    emitted = json.loads(capsys.readouterr().out)
    run_id = emitted["run_id"]
    assert emitted["execution_event"]["event_id"]
    assert emitted["execution_pack"]["pack_type"] == "release_readiness_pack"

    monkeypatch.setattr(
        sys,
        "argv",
        ["controltower", "--config", str(sample_config_path), "execution-queue-list"],
    )
    assert main() == 0
    queue = json.loads(capsys.readouterr().out)
    assert len(queue) == 1
    assert queue[0]["run_id"] == run_id

    monkeypatch.setattr(
        sys,
        "argv",
        ["controltower", "--config", str(sample_config_path), "execution-event-show", "--run-id", run_id],
    )
    assert main() == 0
    event_payload = json.loads(capsys.readouterr().out)
    assert event_payload["run_id"] == run_id
    assert event_payload["pack_type"] == "release_readiness_pack"

    monkeypatch.setattr(
        sys,
        "argv",
        ["controltower", "--config", str(sample_config_path), "execution-closeout-show", "--run-id", run_id],
    )
    assert main() == 0
    closeout_payload = json.loads(capsys.readouterr().out)
    assert closeout_payload["run_id"] == run_id
    assert closeout_payload["final_dispatch_status"] == "queued"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controltower",
            "--config",
            str(sample_config_path),
            "execution-result-ingest",
            "--run-id",
            run_id,
            "--status",
            "succeeded",
            "--summary",
            "CLI demo flow completed.",
            "--external-reference",
            "cli-demo-1",
        ],
    )
    assert main() == 0
    ingested = json.loads(capsys.readouterr().out)
    assert ingested["execution_result"]["status"] == "succeeded"
    assert ingested["execution_result"]["external_reference"] == "cli-demo-1"

    monkeypatch.setattr(
        sys,
        "argv",
        ["controltower", "--config", str(sample_config_path), "review-show", "--run-id", run_id],
    )
    assert main() == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["execution_pack"]["pack_type"] == "release_readiness_pack"
    assert shown["execution_result"]["status"] == "succeeded"


def test_cli_dead_letter_listing_and_retry(sample_config_path, monkeypatch, capsys):
    monkeypatch.setenv("CODEX_EXECUTION_WEBHOOK_URL", "https://example.test/hook")

    class _FakeResponse:
        status = 202

        def read(self):
            return b'{"accepted":true}'

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _boom(request, timeout=0):
        raise OSError("temporary webhook outage")

    monkeypatch.setattr("controltower.services.orchestration.urlopen", _boom)
    monkeypatch.setattr("controltower.services.orchestration.time.sleep", lambda _: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controltower",
            "--config",
            str(sample_config_path),
            "review-simulate",
            "--profile",
            "medium",
        ],
    )
    assert main() == 0
    simulated = json.loads(capsys.readouterr().out)
    run_id = simulated["run_id"]

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controltower",
            "--config",
            str(sample_config_path),
            "review-approve",
            "--run-id",
            run_id,
            "--provider",
            "webhook",
        ],
    )
    assert main() == 1
    failed = json.loads(capsys.readouterr().out)
    assert failed["status"] == "trigger_failed"

    monkeypatch.setattr(
        sys,
        "argv",
        ["controltower", "--config", str(sample_config_path), "execution-dead-letter-list"],
    )
    assert main() == 0
    dead_letters = json.loads(capsys.readouterr().out)
    assert len(dead_letters) == 1
    assert dead_letters[0]["run_id"] == run_id

    monkeypatch.setattr("controltower.services.orchestration.urlopen", lambda request, timeout=0: _FakeResponse())
    monkeypatch.setattr(
        sys,
        "argv",
        ["controltower", "--config", str(sample_config_path), "execution-dispatch-retry", "--run-id", run_id],
    )
    assert main() == 0
    retried = json.loads(capsys.readouterr().out)
    assert retried["status"] == "triggered"

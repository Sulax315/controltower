from __future__ import annotations

import json
import sys
from pathlib import Path

from controltower.cli import main
from controltower.services.approval_ingest import ingest_approval_inbox, sync_pending_release_approval
from controltower.services.signal_receive_adapter import adapt_signal_receive_text


def test_signal_receive_adapter_writes_file_drop_payload(tmp_path: Path):
    orchestration_root = tmp_path / "ops" / "orchestration"
    payload = json.dumps(
        {
            "envelope": {
                "sourceNumber": "+15557654321",
                "sourceDevice": 1,
                "timestamp": 1774960496000,
                "dataMessage": {"message": "APPROVE release_review_run_2026_03_31"},
            }
        }
    )

    result = adapt_signal_receive_text(payload, orchestration_root=orchestration_root)

    assert result["status"] == "ok"
    assert result["written_file_count"] == 1
    inbox_file = Path(result["written"][0]["inbox_file"])
    written_payload = json.loads(inbox_file.read_text(encoding="utf-8"))
    assert written_payload["source_channel"] == "signal"
    assert written_payload["provider"] == "signal_cli"
    assert written_payload["message"] == "APPROVE release_review_run_2026_03_31"
    assert written_payload["source_identity"] == "+***4321"


def test_signal_receive_adapter_reads_sync_sent_message_payload(tmp_path: Path):
    orchestration_root = tmp_path / "ops" / "orchestration"
    payload = json.dumps(
        {
            "envelope": {
                "sourceNumber": "+15557654321",
                "sourceDevice": 3,
                "timestamp": 1774960496000,
                "syncMessage": {
                    "sentMessage": {
                        "timestamp": 1774960496123,
                        "message": "APPROVE release_review_run_2026_03_31",
                    }
                },
            }
        }
    )

    result = adapt_signal_receive_text(payload, orchestration_root=orchestration_root)

    assert result["status"] == "ok"
    assert result["written_file_count"] == 1
    inbox_file = Path(result["written"][0]["inbox_file"])
    written_payload = json.loads(inbox_file.read_text(encoding="utf-8"))
    assert written_payload["message"] == "APPROVE release_review_run_2026_03_31"
    assert written_payload["timestamp"] == "2026-03-31T12:34:56Z"
    assert written_payload["message_id"] == "1774960496123"


def test_signal_receive_adapter_preserves_file_drop_inbox_flow(tmp_path: Path, monkeypatch):
    orchestration_root = tmp_path / "ops" / "orchestration"
    status_path = _write_release_status(tmp_path)
    sync_pending_release_approval(status_path, orchestration_root=orchestration_root)
    payload = json.dumps(
        {
            "envelope": {
                "sourceNumber": "+15557654321",
                "timestamp": 1774960496000,
                "dataMessage": {"message": "APPROVE release_review_run_2026_03_31"},
            }
        }
    )

    adapt_signal_receive_text(payload, orchestration_root=orchestration_root)
    monkeypatch.setattr("controltower.services.approval_ingest.send_operator_notification", lambda *args, **kwargs: None)
    result = ingest_approval_inbox(orchestration_root=orchestration_root)

    pending = json.loads((orchestration_root / "pending_approval.json").read_text(encoding="utf-8"))
    assert result["processed_file_count"] == 1
    assert result["events"][0]["source_channel"] == "signal"
    assert result["events"][0]["normalized_command"] == "APPROVE"
    assert pending["status"] == "approved"


def test_cli_signal_receive_adapter_reads_payload_file(tmp_path: Path, monkeypatch, capsys):
    orchestration_root = tmp_path / "ops" / "orchestration"
    payload_file = tmp_path / "signal_receive.jsonl"
    payload_file.write_text(
        json.dumps(
            {
                "envelope": {
                    "sourceNumber": "+15557654321",
                    "timestamp": 1774960496000,
                    "dataMessage": {"message": "HOLD"},
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controltower",
            "approval-adapt-signal-receive",
            "--payload-file",
            str(payload_file),
            "--orchestration-root",
            str(orchestration_root),
        ],
    )

    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["written_file_count"] == 1
    assert Path(result["written"][0]["inbox_file"]).exists()


def test_cli_signal_receive_adapter_reads_utf8_bom_payload_file(tmp_path: Path, monkeypatch, capsys):
    orchestration_root = tmp_path / "ops" / "orchestration"
    payload_file = tmp_path / "signal_receive_bom.jsonl"
    payload_file.write_text(
        json.dumps(
            {
                "envelope": {
                    "sourceNumber": "+15557654321",
                    "timestamp": 1774960496000,
                    "syncMessage": {
                        "sentMessage": {
                            "timestamp": 1774960496123,
                            "message": "APPROVE release_review_run_2026_03_31",
                        }
                    },
                }
            }
        ),
        encoding="utf-8-sig",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controltower",
            "approval-adapt-signal-receive",
            "--payload-file",
            str(payload_file),
            "--orchestration-root",
            str(orchestration_root),
        ],
    )

    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["written_file_count"] == 1
    assert Path(result["written"][0]["inbox_file"]).exists()


def _write_release_status(tmp_path: Path) -> Path:
    release_root = tmp_path / "release"
    release_root.mkdir(parents=True, exist_ok=True)
    latest_json_path = release_root / "latest_release_readiness.json"
    diagnostics_path = tmp_path / "diagnostics" / "latest_diagnostics.json"
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_path.write_text("{}", encoding="utf-8")
    latest_run_path = tmp_path / "latest_run.json"
    latest_run_path.write_text("{}", encoding="utf-8")
    manifest_path = tmp_path / "runs" / "run_2026_03_31" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("{}", encoding="utf-8")

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

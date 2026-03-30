from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
import yaml

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.services import operations
from controltower.services.operations import (
    EXIT_CONFIG_ERROR,
    EXIT_REGISTRY_ERROR,
    EXIT_TEMPLATE_ERROR,
    run_daily,
    run_preflight,
    run_weekly,
)
from controltower.services.runtime_state import prune_runtime_history, read_json


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_diagnostics_payload_shape_is_stable(sample_config_path: Path):
    summary = run_daily(config_path=sample_config_path)
    assert summary["exit_code"] == 0

    client = TestClient(create_app(str(sample_config_path)))
    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    data = response.json()
    assert data["schema_version"] == "2026-03-27"
    assert data["product"]["build_metadata"]["git_commit"] in {"unavailable", data["product"]["build_metadata"]["git_commit"]}
    assert data["config"]["status"] == "loaded"
    assert data["templates"]["markdown"]["status"] == "ok"
    assert data["templates"]["ui"]["status"] == "ok"
    assert data["registry"]["status"] == "loaded"
    assert data["latest_run"]["success"] is True
    assert "artifact_index_json" in data["artifacts"]["presence_checks"]
    assert "latest_run_status" in data["operations"]


def test_daily_run_writes_artifact_index_and_latest_pointers(sample_config_path: Path):
    summary = run_daily(config_path=sample_config_path, retention_dry_run=True)
    config = load_config(sample_config_path)
    state_root = Path(config.runtime.state_root)

    assert summary["exit_code"] == 0
    assert Path(summary["artifacts"]["summary_json"]).exists()
    assert (state_root / "operations" / "latest_daily.json").exists()
    assert (state_root / "diagnostics" / "latest_diagnostics.json").exists()
    assert (state_root / "artifact_index.json").exists()

    latest_run = read_json(state_root / "latest_run.json")
    artifact_index = read_json(state_root / "artifact_index.json")
    latest_daily = read_json(state_root / "operations" / "latest_daily.json")

    assert artifact_index["latest"]["export_run"]["run_id"] == latest_run["run_id"]
    assert artifact_index["recent_operations"][0]["operation_type"] == "daily"
    assert latest_daily["operation_id"] == summary["operation_id"]
    assert summary["retention"]["dry_run"] is True


def test_retention_prunes_old_history_but_keeps_latest_success_and_pointers(tmp_path: Path):
    state_root = tmp_path / "state"
    (state_root / "runs").mkdir(parents=True)
    (state_root / "history").mkdir(parents=True)
    (state_root / "release").mkdir(parents=True)
    (state_root / "operations" / "history").mkdir(parents=True)
    (state_root / "diagnostics").mkdir(parents=True)
    (state_root / "logs").mkdir(parents=True)

    run_entries = [
        ("2026-03-27T10-00-00Z", "2026-03-27T10:00:00Z", "success"),
        ("2026-03-27T11-00-00Z", "2026-03-27T11:00:00Z", "failed"),
        ("2026-03-27T12-00-00Z", "2026-03-27T12:00:00Z", "failed"),
    ]
    for run_id, generated_at, status in run_entries:
        payload = {"run_id": run_id, "generated_at": generated_at, "status": status, "notes": []}
        run_root = state_root / "runs" / run_id
        run_root.mkdir(parents=True)
        (run_root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
        (state_root / "history" / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    (state_root / "latest_run.json").write_text(
        json.dumps({"run_id": "2026-03-27T12-00-00Z", "generated_at": "2026-03-27T12:00:00Z", "status": "failed", "notes": []}),
        encoding="utf-8",
    )

    release_entries = [
        ("2026-03-27T10-00-00Z", "2026-03-27T10:00:00Z", True),
        ("2026-03-27T11-00-00Z", "2026-03-27T11:00:00Z", False),
    ]
    for stamp, generated_at, ready in release_entries:
        payload = {"generated_at": generated_at, "verdict": {"status": "ready" if ready else "not_ready", "ready_for_live_operations": ready}}
        (state_root / "release" / f"release_readiness_{stamp}.json").write_text(json.dumps(payload), encoding="utf-8")
        (state_root / "release" / f"release_readiness_{stamp}.md").write_text("# release\n", encoding="utf-8")
    (state_root / "release" / "latest_release_readiness.json").write_text(
        json.dumps({"generated_at": "2026-03-27T11:00:00Z", "verdict": {"status": "not_ready", "ready_for_live_operations": False}}),
        encoding="utf-8",
    )
    (state_root / "release" / "latest_release_readiness.md").write_text("# latest\n", encoding="utf-8")

    operation_entries = [
        ("daily_1", "2026-03-27T10:00:00Z", "success"),
        ("daily_2", "2026-03-27T12:00:00Z", "failed"),
    ]
    for operation_id, completed_at, status in operation_entries:
        payload = {"operation_id": operation_id, "operation_type": "daily", "status": status, "completed_at": completed_at}
        (state_root / "operations" / "history" / f"{operation_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    (state_root / "operations" / "latest_daily.json").write_text(
        json.dumps({"operation_id": "daily_2", "operation_type": "daily", "status": "failed", "completed_at": "2026-03-27T12:00:00Z"}),
        encoding="utf-8",
    )
    (state_root / "operations" / "latest_successful_daily.json").write_text(
        json.dumps({"operation_id": "daily_1", "operation_type": "daily", "status": "success", "completed_at": "2026-03-27T10:00:00Z"}),
        encoding="utf-8",
    )

    for stamp in ("2026-03-27T10-00-00Z", "2026-03-27T11-00-00Z"):
        (state_root / "diagnostics" / f"diagnostics_{stamp}.json").write_text(json.dumps({"captured_at": stamp}), encoding="utf-8")
    (state_root / "diagnostics" / "latest_diagnostics.json").write_text(json.dumps({"captured_at": "2026-03-27T11:00:00Z"}), encoding="utf-8")

    old_log = state_root / "logs" / "old.stdout.log"
    new_log = state_root / "logs" / "new.stdout.log"
    old_log.write_text("old", encoding="utf-8")
    new_log.write_text("new", encoding="utf-8")

    retention = SimpleNamespace(
        run_history_limit=1,
        release_history_limit=1,
        operations_history_limit=1,
        diagnostics_history_limit=1,
        log_file_limit=1,
    )

    dry_run = prune_runtime_history(state_root, retention, dry_run=True)
    assert dry_run["dry_run"] is True
    assert (state_root / "history" / "2026-03-27T10-00-00Z.json").exists()

    result = prune_runtime_history(state_root, retention, dry_run=False)
    assert result["dry_run"] is False
    assert (state_root / "history" / "2026-03-27T12-00-00Z.json").exists()
    assert (state_root / "history" / "2026-03-27T10-00-00Z.json").exists()
    assert not (state_root / "history" / "2026-03-27T11-00-00Z.json").exists()
    assert (state_root / "release" / "latest_release_readiness.json").exists()
    assert (state_root / "operations" / "latest_daily.json").exists()
    assert (state_root / "diagnostics" / "latest_diagnostics.json").exists()


def test_preflight_script_honors_retention_dry_run(sample_config_path: Path):
    completed = subprocess.run(
        [sys.executable, "scripts/preflight_controltower.py", "--config", str(sample_config_path), "--retention-dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    config = load_config(sample_config_path)
    latest_preflight = read_json(Path(config.runtime.state_root) / "operations" / "latest_preflight.json")
    assert latest_preflight["retention"]["dry_run"] is True


def test_smoke_script_refresh_export_argument_builds_fresh_export(sample_config_path: Path):
    completed = subprocess.run(
        [sys.executable, "scripts/smoke_controltower.py", "--config", str(sample_config_path), "--refresh-export"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    config = load_config(sample_config_path)
    latest_smoke = read_json(Path(config.runtime.state_root) / "operations" / "latest_smoke.json")
    assert latest_smoke["checks"]["route_checks"]["status"] == "pass"
    assert latest_smoke["checks"]["export_checks"]["status"] == "pass"


def test_missing_config_and_registry_and_template_failures_are_actionable(
    tmp_path: Path,
    sample_config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sample_schedulelab_root: Path,
    sample_profitintel_db: Path,
):
    monkeypatch.setattr(operations, "_default_state_root", lambda: tmp_path / "default_state")

    missing_config_summary = run_preflight(config_path=tmp_path / "missing.yaml")
    assert missing_config_summary["exit_code"] == EXIT_CONFIG_ERROR
    assert missing_config_summary["error"]["type"] == "config_error"

    missing_registry_config = tmp_path / "missing_registry.yaml"
    missing_registry_config.write_text(
        yaml.safe_dump(
            {
                "sources": {
                    "schedulelab": {"published_root": str(sample_schedulelab_root)},
                    "profitintel": {"database_path": str(sample_profitintel_db), "validation_search_roots": []},
                },
                "identity": {"registry_path": str(tmp_path / "nope.yaml")},
                "obsidian": {"vault_root": str(tmp_path / "vault")},
                "runtime": {"state_root": str(tmp_path / "state")},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    missing_registry_summary = run_preflight(config_path=missing_registry_config)
    assert missing_registry_summary["exit_code"] == EXIT_REGISTRY_ERROR
    assert "identity registry" in missing_registry_summary["error"]["message"].lower()

    monkeypatch.setattr(operations, "validate_markdown_templates", lambda: (_ for _ in ()).throw(FileNotFoundError("Control Tower markdown templates are missing: x")))
    template_failure_summary = run_preflight(config_path=sample_config_path)
    assert template_failure_summary["exit_code"] == EXIT_TEMPLATE_ERROR
    assert template_failure_summary["error"]["type"] == "template_error"


def test_weekly_runner_summary_records_release_artifacts(sample_config_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = load_config(sample_config_path)
    release_json = Path(config.runtime.state_root) / "release" / "latest_release_readiness.json"
    release_md = Path(config.runtime.state_root) / "release" / "latest_release_readiness.md"
    release_json.parent.mkdir(parents=True, exist_ok=True)
    release_json.write_text("{}", encoding="utf-8")
    release_md.write_text("# ready\n", encoding="utf-8")

    monkeypatch.setattr(
        operations,
        "build_release_readiness",
        lambda *args, **kwargs: {
            "verdict": {
                "status": "ready",
                "ready_for_live_operations": True,
                "summary": "ready",
                "remaining_risks": [],
                "failing_checks": [],
                "operator_recommendation": "Proceed",
            },
            "artifact_paths": {"json": str(release_json), "markdown": str(release_md)},
            "gate_results": {},
        },
    )

    summary = run_weekly(config_path=sample_config_path, retention_dry_run=True)

    assert summary["exit_code"] == 0
    assert summary["artifacts"]["release_json"] == str(release_json)
    assert summary["artifacts"]["release_markdown"] == str(release_md)

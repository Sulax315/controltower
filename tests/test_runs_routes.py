"""Runs execution helpers and route tests aligned with single-surface publish (Phase 12+)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.runs.execution import execute_run
from controltower.runs.registry import create_run, list_runs, update_run_status
from controltower.schedule_intake.asta_csv import ASTA_EXPORT_HEADERS
from controltower.schedule_intake.export_artifacts import FILENAME_BUNDLE


def _write_schedule_csv(tmp_path: Path) -> Path:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(ASTA_EXPORT_HEADERS))
    writer.writeheader()
    writer.writerow({h: "" for h in ASTA_EXPORT_HEADERS} | {"Task ID": "100", "Task name": "Start", "Successors": "200"})
    writer.writerow({h: "" for h in ASTA_EXPORT_HEADERS} | {"Task ID": "200", "Task name": "Finish", "Predecessors": "100"})
    path = tmp_path / "schedule.csv"
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


def test_post_runs_blocked(sample_config_path) -> None:
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    res = client.post("/runs", data={})
    assert res.status_code == 404


def test_run_detail_route_blocked(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    client = TestClient(create_app(str(sample_config_path)))
    assert client.get(f"/runs/{run_id}").status_code == 404


def test_invalid_run_id_operator_returns_404(sample_config_path) -> None:
    client = TestClient(create_app(str(sample_config_path)))
    assert client.get("/publish/operator/does-not-exist").status_code == 404


def test_operator_route_resolves_bundle_from_run_id(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    client = TestClient(create_app(str(sample_config_path)))
    res = client.get(f"/publish/operator/{run_id}")
    assert res.status_code == 200
    assert 'id="publish-operator-header-strip"' in res.text
    assert 'id="publish-operator-error"' not in res.text


def test_operator_route_print_mode_resolves_bundle_from_run_id(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    client = TestClient(create_app(str(sample_config_path)))
    res = client.get(f"/publish/operator/{run_id}", params={"print": 1})
    assert res.status_code == 200
    assert 'id="publish-operator-header-strip"' in res.text
    assert 'data-auto-print="true"' in res.text
    assert 'id="publish-operator-error"' not in res.text


def test_operator_route_missing_bundle_is_clean_failure(sample_config_path) -> None:
    config = load_config(sample_config_path)
    run_id = "run_20260407_000001_badbundle"
    run_root = config.runtime.state_root / "runs" / run_id
    create_run(
        config.runtime.state_root,
        run_id=run_id,
        input_filename="schedule.csv",
        input_path=run_root / "input" / "schedule.csv",
        artifact_dir=run_root / "artifacts",
        bundle_path=run_root / "artifacts" / FILENAME_BUNDLE,
        manifest_path=run_root / "artifacts" / "manifest.json",
        status="failed",
    )
    client = TestClient(create_app(str(sample_config_path)))
    assert client.get(f"/publish/operator/{run_id}").status_code == 409


def test_operator_route_missing_bundle_path_field_is_clean_failure(sample_config_path) -> None:
    config = load_config(sample_config_path)
    run_id = "run_20260407_000002_nopath"
    run_root = config.runtime.state_root / "runs" / run_id
    create_run(
        config.runtime.state_root,
        run_id=run_id,
        input_filename="schedule.csv",
        input_path=run_root / "input" / "schedule.csv",
        artifact_dir=run_root / "artifacts",
        bundle_path=run_root / "artifacts" / FILENAME_BUNDLE,
        manifest_path=run_root / "artifacts" / "manifest.json",
        status="failed",
    )
    run_meta = run_root / "run.json"
    payload = json.loads(run_meta.read_text(encoding="utf-8"))
    payload["bundle_path"] = "   "
    run_meta.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    client = TestClient(create_app(str(sample_config_path)))
    assert client.get(f"/publish/operator/{run_id}").status_code == 409


def test_failed_run_not_publishable_for_operator(sample_config_path) -> None:
    config = load_config(sample_config_path)
    run_id = "run_20260407_000000_deadbeef"
    run_root = config.runtime.state_root / "runs" / run_id
    create_run(
        config.runtime.state_root,
        run_id=run_id,
        input_filename="schedule.csv",
        input_path=run_root / "input" / "schedule.csv",
        artifact_dir=run_root / "artifacts",
        bundle_path=run_root / "artifacts" / FILENAME_BUNDLE,
        manifest_path=run_root / "artifacts" / "manifest.json",
        status="running",
    )
    update_run_status(config.runtime.state_root, run_id, status="failed", error_message="forced failure for route test")
    client = TestClient(create_app(str(sample_config_path)))
    res = client.get(f"/publish/operator/{run_id}")
    assert res.status_code == 409
    assert "failed" in res.json()["detail"].lower() or "not publishable" in res.json()["detail"].lower()

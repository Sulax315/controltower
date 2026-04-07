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


def _write_schedule_csv(tmp_path: Path) -> Path:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(ASTA_EXPORT_HEADERS))
    writer.writeheader()
    writer.writerow({h: "" for h in ASTA_EXPORT_HEADERS} | {"Task ID": "100", "Task name": "Start", "Successors": "200"})
    writer.writerow({h: "" for h in ASTA_EXPORT_HEADERS} | {"Task ID": "200", "Task name": "Finish", "Predecessors": "100"})
    path = tmp_path / "schedule.csv"
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


def test_homepage_loads_and_shows_upload_form(sample_config_path) -> None:
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    assert 'id="runs-home-upload"' in res.text
    assert 'name="csv_file"' in res.text


def test_homepage_shows_recent_runs(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    csv_path = _write_schedule_csv(tmp_path)
    run_id = execute_run(csv_path, state_root=config.runtime.state_root)
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    assert 'id="runs-home-recent"' in res.text
    assert run_id in res.text
    assert list_runs(config.runtime.state_root)


def test_upload_executes_and_redirects_to_run_detail(sample_config_path, tmp_path: Path) -> None:
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    csv_path = _write_schedule_csv(tmp_path)
    with csv_path.open("rb") as fp:
        res = client.post("/runs", files={"csv_file": ("schedule.csv", fp.read(), "text/csv")}, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"].startswith("/runs/run_")


def test_invalid_upload_rejected_cleanly_for_browser(sample_config_path) -> None:
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    res = client.post("/runs", files={"csv_file": ("schedule.txt", b"x", "text/plain")})
    assert res.status_code == 400
    assert 'id="runs-home-upload-error"' in res.text
    assert "Only .csv uploads are supported." in res.text


def test_empty_upload_rejected_cleanly_for_json(sample_config_path) -> None:
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    res = client.post(
        "/runs",
        files={"csv_file": ("schedule.csv", b"", "text/csv")},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "csv_file upload cannot be empty."


def test_missing_upload_field_rejected_cleanly_for_json(sample_config_path) -> None:
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    res = client.post("/runs", headers={"Accept": "application/json"})
    assert res.status_code == 400
    assert res.json()["detail"] == "csv_file upload is required."


def test_run_detail_loads_for_valid_run(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    res = client.get(f"/runs/{run_id}")
    assert res.status_code == 200
    assert 'id="run-detail-summary"' in res.text
    assert run_id in res.text
    assert f"/publish/operator/{run_id}" in res.text


def test_invalid_run_id_returns_404(sample_config_path) -> None:
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    assert client.get("/runs/does-not-exist").status_code == 404
    assert client.get("/publish/operator/does-not-exist").status_code == 404


def test_operator_route_resolves_bundle_from_run_id(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    res = client.get(f"/publish/operator/{run_id}")
    assert res.status_code == 200
    assert 'id="publish-operator-header-strip"' in res.text
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
        bundle_path=run_root / "artifacts" / "intelligence_bundle.json",
        manifest_path=run_root / "artifacts" / "manifest.json",
        status="failed",
    )
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    res = client.get(f"/publish/operator/{run_id}")
    assert res.status_code == 409


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
        bundle_path=run_root / "artifacts" / "intelligence_bundle.json",
        manifest_path=run_root / "artifacts" / "manifest.json",
        status="failed",
    )
    run_meta = run_root / "run.json"
    payload = json.loads(run_meta.read_text(encoding="utf-8"))
    payload["bundle_path"] = "   "
    run_meta.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    res = client.get(f"/publish/operator/{run_id}")
    assert res.status_code == 409


def test_failed_run_detail_shows_error_state(sample_config_path) -> None:
    config = load_config(sample_config_path)
    run_id = "run_20260407_000000_deadbeef"
    run_root = config.runtime.state_root / "runs" / run_id
    create_run(
        config.runtime.state_root,
        run_id=run_id,
        input_filename="schedule.csv",
        input_path=run_root / "input" / "schedule.csv",
        artifact_dir=run_root / "artifacts",
        bundle_path=run_root / "artifacts" / "intelligence_bundle.json",
        manifest_path=run_root / "artifacts" / "manifest.json",
        status="running",
    )
    update_run_status(config.runtime.state_root, run_id, status="failed", error_message="forced failure for route test")
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    res = client.get(f"/runs/{run_id}")
    assert res.status_code == 200
    assert 'id="run-detail-error"' in res.text
    assert "forced failure for route test" in res.text

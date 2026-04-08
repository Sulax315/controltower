from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.runs.execution import execute_run
from controltower.runs.registry import REGISTRY_FILENAME, create_run, get_run, list_runs, update_run_status
from controltower.schedule_intake import export_directory_file_map
from controltower.schedule_intake.asta_csv import ASTA_EXPORT_HEADERS
from controltower.schedule_intake.verification import ExportValidationResult, validate_export_artifact_set


def _write_schedule_csv(tmp_path: Path) -> Path:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(ASTA_EXPORT_HEADERS), lineterminator="\n")
    writer.writeheader()
    rows = [
        {"Task ID": "100", "Task name": "Start", "Successors": "200", "Critical": "TRUE"},
        {"Task ID": "200", "Task name": "Finish", "Predecessors": "100", "Critical": "TRUE"},
    ]
    for row in rows:
        writer.writerow({h: row.get(h, "") for h in ASTA_EXPORT_HEADERS})
    path = tmp_path / "schedule.csv"
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


def test_execute_run_creates_registry_and_run_structure(sample_config_path, tmp_path: Path) -> None:
    from controltower.config import load_config

    config = load_config(sample_config_path)
    csv_path = _write_schedule_csv(tmp_path)
    run_id = execute_run(csv_path, state_root=config.runtime.state_root)

    record = get_run(config.runtime.state_root, run_id)
    assert record is not None
    assert record["status"] == "completed"
    run_root = config.runtime.state_root / "runs" / run_id
    assert (run_root / "input" / "schedule.csv").exists()
    assert (run_root / "artifacts" / "intelligence_bundle.json").exists()
    assert (run_root / "artifacts" / "command_brief.json").exists()
    assert (run_root / "artifacts" / "engine_snapshot.json").exists()
    assert (run_root / "artifacts" / "exploration.json").exists()
    assert (run_root / "artifacts" / "manifest.json").exists()
    assert (run_root / "run.json").exists()
    assert Path(record["input_path"]) == run_root / "input" / "schedule.csv"
    assert Path(record["artifact_dir"]) == run_root / "artifacts"

    validation = validate_export_artifact_set(run_root / "artifacts")
    assert validation.ok is True
    assert validation.errors == ()

    listed = list_runs(config.runtime.state_root)
    assert any(item["run_id"] == run_id for item in listed)


def test_execute_run_failure_marks_run_failed(sample_config_path, tmp_path: Path, monkeypatch) -> None:
    from controltower.config import load_config

    config = load_config(sample_config_path)
    csv_path = _write_schedule_csv(tmp_path)

    monkeypatch.setattr(
        "controltower.runs.execution.validate_export_artifact_set",
        lambda _path: ExportValidationResult(ok=False, errors=("forced validation failure",)),
    )
    run_id = execute_run(csv_path, state_root=config.runtime.state_root)
    record = get_run(config.runtime.state_root, run_id)
    assert record is not None
    assert record["status"] == "failed"
    assert "forced validation failure" in (record["error_message"] or "")


def test_execute_run_failure_for_empty_activity_csv(sample_config_path, tmp_path: Path) -> None:
    from controltower.config import load_config

    config = load_config(sample_config_path)
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text(",".join(ASTA_EXPORT_HEADERS) + "\n", encoding="utf-8")
    run_id = execute_run(empty_csv, state_root=config.runtime.state_root)
    record = get_run(config.runtime.state_root, run_id)
    assert record is not None
    assert record["status"] == "failed"
    assert "no activities with usable task id" in (record["error_message"] or "").lower()


def test_post_runs_route_executes_and_returns_run_status(sample_config_path, tmp_path: Path) -> None:
    from controltower.config import load_config

    config = load_config(sample_config_path)
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    csv_path = _write_schedule_csv(tmp_path)
    with csv_path.open("rb") as fp:
        response = client.post(
            "/runs",
            files={"csv_file": ("schedule.csv", fp.read(), "text/csv")},
            headers={"Accept": "application/json"},
        )
    assert response.status_code == 404
    run_id = execute_run(csv_path, state_root=config.runtime.state_root)
    run = get_run(config.runtime.state_root, run_id)
    assert run is not None
    assert run["status"] == "completed"


def test_repeat_runs_same_input_have_structurally_equivalent_artifacts(sample_config_path, tmp_path: Path) -> None:
    from controltower.config import load_config

    config = load_config(sample_config_path)
    csv_path = _write_schedule_csv(tmp_path)
    run_a = execute_run(csv_path, state_root=config.runtime.state_root)
    run_b = execute_run(csv_path, state_root=config.runtime.state_root)
    dir_a = config.runtime.state_root / "runs" / run_a / "artifacts"
    dir_b = config.runtime.state_root / "runs" / run_b / "artifacts"
    assert export_directory_file_map(dir_a) == export_directory_file_map(dir_b)


def test_update_run_status_persists_error(sample_config_path, tmp_path: Path) -> None:
    from controltower.config import load_config

    config = load_config(sample_config_path)
    csv_path = _write_schedule_csv(tmp_path)
    run_id = execute_run(csv_path, state_root=config.runtime.state_root)
    update_run_status(config.runtime.state_root, run_id, status="failed", error_message="manual test failure")
    record = get_run(config.runtime.state_root, run_id)
    assert record is not None
    assert record["status"] == "failed"
    assert record["error_message"] == "manual test failure"


def test_registry_consistency_when_run_json_missing(sample_config_path) -> None:
    from controltower.config import load_config

    config = load_config(sample_config_path)
    run_id = "run_20260407_010101_consistency"
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
    (run_root / "run.json").unlink()
    record = get_run(config.runtime.state_root, run_id)
    assert record is not None
    assert record["consistency_state"] == "registry_only"


def test_registry_consistency_when_registry_missing_entry(sample_config_path, tmp_path: Path) -> None:
    from controltower.config import load_config

    config = load_config(sample_config_path)
    run_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    registry_path = config.runtime.state_root / "runs" / REGISTRY_FILENAME
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["runs"] = [r for r in payload.get("runs", []) if r.get("run_id") != run_id]
    registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    record = get_run(config.runtime.state_root, run_id)
    assert record is not None
    assert record["consistency_state"] == "metadata_only"

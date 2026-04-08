"""Phase 13 — publish authority, single-surface routing, and runtime.state_root alignment."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.runs.execution import execute_run
from controltower.runs.publish_authority import (
    assess_run_publishability,
    get_latest_publishable_run,
    resolved_runtime_state_root,
)
from controltower.runs.registry import create_run, get_run
from controltower.schedule_intake.asta_csv import ASTA_EXPORT_HEADERS
from controltower.schedule_intake.export_artifacts import FILENAME_BUNDLE


def _write_schedule_csv(tmp_path: Path) -> Path:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(ASTA_EXPORT_HEADERS), lineterminator="\n")
    writer.writeheader()
    writer.writerow({h: "" for h in ASTA_EXPORT_HEADERS} | {"Task ID": "100", "Task name": "Start", "Successors": "200"})
    writer.writerow({h: "" for h in ASTA_EXPORT_HEADERS} | {"Task ID": "200", "Task name": "Finish", "Predecessors": "100"})
    path = tmp_path / "schedule.csv"
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


def test_root_renders_browser_entry_surface(sample_config_path) -> None:
    client = TestClient(create_app(str(sample_config_path)))
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="runs-home-upload"' in r.text
    assert 'id="runs-home-latest"' in r.text
    assert 'id="runs-home-recent"' in r.text


def test_publish_redirects_to_latest_publishable_operator(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    client = TestClient(create_app(str(sample_config_path)))
    r = client.get("/publish", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/publish/operator/{run_id}"


def test_publish_empty_when_no_publishable_run(sample_config_path) -> None:
    client = TestClient(create_app(str(sample_config_path)))
    r = client.get("/publish", follow_redirects=False)
    assert r.status_code == 200
    assert 'id="publish-operator-surface"' in r.text


def test_latest_skips_incomplete_then_picks_publishable(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    bad_id = "run_20990101_000000_incomplete"
    bad_root = config.runtime.state_root / "runs" / bad_id
    create_run(
        config.runtime.state_root,
        run_id=bad_id,
        input_filename="schedule.csv",
        input_path=bad_root / "input" / "schedule.csv",
        artifact_dir=bad_root / "artifacts",
        bundle_path=bad_root / "artifacts" / FILENAME_BUNDLE,
        manifest_path=bad_root / "artifacts" / "manifest.json",
        status="completed",
    )
    good_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    client = TestClient(create_app(str(sample_config_path)))
    r = client.get("/publish", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/publish/operator/{good_id}"


def test_latest_skips_malformed_completed_run(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    bad_id = "run_20990102_000000_badart"
    bad_root = config.runtime.state_root / "runs" / bad_id
    art = bad_root / "artifacts"
    create_run(
        config.runtime.state_root,
        run_id=bad_id,
        input_filename="schedule.csv",
        input_path=bad_root / "input" / "schedule.csv",
        artifact_dir=art,
        bundle_path=art / FILENAME_BUNDLE,
        manifest_path=art / "manifest.json",
        status="completed",
    )
    (art / FILENAME_BUNDLE).write_text("{}", encoding="utf-8")
    good_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    latest = get_latest_publishable_run(config.runtime.state_root)
    assert latest is not None
    assert latest["run_id"] == good_id


def test_operator_run_rejects_unknown_run(sample_config_path) -> None:
    client = TestClient(create_app(str(sample_config_path)))
    assert client.get("/publish/operator/does-not-exist").status_code == 404


def test_operator_run_rejects_non_publishable_completed_with_bad_bundle(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = "run_20990103_000000_corrupt"
    run_root = config.runtime.state_root / "runs" / run_id
    art = run_root / "artifacts"
    bundle = art / FILENAME_BUNDLE
    create_run(
        config.runtime.state_root,
        run_id=run_id,
        input_filename="schedule.csv",
        input_path=run_root / "input" / "schedule.csv",
        artifact_dir=art,
        bundle_path=bundle,
        manifest_path=art / "manifest.json",
        status="completed",
    )
    bundle.write_text(json.dumps({"command_brief": {}, "exploration": {}}), encoding="utf-8")
    client = TestClient(create_app(str(sample_config_path)))
    res = client.get(f"/publish/operator/{run_id}")
    assert res.status_code == 409


def test_operator_print_matches_non_print_authority(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    client = TestClient(create_app(str(sample_config_path)))
    normal = client.get(f"/publish/operator/{run_id}")
    printed = client.get(f"/publish/operator/{run_id}", params={"print": 1})
    assert normal.status_code == 200
    assert printed.status_code == 200
    assert "data-auto-print=\"true\"" in printed.text
    assert "data-auto-print=\"true\"" not in normal.text
    rec = get_run(config.runtime.state_root, run_id)
    assert rec is not None
    ok, _ = assess_run_publishability(config.runtime.state_root, rec)
    assert ok
    bundle = Path(rec["bundle_path"])
    inner = json.loads(bundle.read_text(encoding="utf-8"))
    needle = str(inner.get("command_brief", {}).get("finish", ""))[:20]
    assert needle
    assert needle in normal.text
    assert needle in printed.text


def test_resolved_runtime_state_root_matches_load_config(sample_config_path) -> None:
    cfg = load_config(sample_config_path)
    resolved = resolved_runtime_state_root(Path(sample_config_path))
    assert resolved == Path(cfg.runtime.state_root).expanduser().resolve()


def test_execution_and_ui_config_share_state_root(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    ui_root = resolved_runtime_state_root(Path(sample_config_path))
    assert ui_root == Path(config.runtime.state_root).expanduser().resolve()
    assert get_run(ui_root, run_id) is not None


def test_legacy_routes_remain_blocked(sample_config_path) -> None:
    client = TestClient(create_app(str(sample_config_path)))
    for path in ("/arena", "/runs", "/projects", "/diagnostics", "/control", "/api/projects"):
        assert client.get(path).status_code == 404

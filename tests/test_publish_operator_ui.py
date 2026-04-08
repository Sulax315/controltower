from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.runs.execution import execute_run
from controltower.runs.registry import create_run
from controltower.schedule_intake.export_artifacts import FILENAME_BUNDLE
from controltower.runs.validation import VALIDATION_JSON_FILENAME
from controltower.schedule_intake.asta_csv import ASTA_EXPORT_HEADERS
import csv
import io


def _write_schedule_csv(tmp_path: Path) -> Path:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(ASTA_EXPORT_HEADERS), lineterminator="\n")
    writer.writeheader()
    writer.writerow({h: "" for h in ASTA_EXPORT_HEADERS} | {"Task ID": "100", "Task name": "Start", "Successors": "200"})
    writer.writerow({h: "" for h in ASTA_EXPORT_HEADERS} | {"Task ID": "200", "Task name": "Finish", "Predecessors": "100"})
    path = tmp_path / "schedule.csv"
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


def test_publish_operator_surface_renders_packet_sections(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    rec = config.runtime.state_root / "runs" / run_id / "artifacts" / FILENAME_BUNDLE
    inner = json.loads(rec.read_text(encoding="utf-8"))

    client = TestClient(create_app(str(sample_config_path)))
    res = client.get(f"/publish/operator/{run_id}")
    assert res.status_code == 200
    text = res.text
    assert 'id="publish-operator-header-strip"' in text
    assert 'id="publish-operator-command-brief"' in text
    assert 'id="publish-operator-evidence"' in text
    assert 'id="publish-operator-evidence-driver"' in text
    assert 'id="publish-operator-evidence-risk"' in text
    assert 'id="publish-operator-graph"' in text
    assert 'id="publish-driver-graph-svg"' in text
    assert "id=\"publish-operator-error\"" not in text
    assert inner["command_brief"]["finish"] in text
    assert inner["command_brief"]["driver"] in text
    assert inner["command_brief"]["risks"] in text
    assert inner["command_brief"]["need"] in text
    assert inner["command_brief"]["doing"] in text
    assert "Finish" in text
    assert "Driver" in text
    assert "Risks" in text
    assert "Need" in text
    assert "Doing" in text
    assert "Inline Structural View" in text
    assert "Driver Evidence" in text
    assert "Risk Evidence" in text
    assert "Primary Driver" in text
    assert "Top Severity" in text
    assert "Priority Action" in text
    assert "Execute Now" in text
    assert "ct-evidence-line-priority" in text
    assert 'id="publish-operator-evidence-driver" open' not in text
    assert 'id="publish-operator-evidence-risk" open' not in text
    assert "Expand to review" in text
    assert "Isolate Driver Path" in text
    assert "Trace Selected to Finish" in text
    assert "SCHEDULE VISUALIZATION LAYER" in text
    assert "Deterministic Key" in text
    assert "Authoritative finish target" in text
    assert "REAL-PROJECT VALIDATION" in text
    assert "Save Validation Note" in text
    assert text.index('id="publish-operator-command-brief"') < text.index('id="publish-operator-evidence"')


def test_publish_operator_surface_print_mode_renders_stakeholder_handout(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    client = TestClient(create_app(str(sample_config_path)))
    res = client.get(f"/publish/operator/{run_id}", params={"print": 1})
    assert res.status_code == 200
    text = res.text
    assert 'id="publish-operator-surface"' in text
    assert 'data-auto-print="true"' in text
    assert "Print / PDF" in text
    assert 'id="publish-operator-evidence-driver"' in text
    assert "Inline Structural View" in text
    assert "Priority Action" in text
    assert "Execute Now" in text
    assert 'id="publish-operator-graph"' in text
    assert "Deterministic Key" in text


def test_publish_operator_print_mode_reuses_same_packet_fields(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    bundle_path = config.runtime.state_root / "runs" / run_id / "artifacts" / FILENAME_BUNDLE
    inner = json.loads(bundle_path.read_text(encoding="utf-8"))
    needle_finish = str(inner.get("command_brief", {}).get("finish", ""))[:24]

    client = TestClient(create_app(str(sample_config_path)))
    normal = client.get(f"/publish/operator/{run_id}")
    printed = client.get(f"/publish/operator/{run_id}", params={"print": 1})
    assert normal.status_code == 200
    assert printed.status_code == 200
    assert needle_finish in normal.text
    assert needle_finish in printed.text
    assert inner["command_brief"]["driver"] in normal.text
    assert inner["command_brief"]["driver"] in printed.text
    assert inner["command_brief"]["risks"] in normal.text
    assert inner["command_brief"]["risks"] in printed.text
    assert inner["command_brief"]["need"] in normal.text
    assert inner["command_brief"]["need"] in printed.text
    assert inner["command_brief"]["doing"] in normal.text
    assert inner["command_brief"]["doing"] in printed.text
    assert "Driver Evidence" in normal.text
    assert "Driver Evidence" in printed.text
    assert "Risk Evidence" in normal.text
    assert "Risk Evidence" in printed.text
    assert "Inline Structural View" in normal.text
    assert "Inline Structural View" in printed.text
    assert "SCHEDULE VISUALIZATION LAYER" in normal.text
    assert "SCHEDULE VISUALIZATION LAYER" in printed.text
    assert "Deterministic Key" in normal.text
    assert "Deterministic Key" in printed.text


def test_publish_operator_empty_when_no_publishable_run(sample_config_path) -> None:
    client = TestClient(create_app(str(sample_config_path)))
    res = client.get("/publish", follow_redirects=False)
    assert res.status_code == 200
    text = res.text
    assert 'id="publish-operator-surface"' in text
    assert 'id="publish-operator-header-strip"' in text
    assert 'id="publish-operator-command-brief"' in text
    assert 'id="publish-operator-evidence"' in text


def test_publish_operator_query_route_is_blocked(sample_config_path, tmp_path: Path) -> None:
    """Legacy ?bundle= entrypoint removed; only /publish/operator/{run_id} is allowed."""
    config = load_config(sample_config_path)
    run_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    bundle_path = config.runtime.state_root / "runs" / run_id / "artifacts" / FILENAME_BUNDLE
    client = TestClient(create_app(str(sample_config_path)))
    assert client.get("/publish/operator", params={"bundle": str(bundle_path)}).status_code == 404


def test_publish_operator_invalid_bundle_run_returns_409(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = "run_publish_op_ui_bad"
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
    bundle.write_text("{not-json", encoding="utf-8")
    client = TestClient(create_app(str(sample_config_path)))
    res = client.get(f"/publish/operator/{run_id}")
    assert res.status_code == 409


def test_publish_operator_incomplete_bundle_run_returns_409(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = "run_publish_op_ui_incomplete"
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


def test_publish_operator_validation_save_writes_run_linked_artifact(sample_config_path, tmp_path: Path) -> None:
    config = load_config(sample_config_path)
    run_id = execute_run(_write_schedule_csv(tmp_path), state_root=config.runtime.state_root)
    client = TestClient(create_app(str(sample_config_path)))
    page = client.get(f"/publish/operator/{run_id}")
    assert page.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match is not None
    token = match.group(1)
    payload = {
        "csrf_token": token,
        "reviewer": "operator-1",
        "schedule_source": "weekly-export",
        "meeting_context": "weekly review",
        "open_friction": "Need quicker confidence for graph-to-evidence transitions.",
        "high_value_hardening": "Add deterministic label hints from normalized intake.",
        "score_command_brief_clarity": "4",
        "score_evidence_precision": "3",
        "score_graph_comprehension": "4",
        "score_interaction_flow": "3",
        "score_export_usefulness": "4",
        "score_stakeholder_readability": "4",
        "note_command_brief_clarity": "Clear enough for weekly cadence.",
        "note_evidence_precision": "Some rows need tighter node mapping.",
        "note_graph_comprehension": "Path direction is legible.",
        "note_interaction_flow": "Focus controls are usable.",
        "note_export_usefulness": "Printed pack is workable.",
        "note_stakeholder_readability": "Legend helps non-operators.",
    }
    post = client.post(f"/publish/operator/{run_id}/validation", data=payload, follow_redirects=False)
    assert post.status_code == 303
    assert post.headers["location"].startswith(f"/publish/operator/{run_id}?validation_saved=1")

    artifact = config.runtime.state_root / "runs" / run_id / "artifacts" / VALIDATION_JSON_FILENAME
    assert artifact.exists()
    saved = json.loads(artifact.read_text(encoding="utf-8"))
    assert saved["run_id"] == run_id
    assert saved["reviewer"] == "operator-1"
    assert "category_scores" in saved
    assert "entry_upload_flow" in saved["category_scores"]

    md_download = client.get(f"/publish/operator/{run_id}/validation.md")
    assert md_download.status_code == 200
    assert "text/markdown" in (md_download.headers.get("content-type") or "")
    assert "Operator Validation" in md_download.text

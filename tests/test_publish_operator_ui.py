from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.schedule_intake import (
    Activity,
    build_command_brief,
    build_exploration_contract,
    build_schedule_graph_summary,
    build_schedule_intelligence_bundle,
    build_schedule_logic_graph,
    collect_schedule_risk_findings,
    rank_driver_candidates,
)
from controltower.schedule_intake.logic_quality import analyze_logic_quality


def _bundle_payload() -> dict:
    g = build_schedule_logic_graph(
        [
            Activity(task_id="1", successors=["2"]),
            Activity(task_id="2", predecessors=["1"], successors=["3"]),
            Activity(task_id="3", predecessors=["2"]),
        ]
    )
    gs = build_schedule_graph_summary(g)
    lq = analyze_logic_quality(g)
    risks = collect_schedule_risk_findings(g, logic_quality=lq, graph_summary=gs)
    top = rank_driver_candidates(g, limit=1)[0]
    brief = build_command_brief(graph_summary=gs, driver=top, risks=risks, delta=None)
    bundle = build_schedule_intelligence_bundle(
        graph_summary=gs,
        logic_quality=lq,
        top_driver=top,
        risks=risks,
        delta=None,
        command_brief=brief,
        exploration=build_exploration_contract(),
    )
    return bundle.to_jsonable_dict()


def test_publish_operator_surface_renders_packet_sections(sample_config_path, tmp_path: Path) -> None:
    payload = _bundle_payload()
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    client = TestClient(create_app(str(sample_config_path)))
    res = client.get("/publish/operator", params={"bundle": str(bundle_path)})
    assert res.status_code == 200
    text = res.text
    assert 'id="publish-operator-header-strip"' in text
    assert 'id="publish-operator-verdict"' in text
    assert 'id="publish-operator-kpis"' in text
    assert 'id="publish-operator-drivers-risks"' in text
    assert 'id="publish-operator-evidence"' in text
    assert "id=\"publish-operator-error\"" not in text
    assert payload["command_brief"]["finish"] in text
    assert payload["command_brief"]["driver"] in text


def test_publish_operator_surface_handles_empty_default(sample_config_path) -> None:
    client = TestClient(create_app(str(sample_config_path)))
    res = client.get("/publish/operator")
    assert res.status_code == 200
    text = res.text
    assert 'id="publish-operator-surface"' in text
    assert 'id="publish-operator-header-strip"' in text
    assert 'id="publish-operator-evidence"' in text

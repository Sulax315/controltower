from __future__ import annotations

from controltower.schedule_intake import (
    Activity,
    build_command_brief,
    build_driver_analysis,
    build_command_brief_contract,
    build_engine_snapshot,
    build_exploration_contract,
    build_schedule_graph_summary,
    build_schedule_intelligence_bundle,
    build_schedule_logic_graph,
    collect_schedule_risk_findings,
    rank_driver_candidates,
)
from controltower.schedule_intake.logic_quality import analyze_logic_quality


def _sample_graph():
    acts = [
        Activity(task_id="1", successors=["2"]),
        Activity(task_id="2", predecessors=["1"], successors=["3"]),
        Activity(task_id="3", predecessors=["2"]),
    ]
    return build_schedule_logic_graph(acts)


def test_command_brief_contract_integrity() -> None:
    g = _sample_graph()
    gs = build_schedule_graph_summary(g)
    risks = collect_schedule_risk_findings(g, graph_summary=gs)
    top = rank_driver_candidates(g, limit=1)[0]
    da = build_driver_analysis(g)
    assert da is not None
    brief = build_command_brief(graph_summary=gs, driver_analysis=da, risks=risks)
    c = build_command_brief_contract(brief)
    d = c.to_dict()
    assert tuple(d.keys()) == ("finish", "driver", "risks", "need", "doing")
    assert d["finish"].startswith("FINISH:")
    assert d["need"].startswith("NEED:")


def test_exploration_contract_integrity_and_defaults() -> None:
    c = build_exploration_contract()
    d = c.to_dict()
    assert tuple(d.keys()) == (
        "immediate_predecessors",
        "immediate_successors",
        "upstream_closure",
        "downstream_closure",
        "shortest_path",
        "all_simple_paths",
        "shared_ancestors",
        "shared_descendants",
        "driver_structure",
        "impact_span",
    )
    assert d["immediate_predecessors"] == ()
    assert d["driver_structure"] is None


def test_engine_snapshot_and_bundle_deterministic_serialization() -> None:
    g = _sample_graph()
    gs = build_schedule_graph_summary(g)
    lq = analyze_logic_quality(g)
    risks = collect_schedule_risk_findings(g, graph_summary=gs)
    top = rank_driver_candidates(g, limit=1)[0]
    da = build_driver_analysis(g)
    assert da is not None
    brief = build_command_brief(graph_summary=gs, driver_analysis=da, risks=risks)

    snap1 = build_engine_snapshot(
        graph_summary=gs,
        logic_quality=lq,
        driver_analysis=da,
        top_driver=top,
        risks=risks,
        delta=None,
        command_brief=brief,
    )
    snap2 = build_engine_snapshot(
        graph_summary=gs,
        logic_quality=lq,
        driver_analysis=da,
        top_driver=top,
        risks=risks,
        delta=None,
        command_brief=brief,
    )
    assert snap1.to_jsonable_dict() == snap2.to_jsonable_dict()

    ex = build_exploration_contract(
        immediate_predecessors=("1",),
        immediate_successors=("3",),
        upstream_closure=("1",),
        downstream_closure=("3",),
        shortest_path=("1", "2", "3"),
        all_simple_paths=(("1", "2", "3"),),
        shared_ancestors=(),
        shared_descendants=(),
        driver_structure={"task_id": "2", "upstream_count": 1},
        impact_span={"task_id": "2", "downstream_node_count": 1},
    )
    bundle = build_schedule_intelligence_bundle(
        graph_summary=gs,
        logic_quality=lq,
        driver_analysis=da,
        top_driver=top,
        risks=risks,
        delta=None,
        command_brief=brief,
        exploration=ex,
    )
    jd = bundle.to_jsonable_dict()
    assert tuple(jd.keys()) == ("command_brief", "engine_snapshot", "exploration")
    assert tuple(jd["engine_snapshot"].keys()) == (
        "command_brief_lines",
        "delta_summary",
        "graph_summary",
        "intelligence_payload",
        "logic_quality",
        "risks",
        "top_driver",
    )
    assert tuple(jd["command_brief"].keys()) == ("doing", "driver", "finish", "need", "risks")
    assert jd["engine_snapshot"]["delta_summary"] is None
    payload = jd["engine_snapshot"]["intelligence_payload"]
    assert payload["schema_version"] == "intelligence_payload_v1"
    assert "finish_summary" in payload
    assert "driver_summary" in payload
    assert "risk_summary" in payload
    assert "artifact_references" in payload


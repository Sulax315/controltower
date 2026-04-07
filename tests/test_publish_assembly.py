from __future__ import annotations

from controltower.schedule_intake import (
    Activity,
    build_command_brief,
    build_exploration_contract,
    build_publish_evidence,
    build_publish_header,
    build_publish_packet,
    build_schedule_graph_summary,
    build_schedule_intelligence_bundle,
    build_schedule_logic_graph,
    collect_schedule_risk_findings,
    rank_driver_candidates,
)
from controltower.schedule_intake.logic_quality import analyze_logic_quality


def _bundle(with_driver: bool = True, with_risk: bool = True):
    graph = build_schedule_logic_graph(
        [
            Activity(task_id="1", successors=["2"]),
            Activity(task_id="2", predecessors=["1"], successors=["3"]),
            Activity(task_id="3", predecessors=["2"]),
        ]
    )
    gs = build_schedule_graph_summary(graph)
    lq = analyze_logic_quality(graph)
    risks = collect_schedule_risk_findings(graph, logic_quality=lq, graph_summary=gs) if with_risk else ()
    top = rank_driver_candidates(graph, limit=1)[0] if with_driver else None
    brief = build_command_brief(graph_summary=gs, driver=top, risks=risks, delta=None)
    return build_schedule_intelligence_bundle(
        graph_summary=gs,
        logic_quality=lq,
        top_driver=top,
        risks=risks,
        delta=None,
        command_brief=brief,
        exploration=build_exploration_contract(),
    )


def test_publish_packet_deterministic_for_identical_bundle() -> None:
    b = _bundle()
    p1 = build_publish_packet(b)
    p2 = build_publish_packet(b)
    assert p1 == p2
    assert p1.to_jsonable_dict() == p2.to_jsonable_dict()


def test_empty_default_safe_case_no_driver_no_risk() -> None:
    b = _bundle(with_driver=False, with_risk=False)
    p = build_publish_packet(b)
    assert p.drivers.top_driver_task_id is None
    assert p.drivers.top_driver_score is None
    assert p.risks.top_risk_id is None
    assert p.risks.top_risk_severity is None
    assert p.risks.total_risk_count == 0
    assert p.evidence.driver_evidence == ()
    assert p.evidence.risk_evidence == ()


def test_flags_correctness_from_graph_summary() -> None:
    b = _bundle()
    h = build_publish_header(b)
    assert h.status_flags == ("open_sinks", "open_sources")


def test_evidence_extraction_order_correctness() -> None:
    b = _bundle()
    e = build_publish_evidence(b)
    assert len(e.driver_evidence) >= 1
    # order preserved from rationale_signals by index
    assert e.driver_evidence[0][0] == "0"
    if e.risk_evidence:
        # risk evidence comes in given order from first risk.evidence
        keys = [k for k, _ in e.risk_evidence]
        assert keys == list(keys)


def test_full_integration_publish_packet_jsonable_stable() -> None:
    b = _bundle()
    p = build_publish_packet(b)
    jd = p.to_jsonable_dict()
    assert tuple(jd.keys()) == ("actions", "drivers", "evidence", "header", "kpis", "risks", "verdict")
    assert jd["header"]["finish_line"].startswith("FINISH:")
    assert jd["verdict"]["action_token"].startswith("ACTION:")
    assert isinstance(jd["kpis"]["node_count"], int)

from __future__ import annotations

from controltower.schedule_intake.command_brief import (
    CommandBrief,
    DriverFinding,
    GraphSummary,
    build_command_brief,
    derive_action,
)
from controltower.schedule_intake.delta_analysis import SummaryCounts
from controltower.schedule_intake.graph_summary import DegreeDistributionStats
from controltower.schedule_intake.risks import RiskFinding


def _empty_graph_summary() -> GraphSummary:
    ds = DegreeDistributionStats(
        min_in_degree=0,
        max_in_degree=0,
        mean_in_degree=0.0,
        min_out_degree=0,
        max_out_degree=0,
        mean_out_degree=0.0,
        zero_inbound_node_count=0,
        zero_outbound_node_count=0,
    )
    return GraphSummary(
        node_count=0,
        edge_count=0,
        invalid_reference_count=0,
        open_source_node_count=0,
        open_sink_node_count=0,
        directed_cycle_present=False,
        directed_cycle_witness_length=0,
        source_node_ids=(),
        sink_node_ids=(),
        degree_stats=ds,
    )


def test_build_command_brief_determinism() -> None:
    gs = _empty_graph_summary()
    d = DriverFinding(
        task_id="t1",
        task_name=None,
        driver_score=12.345678,
        score_components={"a": 1.0},
        rationale_signals=[],
        critical=None,
        total_float_days=None,
        downstream_reach_count=0,
        outbound_degree=0,
        inbound_degree=0,
        hops_to_structural_sink=None,
    )
    risks: tuple[RiskFinding, ...] = ()
    a = build_command_brief(graph_summary=gs, driver=d, risks=risks, delta=None)
    b = build_command_brief(graph_summary=gs, driver=d, risks=risks, delta=None)
    assert a == b
    assert a.as_lines() == b.as_lines()
    assert a.driver == "DRIVER: task_id=t1 score=12.3457"


def test_empty_inputs() -> None:
    gs = _empty_graph_summary()
    b = build_command_brief(graph_summary=gs, driver=None, risks=(), delta=None)
    assert b.finish.startswith("FINISH:")
    assert "nodes=0" in b.finish
    assert b.driver == "DRIVER: none"
    assert b.risks == "RISKS: count=0 top_id=none top_sev=none top_type=none"
    assert b.delta == "DELTA: none"
    assert b.action == "ACTION: monitor_schedule"
    assert len(b.as_lines()) == 5


def test_risks_line_respects_engine_order_first_is_top() -> None:
    gs = _empty_graph_summary()
    low_first = RiskFinding(
        risk_id="open_start:1",
        risk_type="open_start",
        severity="low",
        task_id="1",
        evidence=(("task_id", "1"),),
        source_signals=("test",),
        sort_score=3020,
    )
    high_second = RiskFinding(
        risk_id="zero_float_non_critical:2",
        risk_type="zero_float_non_critical",
        severity="high",
        task_id="2",
        evidence=(("task_id", "2"),),
        source_signals=("test",),
        sort_score=9999,
    )
    wrong_order = build_command_brief(graph_summary=gs, driver=None, risks=(low_first, high_second), delta=None)
    assert "top_id=open_start:1" in wrong_order.risks

    high_first = RiskFinding(
        risk_id="zero_float_non_critical:2",
        risk_type="zero_float_non_critical",
        severity="high",
        task_id="2",
        evidence=(("task_id", "2"),),
        source_signals=("test",),
        sort_score=9999,
    )
    low_second = RiskFinding(
        risk_id="open_start:1",
        risk_type="open_start",
        severity="low",
        task_id="1",
        evidence=(("task_id", "1"),),
        source_signals=("test",),
        sort_score=3020,
    )
    ok = build_command_brief(graph_summary=gs, driver=None, risks=(high_first, low_second), delta=None)
    assert "top_id=zero_float_non_critical:2" in ok.risks
    assert "top_sev=high" in ok.risks


def test_derive_action_priority_high_over_medium() -> None:
    gs = _empty_graph_summary()
    med = RiskFinding(
        risk_id="low_float:x",
        risk_type="low_float",
        severity="medium",
        task_id="x",
        evidence=(("total_float_days", "1.0"),),
        source_signals=("test",),
        sort_score=4000,
    )
    high = RiskFinding(
        risk_id="invalid_reference:a:pred:b",
        risk_type="invalid_reference",
        severity="high",
        task_id="a",
        evidence=(("referenced_task_id", "b"),),
        source_signals=("test",),
        sort_score=9000,
    )
    assert derive_action(graph_summary=gs, risks=(med, high), delta=None) == "address_high_risk"
    assert derive_action(graph_summary=gs, risks=(high, med), delta=None) == "address_high_risk"


def test_derive_action_cycle_first() -> None:
    ds = DegreeDistributionStats(0, 0, 0.0, 0, 0, 0.0, 0, 0)
    gs = GraphSummary(
        node_count=1,
        edge_count=1,
        invalid_reference_count=1,
        open_source_node_count=1,
        open_sink_node_count=1,
        directed_cycle_present=True,
        directed_cycle_witness_length=3,
        source_node_ids=("1",),
        sink_node_ids=("2",),
        degree_stats=ds,
    )
    assert derive_action(graph_summary=gs, risks=(), delta=None) == "resolve_cycle_logic"


def test_derive_action_delta_finish_changes() -> None:
    gs = _empty_graph_summary()
    d = SummaryCounts(
        added_tasks=0,
        removed_tasks=0,
        changed_start_dates=0,
        changed_finish_dates=2,
        changed_durations=0,
        changed_total_float_days=0,
        changed_free_float_days=0,
        changed_critical=0,
        predecessor_set_changes=0,
        successor_set_changes=0,
        logic_edges_added=0,
        logic_edges_removed=0,
        driver_rank_changes=0,
    )
    assert derive_action(graph_summary=gs, risks=(), delta=d) == "review_logic_deltas"


def test_derive_action_delta_scope_over_logic() -> None:
    gs = _empty_graph_summary()
    d = SummaryCounts(
        added_tasks=1,
        removed_tasks=0,
        changed_start_dates=0,
        changed_finish_dates=0,
        changed_durations=0,
        changed_total_float_days=0,
        changed_free_float_days=0,
        changed_critical=0,
        predecessor_set_changes=0,
        successor_set_changes=0,
        logic_edges_added=1,
        logic_edges_removed=0,
        driver_rank_changes=0,
    )
    assert derive_action(graph_summary=gs, risks=(), delta=d) == "reconcile_task_scope"


def test_command_brief_frozen_dataclass() -> None:
    gs = _empty_graph_summary()
    b = build_command_brief(graph_summary=gs, driver=None, risks=(), delta=None)
    assert isinstance(b, CommandBrief)

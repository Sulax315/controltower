from __future__ import annotations

from controltower.intelligence import build_command_brief
from controltower.intelligence.command_brief import CommandBrief
from controltower.schedule_intake import (
    Activity,
    build_driver_analysis,
    build_schedule_graph_summary,
    build_schedule_logic_graph,
    collect_schedule_risk_findings,
)


def _sample_inputs():
    graph = build_schedule_logic_graph(
        [
            Activity(task_id="1", successors=["2"], total_float_days=1.0, critical=True),
            Activity(task_id="2", predecessors=["1"], successors=["3"], total_float_days=0.0, critical=False),
            Activity(task_id="3", predecessors=["2"], total_float_days=8.0, critical=True),
        ]
    )
    gs = build_schedule_graph_summary(graph)
    da = build_driver_analysis(graph)
    assert da is not None
    risks = collect_schedule_risk_findings(graph, graph_summary=gs, driver_analysis=da)
    return gs, da, risks


def test_build_command_brief_determinism() -> None:
    gs, da, risks = _sample_inputs()
    a = build_command_brief(graph_summary=gs, driver_analysis=da, risks=risks)
    b = build_command_brief(graph_summary=gs, driver_analysis=da, risks=risks)
    assert a == b
    assert a.as_lines() == b.as_lines()


def test_command_brief_fields_and_prefixes() -> None:
    gs, da, risks = _sample_inputs()
    brief = build_command_brief(graph_summary=gs, driver_analysis=da, risks=risks)
    assert brief.finish.startswith("FINISH:")
    assert brief.driver.startswith("DRIVER:")
    assert brief.risks.startswith("RISKS:")
    assert brief.need.startswith("NEED:")
    assert brief.doing.startswith("DOING:")
    assert len(brief.as_lines()) == 5


def test_driver_line_uses_driver_analysis_path() -> None:
    gs, da, risks = _sample_inputs()
    brief = build_command_brief(graph_summary=gs, driver_analysis=da, risks=risks)
    assert f"finish_task_id={da.authoritative_finish_target.task_id}" in brief.driver
    assert "path=1,2,3" in brief.driver


def test_need_from_risk_and_doing_from_current_state() -> None:
    gs, da, risks = _sample_inputs()
    brief = build_command_brief(graph_summary=gs, driver_analysis=da, risks=risks)
    assert brief.need in (
        "NEED: resolve_cycle_logic",
        "NEED: address_high_risk",
        "NEED: address_medium_risk",
        "NEED: review_open_endpoints",
        "NEED: monitor_schedule",
    )
    assert f"finish={da.authoritative_finish_target.task_id}" in brief.doing
    assert f"driver_path_len={len(da.driver_path)}" in brief.doing


def test_command_brief_frozen_dataclass() -> None:
    gs, da, risks = _sample_inputs()
    b = build_command_brief(graph_summary=gs, driver_analysis=da, risks=risks)
    assert isinstance(b, CommandBrief)

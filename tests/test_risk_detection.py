from __future__ import annotations

from pathlib import Path

from controltower.schedule_intake import (
    Activity,
    build_schedule_logic_graph,
    collect_schedule_risk_findings,
    parse_asta_export_csv,
)
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "asta_export_authoritative_fixture.csv"


def test_findings_deterministic() -> None:
    acts = [
        Activity(task_id="1", predecessors=["2"], successors=["2"]),
        Activity(task_id="2", predecessors=["1"], successors=["1"]),
    ]
    g = build_schedule_logic_graph(acts)
    a = collect_schedule_risk_findings(g)
    b = collect_schedule_risk_findings(g)
    assert a == b
    assert a[0].risk_type == "cycle_detected"


def test_tie_break_stable_risk_id() -> None:
    acts = [
        Activity(task_id="b", total_float_days=1.0),
        Activity(task_id="a", total_float_days=1.0),
    ]
    g = build_schedule_logic_graph(acts)
    f = collect_schedule_risk_findings(g)
    lows = [x for x in f if x.risk_type == "low_float"]
    assert [x.risk_id for x in lows] == sorted([x.risk_id for x in lows])


def test_invalid_reference_surfaced() -> None:
    acts = [Activity(task_id="x", predecessors=["missing"])]
    g = build_schedule_logic_graph(acts)
    f = collect_schedule_risk_findings(g)
    inv = [x for x in f if x.risk_type == "invalid_reference"]
    assert len(inv) == 1
    assert inv[0].severity == "high"
    assert dict(inv[0].evidence)["referenced_task_id"] == "missing"


def test_asymmetry_surfaced() -> None:
    acts = [
        Activity(task_id="A", successors=["B"]),
        Activity(task_id="B"),
    ]
    g = build_schedule_logic_graph(acts)
    f = collect_schedule_risk_findings(g)
    asym = [x for x in f if x.risk_type == "asymmetric_relationship"]
    assert len(asym) == 1


def test_open_start_finish_present() -> None:
    acts = [Activity(task_id="solo")]
    g = build_schedule_logic_graph(acts)
    f = collect_schedule_risk_findings(g)
    types = {x.risk_type for x in f}
    assert "open_start" in types
    assert "open_finish" in types


def test_zero_float_non_critical() -> None:
    acts = [Activity(task_id="z", total_float_days=0.0, critical=False)]
    g = build_schedule_logic_graph(acts)
    f = collect_schedule_risk_findings(g)
    z = [x for x in f if x.risk_type == "zero_float_non_critical"]
    assert len(z) == 1


def test_critical_not_zero_float_when_critical_true() -> None:
    acts = [Activity(task_id="z", total_float_days=0.0, critical=True)]
    g = build_schedule_logic_graph(acts)
    f = collect_schedule_risk_findings(g)
    assert not any(x.risk_type == "zero_float_non_critical" for x in f)


def test_fixture_contains_expected_types() -> None:
    assert FIXTURE.is_file()
    acts = parse_asta_export_csv(FIXTURE).activities
    g = build_schedule_logic_graph(acts)
    f = collect_schedule_risk_findings(g)
    types = {x.risk_type for x in f}
    assert "invalid_reference" in types
    assert "asymmetric_relationship" in types
    assert "open_start" in types
    assert "open_finish" in types
    assert "cycle_detected" not in types
    assert f[0].severity == "high"

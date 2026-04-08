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


def test_orphan_chain_exposure_present() -> None:
    acts = [
        Activity(task_id="A", successors=["B"]),
        Activity(task_id="B", predecessors=["A"]),
        Activity(task_id="X", successors=["Y"]),
        Activity(task_id="Y", predecessors=["X"]),
    ]
    g = build_schedule_logic_graph(acts)
    f = collect_schedule_risk_findings(g)
    orphan = [x for x in f if x.risk_type == "orphan_chain_exposure"]
    assert len(orphan) == 1
    assert orphan[0].related_task_ids == ("X", "Y")


def test_finish_target_fragility_open_inbound_and_linkage() -> None:
    acts = [Activity(task_id="solo", critical=False)]
    g = build_schedule_logic_graph(acts)
    f = collect_schedule_risk_findings(g)
    frag = [x for x in f if x.risk_type == "finish_target_fragility_open_inbound"]
    assert len(frag) == 1
    assert frag[0].touches_finish_target is True
    assert frag[0].touches_driver_path is True


def test_driver_path_low_float_and_zero_float_non_critical() -> None:
    acts = [
        Activity(task_id="1", successors=["2"], total_float_days=1.0, critical=True),
        Activity(task_id="2", predecessors=["1"], successors=["3"], total_float_days=0.0, critical=False),
        Activity(task_id="3", predecessors=["2"], total_float_days=6.0, critical=True),
    ]
    g = build_schedule_logic_graph(acts)
    f = collect_schedule_risk_findings(g)
    low = [x for x in f if x.risk_type == "driver_path_low_float_pressure"]
    zero = [x for x in f if x.risk_type == "driver_path_zero_float_non_critical"]
    assert len(low) == 1 and low[0].task_id == "1"
    assert low[0].touches_driver_path is True
    assert len(zero) == 1 and zero[0].task_id == "2"
    assert zero[0].severity == "high"


def test_finish_target_not_critical_detection() -> None:
    acts = [
        Activity(task_id="1", successors=["2"], critical=True),
        Activity(task_id="2", predecessors=["1"], critical=False),
    ]
    g = build_schedule_logic_graph(acts)
    f = collect_schedule_risk_findings(g)
    rows = [x for x in f if x.risk_type == "finish_target_not_critical"]
    assert len(rows) == 1
    assert rows[0].task_id == "2"
    assert rows[0].touches_finish_target is True


def test_severity_and_ordering_stable_for_new_types() -> None:
    acts = [
        Activity(task_id="a", successors=["b"], total_float_days=1.0, critical=True),
        Activity(task_id="b", predecessors=["a"], total_float_days=0.0, critical=False),
    ]
    g = build_schedule_logic_graph(acts)
    f1 = collect_schedule_risk_findings(g)
    f2 = collect_schedule_risk_findings(g)
    assert f1 == f2
    by_id = {x.risk_id: x for x in f1}
    assert by_id["driver_path_zero_float_non_critical:b"].severity == "high"
    assert by_id["driver_path_low_float_pressure:a"].severity == "medium"

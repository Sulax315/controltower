from __future__ import annotations

from pathlib import Path

import pytest

from controltower.schedule_intake import (
    Activity,
    build_schedule_logic_graph,
    parse_asta_export_csv,
    rank_driver_candidates,
)
from controltower.schedule_intake.drivers import _float_pressure_component

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "asta_export_authoritative_fixture.csv"


def test_ranking_deterministic_same_graph_twice() -> None:
    acts = [
        Activity(task_id="b", total_float_days=0.0, critical=True, successors=["c"]),
        Activity(task_id="a", total_float_days=10.0, predecessors=["b"]),
        Activity(task_id="c", predecessors=["b"]),
    ]
    g = build_schedule_logic_graph(acts)
    r1 = rank_driver_candidates(g)
    r2 = rank_driver_candidates(g)
    assert r1 == r2
    assert r1[0].driver_score >= r1[-1].driver_score


def test_tie_break_lexicographic_task_id() -> None:
    """Identical scores: lower task_id ranks earlier (second sort key)."""
    acts = [
        Activity(task_id="m2", total_float_days=None, critical=None),
        Activity(task_id="m1", total_float_days=None, critical=None),
    ]
    g = build_schedule_logic_graph(acts)
    ranked = rank_driver_candidates(g)
    assert ranked[0].task_id == "m1"
    assert ranked[1].task_id == "m2"
    assert ranked[0].driver_score == ranked[1].driver_score


def test_missing_float_uses_neutral_component() -> None:
    assert _float_pressure_component(None) == 4.0
    acts = [Activity(task_id="x", total_float_days=None)]
    g = build_schedule_logic_graph(acts)
    c = rank_driver_candidates(g)[0]
    assert c.score_components["float_pressure"] == 4.0


def test_fixture_graph_top_driver_is_critical_or_high_float_pressure() -> None:
    assert FIXTURE.is_file()
    acts = parse_asta_export_csv(FIXTURE).activities
    g = build_schedule_logic_graph(acts)
    top = rank_driver_candidates(g, limit=1)[0]
    assert top.task_id == "101"
    assert top.critical is True
    assert top.score_components["critical_flag"] == 10.0


def test_limit_slices_tail() -> None:
    acts = [Activity(task_id=str(i)) for i in range(5)]
    g = build_schedule_logic_graph(acts)
    full = len(rank_driver_candidates(g))
    assert full == 5
    assert len(rank_driver_candidates(g, limit=2)) == 2

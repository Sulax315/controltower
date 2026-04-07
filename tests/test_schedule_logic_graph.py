from __future__ import annotations

from pathlib import Path

import pytest

from controltower.schedule_intake import Activity, build_schedule_logic_graph, parse_asta_export_csv

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "asta_export_authoritative_fixture.csv"


def test_graph_simple_chain() -> None:
    acts = [
        Activity(task_id="1", predecessors=None, successors=["2"]),
        Activity(task_id="2", predecessors=["1"], successors=None),
    ]
    g = build_schedule_logic_graph(acts)
    assert set(g.nodes_by_id) == {"1", "2"}
    assert g.outbound_edges_by_id["1"] == [("1", "2")]
    assert g.inbound_edges_by_id["2"] == [("1", "2")]
    assert g.no_predecessor_nodes == ("1",)
    assert g.no_successor_nodes == ("2",)
    assert not g.invalid_references


def test_graph_invalid_predecessor() -> None:
    acts = [Activity(task_id="A", predecessors=["missing"], successors=None)]
    g = build_schedule_logic_graph(acts)
    assert len(g.invalid_references) == 1
    assert g.invalid_references[0].referenced_task_id == "missing"
    assert g.no_predecessor_nodes == ("A",)
    assert g.no_successor_nodes == ("A",)


@pytest.mark.skipif(not FIXTURE.is_file(), reason="fixture missing")
def test_authoritative_fixture_graph_shape() -> None:
    acts = parse_asta_export_csv(FIXTURE).activities
    g = build_schedule_logic_graph(acts)
    assert len(g.nodes_by_id) == 6
    assert sum(len(es) for es in g.outbound_edges_by_id.values()) == 5
    assert len(g.invalid_references) == 1
    assert g.invalid_references[0].referenced_task_id == "99"


def test_graph_dedupes_duplicate_edge() -> None:
    """Same edge implied by A.succ and B.pred."""
    acts = [
        Activity(task_id="A", predecessors=None, successors=["B"]),
        Activity(task_id="B", predecessors=["A"], successors=None),
    ]
    g = build_schedule_logic_graph(acts)
    assert sum(len(es) for es in g.outbound_edges_by_id.values()) == 1

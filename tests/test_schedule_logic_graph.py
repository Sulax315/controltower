from __future__ import annotations

from pathlib import Path

import pytest

from controltower.schedule_intake import (
    Activity,
    build_logic_graph_payload,
    build_schedule_logic_graph,
    find_orphan_chains,
    list_finish_candidates,
    parse_asta_export_csv,
)

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


def test_graph_resolves_task_id_tokens() -> None:
    acts = [
        Activity(task_id="10", unique_task_id="U-10", successors=["11"]),
        Activity(task_id="11", unique_task_id="U-11", predecessors=["10"]),
    ]
    g = build_schedule_logic_graph(acts)
    assert g.outbound_edges_by_id["10"] == [("10", "11")]
    assert g.inbound_edges_by_id["11"] == [("10", "11")]
    assert not g.invalid_references


def test_graph_resolves_unique_task_id_tokens() -> None:
    acts = [
        Activity(task_id="10", unique_task_id="U-10", successors=["U-11"]),
        Activity(task_id="11", unique_task_id="U-11", predecessors=["U-10"]),
    ]
    g = build_schedule_logic_graph(acts)
    assert g.outbound_edges_by_id["10"] == [("10", "11")]
    assert g.inbound_edges_by_id["11"] == [("10", "11")]
    assert not g.invalid_references


def test_graph_unique_task_id_resolution_reduces_invalid_references() -> None:
    acts = [
        Activity(task_id="A", unique_task_id="UA", successors=["UB", "UC"]),
        Activity(task_id="B", unique_task_id="UB", predecessors=["UA"], successors=["UC"]),
        Activity(task_id="C", unique_task_id="UC", predecessors=["UA", "UB"]),
    ]
    g = build_schedule_logic_graph(acts)
    assert sum(len(es) for es in g.outbound_edges_by_id.values()) == 3
    assert len(g.invalid_references) == 0


def test_graph_ambiguous_unique_task_id_reference_is_invalid() -> None:
    acts = [
        Activity(task_id="A", unique_task_id="U-DUP"),
        Activity(task_id="B", unique_task_id="U-DUP"),
        Activity(task_id="C", predecessors=["U-DUP"]),
    ]
    g = build_schedule_logic_graph(acts)
    assert len(g.invalid_references) == 1
    assert g.invalid_references[0].referencing_task_id == "C"
    assert g.invalid_references[0].referenced_task_id == "U-DUP"


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


def test_finish_candidates_structural_only() -> None:
    acts = [
        Activity(task_id="A", successors=["B"]),
        Activity(task_id="B", predecessors=["A"]),
        Activity(task_id="Z"),  # isolated node is also a structural sink
    ]
    g = build_schedule_logic_graph(acts)
    candidates = list_finish_candidates(g)
    assert tuple(c.task_id for c in candidates) == ("B", "Z")
    assert candidates[0].has_predecessor is True
    assert candidates[1].has_predecessor is False


def test_orphan_chains_detect_disconnected_components() -> None:
    acts = [
        Activity(task_id="A", successors=["B"]),
        Activity(task_id="B", predecessors=["A"], successors=["C"]),
        Activity(task_id="C", predecessors=["B"]),  # primary network
        Activity(task_id="X", successors=["Y"]),
        Activity(task_id="Y", predecessors=["X"]),  # orphan chain
    ]
    g = build_schedule_logic_graph(acts)
    assert find_orphan_chains(g) == (("X", "Y"),)


def test_logic_graph_payload_deterministic_shape() -> None:
    acts = [
        Activity(task_id="2", predecessors=["1"]),
        Activity(task_id="1", successors=["2"]),
        Activity(task_id="5"),
        Activity(task_id="4", successors=["6"]),
        Activity(task_id="6", predecessors=["4"]),
    ]
    g = build_schedule_logic_graph(acts)
    payload = build_logic_graph_payload(g)
    assert payload["schema_version"] == "schedule_logic_graph_v1"
    assert payload["nodes"] == ["1", "2", "4", "5", "6"]
    assert payload["edges"] == [
        {"from_task_id": "1", "to_task_id": "2"},
        {"from_task_id": "4", "to_task_id": "6"},
    ]
    assert payload["finish_candidates"] == [
        {"task_id": "2", "in_degree": 1, "out_degree": 0, "has_predecessor": True},
        {"task_id": "5", "in_degree": 0, "out_degree": 0, "has_predecessor": False},
        {"task_id": "6", "in_degree": 1, "out_degree": 0, "has_predecessor": True},
    ]
    assert payload["orphan_chains"] == [["4", "6"], ["5"]]

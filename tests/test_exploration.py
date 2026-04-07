from __future__ import annotations

from controltower.schedule_intake import (
    Activity,
    all_simple_paths_between,
    build_schedule_logic_graph,
    downstream_closure,
    downstream_impact_span,
    explain_driver_structure,
    immediate_predecessors,
    immediate_successors,
    is_reachable,
    shared_ancestors,
    shared_descendants,
    shortest_path_between,
    upstream_closure,
)


def _graph() -> object:
    acts = [
        Activity(task_id="A", successors=["B", "C"]),
        Activity(task_id="B", predecessors=["A"], successors=["D"]),
        Activity(task_id="C", predecessors=["A"], successors=["D", "E"]),
        Activity(task_id="D", predecessors=["B", "C"], successors=["F"]),
        Activity(task_id="E", predecessors=["C"], successors=["F"]),
        Activity(task_id="F", predecessors=["D", "E"]),
        Activity(task_id="X"),  # isolated
    ]
    return build_schedule_logic_graph(acts)


def _cycle_graph() -> object:
    acts = [
        Activity(task_id="1", successors=["2"]),
        Activity(task_id="2", predecessors=["1"], successors=["3"]),
        Activity(task_id="3", predecessors=["2"], successors=["1"]),
    ]
    return build_schedule_logic_graph(acts)


def test_immediate_predecessors_successors() -> None:
    g = _graph()
    assert immediate_predecessors(g, "D") == ("B", "C")
    assert immediate_successors(g, "C") == ("D", "E")


def test_upstream_downstream_closure() -> None:
    g = _graph()
    assert upstream_closure(g, "F") == ("A", "B", "C", "D", "E")
    assert downstream_closure(g, "A") == ("B", "C", "D", "E", "F")
    assert upstream_closure(g, "F", max_depth=1) == ("D", "E")
    assert downstream_closure(g, "A", max_depth=1) == ("B", "C")


def test_reachability_and_no_path() -> None:
    g = _graph()
    assert is_reachable(g, "A", "F") is True
    assert is_reachable(g, "B", "E") is False
    assert shortest_path_between(g, "A", "F") == ("A", "B", "D", "F")
    assert shortest_path_between(g, "B", "E") == ()


def test_all_simple_paths_between_bounds() -> None:
    g = _graph()
    paths = all_simple_paths_between(g, "A", "F")
    assert paths == (
        ("A", "B", "D", "F"),
        ("A", "C", "D", "F"),
        ("A", "C", "E", "F"),
    )
    limited = all_simple_paths_between(g, "A", "F", max_paths=2)
    assert limited == (("A", "B", "D", "F"), ("A", "C", "D", "F"))
    shallow = all_simple_paths_between(g, "A", "F", max_depth=2)
    assert shallow == ()


def test_cycle_safety() -> None:
    g = _cycle_graph()
    assert downstream_closure(g, "1", max_depth=None) == ("1", "2", "3")
    assert upstream_closure(g, "1", max_depth=None) == ("1", "2", "3")
    assert shortest_path_between(g, "1", "3") == ("1", "2", "3")
    assert all_simple_paths_between(g, "1", "3", max_depth=5, max_paths=10) == (("1", "2", "3"),)


def test_shared_ancestors_descendants() -> None:
    g = _graph()
    assert shared_ancestors(g, "D", "E") == ("A", "C")
    assert shared_descendants(g, "B", "C") == ("D", "F")


def test_deterministic_ordering_under_ties() -> None:
    acts = [
        Activity(task_id="Z", successors=["Y", "X"]),
        Activity(task_id="Y", predecessors=["Z"]),
        Activity(task_id="X", predecessors=["Z"]),
    ]
    g = build_schedule_logic_graph(acts)
    assert immediate_successors(g, "Z") == ("X", "Y")
    assert downstream_closure(g, "Z") == ("X", "Y")
    assert all_simple_paths_between(g, "Z", "Y") == (("Z", "Y"),)


def test_driver_structure_output() -> None:
    g = _graph()
    out = explain_driver_structure(g, "C", max_depth=3)
    assert out["task_id"] == "C"
    assert out["immediate_predecessors"] == ("A",)
    assert out["immediate_successors"] == ("D", "E")
    assert out["upstream_count"] == 1
    assert out["downstream_count"] == 3


def test_impact_span_output() -> None:
    g = _graph()
    span = downstream_impact_span(g, "C")
    assert span["task_id"] == "C"
    assert span["downstream_nodes"] == ("D", "E", "F")
    assert span["downstream_node_count"] == 3

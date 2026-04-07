from __future__ import annotations

from controltower.schedule_intake import Activity, build_schedule_logic_graph, build_schedule_graph_summary
from controltower.schedule_intake.graph_summary import (
    reachable_downstream_nodes,
    reachable_upstream_nodes,
    top_nodes_by_in_degree,
    top_nodes_by_out_degree,
)


def test_summary_degrees_and_counts() -> None:
    acts = [
        Activity(task_id="1", successors=["2"]),
        Activity(task_id="2", predecessors=["1"], successors=["3"]),
        Activity(task_id="3", predecessors=["2"]),
    ]
    g = build_schedule_logic_graph(acts)
    s = build_schedule_graph_summary(g)
    assert s.node_count == 3
    assert s.edge_count == 2
    assert s.open_source_node_count == 1
    assert s.open_sink_node_count == 1
    assert s.source_node_ids == ("1",)
    assert s.sink_node_ids == ("3",)
    assert s.directed_cycle_present is False
    assert s.degree_stats.min_in_degree == 0
    assert s.degree_stats.max_in_degree == 1
    assert s.degree_stats.mean_in_degree == 2 / 3
    assert s.degree_stats.zero_inbound_node_count == 1


def test_reachable_bounded_fixture_shape() -> None:
    acts = [
        Activity(task_id="a", successors=["b"]),
        Activity(task_id="b", predecessors=["a"], successors=["c"]),
        Activity(task_id="c", predecessors=["b"]),
    ]
    g = build_schedule_logic_graph(acts)
    up = reachable_upstream_nodes(g, "c", max_depth=1)
    assert up == frozenset({"b", "c"})
    down = reachable_downstream_nodes(g, "a", max_depth=1)
    assert down == frozenset({"a", "b"})


def test_top_nodes_tiebreak() -> None:
    acts = [
        Activity(task_id="z", successors=["m"]),
        Activity(task_id="m", predecessors=["z", "a"]),
        Activity(task_id="a", successors=["m"]),
    ]
    g = build_schedule_logic_graph(acts)
    assert top_nodes_by_out_degree(g, limit=3) == (("a", 1), ("z", 1), ("m", 0))
    assert top_nodes_by_in_degree(g, limit=3) == (("m", 2), ("a", 0), ("z", 0))


def test_unknown_task_raises() -> None:
    g = build_schedule_logic_graph([Activity(task_id="x")])
    try:
        reachable_upstream_nodes(g, "nope")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")

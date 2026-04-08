from __future__ import annotations

from controltower.schedule_intake import Activity, analyze_logic_quality, build_schedule_logic_graph, find_cycle_witness


def test_cycle_witness_two_node() -> None:
    acts = [
        Activity(task_id="1", predecessors=["2"], successors=["2"]),
        Activity(task_id="2", predecessors=["1"], successors=["1"]),
    ]
    g = build_schedule_logic_graph(acts)
    cyc = find_cycle_witness(g)
    assert cyc is not None
    assert set(cyc) == {"1", "2"}
    sig = analyze_logic_quality(g)
    assert sig.cycle_witness is not None


def test_acyclic_chain() -> None:
    acts = [
        Activity(task_id="1", successors=["2"]),
        Activity(task_id="2", predecessors=["1"]),
    ]
    g = build_schedule_logic_graph(acts)
    assert find_cycle_witness(g) is None
    sig = analyze_logic_quality(g)
    assert sig.cycle_witness is None


def test_asymmetric_successor_only() -> None:
    acts = [
        Activity(task_id="A", successors=["B"]),
        Activity(task_id="B", predecessors=None),
    ]
    g = build_schedule_logic_graph(acts)
    sig = analyze_logic_quality(g)
    assert len(sig.asymmetric_relationships) == 1
    ar = sig.asymmetric_relationships[0]
    assert ar.from_task_id == "A" and ar.to_task_id == "B"
    assert ar.missing_on_predecessor_side is True
    assert ar.missing_on_successor_side is False


def test_open_ends_match_graph_degrees() -> None:
    acts = [Activity(task_id="solo")]
    g = build_schedule_logic_graph(acts)
    sig = analyze_logic_quality(g)
    assert sig.open_end_sources == ("solo",)
    assert sig.open_end_sinks == ("solo",)
    assert sig.finish_candidates == ("solo",)
    assert sig.orphan_chains == ()


def test_cycle_witness_is_deterministic_across_ordering() -> None:
    acts_a = [
        Activity(task_id="1", successors=["2"]),
        Activity(task_id="2", predecessors=["1"], successors=["3"]),
        Activity(task_id="3", predecessors=["2"], successors=["1"]),
    ]
    acts_b = list(reversed(acts_a))
    cyc_a = find_cycle_witness(build_schedule_logic_graph(acts_a))
    cyc_b = find_cycle_witness(build_schedule_logic_graph(acts_b))
    assert cyc_a == cyc_b == ("1", "2", "3")

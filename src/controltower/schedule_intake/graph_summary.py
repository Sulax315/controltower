from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .graph import ScheduleLogicGraph
from .logic_quality import find_cycle_witness


@dataclass(frozen=True)
class DegreeDistributionStats:
    """
    Degrees are resolved directed edge counts per `ScheduleLogicGraph`:
    in-degree = len(inbound_edges_by_id[task_id]); out-degree = len(outbound_edges_by_id[task_id]).
    """

    min_in_degree: int
    max_in_degree: int
    mean_in_degree: float
    min_out_degree: int
    max_out_degree: int
    mean_out_degree: float
    zero_inbound_node_count: int
    zero_outbound_node_count: int


@dataclass(frozen=True)
class ScheduleGraphSummary:
    """Deterministic structural metrics over a `ScheduleLogicGraph` (Track 3C)."""

    node_count: int
    edge_count: int
    invalid_reference_count: int
    open_source_node_count: int
    open_sink_node_count: int
    directed_cycle_present: bool
    directed_cycle_witness_length: int
    source_node_ids: tuple[str, ...]
    sink_node_ids: tuple[str, ...]
    degree_stats: DegreeDistributionStats


def count_directed_edges(graph: ScheduleLogicGraph) -> int:
    return sum(len(es) for es in graph.outbound_edges_by_id.values())


def _sorted_predecessors(graph: ScheduleLogicGraph, task_id: str) -> list[str]:
    return sorted({e[0] for e in graph.inbound_edges_by_id.get(task_id, [])})


def _sorted_successors(graph: ScheduleLogicGraph, task_id: str) -> list[str]:
    return sorted({e[1] for e in graph.outbound_edges_by_id.get(task_id, [])})


def list_structural_source_nodes(graph: ScheduleLogicGraph) -> tuple[str, ...]:
    """Nodes with zero inbound resolved edges (open sources / potential schedule starts)."""
    return graph.no_predecessor_nodes


def list_structural_sink_nodes(graph: ScheduleLogicGraph) -> tuple[str, ...]:
    """Nodes with zero outbound resolved edges (open sinks / potential schedule ends)."""
    return graph.no_successor_nodes


def reachable_upstream_nodes(
    graph: ScheduleLogicGraph,
    task_id: str,
    *,
    max_depth: int | None = None,
) -> frozenset[str]:
    """
    Nodes that can reach ``task_id`` via directed edges (predecessor direction), including ``task_id``.

    ``max_depth`` limits the number of *edges* on a path from an upstream node to ``task_id`` (None = unbounded).
    """
    if task_id not in graph.nodes_by_id:
        raise KeyError(f"unknown task_id: {task_id!r}")
    seen: set[str] = set()
    q: deque[tuple[str, int]] = deque([(task_id, 0)])
    while q:
        u, d = q.popleft()
        if u in seen:
            continue
        seen.add(u)
        if max_depth is not None and d >= max_depth:
            continue
        for p in _sorted_predecessors(graph, u):
            if p not in seen:
                q.append((p, d + 1))
    return frozenset(seen)


def reachable_downstream_nodes(
    graph: ScheduleLogicGraph,
    task_id: str,
    *,
    max_depth: int | None = None,
) -> frozenset[str]:
    """
    Nodes reachable from ``task_id`` along outbound edges, including ``task_id``.

    ``max_depth`` is the maximum number of edges from ``task_id`` (None = unbounded).
    """
    if task_id not in graph.nodes_by_id:
        raise KeyError(f"unknown task_id: {task_id!r}")
    seen: set[str] = set()
    q: deque[tuple[str, int]] = deque([(task_id, 0)])
    while q:
        u, d = q.popleft()
        if u in seen:
            continue
        seen.add(u)
        if max_depth is not None and d >= max_depth:
            continue
        for s in _sorted_successors(graph, u):
            if s not in seen:
                q.append((s, d + 1))
    return frozenset(seen)


def _degree_stats(graph: ScheduleLogicGraph) -> DegreeDistributionStats:
    n = len(graph.nodes_by_id)
    if n == 0:
        return DegreeDistributionStats(
            min_in_degree=0,
            max_in_degree=0,
            mean_in_degree=0.0,
            min_out_degree=0,
            max_out_degree=0,
            mean_out_degree=0.0,
            zero_inbound_node_count=0,
            zero_outbound_node_count=0,
        )
    ins = [len(graph.inbound_edges_by_id[tid]) for tid in sorted(graph.nodes_by_id)]
    outs = [len(graph.outbound_edges_by_id[tid]) for tid in sorted(graph.nodes_by_id)]
    zi = sum(1 for x in ins if x == 0)
    zo = sum(1 for x in outs if x == 0)
    return DegreeDistributionStats(
        min_in_degree=min(ins),
        max_in_degree=max(ins),
        mean_in_degree=sum(ins) / n,
        min_out_degree=min(outs),
        max_out_degree=max(outs),
        mean_out_degree=sum(outs) / n,
        zero_inbound_node_count=zi,
        zero_outbound_node_count=zo,
    )


def build_schedule_graph_summary(graph: ScheduleLogicGraph) -> ScheduleGraphSummary:
    """Compute a frozen summary snapshot (deterministic field order and tuple sorting)."""
    witness = find_cycle_witness(graph)
    cyc_len = len(witness) if witness else 0
    ds = _degree_stats(graph)
    return ScheduleGraphSummary(
        node_count=len(graph.nodes_by_id),
        edge_count=count_directed_edges(graph),
        invalid_reference_count=len(graph.invalid_references),
        open_source_node_count=len(graph.no_predecessor_nodes),
        open_sink_node_count=len(graph.no_successor_nodes),
        directed_cycle_present=witness is not None,
        directed_cycle_witness_length=cyc_len,
        source_node_ids=graph.no_predecessor_nodes,
        sink_node_ids=graph.no_successor_nodes,
        degree_stats=ds,
    )


def top_nodes_by_out_degree(
    graph: ScheduleLogicGraph,
    *,
    limit: int = 5,
) -> tuple[tuple[str, int], ...]:
    """Stable tie-break: higher out-degree first, then task_id lexicographically."""
    scored = [(tid, len(graph.outbound_edges_by_id[tid])) for tid in sorted(graph.nodes_by_id)]
    scored.sort(key=lambda x: (-x[1], x[0]))
    return tuple(scored[:limit])


def top_nodes_by_in_degree(
    graph: ScheduleLogicGraph,
    *,
    limit: int = 5,
) -> tuple[tuple[str, int], ...]:
    scored = [(tid, len(graph.inbound_edges_by_id[tid])) for tid in sorted(graph.nodes_by_id)]
    scored.sort(key=lambda x: (-x[1], x[0]))
    return tuple(scored[:limit])

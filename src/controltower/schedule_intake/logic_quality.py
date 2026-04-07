from __future__ import annotations

from dataclasses import dataclass

from .graph import InvalidReference, ScheduleLogicGraph

Edge = tuple[str, str]


@dataclass(frozen=True)
class AsymmetricRelationship:
    """
    A resolved edge (from_id -> to_id) where only one side lists the other in CSV fields.

    Example: A lists successor B, but B does not list A as predecessor.
    """

    from_task_id: str
    to_task_id: str
    missing_on_predecessor_side: bool  # True if to_id lacks from_id in predecessors
    missing_on_successor_side: bool  # True if from_id lacks to_id in successors


def _edge_set(graph: ScheduleLogicGraph) -> set[Edge]:
    return {e for es in graph.outbound_edges_by_id.values() for e in es}


def find_asymmetric_relationships(graph: ScheduleLogicGraph) -> tuple[AsymmetricRelationship, ...]:
    """
    For each graph edge, check predecessor/successor columns on both endpoints.

    An edge is asymmetric if at least one of the reciprocal list entries is missing.
    """
    out: list[AsymmetricRelationship] = []
    for f, t in sorted(_edge_set(graph)):
        pred_a = graph.nodes_by_id[t].predecessors
        succ_a = graph.nodes_by_id[f].successors
        has_pred = f in (pred_a or [])
        has_succ = t in (succ_a or [])
        if has_pred and has_succ:
            continue
        out.append(
            AsymmetricRelationship(
                from_task_id=f,
                to_task_id=t,
                missing_on_predecessor_side=not has_pred,
                missing_on_successor_side=not has_succ,
            )
        )
    return tuple(out)


def find_cycle_witness(graph: ScheduleLogicGraph) -> tuple[str, ...] | None:
    """
    If the graph contains a directed cycle, return one simple cycle as an ordered tuple of task_ids.

    Deterministic: nodes processed in sorted order; adjacency lists sorted.
    """
    nodes = sorted(graph.nodes_by_id)
    adj: dict[str, list[str]] = {
        u: sorted(t for _, t in graph.outbound_edges_by_id.get(u, [])) for u in graph.nodes_by_id
    }

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {u: WHITE for u in nodes}
    path: list[str] = []

    def dfs(u: str) -> tuple[str, ...] | None:
        color[u] = GRAY
        path.append(u)
        for v in adj[u]:
            if color[v] == GRAY:
                try:
                    i = path.index(v)
                except ValueError:
                    continue
                seg = path[i:]
                if len(seg) == 1:
                    return (seg[0], seg[0])
                return tuple(seg)
            if color[v] == WHITE:
                cyc = dfs(v)
                if cyc is not None:
                    return cyc
        path.pop()
        color[u] = BLACK
        return None

    for start in nodes:
        if color[start] == WHITE:
            cyc = dfs(start)
            if cyc is not None:
                return cyc
    return None


@dataclass
class LogicQualitySignals:
    """Track 3B — schedule logic quality over a built graph."""

    # Open ends: no inbound / no outbound (CPM-style boundary or dangling logic)
    open_end_sources: tuple[str, ...]
    open_end_sinks: tuple[str, ...]
    # Same as graph.invalid_references; surfaced for "invalid relationship conditions"
    invalid_references: tuple[InvalidReference, ...]
    asymmetric_relationships: tuple[AsymmetricRelationship, ...]
    cycle_witness: tuple[str, ...] | None


def analyze_logic_quality(graph: ScheduleLogicGraph) -> LogicQualitySignals:
    """
    Derive logic-quality signals from a ScheduleLogicGraph.

    Open-end policy: use structural in-degree / out-degree (resolved edges only).
    """
    asym = find_asymmetric_relationships(graph)
    cyc = find_cycle_witness(graph)
    return LogicQualitySignals(
        open_end_sources=graph.no_predecessor_nodes,
        open_end_sinks=graph.no_successor_nodes,
        invalid_references=tuple(graph.invalid_references),
        asymmetric_relationships=asym,
        cycle_witness=cyc,
    )

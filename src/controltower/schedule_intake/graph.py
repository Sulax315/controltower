from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from typing import Literal

from .models import Activity

Edge = tuple[str, str]  # (from_task_id, to_task_id) — logic flow from predecessor to successor


@dataclass(frozen=True)
class InvalidReference:
    """A predecessor/successor token that does not resolve to a parsed activity task_id."""

    referencing_task_id: str
    role: Literal["predecessor", "successor"]
    referenced_task_id: str


@dataclass
class ScheduleLogicGraph:
    """
    Directed schedule logic graph: edge (A, B) means B depends on A (A precedes B).

    Built from Activity.predecessors and Activity.successors; duplicate implied edges are deduped.
    """

    nodes_by_id: dict[str, Activity]
    inbound_edges_by_id: dict[str, list[Edge]] = field(default_factory=dict)
    outbound_edges_by_id: dict[str, list[Edge]] = field(default_factory=dict)
    invalid_references: list[InvalidReference] = field(default_factory=list)
    no_predecessor_nodes: tuple[str, ...] = ()
    no_successor_nodes: tuple[str, ...] = ()


@dataclass(frozen=True)
class StructuralFinishCandidate:
    """Structural-only terminal node candidate; no driver semantics."""

    task_id: str
    in_degree: int
    out_degree: int
    has_predecessor: bool


def build_schedule_logic_graph(activities: list[Activity]) -> ScheduleLogicGraph:
    """
    Construct a deterministic graph from parsed activities.

    - Each activity is a node keyed by task_id.
    - For activity B with predecessor P, add edge (P, B).
    - For activity A with successor S, add edge (A, S).
    - Missing referenced task_ids are recorded in invalid_references (not silently dropped).
    """
    nodes_by_id = {a.task_id: a for a in activities}
    known = frozenset(nodes_by_id)
    unique_to_task_ids: dict[str, set[str]] = {}
    for act in activities:
        if act.unique_task_id is None:
            continue
        unique_to_task_ids.setdefault(act.unique_task_id, set()).add(act.task_id)

    def _resolve_reference_token(token: str) -> str | None:
        # Primary resolution is Task ID, with deterministic Unique task ID fallback.
        if token in known:
            return token
        matched_task_ids = unique_to_task_ids.get(token)
        if not matched_task_ids or len(matched_task_ids) != 1:
            return None
        return next(iter(matched_task_ids))
    edge_set: set[Edge] = set()
    invalid: list[InvalidReference] = []

    for act in activities:
        tid = act.task_id
        for ref in act.predecessors or []:
            resolved = _resolve_reference_token(ref)
            if resolved is not None:
                edge_set.add((resolved, tid))
            else:
                invalid.append(
                    InvalidReference(
                        referencing_task_id=tid,
                        role="predecessor",
                        referenced_task_id=ref,
                    )
                )
        for ref in act.successors or []:
            resolved = _resolve_reference_token(ref)
            if resolved is not None:
                edge_set.add((tid, resolved))
            else:
                invalid.append(
                    InvalidReference(
                        referencing_task_id=tid,
                        role="successor",
                        referenced_task_id=ref,
                    )
                )

    inbound: dict[str, list[Edge]] = {nid: [] for nid in nodes_by_id}
    outbound: dict[str, list[Edge]] = {nid: [] for nid in nodes_by_id}
    for f, t in sorted(edge_set):
        inbound[t].append((f, t))
        outbound[f].append((f, t))

    no_pred = tuple(sorted(nid for nid, es in inbound.items() if not es))
    no_succ = tuple(sorted(nid for nid, es in outbound.items() if not es))

    invalid.sort(key=lambda r: (r.referencing_task_id, r.role, r.referenced_task_id))

    return ScheduleLogicGraph(
        nodes_by_id=nodes_by_id,
        inbound_edges_by_id=inbound,
        outbound_edges_by_id=outbound,
        invalid_references=invalid,
        no_predecessor_nodes=no_pred,
        no_successor_nodes=no_succ,
    )


def list_finish_candidates(graph: ScheduleLogicGraph) -> tuple[StructuralFinishCandidate, ...]:
    """
    Structural finish candidates = nodes with zero outbound resolved edges.

    Deterministic ordering: task_id lexicographic.
    """
    out: list[StructuralFinishCandidate] = []
    for task_id in graph.no_successor_nodes:
        in_degree = len(graph.inbound_edges_by_id.get(task_id, []))
        out.append(
            StructuralFinishCandidate(
                task_id=task_id,
                in_degree=in_degree,
                out_degree=0,
                has_predecessor=in_degree > 0,
            )
        )
    return tuple(out)


def find_orphan_chains(graph: ScheduleLogicGraph) -> tuple[tuple[str, ...], ...]:
    """
    Structural orphan chains/components disconnected from the primary project network.

    Primary network is the weakly connected component containing the primary finish
    candidate (first by task_id). If no finish exists, primary network is the largest
    component (tie-break by smallest task_id). Returned orphan components are sorted
    deterministically by first node id.
    """
    if not graph.nodes_by_id:
        return ()

    undirected: dict[str, set[str]] = {tid: set() for tid in graph.nodes_by_id}
    for from_id, to_id in sorted(
        (e for edges in graph.outbound_edges_by_id.values() for e in edges),
    ):
        undirected[from_id].add(to_id)
        undirected[to_id].add(from_id)

    components: list[tuple[str, ...]] = []
    seen: set[str] = set()
    for start in sorted(graph.nodes_by_id):
        if start in seen:
            continue
        stack = [start]
        comp: set[str] = set()
        while stack:
            node = stack.pop()
            if node in comp:
                continue
            comp.add(node)
            for nxt in sorted(undirected[node], reverse=True):
                if nxt not in comp:
                    stack.append(nxt)
        seen.update(comp)
        components.append(tuple(sorted(comp)))

    if len(components) <= 1:
        return ()

    primary_finish_id = list_finish_candidates(graph)[0].task_id if graph.no_successor_nodes else None
    primary_component: tuple[str, ...] | None = None
    if primary_finish_id is not None:
        for comp in components:
            if primary_finish_id in comp:
                primary_component = comp
                break
    if primary_component is None:
        primary_component = sorted(components, key=lambda c: (-len(c), c[0]))[0]

    return tuple(sorted((c for c in components if c != primary_component), key=lambda c: c[0]))


LOGIC_GRAPH_SCHEMA_VERSION = "schedule_logic_graph_v1"


def build_logic_graph_payload(graph: ScheduleLogicGraph) -> dict[str, Any]:
    """
    Deterministic machine-readable graph payload for Phase 15 export.
    """
    edges = sorted((e for es in graph.outbound_edges_by_id.values() for e in es))
    invalid_refs = sorted(
        graph.invalid_references,
        key=lambda r: (r.referencing_task_id, r.role, r.referenced_task_id),
    )
    finish_candidates = list_finish_candidates(graph)
    orphan_chains = find_orphan_chains(graph)
    return {
        "schema_version": LOGIC_GRAPH_SCHEMA_VERSION,
        "node_count": len(graph.nodes_by_id),
        "edge_count": len(edges),
        "nodes": sorted(graph.nodes_by_id),
        "edges": [{"from_task_id": f, "to_task_id": t} for f, t in edges],
        "invalid_references": [
            {
                "referencing_task_id": r.referencing_task_id,
                "role": r.role,
                "referenced_task_id": r.referenced_task_id,
            }
            for r in invalid_refs
        ],
        "open_end_sources": list(graph.no_predecessor_nodes),
        "open_end_sinks": list(graph.no_successor_nodes),
        "finish_candidates": [
            {
                "task_id": c.task_id,
                "in_degree": c.in_degree,
                "out_degree": c.out_degree,
                "has_predecessor": c.has_predecessor,
            }
            for c in finish_candidates
        ],
        "orphan_chains": [list(chain) for chain in orphan_chains],
    }

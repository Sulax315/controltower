from __future__ import annotations

from dataclasses import dataclass, field
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
    edge_set: set[Edge] = set()
    invalid: list[InvalidReference] = []

    for act in activities:
        tid = act.task_id
        for ref in act.predecessors or []:
            if ref in known:
                edge_set.add((ref, tid))
            else:
                invalid.append(
                    InvalidReference(
                        referencing_task_id=tid,
                        role="predecessor",
                        referenced_task_id=ref,
                    )
                )
        for ref in act.successors or []:
            if ref in known:
                edge_set.add((tid, ref))
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

"""
Track 4A — deterministic schedule driver scoring.

Scoring is a transparent sum of named components. Each component is documented below
and mirrored in ``score_components`` on ``DriverCandidate`` so downstream code never
depends on an opaque scalar.

Composite (``driver_score``)::

    driver_score = sum(score_components.values())

Components (all >= 0; missing activity fields use explicit neutral substitutes):

1. ``float_pressure``
   - Interprets ``Activity.total_float_days`` when present: lower (or more negative)
     float increases pressure. ``driver_score`` contribution is::

         max(0.0, min(16.0, 16.0 - 0.4 * total_float_days))

     Capped so extreme positive float does not yield negative contribution.
   - If ``total_float_days`` is *None* (unknown): contributes ``4.0`` (mild default).

2. ``critical_flag``
   - ``10.0`` if ``Activity.critical is True``, else ``0.0``.
   - If ``critical`` is *None* (unknown): ``0.0``.

3. ``downstream_reach``
   - Let R = ``|reachable_downstream_nodes(graph, task_id)| - 1`` (exclude self).
   - ``min(12.0, 2.0 * max(0, R))`` — rewards tasks that structurally cover more
     downstream scope (fan-out / chain length proxy), capped.

4. ``outbound_fan``
   - ``min(8.0, 2.0 * outbound_degree)`` using resolved graph out-degree.

5. ``inbound_fan``
   - ``min(5.0, 1.0 * inbound_degree)`` — merge / convergence proxy, capped.

6. ``sink_proximity``
   - Shortest hop count (edges) from ``task_id`` to any *structural* sink node
     (``ScheduleLogicGraph.no_successor_nodes``), forward along outbound edges.
   - ``0`` hops if the task is already a sink.
   - Contribution ``max(0.0, 12.0 - 2.0 * hops)``; if no sink is reachable in the
     forward subgraph, contribution ``0.0``.

Tie-breaking for ranking: sort by ``(-driver_score, task_id)`` (lexicographic id).
"""

from __future__ import annotations

from collections import deque

from pydantic import BaseModel, ConfigDict, Field

from .graph import ScheduleLogicGraph
from .graph_summary import reachable_downstream_nodes


class DriverCandidate(BaseModel):
    """One ranked driver candidate with explicit factor breakdown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    task_name: str | None
    driver_score: float
    score_components: dict[str, float] = Field(description="Named partial scores; sum == driver_score")
    rationale_signals: list[str] = Field(description="Short factual tokens traceable to inputs")
    critical: bool | None
    total_float_days: float | None
    downstream_reach_count: int
    outbound_degree: int
    inbound_degree: int
    hops_to_structural_sink: int | None


def _shortest_hops_to_structural_sink(graph: ScheduleLogicGraph, task_id: str) -> int | None:
    """Minimum number of forward edges to reach any node in ``no_successor_nodes``."""
    sinks = frozenset(graph.no_successor_nodes)
    if task_id in sinks:
        return 0
    q: deque[tuple[str, int]] = deque([(task_id, 0)])
    seen: set[str] = {task_id}
    while q:
        u, d = q.popleft()
        succs = sorted({e[1] for e in graph.outbound_edges_by_id.get(u, [])})
        for v in succs:
            if v in sinks:
                return d + 1
            if v not in seen:
                seen.add(v)
                q.append((v, d + 1))
    return None


def _float_pressure_component(total_float_days: float | None) -> float:
    if total_float_days is None:
        return 4.0
    raw = 16.0 - 0.4 * total_float_days
    return max(0.0, min(16.0, raw))


def _score_one(graph: ScheduleLogicGraph, task_id: str) -> DriverCandidate:
    act = graph.nodes_by_id[task_id]
    out_deg = len(graph.outbound_edges_by_id.get(task_id, []))
    in_deg = len(graph.inbound_edges_by_id.get(task_id, []))
    down = reachable_downstream_nodes(graph, task_id, max_depth=None)
    reach_excl_self = max(0, len(down) - 1)
    hops = _shortest_hops_to_structural_sink(graph, task_id)

    c_float = _float_pressure_component(act.total_float_days)
    c_crit = 10.0 if act.critical is True else 0.0
    c_down = min(12.0, 2.0 * reach_excl_self)
    c_out = min(8.0, 2.0 * out_deg)
    c_in = min(5.0, 1.0 * in_deg)
    if hops is None:
        c_sink = 0.0
    else:
        c_sink = max(0.0, 12.0 - 2.0 * hops)

    components = {
        "float_pressure": round(c_float, 6),
        "critical_flag": round(c_crit, 6),
        "downstream_reach": round(c_down, 6),
        "outbound_fan": round(c_out, 6),
        "inbound_fan": round(c_in, 6),
        "sink_proximity": round(c_sink, 6),
    }
    total = round(sum(components.values()), 6)

    signals: list[str] = [
        f"total_float_days={act.total_float_days!r}",
        f"critical={act.critical!r}",
        f"downstream_reach_count={reach_excl_self}",
        f"outbound_degree={out_deg}",
        f"inbound_degree={in_deg}",
        f"hops_to_structural_sink={hops!r}",
    ]

    return DriverCandidate(
        task_id=task_id,
        task_name=act.task_name,
        driver_score=total,
        score_components=components,
        rationale_signals=signals,
        critical=act.critical,
        total_float_days=act.total_float_days,
        downstream_reach_count=reach_excl_self,
        outbound_degree=out_deg,
        inbound_degree=in_deg,
        hops_to_structural_sink=hops,
    )


def rank_driver_candidates(
    graph: ScheduleLogicGraph,
    *,
    limit: int | None = None,
) -> tuple[DriverCandidate, ...]:
    """
    Return driver candidates sorted by descending ``driver_score``, then ``task_id``.

    If ``limit`` is set, only the first *limit* rows are returned (still fully scored).
    """
    scored = [_score_one(graph, tid) for tid in sorted(graph.nodes_by_id)]
    scored.sort(key=lambda c: (-c.driver_score, c.task_id))
    if limit is not None:
        scored = scored[: max(0, limit)]
    return tuple(scored)

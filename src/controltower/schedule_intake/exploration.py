from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .graph import ScheduleLogicGraph


@dataclass(frozen=True)
class ReachabilityResult:
    source_task_id: str
    target_task_id: str
    reachable: bool


@dataclass(frozen=True)
class PathQueryResult:
    source_task_id: str
    target_task_id: str
    path_exists: bool
    shortest_path: tuple[str, ...]
    all_paths: tuple[tuple[str, ...], ...]


def _ensure_known(graph: ScheduleLogicGraph, task_id: str) -> None:
    if task_id not in graph.nodes_by_id:
        raise KeyError(f"unknown task_id: {task_id!r}")


def immediate_predecessors(graph: ScheduleLogicGraph, task_id: str) -> tuple[str, ...]:
    _ensure_known(graph, task_id)
    return tuple(sorted({a for a, _ in graph.inbound_edges_by_id.get(task_id, [])}))


def immediate_successors(graph: ScheduleLogicGraph, task_id: str) -> tuple[str, ...]:
    _ensure_known(graph, task_id)
    return tuple(sorted({b for _, b in graph.outbound_edges_by_id.get(task_id, [])}))


def upstream_closure(graph: ScheduleLogicGraph, task_id: str, max_depth: int | None = None) -> tuple[str, ...]:
    _ensure_known(graph, task_id)
    if max_depth is not None and max_depth < 0:
        return ()
    seen: set[str] = set()
    q: deque[tuple[str, int]] = deque((p, 1) for p in immediate_predecessors(graph, task_id))
    while q:
        cur, depth = q.popleft()
        if cur in seen:
            continue
        seen.add(cur)
        if max_depth is not None and depth >= max_depth:
            continue
        for nxt in immediate_predecessors(graph, cur):
            if nxt not in seen:
                q.append((nxt, depth + 1))
    return tuple(sorted(seen))


def downstream_closure(graph: ScheduleLogicGraph, task_id: str, max_depth: int | None = None) -> tuple[str, ...]:
    _ensure_known(graph, task_id)
    if max_depth is not None and max_depth < 0:
        return ()
    seen: set[str] = set()
    q: deque[tuple[str, int]] = deque((s, 1) for s in immediate_successors(graph, task_id))
    while q:
        cur, depth = q.popleft()
        if cur in seen:
            continue
        seen.add(cur)
        if max_depth is not None and depth >= max_depth:
            continue
        for nxt in immediate_successors(graph, cur):
            if nxt not in seen:
                q.append((nxt, depth + 1))
    return tuple(sorted(seen))


def is_reachable(graph: ScheduleLogicGraph, source_task_id: str, target_task_id: str) -> bool:
    _ensure_known(graph, source_task_id)
    _ensure_known(graph, target_task_id)
    if source_task_id == target_task_id:
        return True
    q: deque[str] = deque([source_task_id])
    seen: set[str] = {source_task_id}
    while q:
        cur = q.popleft()
        for nxt in immediate_successors(graph, cur):
            if nxt == target_task_id:
                return True
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return False


def shortest_path_between(graph: ScheduleLogicGraph, source_task_id: str, target_task_id: str) -> tuple[str, ...]:
    _ensure_known(graph, source_task_id)
    _ensure_known(graph, target_task_id)
    if source_task_id == target_task_id:
        return (source_task_id,)
    q: deque[tuple[str, tuple[str, ...]]] = deque([(source_task_id, (source_task_id,))])
    seen: set[str] = {source_task_id}
    while q:
        cur, path = q.popleft()
        for nxt in immediate_successors(graph, cur):
            if nxt in seen:
                continue
            np = path + (nxt,)
            if nxt == target_task_id:
                return np
            seen.add(nxt)
            q.append((nxt, np))
    return ()


def all_simple_paths_between(
    graph: ScheduleLogicGraph,
    source_task_id: str,
    target_task_id: str,
    max_depth: int = 12,
    max_paths: int = 25,
) -> tuple[tuple[str, ...], ...]:
    _ensure_known(graph, source_task_id)
    _ensure_known(graph, target_task_id)
    if max_depth < 0 or max_paths <= 0:
        return ()
    if source_task_id == target_task_id:
        return ((source_task_id,),)
    out: list[tuple[str, ...]] = []
    stack: list[tuple[str, tuple[str, ...], frozenset[str]]] = [
        (source_task_id, (source_task_id,), frozenset({source_task_id}))
    ]
    while stack and len(out) < max_paths:
        cur, path, visited = stack.pop()
        if len(path) - 1 >= max_depth:
            continue
        neighbors = immediate_successors(graph, cur)
        for nxt in reversed(neighbors):
            if nxt in visited:
                continue
            np = path + (nxt,)
            if nxt == target_task_id:
                out.append(np)
                if len(out) >= max_paths:
                    break
                continue
            stack.append((nxt, np, visited | {nxt}))
    out.sort()
    return tuple(out)


def shared_ancestors(graph: ScheduleLogicGraph, left_task_id: str, right_task_id: str) -> tuple[str, ...]:
    _ensure_known(graph, left_task_id)
    _ensure_known(graph, right_task_id)
    l = frozenset(upstream_closure(graph, left_task_id))
    r = frozenset(upstream_closure(graph, right_task_id))
    return tuple(sorted(l & r))


def shared_descendants(graph: ScheduleLogicGraph, left_task_id: str, right_task_id: str) -> tuple[str, ...]:
    _ensure_known(graph, left_task_id)
    _ensure_known(graph, right_task_id)
    l = frozenset(downstream_closure(graph, left_task_id))
    r = frozenset(downstream_closure(graph, right_task_id))
    return tuple(sorted(l & r))


def explain_driver_structure(graph: ScheduleLogicGraph, task_id: str, max_depth: int = 8) -> dict[str, object]:
    _ensure_known(graph, task_id)
    up = upstream_closure(graph, task_id, max_depth=max_depth)
    down = downstream_closure(graph, task_id, max_depth=max_depth)
    return {
        "task_id": task_id,
        "immediate_predecessors": immediate_predecessors(graph, task_id),
        "immediate_successors": immediate_successors(graph, task_id),
        "upstream_closure": up,
        "downstream_closure": down,
        "upstream_count": len(up),
        "downstream_count": len(down),
        "max_depth": max_depth,
    }


def downstream_impact_span(graph: ScheduleLogicGraph, task_id: str, max_depth: int | None = None) -> dict[str, object]:
    _ensure_known(graph, task_id)
    closure = downstream_closure(graph, task_id, max_depth=max_depth)
    return {
        "task_id": task_id,
        "downstream_nodes": closure,
        "downstream_node_count": len(closure),
        "max_depth": max_depth,
    }

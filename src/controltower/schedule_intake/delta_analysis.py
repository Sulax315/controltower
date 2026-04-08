"""
Track 4C — deterministic comparison of two parsed Asta activity lists (baseline vs current).

Alignment is **only** by ``task_id`` (no fuzzy matching). All collections are sorted for
stable ordering. Values are compared as normalized string forms suitable for diffing and
downstream narrative generation (which is **out of scope** for this module).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .asta_csv import parse_asta_export_csv
from .drivers import rank_driver_candidates
from .graph import build_schedule_logic_graph
from .models import Activity

Edge = tuple[str, str]


def _norm_tokens(xs: list[str] | None) -> tuple[str, ...]:
    return tuple(sorted(xs or []))


def _dt_str(v: datetime | None) -> str:
    if v is None:
        return "None"
    return v.replace(tzinfo=None).isoformat(timespec="seconds")


def _scalar_str(v: object | None) -> str:
    if v is None:
        return "None"
    return str(v)


class TaskFieldChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    field_name: str
    old_value: str
    new_value: str


class TokenSetDelta(BaseModel):
    """Predecessor or successor token set change for a task present in both exports."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    role: Literal["predecessors", "successors"]
    tokens_removed: tuple[str, ...]
    tokens_added: tuple[str, ...]


class DriverRankDelta(BaseModel):
    """Rank/score change for a task present in both graphs (1-based rank, higher score = stronger driver)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    baseline_rank: int
    current_rank: int
    rank_delta: int  # current_rank - baseline_rank (positive => worse / later in sorted driver list)
    baseline_driver_score: float
    current_driver_score: float


class SummaryCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    added_tasks: int
    removed_tasks: int
    changed_start_dates: int
    changed_finish_dates: int
    changed_durations: int
    changed_total_float_days: int
    changed_free_float_days: int
    changed_critical: int
    predecessor_set_changes: int
    successor_set_changes: int
    logic_edges_added: int
    logic_edges_removed: int
    driver_rank_changes: int


class ScheduleDeltaResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_task_count: int
    current_task_count: int
    added_task_ids: tuple[str, ...]
    removed_task_ids: tuple[str, ...]
    changed_start_dates: tuple[TaskFieldChange, ...]
    changed_finish_dates: tuple[TaskFieldChange, ...]
    changed_durations: tuple[TaskFieldChange, ...]
    changed_total_float_days: tuple[TaskFieldChange, ...]
    changed_free_float_days: tuple[TaskFieldChange, ...]
    changed_critical: tuple[TaskFieldChange, ...]
    changed_predecessors: tuple[TokenSetDelta, ...]
    changed_successors: tuple[TokenSetDelta, ...]
    logic_edges_added: tuple[Edge, ...]
    logic_edges_removed: tuple[Edge, ...]
    driver_rank_deltas: tuple[DriverRankDelta, ...]
    summary_counts: SummaryCounts


def _edge_set(activities: list[Activity]) -> frozenset[Edge]:
    g = build_schedule_logic_graph(activities)
    return frozenset(e for es in g.outbound_edges_by_id.values() for e in es)


def _driver_rank_score_maps(activities: list[Activity]) -> tuple[dict[str, int], dict[str, float]]:
    g = build_schedule_logic_graph(activities)
    ranked = rank_driver_candidates(g, limit=None)
    rank = {c.task_id: i + 1 for i, c in enumerate(ranked)}
    score = {c.task_id: c.driver_score for c in ranked}
    return rank, score


def compare_schedule_csv_paths(
    baseline_csv: Path | str,
    current_csv: Path | str,
    *,
    include_driver_rank_deltas: bool = True,
) -> ScheduleDeltaResult:
    """Parse two exports then diff (UTF-8-sig as in ``parse_asta_export_csv``)."""
    b = parse_asta_export_csv(Path(baseline_csv)).activities
    c = parse_asta_export_csv(Path(current_csv)).activities
    return compare_schedule_exports(b, c, include_driver_rank_deltas=include_driver_rank_deltas)


def compare_schedule_exports(
    baseline_activities: list[Activity],
    current_activities: list[Activity],
    *,
    include_driver_rank_deltas: bool = True,
) -> ScheduleDeltaResult:
    """
    Compare baseline vs current activities (already parsed).

    Driver rank deltas are emitted only for ``task_id`` values present in **both** exports,
    and only when rank **or** driver score differs between runs.
    """
    b_map = {a.task_id: a for a in baseline_activities}
    c_map = {a.task_id: a for a in current_activities}
    b_ids = frozenset(b_map)
    c_ids = frozenset(c_map)

    added = tuple(sorted(c_ids - b_ids))
    removed = tuple(sorted(b_ids - c_ids))
    common = sorted(b_ids & c_ids)

    ch_start: list[TaskFieldChange] = []
    ch_finish: list[TaskFieldChange] = []
    ch_dur: list[TaskFieldChange] = []
    ch_tf: list[TaskFieldChange] = []
    ch_ff: list[TaskFieldChange] = []
    ch_crit: list[TaskFieldChange] = []
    ch_pred: list[TokenSetDelta] = []
    ch_succ: list[TokenSetDelta] = []

    for tid in common:
        b = b_map[tid]
        c = c_map[tid]

        os, ns = _dt_str(b.start), _dt_str(c.start)
        if os != ns:
            ch_start.append(TaskFieldChange(task_id=tid, field_name="start", old_value=os, new_value=ns))

        of, nf = _dt_str(b.finish), _dt_str(c.finish)
        if of != nf:
            ch_finish.append(TaskFieldChange(task_id=tid, field_name="finish", old_value=of, new_value=nf))

        od, nd = _scalar_str(b.duration_days), _scalar_str(c.duration_days)
        if od != nd:
            ch_dur.append(TaskFieldChange(task_id=tid, field_name="duration_days", old_value=od, new_value=nd))

        otf, ntf = _scalar_str(b.total_float_days), _scalar_str(c.total_float_days)
        if otf != ntf:
            ch_tf.append(TaskFieldChange(task_id=tid, field_name="total_float_days", old_value=otf, new_value=ntf))

        off, nff = _scalar_str(b.free_float_days), _scalar_str(c.free_float_days)
        if off != nff:
            ch_ff.append(TaskFieldChange(task_id=tid, field_name="free_float_days", old_value=off, new_value=nff))

        oc, nc = _scalar_str(b.critical), _scalar_str(c.critical)
        if oc != nc:
            ch_crit.append(TaskFieldChange(task_id=tid, field_name="critical", old_value=oc, new_value=nc))

        bp, cp = _norm_tokens(b.predecessors), _norm_tokens(c.predecessors)
        if bp != cp:
            rem = tuple(sorted(frozenset(bp) - frozenset(cp)))
            add = tuple(sorted(frozenset(cp) - frozenset(bp)))
            ch_pred.append(
                TokenSetDelta(task_id=tid, role="predecessors", tokens_removed=rem, tokens_added=add)
            )

        bs, cs_succ = _norm_tokens(b.successors), _norm_tokens(c.successors)
        if bs != cs_succ:
            rem = tuple(sorted(frozenset(bs) - frozenset(cs_succ)))
            add = tuple(sorted(frozenset(cs_succ) - frozenset(bs)))
            ch_succ.append(
                TokenSetDelta(task_id=tid, role="successors", tokens_removed=rem, tokens_added=add)
            )

    eb = _edge_set(baseline_activities)
    ec = _edge_set(current_activities)
    edges_added = tuple(sorted(ec - eb))
    edges_removed = tuple(sorted(eb - ec))

    drv: list[DriverRankDelta] = []
    if include_driver_rank_deltas and common:
        b_rank, b_score = _driver_rank_score_maps(baseline_activities)
        c_rank, c_score = _driver_rank_score_maps(current_activities)
        for tid in common:
            if tid not in b_rank or tid not in c_rank:
                continue
            b_r, c_r = b_rank[tid], c_rank[tid]
            b_s, c_s = b_score[tid], c_score[tid]
            if b_r == c_r and b_s == c_s:
                continue
            drv.append(
                DriverRankDelta(
                    task_id=tid,
                    baseline_rank=b_r,
                    current_rank=c_r,
                    rank_delta=c_r - b_r,
                    baseline_driver_score=b_s,
                    current_driver_score=c_s,
                )
            )
        drv.sort(key=lambda d: d.task_id)

    counts = SummaryCounts(
        added_tasks=len(added),
        removed_tasks=len(removed),
        changed_start_dates=len(ch_start),
        changed_finish_dates=len(ch_finish),
        changed_durations=len(ch_dur),
        changed_total_float_days=len(ch_tf),
        changed_free_float_days=len(ch_ff),
        changed_critical=len(ch_crit),
        predecessor_set_changes=len(ch_pred),
        successor_set_changes=len(ch_succ),
        logic_edges_added=len(edges_added),
        logic_edges_removed=len(edges_removed),
        driver_rank_changes=len(drv),
    )

    return ScheduleDeltaResult(
        baseline_task_count=len(b_map),
        current_task_count=len(c_map),
        added_task_ids=added,
        removed_task_ids=removed,
        changed_start_dates=tuple(sorted(ch_start, key=lambda x: (x.task_id, x.field_name))),
        changed_finish_dates=tuple(sorted(ch_finish, key=lambda x: (x.task_id, x.field_name))),
        changed_durations=tuple(sorted(ch_dur, key=lambda x: (x.task_id, x.field_name))),
        changed_total_float_days=tuple(sorted(ch_tf, key=lambda x: (x.task_id, x.field_name))),
        changed_free_float_days=tuple(sorted(ch_ff, key=lambda x: (x.task_id, x.field_name))),
        changed_critical=tuple(sorted(ch_crit, key=lambda x: (x.task_id, x.field_name))),
        changed_predecessors=tuple(sorted(ch_pred, key=lambda x: x.task_id)),
        changed_successors=tuple(sorted(ch_succ, key=lambda x: x.task_id)),
        logic_edges_added=edges_added,
        logic_edges_removed=edges_removed,
        driver_rank_deltas=tuple(drv),
        summary_counts=counts,
    )

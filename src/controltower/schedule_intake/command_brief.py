"""
Track 5A — deterministic five-line command brief from existing engine outputs only.

Contract types (aliases): ``GraphSummary``, ``DriverFinding``, ``DeltaSummary`` map to
``ScheduleGraphSummary``, ``DriverCandidate``, and ``SummaryCounts`` respectively.
Callers should pass ``risks`` in the same order as ``collect_schedule_risk_findings``
(highest ``sort_score`` first).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from .delta_analysis import SummaryCounts
from .drivers import DriverCandidate
from .graph_summary import ScheduleGraphSummary
from .risks import RiskFinding

GraphSummary: TypeAlias = ScheduleGraphSummary
DriverFinding: TypeAlias = DriverCandidate
DeltaSummary: TypeAlias = SummaryCounts


@dataclass(frozen=True)
class CommandBrief:
    """Exactly five lines: FINISH, DRIVER, RISKS, DELTA, ACTION (each includes its label prefix)."""

    finish: str
    driver: str
    risks: str
    delta: str
    action: str

    def as_lines(self) -> tuple[str, str, str, str, str]:
        return (self.finish, self.driver, self.risks, self.delta, self.action)


def _fmt_finish(gs: GraphSummary) -> str:
    return (
        f"FINISH: nodes={gs.node_count} edges={gs.edge_count} "
        f"open_sink={gs.open_sink_node_count} open_source={gs.open_source_node_count} "
        f"cycle={gs.directed_cycle_present} invref={gs.invalid_reference_count}"
    )


def _fmt_driver(d: DriverFinding | None) -> str:
    if d is None:
        return "DRIVER: none"
    return f"DRIVER: task_id={d.task_id} score={d.driver_score:.4f}"


def _fmt_risks(risks: tuple[RiskFinding, ...]) -> str:
    n = len(risks)
    if n == 0:
        return "RISKS: count=0 top_id=none top_sev=none top_type=none"
    t = risks[0]
    return f"RISKS: count={n} top_id={t.risk_id} top_sev={t.severity} top_type={t.risk_type}"


def _fmt_delta(d: DeltaSummary | None) -> str:
    if d is None:
        return "DELTA: none"
    return (
        f"DELTA: +tasks={d.added_tasks} -tasks={d.removed_tasks} "
        f"finish_ch={d.changed_finish_dates} start_ch={d.changed_start_dates} "
        f"edges+={d.logic_edges_added} edges-={d.logic_edges_removed} "
        f"pred_ch={d.predecessor_set_changes} succ_ch={d.successor_set_changes} "
        f"drv_rank_ch={d.driver_rank_changes}"
    )


def derive_action(
    *,
    graph_summary: GraphSummary,
    risks: tuple[RiskFinding, ...],
    delta: DeltaSummary | None,
) -> str:
    """
    Single deterministic action token from fixed rule precedence (no free text).
    Prefix ``ACTION:`` is applied in ``build_command_brief``.
    """
    if graph_summary.directed_cycle_present:
        return "resolve_cycle_logic"
    if graph_summary.invalid_reference_count > 0:
        return "repair_invalid_references"
    if any(r.severity == "high" for r in risks):
        return "address_high_risk"
    if delta is not None:
        if delta.added_tasks > 0 or delta.removed_tasks > 0:
            return "reconcile_task_scope"
        if (
            delta.logic_edges_added > 0
            or delta.logic_edges_removed > 0
            or delta.predecessor_set_changes > 0
            or delta.successor_set_changes > 0
            or delta.changed_finish_dates > 0
            or delta.changed_start_dates > 0
        ):
            return "review_logic_deltas"
    if any(r.severity == "medium" for r in risks):
        return "address_medium_risk"
    if graph_summary.open_source_node_count > 0 or graph_summary.open_sink_node_count > 0:
        return "review_open_endpoints"
    return "monitor_schedule"


def build_command_brief(
    *,
    graph_summary: GraphSummary,
    driver: DriverFinding | None,
    risks: tuple[RiskFinding, ...],
    delta: DeltaSummary | None,
) -> CommandBrief:
    """Assemble the five-line brief from existing structured outputs only."""
    token = derive_action(graph_summary=graph_summary, risks=risks, delta=delta)
    return CommandBrief(
        finish=_fmt_finish(graph_summary),
        driver=_fmt_driver(driver),
        risks=_fmt_risks(risks),
        delta=_fmt_delta(delta),
        action=f"ACTION: {token}",
    )

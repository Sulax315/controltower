"""Compatibility shim for legacy imports; authoritative assembly is in intelligence modules."""

from __future__ import annotations

from typing import TypeAlias

from controltower.intelligence.command_brief import CommandBrief, build_command_brief as _build_command_brief_new

from .delta_analysis import SummaryCounts
from .drivers import AuthoritativeFinishTarget, DriverActivityEvidence, DriverAnalysis, DriverCandidate
from .graph_summary import ScheduleGraphSummary
from .risks import RiskFinding

GraphSummary: TypeAlias = ScheduleGraphSummary
DriverFinding: TypeAlias = DriverCandidate
DeltaSummary: TypeAlias = SummaryCounts


def derive_action(*, graph_summary: GraphSummary, risks: tuple[RiskFinding, ...], delta: DeltaSummary | None) -> str:
    """Deprecated compatibility helper mapping to deterministic NEED token."""
    if graph_summary.directed_cycle_present:
        return "resolve_cycle_logic"
    if any(r.severity == "high" for r in risks):
        return "address_high_risk"
    if any(r.severity == "medium" for r in risks):
        return "address_medium_risk"
    if graph_summary.open_source_node_count > 0 or graph_summary.open_sink_node_count > 0:
        return "review_open_endpoints"
    return "monitor_schedule"


def build_command_brief(
    *,
    graph_summary: GraphSummary,
    driver_analysis: DriverAnalysis | None = None,
    driver: DriverFinding | None = None,
    risks: tuple[RiskFinding, ...],
    delta: DeltaSummary | None = None,
) -> CommandBrief:
    if driver_analysis is None:
        driver_task_id = driver.task_id if driver is not None else "none"
        driver_analysis = DriverAnalysis(
            authoritative_finish_target=AuthoritativeFinishTarget(
                task_id=driver_task_id,
                selection_rule="compat_driver_fallback",
                candidate_count=1 if driver is not None else 0,
                tie_break="lexicographic_task_id",
            ),
            driver_path=((driver_task_id,) if driver is not None else ()),
            driver_activities=(
                (
                    DriverActivityEvidence(
                        task_id=driver_task_id,
                        position_on_driver_path=0,
                        is_finish_target=True,
                        immediate_predecessors_on_path=(),
                        immediate_successors_on_path=(),
                        reachable_to_finish_target=True,
                        total_float_days=driver.total_float_days,
                        critical=driver.critical,
                    ),
                )
                if driver is not None
                else ()
            ),
        )
    return _build_command_brief_new(graph_summary=graph_summary, driver_analysis=driver_analysis, risks=risks)


def build_legacy_command_brief(
    *,
    graph_summary: GraphSummary,
    driver_analysis: DriverAnalysis,
    risks: tuple[RiskFinding, ...],
) -> CommandBrief:
    return _build_command_brief_new(graph_summary=graph_summary, driver_analysis=driver_analysis, risks=risks)

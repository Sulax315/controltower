"""Deterministic graph-derived command brief; packet-based brief lives in intelligence.command_brief."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from .delta_analysis import SummaryCounts
from .drivers import AuthoritativeFinishTarget, DriverActivityEvidence, DriverAnalysis, DriverCandidate
from .graph_summary import ScheduleGraphSummary
from .risks import RiskFinding

GraphSummary: TypeAlias = ScheduleGraphSummary
DriverFinding: TypeAlias = DriverCandidate
DeltaSummary: TypeAlias = SummaryCounts


@dataclass(frozen=True)
class CommandBrief:
    """Deterministic five-line command brief (structural graph path)."""

    finish: str
    driver: str
    risks: str
    need: str
    doing: str

    def as_lines(self) -> tuple[str, str, str, str, str]:
        return (self.finish, self.driver, self.risks, self.need, self.doing)


def _fmt_finish(graph_summary: ScheduleGraphSummary, driver_analysis: DriverAnalysis) -> str:
    finish_id = driver_analysis.authoritative_finish_target.task_id
    return (
        f"FINISH: task_id={finish_id} nodes={graph_summary.node_count} "
        f"open_sink={graph_summary.open_sink_node_count} cycle={graph_summary.directed_cycle_present}"
    )


def _fmt_driver(driver_analysis: DriverAnalysis) -> str:
    path = ",".join(driver_analysis.driver_path)
    return (
        f"DRIVER: finish_task_id={driver_analysis.authoritative_finish_target.task_id} "
        f"path_len={len(driver_analysis.driver_path)} path={path}"
    )


def _fmt_risks(risks: tuple[RiskFinding, ...]) -> str:
    if not risks:
        return "RISKS: count=0 top_id=none top_sev=none top_type=none"
    top = risks[0]
    return f"RISKS: count={len(risks)} top_id={top.risk_id} top_sev={top.severity} top_type={top.risk_type}"


def _derive_need(risks: tuple[RiskFinding, ...], graph_summary: ScheduleGraphSummary) -> str:
    if graph_summary.directed_cycle_present:
        return "NEED: resolve_cycle_logic"
    if any(r.severity == "high" for r in risks):
        return "NEED: address_high_risk"
    if any(r.severity == "medium" for r in risks):
        return "NEED: address_medium_risk"
    if graph_summary.open_source_node_count > 0 or graph_summary.open_sink_node_count > 0:
        return "NEED: review_open_endpoints"
    return "NEED: monitor_schedule"


def _derive_doing(risks: tuple[RiskFinding, ...], driver_analysis: DriverAnalysis) -> str:
    finish_id = driver_analysis.authoritative_finish_target.task_id
    driver_path_size = len(driver_analysis.driver_path)
    touches_path = sum(1 for r in risks if r.touches_driver_path)
    return f"DOING: finish={finish_id} driver_path_len={driver_path_size} active_path_risks={touches_path}"


def _build_graph_command_brief(
    *,
    graph_summary: ScheduleGraphSummary,
    driver_analysis: DriverAnalysis,
    risks: tuple[RiskFinding, ...],
) -> CommandBrief:
    return CommandBrief(
        finish=_fmt_finish(graph_summary, driver_analysis),
        driver=_fmt_driver(driver_analysis),
        risks=_fmt_risks(risks),
        need=_derive_need(risks, graph_summary),
        doing=_derive_doing(risks, driver_analysis),
    )


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
    return _build_graph_command_brief(
        graph_summary=graph_summary,
        driver_analysis=driver_analysis,
        risks=risks,
    )


def build_legacy_command_brief(
    *,
    graph_summary: GraphSummary,
    driver_analysis: DriverAnalysis,
    risks: tuple[RiskFinding, ...],
) -> CommandBrief:
    return _build_graph_command_brief(
        graph_summary=graph_summary,
        driver_analysis=driver_analysis,
        risks=risks,
    )

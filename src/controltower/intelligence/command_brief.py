from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from controltower.schedule_intake.drivers import DriverAnalysis
    from controltower.schedule_intake.graph_summary import ScheduleGraphSummary
    from controltower.schedule_intake.risks import RiskFinding


@dataclass(frozen=True)
class CommandBrief:
    """Deterministic five-line command brief (Phase 18)."""

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


def build_command_brief(
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

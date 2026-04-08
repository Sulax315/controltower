from __future__ import annotations

from typing import TYPE_CHECKING, Any

from controltower.intelligence.command_brief import CommandBrief

if TYPE_CHECKING:
    from controltower.schedule_intake.drivers import DriverAnalysis
    from controltower.schedule_intake.graph_summary import ScheduleGraphSummary
    from controltower.schedule_intake.risks import RiskFinding

INTELLIGENCE_PAYLOAD_SCHEMA_VERSION = "intelligence_payload_v1"


def build_intelligence_payload(
    *,
    graph_summary: ScheduleGraphSummary,
    driver_analysis: DriverAnalysis,
    risks: tuple[RiskFinding, ...],
    command_brief: CommandBrief,
) -> dict[str, Any]:
    top_risk = risks[0] if risks else None
    return {
        "schema_version": INTELLIGENCE_PAYLOAD_SCHEMA_VERSION,
        "finish_summary": {
            "authoritative_finish_target": driver_analysis.authoritative_finish_target.task_id,
            "selection_rule": driver_analysis.authoritative_finish_target.selection_rule,
            "graph_open_sink_count": graph_summary.open_sink_node_count,
        },
        "driver_summary": {
            "authoritative_finish_target": driver_analysis.authoritative_finish_target.model_dump(mode="json"),
            "driver_path": list(driver_analysis.driver_path),
            "driver_activity_count": len(driver_analysis.driver_activities),
        },
        "risk_summary": {
            "risk_count": len(risks),
            "top_risk_id": top_risk.risk_id if top_risk is not None else None,
            "top_risk_severity": top_risk.severity if top_risk is not None else None,
            "top_risk_type": top_risk.risk_type if top_risk is not None else None,
            "risk_ids": [r.risk_id for r in risks],
        },
        "command_brief": {
            "finish": command_brief.finish,
            "driver": command_brief.driver,
            "risks": command_brief.risks,
            "need": command_brief.need,
            "doing": command_brief.doing,
        },
        "artifact_references": {
            "driver_analysis": "driver_analysis.json",
            "risk_findings": "engine_snapshot.risks",
            "logic_graph": "logic_graph.json",
            "normalized_activities": "normalized_intake.json",
        },
    }

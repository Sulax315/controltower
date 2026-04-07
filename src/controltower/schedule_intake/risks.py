"""
Track 4B — deterministic schedule risk findings from existing engine signals.

Severity ladder (``severity`` field) is assigned from ``risk_type`` using a fixed table
(see ``_SEVERITY_BY_TYPE``). ``sort_score`` is a separate integer used only for stable
ordering: higher scores sort first. It is computed as::

    sort_score = base_severity_rank * 1000 + type_offset + tie_breaker

where ``base_severity_rank`` is 3=high, 2=medium, 1=low, ``type_offset`` disambiguates
types within the same severity band, and ``tie_breaker`` is a small deterministic
integer derived from evidence (e.g. referenced id length) when needed.

Final ordering: ``(-sort_score, risk_id)`` lexicographically on ``risk_id`` for ties.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .graph import InvalidReference, ScheduleLogicGraph
from .graph_summary import ScheduleGraphSummary, build_schedule_graph_summary
from .logic_quality import AsymmetricRelationship, LogicQualitySignals, analyze_logic_quality

RiskType = Literal[
    "cycle_detected",
    "invalid_reference",
    "asymmetric_relationship",
    "open_start",
    "open_finish",
    "low_float",
    "zero_float_non_critical",
    "critical_high_fanout",
]

Severity = Literal["high", "medium", "low"]

_SEVERITY_BY_TYPE: dict[str, Severity] = {
    "cycle_detected": "high",
    "invalid_reference": "high",
    "zero_float_non_critical": "high",
    "asymmetric_relationship": "medium",
    "low_float": "medium",
    "critical_high_fanout": "medium",
    "open_start": "low",
    "open_finish": "low",
}

_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}

# Offsets keep types ordered inside a band (larger = earlier in same rank if we only used rank*1000 — we add these into sort_score)
_TYPE_OFFSET = {
    "cycle_detected": 80,
    "invalid_reference": 70,
    "zero_float_non_critical": 60,
    "asymmetric_relationship": 50,
    "low_float": 40,
    "critical_high_fanout": 35,
    "open_start": 20,
    "open_finish": 10,
}

LOW_FLOAT_MAX_EXCLUSIVE = 5.0  # days: (0, 5] triggers low_float; 0 handled by zero_float_non_critical when non-critical


class RiskFinding(BaseModel):
    """One deterministic risk row; no narrative text — only structured evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    risk_id: str
    risk_type: RiskType
    severity: Severity
    task_id: str | None = None
    task_name: str | None = None
    related_task_ids: tuple[str, ...] = ()
    evidence: tuple[tuple[str, str], ...] = Field(description="Sorted (key, value) pairs")
    source_signals: tuple[str, ...] = Field(description="Which signal families produced this row")
    sort_score: int


def _evidence(pairs: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(pairs.items(), key=lambda kv: kv[0]))


def _make_sort_score(severity: Severity, risk_type: str, tie: int = 0) -> int:
    return _SEVERITY_RANK[severity] * 1000 + _TYPE_OFFSET[risk_type] + tie


def collect_schedule_risk_findings(
    graph: ScheduleLogicGraph,
    logic_quality: LogicQualitySignals | None = None,
    graph_summary: ScheduleGraphSummary | None = None,
) -> tuple[RiskFinding, ...]:
    """
    Aggregate risks from logic quality, graph summary, and per-activity fields.

    ``logic_quality`` / ``graph_summary`` default to freshly computed values when omitted.
    """
    lq = logic_quality or analyze_logic_quality(graph)
    gs = graph_summary or build_schedule_graph_summary(graph)
    findings: list[RiskFinding] = []

    if lq.cycle_witness:
        w = lq.cycle_witness
        rid = "cycle_detected"
        sev = _SEVERITY_BY_TYPE[rid]
        findings.append(
            RiskFinding(
                risk_id=rid,
                risk_type="cycle_detected",
                severity=sev,
                task_id=w[0],
                task_name=graph.nodes_by_id[w[0]].task_name,
                related_task_ids=tuple(w),
                evidence=_evidence(
                    {
                        "cycle_witness_task_ids": ",".join(w),
                        "cycle_witness_length": str(len(w)),
                    }
                ),
                source_signals=("LogicQualitySignals.cycle_witness", "ScheduleLogicGraph.outbound_edges"),
                sort_score=_make_sort_score(sev, rid),
            )
        )

    for ir in lq.invalid_references:
        rid = f"invalid_reference:{ir.referencing_task_id}:{ir.role}:{ir.referenced_task_id}"
        sev = _SEVERITY_BY_TYPE["invalid_reference"]
        act = graph.nodes_by_id.get(ir.referencing_task_id)
        tie = min(99, len(ir.referenced_task_id))
        findings.append(
            RiskFinding(
                risk_id=rid,
                risk_type="invalid_reference",
                severity=sev,
                task_id=ir.referencing_task_id,
                task_name=act.task_name if act else None,
                related_task_ids=(ir.referenced_task_id,),
                evidence=_evidence(
                    {
                        "referenced_task_id": ir.referenced_task_id,
                        "reference_role": ir.role,
                        "referencing_task_id": ir.referencing_task_id,
                    }
                ),
                source_signals=("LogicQualitySignals.invalid_references", "ScheduleLogicGraph.invalid_references"),
                sort_score=_make_sort_score(sev, "invalid_reference", tie),
            )
        )

    for ar in lq.asymmetric_relationships:
        rid = f"asymmetric_relationship:{ar.from_task_id}:{ar.to_task_id}"
        sev = _SEVERITY_BY_TYPE["asymmetric_relationship"]
        findings.append(
            RiskFinding(
                risk_id=rid,
                risk_type="asymmetric_relationship",
                severity=sev,
                task_id=ar.from_task_id,
                task_name=graph.nodes_by_id[ar.from_task_id].task_name,
                related_task_ids=(ar.to_task_id,),
                evidence=_evidence(
                    {
                        "edge_from_task_id": ar.from_task_id,
                        "edge_to_task_id": ar.to_task_id,
                        "missing_on_predecessor_side": str(ar.missing_on_predecessor_side),
                        "missing_on_successor_side": str(ar.missing_on_successor_side),
                    }
                ),
                source_signals=(
                    "LogicQualitySignals.asymmetric_relationships",
                    "Activity.predecessors",
                    "Activity.successors",
                ),
                sort_score=_make_sort_score(sev, "asymmetric_relationship"),
            )
        )

    for tid in gs.source_node_ids:
        rid = f"open_start:{tid}"
        sev = _SEVERITY_BY_TYPE["open_start"]
        act = graph.nodes_by_id[tid]
        findings.append(
            RiskFinding(
                risk_id=rid,
                risk_type="open_start",
                severity=sev,
                task_id=tid,
                task_name=act.task_name,
                evidence=_evidence(
                    {
                        "inbound_edge_count": "0",
                        "structural_role": "source",
                        "task_id": tid,
                    }
                ),
                source_signals=("ScheduleGraphSummary.source_node_ids", "ScheduleLogicGraph.no_predecessor_nodes"),
                sort_score=_make_sort_score(sev, "open_start"),
            )
        )

    for tid in gs.sink_node_ids:
        rid = f"open_finish:{tid}"
        sev = _SEVERITY_BY_TYPE["open_finish"]
        act = graph.nodes_by_id[tid]
        findings.append(
            RiskFinding(
                risk_id=rid,
                risk_type="open_finish",
                severity=sev,
                task_id=tid,
                task_name=act.task_name,
                evidence=_evidence(
                    {
                        "outbound_edge_count": "0",
                        "structural_role": "sink",
                        "task_id": tid,
                    }
                ),
                source_signals=("ScheduleGraphSummary.sink_node_ids", "ScheduleLogicGraph.no_successor_nodes"),
                sort_score=_make_sort_score(sev, "open_finish"),
            )
        )

    for tid in sorted(graph.nodes_by_id):
        act = graph.nodes_by_id[tid]
        tf = act.total_float_days
        crit = act.critical
        out_deg = len(graph.outbound_edges_by_id.get(tid, []))

        if tf is not None and tf <= 0.0 and crit is not True:
            rid = f"zero_float_non_critical:{tid}"
            sev = _SEVERITY_BY_TYPE["zero_float_non_critical"]
            findings.append(
                RiskFinding(
                    risk_id=rid,
                    risk_type="zero_float_non_critical",
                    severity=sev,
                    task_id=tid,
                    task_name=act.task_name,
                    evidence=_evidence(
                        {
                            "critical": str(crit),
                            "total_float_days": str(tf),
                            "task_id": tid,
                        }
                    ),
                    source_signals=("Activity.total_float_days", "Activity.critical"),
                    sort_score=_make_sort_score(sev, "zero_float_non_critical", min(99, int(abs(tf) * 10) % 100)),
                )
            )
        elif tf is not None and 0.0 < tf <= LOW_FLOAT_MAX_EXCLUSIVE:
            rid = f"low_float:{tid}"
            sev = _SEVERITY_BY_TYPE["low_float"]
            tie = min(99, int(tf * 10))
            findings.append(
                RiskFinding(
                    risk_id=rid,
                    risk_type="low_float",
                    severity=sev,
                    task_id=tid,
                    task_name=act.task_name,
                    evidence=_evidence(
                        {
                            "low_float_max_exclusive_days": str(LOW_FLOAT_MAX_EXCLUSIVE),
                            "total_float_days": str(tf),
                            "task_id": tid,
                        }
                    ),
                    source_signals=("Activity.total_float_days",),
                    sort_score=_make_sort_score(sev, "low_float", tie),
                )
            )

        if crit is True and out_deg >= 2:
            rid = f"critical_high_fanout:{tid}"
            sev = _SEVERITY_BY_TYPE["critical_high_fanout"]
            findings.append(
                RiskFinding(
                    risk_id=rid,
                    risk_type="critical_high_fanout",
                    severity=sev,
                    task_id=tid,
                    task_name=act.task_name,
                    evidence=_evidence(
                        {
                            "critical": "True",
                            "outbound_degree": str(out_deg),
                            "task_id": tid,
                        }
                    ),
                    source_signals=("Activity.critical", "ScheduleLogicGraph.outbound_edges_by_id"),
                    sort_score=_make_sort_score(sev, "critical_high_fanout", min(99, out_deg)),
                )
            )

    findings.sort(key=lambda r: (-r.sort_score, r.risk_id))
    return tuple(findings)

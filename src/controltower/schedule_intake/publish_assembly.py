from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .output_contracts import ScheduleIntelligenceBundle


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _jsonable(v[k]) for k in sorted(v)}
    if isinstance(v, tuple):
        return [_jsonable(x) for x in v]
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    return v


@dataclass(frozen=True)
class PublishHeader:
    finish_line: str
    delta_line: str
    status_flags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonable_dict(self) -> dict[str, Any]:
        return _jsonable(self.to_dict())


@dataclass(frozen=True)
class PublishVerdict:
    primary_driver: str
    primary_risk: str
    action_token: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonable_dict(self) -> dict[str, Any]:
        return _jsonable(self.to_dict())


@dataclass(frozen=True)
class PublishKpis:
    node_count: int
    edge_count: int
    open_sources: int
    open_sinks: int
    risk_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonable_dict(self) -> dict[str, Any]:
        return _jsonable(self.to_dict())


@dataclass(frozen=True)
class PublishDrivers:
    top_driver_task_id: str | None
    top_driver_score: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonable_dict(self) -> dict[str, Any]:
        return _jsonable(self.to_dict())


@dataclass(frozen=True)
class PublishRisks:
    top_risk_id: str | None
    top_risk_severity: str | None
    total_risk_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonable_dict(self) -> dict[str, Any]:
        return _jsonable(self.to_dict())


@dataclass(frozen=True)
class PublishActions:
    action_token: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonable_dict(self) -> dict[str, Any]:
        return _jsonable(self.to_dict())


@dataclass(frozen=True)
class PublishEvidence:
    driver_evidence: tuple[tuple[str, str], ...]
    risk_evidence: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonable_dict(self) -> dict[str, Any]:
        return _jsonable(self.to_dict())


@dataclass(frozen=True)
class PublishPacket:
    header: PublishHeader
    verdict: PublishVerdict
    kpis: PublishKpis
    drivers: PublishDrivers
    risks: PublishRisks
    actions: PublishActions
    evidence: PublishEvidence

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonable_dict(self) -> dict[str, Any]:
        return _jsonable(self.to_dict())


def build_publish_header(bundle: ScheduleIntelligenceBundle) -> PublishHeader:
    gs = bundle.engine_snapshot.graph_summary
    flags: list[str] = []
    if bool(gs.get("directed_cycle_present")):
        flags.append("cycle")
    if int(gs.get("invalid_reference_count", 0)) > 0:
        flags.append("invalid_refs")
    if int(gs.get("open_source_node_count", 0)) > 0:
        flags.append("open_sources")
    if int(gs.get("open_sink_node_count", 0)) > 0:
        flags.append("open_sinks")
    return PublishHeader(
        finish_line=bundle.command_brief.finish,
        delta_line=bundle.command_brief.doing,
        status_flags=tuple(sorted(flags)),
    )


def build_publish_verdict(bundle: ScheduleIntelligenceBundle) -> PublishVerdict:
    return PublishVerdict(
        primary_driver=bundle.command_brief.driver,
        primary_risk=bundle.command_brief.risks,
        action_token=bundle.command_brief.need,
    )


def build_publish_kpis(bundle: ScheduleIntelligenceBundle) -> PublishKpis:
    gs = bundle.engine_snapshot.graph_summary
    return PublishKpis(
        node_count=int(gs.get("node_count", 0)),
        edge_count=int(gs.get("edge_count", 0)),
        open_sources=int(gs.get("open_source_node_count", 0)),
        open_sinks=int(gs.get("open_sink_node_count", 0)),
        risk_count=len(bundle.engine_snapshot.risks),
    )


def build_publish_drivers(bundle: ScheduleIntelligenceBundle) -> PublishDrivers:
    td = bundle.engine_snapshot.top_driver
    return PublishDrivers(
        top_driver_task_id=(str(td.get("task_id")) if td and td.get("task_id") is not None else None),
        top_driver_score=(float(td.get("driver_score")) if td and td.get("driver_score") is not None else None),
    )


def build_publish_risks(bundle: ScheduleIntelligenceBundle) -> PublishRisks:
    risks = bundle.engine_snapshot.risks
    top = risks[0] if risks else None
    return PublishRisks(
        top_risk_id=(str(top.get("risk_id")) if top and top.get("risk_id") is not None else None),
        top_risk_severity=(str(top.get("severity")) if top and top.get("severity") is not None else None),
        total_risk_count=len(risks),
    )


def build_publish_actions(bundle: ScheduleIntelligenceBundle) -> PublishActions:
    return PublishActions(action_token=bundle.command_brief.need)


def build_publish_evidence(bundle: ScheduleIntelligenceBundle) -> PublishEvidence:
    td = bundle.engine_snapshot.top_driver or {}
    signals = td.get("rationale_signals") or []
    driver_evidence = tuple((str(i), str(v)) for i, v in enumerate(signals))

    risks = bundle.engine_snapshot.risks
    if not risks:
        risk_evidence: tuple[tuple[str, str], ...] = ()
    else:
        raw = risks[0].get("evidence") or ()
        # Keep incoming order; do not sort here.
        risk_evidence = tuple((str(k), str(v)) for k, v in raw)

    return PublishEvidence(driver_evidence=driver_evidence, risk_evidence=risk_evidence)


def build_publish_packet(bundle: ScheduleIntelligenceBundle) -> PublishPacket:
    return PublishPacket(
        header=build_publish_header(bundle),
        verdict=build_publish_verdict(bundle),
        kpis=build_publish_kpis(bundle),
        drivers=build_publish_drivers(bundle),
        risks=build_publish_risks(bundle),
        actions=build_publish_actions(bundle),
        evidence=build_publish_evidence(bundle),
    )

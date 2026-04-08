from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .command_brief import CommandBrief
from .delta_analysis import ScheduleDeltaResult
from .drivers import DriverCandidate
from .graph_summary import ScheduleGraphSummary
from .logic_quality import LogicQualitySignals
from .risks import RiskFinding


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _jsonable(v[k]) for k in sorted(v)}
    if isinstance(v, tuple):
        return [_jsonable(x) for x in v]
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    return v


@dataclass(frozen=True)
class CommandBriefContract:
    finish: str
    driver: str
    risks: str
    delta: str
    action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonable_dict(self) -> dict[str, Any]:
        return _jsonable(self.to_dict())


@dataclass(frozen=True)
class ExplorationContract:
    immediate_predecessors: tuple[str, ...] = ()
    immediate_successors: tuple[str, ...] = ()
    upstream_closure: tuple[str, ...] = ()
    downstream_closure: tuple[str, ...] = ()
    shortest_path: tuple[str, ...] = ()
    all_simple_paths: tuple[tuple[str, ...], ...] = ()
    shared_ancestors: tuple[str, ...] = ()
    shared_descendants: tuple[str, ...] = ()
    driver_structure: dict[str, Any] | None = None
    impact_span: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonable_dict(self) -> dict[str, Any]:
        return _jsonable(self.to_dict())


@dataclass(frozen=True)
class EngineSnapshot:
    graph_summary: dict[str, Any]
    logic_quality: dict[str, Any]
    top_driver: dict[str, Any] | None
    risks: tuple[dict[str, Any], ...]
    delta_summary: dict[str, Any] | None
    command_brief_lines: tuple[str, str, str, str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonable_dict(self) -> dict[str, Any]:
        return _jsonable(self.to_dict())


@dataclass(frozen=True)
class ScheduleIntelligenceBundle:
    engine_snapshot: EngineSnapshot
    command_brief: CommandBriefContract
    exploration: ExplorationContract

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonable_dict(self) -> dict[str, Any]:
        return _jsonable(self.to_dict())


def build_command_brief_contract(brief: CommandBrief) -> CommandBriefContract:
    return CommandBriefContract(
        finish=brief.finish,
        driver=brief.driver,
        risks=brief.risks,
        delta=brief.delta,
        action=brief.action,
    )


def build_exploration_contract(
    *,
    immediate_predecessors: tuple[str, ...] = (),
    immediate_successors: tuple[str, ...] = (),
    upstream_closure: tuple[str, ...] = (),
    downstream_closure: tuple[str, ...] = (),
    shortest_path: tuple[str, ...] = (),
    all_simple_paths: tuple[tuple[str, ...], ...] = (),
    shared_ancestors: tuple[str, ...] = (),
    shared_descendants: tuple[str, ...] = (),
    driver_structure: dict[str, Any] | None = None,
    impact_span: dict[str, Any] | None = None,
) -> ExplorationContract:
    return ExplorationContract(
        immediate_predecessors=tuple(immediate_predecessors),
        immediate_successors=tuple(immediate_successors),
        upstream_closure=tuple(upstream_closure),
        downstream_closure=tuple(downstream_closure),
        shortest_path=tuple(shortest_path),
        all_simple_paths=tuple(tuple(p) for p in all_simple_paths),
        shared_ancestors=tuple(shared_ancestors),
        shared_descendants=tuple(shared_descendants),
        driver_structure=driver_structure,
        impact_span=impact_span,
    )


def build_engine_snapshot(
    *,
    graph_summary: ScheduleGraphSummary,
    logic_quality: LogicQualitySignals,
    top_driver: DriverCandidate | None,
    risks: tuple[RiskFinding, ...],
    delta: ScheduleDeltaResult | None,
    command_brief: CommandBrief,
) -> EngineSnapshot:
    return EngineSnapshot(
        graph_summary=graph_summary.__dict__,
        logic_quality={
            "open_end_sources": tuple(logic_quality.open_end_sources),
            "open_end_sinks": tuple(logic_quality.open_end_sinks),
            "invalid_references": tuple(
                (x.referencing_task_id, x.role, x.referenced_task_id) for x in logic_quality.invalid_references
            ),
            "asymmetric_relationships": tuple(
                (x.from_task_id, x.to_task_id, x.missing_on_predecessor_side, x.missing_on_successor_side)
                for x in logic_quality.asymmetric_relationships
            ),
            "cycle_witness": tuple(logic_quality.cycle_witness) if logic_quality.cycle_witness else (),
            "finish_candidates": tuple(logic_quality.finish_candidates),
            "orphan_chains": tuple(tuple(x) for x in logic_quality.orphan_chains),
        },
        top_driver=top_driver.model_dump() if top_driver is not None else None,
        risks=tuple(r.model_dump() for r in risks),
        delta_summary=delta.summary_counts.model_dump() if delta is not None else None,
        command_brief_lines=command_brief.as_lines(),
    )


def build_schedule_intelligence_bundle(
    *,
    graph_summary: ScheduleGraphSummary,
    logic_quality: LogicQualitySignals,
    top_driver: DriverCandidate | None,
    risks: tuple[RiskFinding, ...],
    delta: ScheduleDeltaResult | None,
    command_brief: CommandBrief,
    exploration: ExplorationContract | None = None,
) -> ScheduleIntelligenceBundle:
    brief_contract = build_command_brief_contract(command_brief)
    snapshot = build_engine_snapshot(
        graph_summary=graph_summary,
        logic_quality=logic_quality,
        top_driver=top_driver,
        risks=risks,
        delta=delta,
        command_brief=command_brief,
    )
    return ScheduleIntelligenceBundle(
        engine_snapshot=snapshot,
        command_brief=brief_contract,
        exploration=exploration or ExplorationContract(),
    )

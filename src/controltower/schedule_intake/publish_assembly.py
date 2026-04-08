from __future__ import annotations

from collections import deque
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
    visualization: dict[str, Any] | None = None

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


def build_publish_packet(
    bundle: ScheduleIntelligenceBundle,
    *,
    visualization: dict[str, Any] | None = None,
) -> PublishPacket:
    return PublishPacket(
        header=build_publish_header(bundle),
        verdict=build_publish_verdict(bundle),
        kpis=build_publish_kpis(bundle),
        drivers=build_publish_drivers(bundle),
        risks=build_publish_risks(bundle),
        actions=build_publish_actions(bundle),
        evidence=build_publish_evidence(bundle),
        visualization=visualization,
    )


def _safe_task_id_list(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple):
        return ()
    out: list[str] = []
    for item in raw:
        if item is None:
            continue
        value = str(item).strip()
        if value:
            out.append(value)
    return tuple(out)


def _parse_task_ids_from_evidence_row(*, key: str, value: str) -> tuple[str, ...]:
    k = key.strip().lower()
    v = value.strip()
    if not v:
        return ()
    if "task_ids" in k or "task_id" in k:
        if "," in v:
            return tuple(sorted({part.strip() for part in v.split(",") if part.strip()}))
        return (v,)
    return ()


def _safe_edges(raw: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, list):
        return ()
    edges: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        src = str(item.get("from_task_id") or "").strip()
        dst = str(item.get("to_task_id") or "").strip()
        if src and dst:
            edges.append((src, dst))
    return tuple(sorted(set(edges)))


def _shortest_path_to_finish(
    *,
    start_task_id: str,
    finish_task_id: str,
    successors: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    if start_task_id == finish_task_id:
        return (finish_task_id,)
    q: deque[str] = deque([start_task_id])
    parent: dict[str, str | None] = {start_task_id: None}
    while q:
        node = q.popleft()
        for nxt in successors.get(node, ()):
            if nxt in parent:
                continue
            parent[nxt] = node
            if nxt == finish_task_id:
                rev: list[str] = [finish_task_id]
                cur: str | None = node
                while cur is not None:
                    rev.append(cur)
                    cur = parent.get(cur)
                rev.reverse()
                return tuple(rev)
            q.append(nxt)
    return ()


def build_publish_visualization(
    bundle: ScheduleIntelligenceBundle,
    *,
    logic_graph: dict[str, Any] | None,
    driver_analysis: dict[str, Any] | None,
) -> dict[str, Any] | None:
    graph = logic_graph or {}
    driver = driver_analysis or {}
    driver_path = _safe_task_id_list(driver.get("driver_path"))
    finish_obj = driver.get("authoritative_finish_target") if isinstance(driver.get("authoritative_finish_target"), dict) else {}
    finish_task_id = str(finish_obj.get("task_id") or "").strip()
    edges = _safe_edges(graph.get("edges"))
    if not driver_path or not finish_task_id or not edges:
        return None

    predecessors: dict[str, list[str]] = {}
    successors: dict[str, list[str]] = {}
    for src, dst in edges:
        successors.setdefault(src, []).append(dst)
        predecessors.setdefault(dst, []).append(src)
    pred_map = {k: tuple(sorted(set(v))) for k, v in predecessors.items()}
    succ_map = {k: tuple(sorted(set(v))) for k, v in successors.items()}

    path_set = frozenset(driver_path)
    localized_nodes: set[str] = set(driver_path)
    for task_id in driver_path:
        localized_nodes.update(pred_map.get(task_id, ()))
        localized_nodes.update(succ_map.get(task_id, ()))
    localized_nodes.add(finish_task_id)

    localized_edges = tuple(
        (src, dst)
        for src, dst in edges
        if src in localized_nodes and dst in localized_nodes and (src in path_set or dst in path_set)
    )

    node_risks: dict[str, set[str]] = {}
    edge_risks: dict[tuple[str, str], set[str]] = {}
    for risk in bundle.engine_snapshot.risks:
        rid = str(risk.get("risk_id") or "").strip()
        if not rid:
            continue
        related = _safe_task_id_list(risk.get("related_task_ids"))
        task_id = str(risk.get("task_id") or "").strip()
        touched = set(related)
        if task_id:
            touched.add(task_id)
        for tid in touched:
            node_risks.setdefault(tid, set()).add(rid)
        for src, dst in localized_edges:
            if src in touched and dst in touched:
                edge_risks.setdefault((src, dst), set()).add(rid)

    rank_by_task = {task_id: idx for idx, task_id in enumerate(driver_path)}
    lane_by_task: dict[str, str] = {task_id: "path" for task_id in driver_path}
    for src, dst in localized_edges:
        if src in path_set and dst not in path_set:
            rank_by_task[dst] = max(0, min(len(driver_path) - 1, rank_by_task[src] + 1))
            lane_by_task[dst] = "downstream"
        elif dst in path_set and src not in path_set:
            rank_by_task[src] = max(0, min(len(driver_path) - 1, rank_by_task[dst] - 1))
            lane_by_task[src] = "upstream"
    for tid in sorted(localized_nodes):
        if tid not in rank_by_task:
            rank_by_task[tid] = 0
            lane_by_task[tid] = "upstream"

    lane_order = {"upstream": 0, "path": 1, "downstream": 2}
    sorted_nodes = sorted(localized_nodes, key=lambda tid: (rank_by_task[tid], lane_order[lane_by_task[tid]], tid))
    nodes_payload: list[dict[str, Any]] = []
    for tid in sorted_nodes:
        nodes_payload.append(
            {
                "task_id": tid,
                "label": tid,
                "lane": lane_by_task[tid],
                "rank": rank_by_task[tid],
                "is_driver_path": tid in path_set,
                "is_finish_target": tid == finish_task_id,
                "risk_ids": sorted(node_risks.get(tid, set())),
                "is_risk_flagged": tid in node_risks,
            }
        )

    links_payload = [
        {
            "from_task_id": src,
            "to_task_id": dst,
            "is_driver_path": src in path_set and dst in path_set,
            "risk_ids": sorted(edge_risks.get((src, dst), set())),
            "is_risk_flagged": (src, dst) in edge_risks,
            "direction": "predecessor_to_successor",
        }
        for src, dst in sorted(localized_edges)
    ]

    path_to_finish: dict[str, list[str]] = {}
    for tid in sorted(localized_nodes):
        path_to_finish[tid] = list(
            _shortest_path_to_finish(start_task_id=tid, finish_task_id=finish_task_id, successors=succ_map)
        )

    risk_nodes = sorted(
        tid
        for tid in localized_nodes
        if tid in node_risks
    )
    top_risk = bundle.engine_snapshot.risks[0] if bundle.engine_snapshot.risks else {}
    top_risk_nodes = sorted(
        {
            *(_safe_task_id_list(top_risk.get("related_task_ids"))),
            *(tuple([str(top_risk.get("task_id") or "").strip()]) if str(top_risk.get("task_id") or "").strip() else ()),
        }
    )
    top_driver_task_id = str((bundle.engine_snapshot.top_driver or {}).get("task_id") or "").strip()
    driver_rows = [
        ([top_driver_task_id] if top_driver_task_id else [])
        for _ in tuple(bundle.engine_snapshot.top_driver.get("rationale_signals") or ())
    ] if bundle.engine_snapshot.top_driver else []
    risk_rows: list[list[str]] = []
    top_risk_evidence = tuple(top_risk.get("evidence") or ()) if isinstance(top_risk, dict) else ()
    for row in top_risk_evidence:
        if not isinstance(row, list | tuple) or len(row) != 2:
            risk_rows.append([])
            continue
        row_ids = _parse_task_ids_from_evidence_row(key=str(row[0]), value=str(row[1]))
        risk_rows.append(sorted(tid for tid in row_ids if tid in localized_nodes))

    return {
        "schema_version": "publish_visualization_v1",
        "finish_task_id": finish_task_id,
        "driver_path_task_ids": list(driver_path),
        "nodes": nodes_payload,
        "links": links_payload,
        "path_to_finish_by_task_id": path_to_finish,
        "focus_sets": {
            "driver_path": list(driver_path),
            "risk_overlay": risk_nodes,
            "top_risk": top_risk_nodes,
        },
        "evidence_links": {
            "driver_evidence_task_ids": list(driver_path),
            "risk_evidence_task_ids": top_risk_nodes,
            "driver_rows": driver_rows,
            "risk_rows": risk_rows,
        },
    }

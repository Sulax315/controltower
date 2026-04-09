from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import re
from typing import Any

from .output_contracts import ScheduleIntelligenceBundle

LONG_RANGE_EXTREME_SHIFT_DAYS = 180
PRESSURE_NEW_CRITICAL_THRESHOLD = 3
PRESSURE_MAX_SLIP_DAYS_THRESHOLD = 90
PRESSURE_BASELINE_SLIP_COUNT_THRESHOLD = 3
PRESSURE_BASELINE_SLIP_DAYS_THRESHOLD = 30


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
    pm_translation_v1: dict[str, dict[str, Any]] | None = None

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
    pm_translation_v1: dict[str, dict[str, Any]] | None = None,
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
        pm_translation_v1=pm_translation_v1,
    )


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.date()
    return None


def _fmt_date(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _statement(
    *,
    text: str | None,
    rule_id: str,
    artifact: str,
    fields: tuple[str, ...],
    task_ids: tuple[str, ...] = (),
    dependency_links: tuple[tuple[str, str], ...] = (),
    float_values: tuple[tuple[str, float], ...] = (),
    milestone_ids: tuple[str, ...] = (),
    thresholds: tuple[tuple[str, float], ...] = (),
) -> dict[str, Any]:
    source: dict[str, Any] = {
        "artifact": artifact,
        "fields": list(fields),
        "task_ids": list(task_ids),
        "dependency_links": [{"from_task_id": src, "to_task_id": dst} for src, dst in dependency_links],
        "float_values": [{"task_id": tid, "total_float_days": value} for tid, value in float_values],
        "milestone_ids": list(milestone_ids),
        "thresholds": [{"name": name, "value": value} for name, value in thresholds],
    }
    return {"text": text, "sources": [source] if text is not None else [], "rule_id": rule_id}


def _suppressed_statement() -> dict[str, Any]:
    return {"text": None, "sources": [], "rule_id": None}


def translate_finish_position(
    *,
    final_finish_current: Any,
    substantial_finish_current: Any,
    milestone_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    final_date = _coerce_date(final_finish_current)
    substantial_date = _coerce_date(substantial_finish_current)
    if final_date is None or substantial_date is None:
        return _statement(
            text=None,
            rule_id="F1",
            artifact="finish_trend",
            fields=("final_finish_current", "substantial_finish_current"),
            milestone_ids=milestone_ids,
        )
    return _statement(
        text=f"Final completion is {_fmt_date(final_date)} and substantial completion is {_fmt_date(substantial_date)}.",
        rule_id="F1",
        artifact="finish_trend",
        fields=("final_finish_current", "substantial_finish_current"),
        milestone_ids=milestone_ids,
    )


def translate_movement(
    *,
    final_finish_current: Any,
    final_finish_prior: Any,
) -> dict[str, Any]:
    current = _coerce_date(final_finish_current)
    prior = _coerce_date(final_finish_prior)
    if current is None or prior is None:
        return _statement(
            text=None,
            rule_id="M1",
            artifact="finish_trend",
            fields=("final_finish_current", "final_finish_prior"),
        )
    delta_days = (current - prior).days
    if delta_days < 0:
        text = f"Final completion improved {abs(delta_days)} days."
    elif delta_days > 0:
        text = f"Final completion slipped {delta_days} days."
    else:
        text = "Final completion held."
    return _statement(
        text=text,
        rule_id="M1",
        artifact="finish_trend",
        fields=("final_finish_current", "final_finish_prior", "delta_days"),
    )


def translate_baseline_status(
    *,
    final_finish_current: Any,
    final_finish_baseline: Any,
) -> dict[str, Any]:
    current = _coerce_date(final_finish_current)
    baseline = _coerce_date(final_finish_baseline)
    if current is None or baseline is None:
        return _statement(
            text=None,
            rule_id="B1",
            artifact="finish_trend",
            fields=("final_finish_current", "final_finish_baseline"),
        )
    variance_days = (current - baseline).days
    if variance_days == 0:
        text = "Final completion is aligned with baseline."
    elif variance_days < 0:
        text = f"Final completion is ahead of baseline by {abs(variance_days)} days."
    else:
        text = f"Final completion is behind baseline by {variance_days} days."
    return _statement(
        text=text,
        rule_id="B1",
        artifact="finish_trend",
        fields=("final_finish_current", "final_finish_baseline", "variance_days"),
    )


def _tokenize_task_name(name: str) -> tuple[str, ...]:
    return tuple(tok for tok in re.findall(r"[A-Za-z0-9]+", name.lower()) if len(tok) >= 3)


def _dominant_token(task_names: tuple[str, ...]) -> str | None:
    counts: dict[str, int] = {}
    for name in task_names:
        for token in _tokenize_task_name(name):
            counts[token] = counts.get(token, 0) + 1
    if not counts:
        return None
    max_count = max(counts.values())
    winners = sorted(token for token, count in counts.items() if count == max_count)
    return winners[0] if winners else None


def _longest_chain(nodes: frozenset[str], edges: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    successors: dict[str, list[str]] = {n: [] for n in nodes}
    indegree: dict[str, int] = {n: 0 for n in nodes}
    for src, dst in edges:
        if src in nodes and dst in nodes:
            successors[src].append(dst)
            indegree[dst] += 1
    starts = sorted((n for n, deg in indegree.items() if deg == 0))
    if not starts:
        return ()

    memo: dict[str, tuple[str, ...]] = {}

    def visit(node: str, seen: frozenset[str]) -> tuple[str, ...]:
        if node in memo:
            return memo[node]
        best = (node,)
        for nxt in sorted(successors.get(node, [])):
            if nxt in seen:
                continue
            chain = (node,) + visit(nxt, seen | {nxt})
            if len(chain) > len(best):
                best = chain
        memo[node] = best
        return best

    best_chain: tuple[str, ...] = ()
    for start in starts:
        chain = visit(start, frozenset({start}))
        if len(chain) > len(best_chain):
            best_chain = chain
    return best_chain


def translate_near_term_driver(
    *,
    data_date: Any,
    activities: tuple[dict[str, Any], ...],
    dependency_links: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    anchor = _coerce_date(data_date)
    if anchor is None:
        return _statement(text=None, rule_id="D1", artifact="lookahead", fields=("data_date",))
    window_end = anchor + timedelta(days=21)

    by_id: dict[str, dict[str, Any]] = {}
    candidate_ids: set[str] = set()
    float_by_task: dict[str, float] = {}
    for activity in activities:
        tid = str(activity.get("task_id") or "").strip()
        if not tid:
            continue
        start = _coerce_date(activity.get("start"))
        finish = _coerce_date(activity.get("finish"))
        if start is None or finish is None:
            continue
        if finish < anchor or start > window_end:
            continue
        critical = activity.get("critical") is True
        tf_raw = activity.get("total_float_days")
        tf = float(tf_raw) if isinstance(tf_raw, int | float) else None
        if not critical and (tf is None or tf > 0):
            continue
        by_id[tid] = activity
        candidate_ids.add(tid)
        if tf is not None:
            float_by_task[tid] = tf

    if not candidate_ids:
        return _statement(
            text=None,
            rule_id="D1",
            artifact="lookahead",
            fields=("data_date", "activities.critical", "activities.total_float_days", "activities.start", "activities.finish"),
        )

    filtered_edges = tuple(
        (src, dst) for src, dst in dependency_links if src in candidate_ids and dst in candidate_ids
    )
    chain = _longest_chain(frozenset(candidate_ids), filtered_edges)
    if len(chain) < 3:
        return _statement(
            text=None,
            rule_id="D1",
            artifact="lookahead",
            fields=("data_date", "dependency_links", "activities.total_float_days"),
        )

    chain_floats = [float_by_task.get(tid, 0.0) for tid in chain]
    if max(chain_floats) > 0:
        return _statement(
            text=None,
            rule_id="D1",
            artifact="lookahead",
            fields=("activities.total_float_days", "dependency_links"),
        )

    phase_counts: dict[str, int] = {}
    task_names: list[str] = []
    for tid in chain:
        phase = str(by_id[tid].get("phase_exec") or "").strip()
        if phase:
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
        name = str(by_id[tid].get("task_name") or "").strip()
        if name:
            task_names.append(name)

    dominant_phase = None
    if phase_counts:
        top_phase, top_count = sorted(phase_counts.items(), key=lambda x: (-x[1], x[0]))[0]
        if (top_count / len(chain)) > 0.6:
            dominant_phase = top_phase

    if dominant_phase is not None:
        driver_name = dominant_phase
    else:
        token = _dominant_token(tuple(task_names))
        if token is not None:
            driver_name = token
        else:
            fallback_names = [name for name in task_names[:3] if name]
            if not fallback_names:
                return _statement(
                    text=None,
                    rule_id="D1",
                    artifact="lookahead",
                    fields=("activities.task_name",),
                )
            driver_name = ", ".join(fallback_names)

    finish_dates = [_coerce_date(by_id[tid].get("finish")) for tid in chain]
    if any(value is None for value in finish_dates):
        return _statement(
            text=None,
            rule_id="D1",
            artifact="lookahead",
            fields=("activities.finish",),
        )
    through_date = max(value for value in finish_dates if value is not None)
    text = f"The near-term path is driven by {driver_name} through {_fmt_date(through_date)} with zero float."
    chain_edges = tuple((chain[i], chain[i + 1]) for i in range(len(chain) - 1))
    return _statement(
        text=text,
        rule_id="D1",
        artifact="lookahead",
        fields=("data_date", "activities.critical", "activities.total_float_days", "activities.phase_exec", "activities.task_name", "dependency_links"),
        task_ids=chain,
        dependency_links=chain_edges,
        float_values=tuple((tid, float_by_task.get(tid, 0.0)) for tid in chain),
    )


def build_pm_translation_v1_partial(
    *,
    final_finish_current: Any,
    substantial_finish_current: Any,
    final_finish_prior: Any,
    final_finish_baseline: Any,
    data_date: Any,
    activities: tuple[dict[str, Any], ...],
    dependency_links: tuple[tuple[str, str], ...],
    finish_milestone_ids: tuple[str, ...] = (),
) -> dict[str, dict[str, Any]]:
    return {
        "finish_position": translate_finish_position(
            final_finish_current=final_finish_current,
            substantial_finish_current=substantial_finish_current,
            milestone_ids=finish_milestone_ids,
        ),
        "movement": translate_movement(
            final_finish_current=final_finish_current,
            final_finish_prior=final_finish_prior,
        ),
        "baseline_status": translate_baseline_status(
            final_finish_current=final_finish_current,
            final_finish_baseline=final_finish_baseline,
        ),
        "near_term_driver": translate_near_term_driver(
            data_date=data_date,
            activities=activities,
            dependency_links=dependency_links,
        ),
    }


def translate_long_range_concern(
    *,
    data_date: Any,
    activities: tuple[dict[str, Any], ...],
    near_term_window_days: int = 21,
    extreme_shift_days_threshold: int = LONG_RANGE_EXTREME_SHIFT_DAYS,
) -> dict[str, Any]:
    anchor = _coerce_date(data_date)
    if anchor is None:
        return _suppressed_statement()
    window_end = anchor + timedelta(days=near_term_window_days)

    triggered: list[dict[str, Any]] = []
    for activity in activities:
        task_id = str(activity.get("task_id") or "").strip()
        if not task_id:
            continue
        finish_current = _coerce_date(activity.get("finish_current"))
        finish_prior = _coerce_date(activity.get("finish_prior"))
        if finish_current is None or finish_prior is None:
            continue
        shift_days = (finish_current - finish_prior).days
        if shift_days < extreme_shift_days_threshold:
            continue
        start = _coerce_date(activity.get("start"))
        outside_near_term = (start is not None and start > window_end) or (finish_current > window_end)
        if not outside_near_term:
            continue
        critical_current = activity.get("critical_current") is True
        critical_prior = activity.get("critical_prior") is True
        became_critical = critical_current and not critical_prior
        tf_raw = activity.get("total_float_days")
        total_float = float(tf_raw) if isinstance(tf_raw, int | float) else None
        zero_or_negative_float = total_float is not None and total_float <= 0.0
        if not (became_critical or zero_or_negative_float):
            continue
        triggered.append(activity)

    if not triggered:
        return _suppressed_statement()

    phase_counts: dict[str, int] = {}
    task_ids: list[str] = []
    names: list[str] = []
    for activity in triggered:
        task_ids.append(str(activity.get("task_id")))
        phase = str(activity.get("phase_exec") or "").strip()
        if phase:
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
        name = str(activity.get("task_name") or "").strip()
        if name:
            names.append(name)

    label = "long-range"
    if phase_counts:
        top_phase, top_count = sorted(phase_counts.items(), key=lambda x: (-x[1], x[0]))[0]
        if (top_count / len(triggered)) > 0.6:
            label = top_phase
    elif names:
        label = ", ".join(names[:2])

    return _statement(
        text=f"Several {label} activities experienced extreme finish shifts and are now critical or zero-float, requiring validation of the long-range path.",
        rule_id="L1",
        artifact="finish_trend",
        fields=(
            "data_date",
            "activities.finish_current",
            "activities.finish_prior",
            "activities.start",
            "activities.critical_current",
            "activities.critical_prior",
            "activities.total_float_days",
            "activities.phase_exec",
            "activities.task_name",
        ),
        task_ids=tuple(task_ids),
        thresholds=(("extreme_shift_days_threshold", float(extreme_shift_days_threshold)),),
    )


def translate_pressure_statement(
    *,
    movement: dict[str, Any],
    pressure_metrics: dict[str, Any],
) -> dict[str, Any]:
    movement_text = str(movement.get("text") or "").strip().lower()
    finish_favorable = ("held" in movement_text) or ("improved" in movement_text)
    if not finish_favorable:
        return _suppressed_statement()

    new_critical_count = int(pressure_metrics.get("new_critical_count", 0) or 0)
    max_slip_days = int(pressure_metrics.get("max_slip_days", 0) or 0)
    baseline_slip_count = int(pressure_metrics.get("baseline_slip_count_gt30", 0) or 0)
    low_float_density_increase = bool(pressure_metrics.get("low_float_density_increase", False))
    dominant_phase = str(pressure_metrics.get("dominant_phase") or "").strip()

    triggered = (
        new_critical_count >= PRESSURE_NEW_CRITICAL_THRESHOLD
        or max_slip_days >= PRESSURE_MAX_SLIP_DAYS_THRESHOLD
        or baseline_slip_count >= PRESSURE_BASELINE_SLIP_COUNT_THRESHOLD
        or low_float_density_increase
    )
    if not triggered:
        return _suppressed_statement()

    task_ids_raw = pressure_metrics.get("task_ids")
    task_ids = _safe_task_id_list(task_ids_raw)
    fields = [
        "movement.text",
        "pressure_metrics.new_critical_count",
        "pressure_metrics.max_slip_days",
        "pressure_metrics.baseline_slip_count_gt30",
        "pressure_metrics.low_float_density_increase",
    ]
    if dominant_phase:
        fields.append("pressure_metrics.dominant_phase")
    return _statement(
        text="The finish is holding, but internal pressure is increasing.",
        rule_id="P1",
        artifact="pressure_metrics",
        fields=tuple(fields),
        task_ids=task_ids,
        thresholds=(
            ("new_critical_threshold", float(PRESSURE_NEW_CRITICAL_THRESHOLD)),
            ("max_slip_days_threshold", float(PRESSURE_MAX_SLIP_DAYS_THRESHOLD)),
            ("baseline_slip_count_threshold", float(PRESSURE_BASELINE_SLIP_COUNT_THRESHOLD)),
            ("baseline_slip_days_threshold", float(PRESSURE_BASELINE_SLIP_DAYS_THRESHOLD)),
        ),
    )


def _extract_near_term_driver_label(text: str) -> str | None:
    match = re.search(r"driven by (.+?) through", text)
    if not match:
        return None
    label = match.group(1).strip()
    return label or None


def translate_operating_focus(
    *,
    near_term_driver: dict[str, Any],
    long_range_concern: dict[str, Any],
    pressure_statement: dict[str, Any],
) -> dict[str, Any]:
    near_term_text = str(near_term_driver.get("text") or "").strip()
    if not near_term_text:
        return _suppressed_statement()
    label = _extract_near_term_driver_label(near_term_text)
    if not label:
        return _suppressed_statement()

    has_long_range = bool(long_range_concern.get("text"))
    has_pressure = bool(pressure_statement.get("text"))
    if has_long_range:
        return _statement(
            text=f"Our focus is protecting the {label} and validating newly critical long-range activities.",
            rule_id="O2",
            artifact="pm_translation_v1",
            fields=("near_term_driver.text", "long_range_concern.text"),
        )
    if has_pressure:
        return _statement(
            text=f"Our focus is protecting the {label} while monitoring rising internal schedule pressure.",
            rule_id="O2",
            artifact="pm_translation_v1",
            fields=("near_term_driver.text", "pressure_statement.text"),
        )
    return _suppressed_statement()


def extend_pm_translation_v1_phase32b(
    *,
    pm_translation_v1: dict[str, dict[str, Any]],
    data_date: Any,
    long_range_activities: tuple[dict[str, Any], ...],
    pressure_metrics: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    long_range = translate_long_range_concern(
        data_date=data_date,
        activities=long_range_activities,
    )
    pressure = translate_pressure_statement(
        movement=pm_translation_v1.get("movement", {}),
        pressure_metrics=pressure_metrics,
    )
    focus = translate_operating_focus(
        near_term_driver=pm_translation_v1.get("near_term_driver", {}),
        long_range_concern=long_range,
        pressure_statement=pressure,
    )
    return {
        **pm_translation_v1,
        "long_range_concern": long_range,
        "pressure_statement": pressure,
        "operating_focus": focus,
    }


def _compose_text(parts: tuple[str | None, ...]) -> str | None:
    present = [p.strip() for p in parts if isinstance(p, str) and p.strip()]
    if not present:
        return None
    return " ".join(present)


def _merge_sources(*entries: dict[str, Any]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        for source in entry.get("sources", []):
            key = repr(_jsonable(source))
            if key in seen:
                continue
            seen.add(key)
            merged.append(source)
    return merged


def _merge_rule_ids(*entries: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        rid = entry.get("rule_id")
        if not isinstance(rid, str) or not rid.strip():
            continue
        if rid in seen:
            continue
        seen.add(rid)
        out.append(rid)
    return out


def compose_finish_summary(pm_translation_v1: dict[str, dict[str, Any]]) -> dict[str, Any]:
    f1 = pm_translation_v1.get("finish_position", {})
    m1 = pm_translation_v1.get("movement", {})
    b1 = pm_translation_v1.get("baseline_status", {})
    text = _compose_text((f1.get("text"), m1.get("text"), b1.get("text")))
    if text is None:
        return {"text": None, "sources": [], "rule_ids": []}
    return {
        "text": text,
        "sources": _merge_sources(f1, m1, b1),
        "rule_ids": _merge_rule_ids(f1, m1, b1),
    }


def compose_driver_summary(pm_translation_v1: dict[str, dict[str, Any]]) -> dict[str, Any]:
    d1 = pm_translation_v1.get("near_term_driver", {})
    text = d1.get("text")
    if not isinstance(text, str) or not text.strip():
        return {"text": None, "sources": [], "rule_ids": []}
    return {
        "text": text,
        "sources": _merge_sources(d1),
        "rule_ids": _merge_rule_ids(d1),
    }


def compose_risk_summary(pm_translation_v1: dict[str, dict[str, Any]]) -> dict[str, Any]:
    l1 = pm_translation_v1.get("long_range_concern", {})
    p1 = pm_translation_v1.get("pressure_statement", {})
    text = _compose_text((l1.get("text"), p1.get("text")))
    if text is None:
        return {"text": None, "sources": [], "rule_ids": []}
    return {
        "text": text,
        "sources": _merge_sources(l1, p1),
        "rule_ids": _merge_rule_ids(l1, p1),
    }


def compose_need_summary(pm_translation_v1: dict[str, dict[str, Any]]) -> dict[str, Any]:
    l1 = pm_translation_v1.get("long_range_concern", {})
    if not isinstance(l1.get("text"), str) or not str(l1.get("text")).strip():
        return {"text": None, "sources": [], "rule_ids": []}
    return {
        "text": "This requires validation of newly critical long-range activities.",
        "sources": _merge_sources(l1),
        "rule_ids": _merge_rule_ids(l1),
    }


def compose_doing_summary(pm_translation_v1: dict[str, dict[str, Any]]) -> dict[str, Any]:
    o2 = pm_translation_v1.get("operating_focus", {})
    text = o2.get("text")
    if not isinstance(text, str) or not text.strip():
        return {"text": None, "sources": [], "rule_ids": []}
    return {
        "text": text,
        "sources": _merge_sources(o2),
        "rule_ids": _merge_rule_ids(o2),
    }


def compose_meeting_summary(
    *,
    finish_summary: dict[str, Any],
    driver_summary: dict[str, Any],
    risk_summary: dict[str, Any],
    need_summary: dict[str, Any],
    doing_summary: dict[str, Any],
) -> dict[str, Any]:
    meeting: dict[str, Any] = {}
    if isinstance(finish_summary.get("text"), str) and finish_summary.get("text").strip():
        meeting["finish"] = finish_summary["text"]
    if isinstance(driver_summary.get("text"), str) and driver_summary.get("text").strip():
        meeting["driver"] = driver_summary["text"]
    if isinstance(risk_summary.get("text"), str) and risk_summary.get("text").strip():
        meeting["risk"] = risk_summary["text"]
    if isinstance(need_summary.get("text"), str) and need_summary.get("text").strip():
        meeting["need"] = need_summary["text"]
    if isinstance(doing_summary.get("text"), str) and doing_summary.get("text").strip():
        meeting["doing"] = doing_summary["text"]
    meeting["sources"] = _merge_sources(
        finish_summary,
        driver_summary,
        risk_summary,
        need_summary,
        doing_summary,
    )
    rule_ids: list[str] = []
    seen: set[str] = set()
    for summary in (finish_summary, driver_summary, risk_summary, need_summary, doing_summary):
        for rid in summary.get("rule_ids", []):
            if not isinstance(rid, str) or rid in seen:
                continue
            seen.add(rid)
            rule_ids.append(rid)
    meeting["rule_ids"] = rule_ids
    return meeting


def extend_pm_translation_v1_phase32c(
    *,
    pm_translation_v1: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    finish_summary = compose_finish_summary(pm_translation_v1)
    driver_summary = compose_driver_summary(pm_translation_v1)
    risk_summary = compose_risk_summary(pm_translation_v1)
    need_summary = compose_need_summary(pm_translation_v1)
    doing_summary = compose_doing_summary(pm_translation_v1)
    meeting_summary = compose_meeting_summary(
        finish_summary=finish_summary,
        driver_summary=driver_summary,
        risk_summary=risk_summary,
        need_summary=need_summary,
        doing_summary=doing_summary,
    )
    return {
        **pm_translation_v1,
        "finish_summary": finish_summary,
        "driver_summary": driver_summary,
        "risk_summary": risk_summary,
        "need_summary": need_summary,
        "doing_summary": doing_summary,
        "meeting_summary": meeting_summary,
    }

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

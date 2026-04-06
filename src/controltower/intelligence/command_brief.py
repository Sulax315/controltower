from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from controltower.services.intelligence_packets import IntelligencePacketRecord

_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MD_ITAL = re.compile(r"\*([^*]+)\*")
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _section_md(packet: IntelligencePacketRecord, key: str) -> str:
    for sec in packet.sections:
        if sec.key == key:
            return sec.body_markdown.strip()
    return ""


def _strip_md(text: str) -> str:
    s = text.replace("\u2014", "-").strip()
    s = _MD_BOLD.sub(r"\1", s)
    s = _MD_ITAL.sub(r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def _clamp(text: str, max_len: int = 160) -> str:
    s = _strip_md(text)
    if not s:
        return ""
    if len(s) <= max_len:
        return s
    cut = s[: max_len - 1].rstrip()
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut + "…"


def _first_bullet(md: str) -> str:
    for ln in md.splitlines():
        t = ln.strip()
        if t.startswith("- "):
            return _clamp(t[2:], 200)
    return ""


def _first_non_empty_line(md: str) -> str:
    for ln in md.splitlines():
        t = _strip_md(ln)
        if t and not t.startswith("#"):
            return _clamp(t, 200)
    return ""


def _all_bullets(md: str, *, max_items: int = 24) -> list[str]:
    out: list[str] = []
    for ln in md.splitlines():
        t = ln.strip()
        if t.startswith("- "):
            s = _clamp(t[2:], 220)
            if s and s not in out:
                out.append(s)
        if len(out) >= max_items:
            break
    return out


def _line_items(md: str, *, max_items: int = 24) -> list[str]:
    bullets = _all_bullets(md, max_items=max_items)
    if bullets:
        return bullets
    out: list[str] = []
    for ln in md.splitlines():
        t = _strip_md(ln)
        if t and not t.startswith("#") and t not in out:
            out.append(_clamp(t, 220))
        if len(out) >= max_items:
            break
    return out


def _parse_first_number(text: str) -> float | None:
    m = _NUM_RE.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    low = (text or "").lower()
    return any(t in low for t in terms)


def _parse_iso_date(text: str) -> str | None:
    m = _ISO_DATE_RE.search(text or "")
    return m.group(1) if m else None


def _date_delta_days(current_iso: str | None, baseline_iso: str | None) -> int | None:
    if not current_iso or not baseline_iso:
        return None
    try:
        cur = datetime.strptime(current_iso, "%Y-%m-%d")
        base = datetime.strptime(baseline_iso, "%Y-%m-%d")
        return (cur - base).days
    except Exception:
        return None


def _baseline_finish_date(packet: IntelligencePacketRecord, intelligence_data: dict[str, Any]) -> str | None:
    # Priority: explicit rail_changed text, then broader summary text.
    for source in (
        str(intelligence_data.get("rail_changed") or ""),
        str(intelligence_data.get("intelligence_summary") or ""),
        _section_md(packet, "delta_vs_prior"),
    ):
        d = _parse_iso_date(source)
        if d:
            return d
    return None


def compute_schedule_variance(packet: IntelligencePacketRecord, intelligence_data: dict[str, Any]) -> dict[str, Any]:
    finish_md = _section_md(packet, "finish_milestone_outlook")
    delta_md = _section_md(packet, "delta_vs_prior")
    current_finish = _parse_iso_date(finish_md) or _parse_iso_date(delta_md)
    baseline_finish = _baseline_finish_date(packet, intelligence_data)
    delta_days = _date_delta_days(current_finish, baseline_finish)

    if delta_days is None:
        movement = "unknown"
    elif delta_days > 0:
        movement = "slip"
    elif delta_days < 0:
        movement = "gain"
    else:
        movement = "flat"

    confidence = "high" if current_finish and baseline_finish else ("medium" if current_finish else "low")
    rationale = _first_non_empty_line(delta_md) or _first_non_empty_line(finish_md)
    return {
        "current_finish_date": current_finish,
        "baseline_finish_date": baseline_finish,
        "finish_variance_days": delta_days,
        "finish_movement": movement,
        "confidence": confidence,
        "rationale": rationale,
    }


def compute_activity_changes(packet: IntelligencePacketRecord, intelligence_data: dict[str, Any]) -> list[dict[str, Any]]:
    key_drivers = _line_items(_section_md(packet, "key_drivers"), max_items=18)
    risks = _line_items(_section_md(packet, "near_term_risks"), max_items=18)
    changes: list[dict[str, Any]] = []
    for item in [*key_drivers, *risks]:
        low = item.lower()
        if _contains_any(low, ("slip", "delay", "late", "push")):
            direction = "negative"
            score = 3
        elif _contains_any(low, ("recover", "gain", "improv", "accelerate", "ahead")):
            direction = "positive"
            score = 2
        else:
            direction = "neutral"
            score = 1
        changes.append(
            {
                "activity": item,
                "direction": direction,
                "impact_score": score,
                "source": "key_drivers" if item in key_drivers else "near_term_risks",
            }
        )
    return changes


def detect_movement_clusters(activity_changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {
        "negative": [],
        "positive": [],
        "neutral": [],
    }
    for item in activity_changes:
        buckets[item.get("direction", "neutral")].append(item)
    clusters: list[dict[str, Any]] = []
    for key in ("negative", "positive", "neutral"):
        members = buckets[key]
        if not members:
            continue
        clusters.append(
            {
                "cluster_key": key,
                "count": len(members),
                "total_impact": sum(int(m.get("impact_score") or 0) for m in members),
                "members": members,
            }
        )
    return clusters


def extract_top_movements(
    schedule_variance: dict[str, Any],
    movement_clusters: list[dict[str, Any]],
    *,
    max_items: int = 5,
) -> list[str]:
    items: list[tuple[int, str]] = []
    delta_days = schedule_variance.get("finish_variance_days")
    move = schedule_variance.get("finish_movement")
    if delta_days is not None:
        if move == "slip":
            items.append((100 + abs(int(delta_days)), f"Finish slipped by {int(delta_days)}d"))
        elif move == "gain":
            items.append((90 + abs(int(delta_days)), f"Finish gained {abs(int(delta_days))}d"))
        elif move == "flat":
            items.append((50, "Finish held vs baseline"))
    for cluster in movement_clusters:
        score = int(cluster.get("total_impact") or 0) + int(cluster.get("count") or 0)
        label = f"{cluster['cluster_key'].title()} movement cluster ({cluster['count']} signals)"
        items.append((score, label))
    ranked = sorted(items, key=lambda x: x[0], reverse=True)
    return [label for _, label in ranked[:max_items]]


def build_lookahead_window(packet: IntelligencePacketRecord, intelligence_data: dict[str, Any]) -> list[str]:
    decisions = _line_items(_section_md(packet, "required_decisions"), max_items=10)
    actions = _line_items(_section_md(packet, "action_register"), max_items=10)
    rail = _line_items(str(intelligence_data.get("rail_do") or ""), max_items=6)
    lookahead = []
    for item in [*decisions, *actions, *rail]:
        s = _clamp(item, 180)
        if s and s not in lookahead:
            lookahead.append(s)
        if len(lookahead) >= 6:
            break
    return lookahead


def analyze_critical_path(packet: IntelligencePacketRecord, activity_changes: list[dict[str, Any]]) -> dict[str, Any]:
    finish_md = _section_md(packet, "finish_milestone_outlook")
    drivers_md = _section_md(packet, "key_drivers")
    lines = [*(_line_items(finish_md, max_items=12)), *(_line_items(drivers_md, max_items=12))]
    cp_signals = [ln for ln in lines if _contains_any(ln, ("critical path", "float", "constraint", "driver"))]
    at_risk = any(c.get("direction") == "negative" for c in activity_changes) and bool(cp_signals)
    return {
        "is_critical_path_at_risk": at_risk,
        "critical_signals": cp_signals[:6],
        "primary_constraint": cp_signals[0] if cp_signals else (_first_non_empty_line(drivers_md) or "No controlling constraint detected"),
    }


def generate_narrative(
    *,
    schedule_variance: dict[str, Any],
    top_movements: list[str],
    lookahead_window: list[str],
    critical_path_analysis: dict[str, Any],
) -> dict[str, str]:
    finish_date = schedule_variance.get("current_finish_date") or "unavailable"
    move = schedule_variance.get("finish_movement")
    delta_days = schedule_variance.get("finish_variance_days")
    if move == "slip" and delta_days is not None:
        finish_line = f"Projected finish is {finish_date} ({int(delta_days)}d slip vs baseline)."
    elif move == "gain" and delta_days is not None:
        finish_line = f"Projected finish is {finish_date} ({abs(int(delta_days))}d gain vs baseline)."
    elif move == "flat":
        finish_line = f"Projected finish is {finish_date} (no baseline movement)."
    else:
        finish_line = f"Projected finish is {finish_date} (baseline movement unresolved)."

    movement_line = top_movements[0] if top_movements else "No ranked movement extracted."
    cp_line = critical_path_analysis.get("primary_constraint") or "No controlling constraint detected."
    lookahead_line = lookahead_window[0] if lookahead_window else "No immediate action candidate extracted."

    headline = f"{finish_line} Top movement: {movement_line}."
    why = f"Controlling path signal: {cp_line}."
    action = f"Next action focus: {lookahead_line}."
    return {
        "headline": _clamp(headline, 260),
        "why_it_matters": _clamp(why, 240),
        "action_statement": _clamp(action, 240),
    }


def assemble_command_brief(
    *,
    packet: IntelligencePacketRecord,
    intelligence_data: dict[str, Any],
    schedule_variance: dict[str, Any],
    activity_changes: list[dict[str, Any]],
    movement_clusters: list[dict[str, Any]],
    top_movements: list[str],
    lookahead_window: list[str],
    critical_path_analysis: dict[str, Any],
    narrative: dict[str, str],
) -> dict[str, Any]:
    driver = critical_path_analysis.get("primary_constraint") or ""
    risks = _first_bullet(_section_md(packet, "near_term_risks")) or _first_non_empty_line(_section_md(packet, "near_term_risks"))
    need = lookahead_window[0] if lookahead_window else ""
    doing = lookahead_window[1] if len(lookahead_window) > 1 else need
    finish_legacy = schedule_variance.get("current_finish_date") or ""
    delta_days = schedule_variance.get("finish_variance_days")
    if delta_days is not None:
        finish_legacy = f"{finish_legacy} Δ {int(delta_days)}d".strip()

    return {
        "schema_version": "command_brief.v2",
        "packet_id": packet.packet_id,
        "project_code": packet.canonical_project_code,
        "project_name": packet.project_name,
        "reporting_period": packet.reporting_period,
        "schedule_variance": schedule_variance,
        "activity_changes": activity_changes,
        "movement_clusters": movement_clusters,
        "top_movements": top_movements,
        "lookahead_window": lookahead_window,
        "critical_path_analysis": critical_path_analysis,
        "narrative": narrative,
        # Backward-compatible fields used by current templates/helpers.
        "finish": _clamp(finish_legacy, 220),
        "driver": _clamp(driver, 200),
        "risks": _clamp(risks, 200),
        "need": _clamp(need, 200),
        "doing": _clamp(doing, 200),
    }


def build_command_brief(packet: IntelligencePacketRecord, intelligence_data: dict[str, Any]) -> dict[str, Any]:
    schedule_variance = compute_schedule_variance(packet, intelligence_data)
    activity_changes = compute_activity_changes(packet, intelligence_data)
    movement_clusters = detect_movement_clusters(activity_changes)
    top_movements = extract_top_movements(schedule_variance, movement_clusters)
    lookahead_window = build_lookahead_window(packet, intelligence_data)
    critical_path_analysis = analyze_critical_path(packet, activity_changes)
    narrative = generate_narrative(
        schedule_variance=schedule_variance,
        top_movements=top_movements,
        lookahead_window=lookahead_window,
        critical_path_analysis=critical_path_analysis,
    )
    return assemble_command_brief(
        packet=packet,
        intelligence_data=intelligence_data,
        schedule_variance=schedule_variance,
        activity_changes=activity_changes,
        movement_clusters=movement_clusters,
        top_movements=top_movements,
        lookahead_window=lookahead_window,
        critical_path_analysis=critical_path_analysis,
        narrative=narrative,
    )

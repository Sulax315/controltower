from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from controltower.config import ObsidianConfig
from controltower.domain.models import utc_now_iso
from controltower.services.intelligence_packets import IntelligencePacketRecord
from controltower.services.runtime_state import ensure_runtime_layout, write_json

logger = logging.getLogger(__name__)

_WIN_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_LEGACY_PACKET_TAIL = re.compile(r"\s*—\s*_Packet:_\s*(\[\[[^\]]+\]\])\s*$")
_RISK_FP_MARK = re.compile(r"<!--\s*ct-risk-fp:([^>]+)\s*-->")
_ACT_FP_MARK = re.compile(r"<!--\s*ct-act-fp:([^>]+)\s*-->")


@dataclass
class _RiskSection:
    fp: str
    title: str
    first_seen: str
    latest_seen: str
    status: str
    history_rows: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class _ActionSection:
    fp: str
    title: str
    role: str
    action: str
    timing: str
    continuity: str
    first_seen: str
    latest_seen: str
    status: str
    history_rows: list[tuple[str, str, str]] = field(default_factory=list)


def intelligence_vault_project_slug(*, canonical_project_code: str, project_name: str) -> str:
    code = (canonical_project_code or "").strip()
    base = code if code else (project_name or "project")
    s = base.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "project"


def project_slug_for_record(record: IntelligencePacketRecord) -> str:
    return intelligence_vault_project_slug(
        canonical_project_code=record.canonical_project_code or "",
        project_name=record.project_name or "",
    )


def packet_note_stem(packet_date: str, packet_id: str) -> str:
    return f"{packet_date} — {packet_id}"


def intelligence_packet_note_stem(record: IntelligencePacketRecord) -> str:
    return packet_note_stem(_packet_iso_date(record), record.packet_id)


def _packet_iso_date(record: IntelligencePacketRecord) -> str:
    raw = (record.created_at or "").strip()
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    return raw[:10] if raw else "unknown-date"


def _section_body(record: IntelligencePacketRecord, key: str) -> str:
    for sec in record.sections:
        if sec.key == key:
            return sec.body_markdown.strip()
    return ""


def _wikilink(path_without_ext: str) -> str:
    inner = path_without_ext.replace("]]", "")
    return f"[[{inner}]]"


def _alias_frontmatter(aliases: list[str]) -> str:
    return "---\n" + yaml.safe_dump({"aliases": aliases}, allow_unicode=True, sort_keys=False) + "---\n\n"


def _project_aliases(project_name: str) -> tuple[str, str, str]:
    return (
        f"{project_name} — Project Index",
        f"{project_name} — Active Risks",
        f"{project_name} — Action Register",
    )


def _packet_yaml_frontmatter(
    record: IntelligencePacketRecord,
    *,
    packet_date: str,
    project_slug: str,
) -> str:
    fm: dict[str, Any] = {
        "type": "controltower_packet",
        "packet_id": record.packet_id,
        "project": record.project_name.strip(),
        "project_slug": project_slug,
        "date": packet_date,
        "status": "published",
    }
    if record.canonical_project_code:
        fm["canonical_project_code"] = record.canonical_project_code
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n"


def _build_obsidian_packet_markdown(
    record: IntelligencePacketRecord,
    packet_date: str,
    *,
    project_slug: str,
) -> str:
    pn = record.project_name.strip()
    nav = (
        f"*Project:* {_wikilink('../00 Project Index')} · "
        f"*Risks:* {_wikilink('../02 Risks/Active Risks')} · "
        f"*Actions:* {_wikilink('../03 Actions/Action Register')}"
    )
    exec_s = _section_body(record, "executive_summary")
    finish = _section_body(record, "finish_milestone_outlook")
    delta = _section_body(record, "delta_vs_prior")
    drivers = _section_body(record, "key_drivers")
    risks = _section_body(record, "near_term_risks")
    decisions = _section_body(record, "required_decisions")
    actions = _section_body(record, "action_register")
    evidence = _section_body(record, "source_evidence_appendix")

    finish_block = finish
    if delta:
        finish_block = (finish + "\n\n### Movement vs prior\n\n" + delta).strip()

    required_actions_block = ""
    if decisions:
        required_actions_block += "### Decisions / asks\n\n" + decisions
    if actions:
        if required_actions_block:
            required_actions_block += "\n\n### Action register (queue)\n\n" + actions
        else:
            required_actions_block = actions

    fm = _packet_yaml_frontmatter(record, packet_date=packet_date, project_slug=project_slug)
    parts = [
        fm.rstrip(),
        "",
        f"# {pn} — Intelligence Packet",
        "",
        f"Date: {packet_date}",
        "",
        nav,
        "",
        "## Executive Summary",
        "",
        exec_s or "_No content._",
        "",
        "## Finish Outlook",
        "",
        finish_block or "_No content._",
        "",
        "## Key Drivers",
        "",
        drivers or "_No content._",
        "",
        "## Risks",
        "",
        risks or "_No content._",
        "",
        "## Required Actions",
        "",
        required_actions_block.strip() or "_No content._",
        "",
        "## Evidence",
        "",
        evidence or "_No content._",
        "",
    ]
    return "\n".join(parts).rstrip() + "\n"


def _current_status_snippet(record: IntelligencePacketRecord, *, max_chars: int = 480) -> str:
    body = _section_body(record, "executive_summary")
    one_line = " ".join(body.split())
    if len(one_line) <= max_chars:
        return one_line or "_No executive summary._"
    return one_line[: max_chars - 1].rstrip() + "…"


def _extract_risk_bullets(near_term_risks_md: str) -> list[str]:
    out: list[str] = []
    for line in near_term_risks_md.splitlines():
        s = line.strip()
        if not s.startswith("- "):
            continue
        if "_No elevated issue" in s:
            continue
        out.append(s)
    return out


def _risk_fingerprint_from_bullet(bullet: str) -> str:
    b = bullet.strip()
    if b.startswith("- "):
        b = b[2:]
    b = re.sub(r"\s*—\s*_Packet:_\s*\[\[[^\]]+\]\]\s*$", "", b)
    return re.sub(r"\s+", " ", b).strip().lower()


def _risk_display_title(bullet: str) -> str:
    b = bullet.strip()
    if b.startswith("- "):
        b = b[2:]
    b = re.sub(r"\s*—\s*_Packet:_\s*\[\[[^\]]+\]\]\s*$", "", b)
    b = re.sub(r"\s+", " ", b).strip()
    return (b[:120] if len(b) > 120 else b) or "Risk"


def _split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", text
    for i, ln in enumerate(lines[1:], 1):
        if ln.strip() == "---":
            fm = "\n".join(lines[: i + 1])
            body = "\n".join(lines[i + 1 :])
            return fm + "\n\n", body
    return "", text


def _parse_frontmatter_dict(fm_block: str) -> dict[str, Any]:
    if not fm_block.strip().startswith("---"):
        return {}
    lines = fm_block.strip().splitlines()
    inner: list[str] = []
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        inner.append(ln)
    if not inner:
        return {}
    try:
        loaded = yaml.safe_load("\n".join(inner))
        return loaded if isinstance(loaded, dict) else {}
    except yaml.YAMLError:
        return {}


def _extract_packet_id_from_cell(cell: str) -> str | None:
    m = re.search(r"(pkt_[0-9a-f]{32})", cell)
    return m.group(1) if m else None


def _wikilink_intel_from_risks(stem: str) -> str:
    return _wikilink(f"../01 Intelligence/{stem}")


def _wikilink_intel_from_timeline(stem: str) -> str:
    return _wikilink(f"../01 Intelligence/{stem}")


def _wikilink_intel_from_actions(stem: str) -> str:
    return _wikilink(f"../01 Intelligence/{stem}")


def _parse_risk_history_table(chunk_lines: list[str]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    in_hist = False
    for ln in chunk_lines:
        if ln.strip() == "### History":
            in_hist = True
            continue
        if not in_hist:
            continue
        s = ln.strip()
        if not s.startswith("|"):
            continue
        if s.startswith("|---") or ("Packet" in s and "Note" in s):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 2:
            continue
        link_cell, note_cell = parts[0], parts[1]
        pid = _extract_packet_id_from_cell(link_cell)
        if not pid:
            continue
        rows.append((link_cell, note_cell, pid))
    return rows


def _parse_risk_section_body(title: str, fp: str, chunk_lines: list[str]) -> _RiskSection:
    first = ""
    latest = ""
    status = "Active"
    hist_start: int | None = None
    for i, ln in enumerate(chunk_lines):
        t = ln.strip()
        if t.startswith("- First Seen:"):
            first = t.split(":", 1)[1].strip()
        elif t.startswith("- Latest Seen:"):
            latest = t.split(":", 1)[1].strip()
        elif t.startswith("- Status:"):
            status = t.split(":", 1)[1].strip() or "Active"
        elif t == "### History":
            hist_start = i
            break
    hist_lines = chunk_lines[hist_start:] if hist_start is not None else []
    history = _parse_risk_history_table(hist_lines)
    return _RiskSection(fp=fp, title=title, first_seen=first, latest_seen=latest, status=status, history_rows=history)


def _parse_longitudinal_risk_sections(body: str) -> dict[str, _RiskSection]:
    sections: dict[str, _RiskSection] = {}
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("## "):
            title = ln[3:].strip()
            i += 1
            if i >= len(lines):
                break
            mfp = _RISK_FP_MARK.search(lines[i])
            if not mfp:
                i += 1
                continue
            fp = mfp.group(1).strip()
            i += 1
            chunk: list[str] = []
            while i < len(lines) and not lines[i].startswith("## "):
                chunk.append(lines[i])
                i += 1
            sections[fp] = _parse_risk_section_body(title, fp, chunk)
            continue
        i += 1
    return sections


def _collect_legacy_risk_bullets(body: str) -> list[str]:
    bullets: list[str] = []
    lines = body.splitlines()
    in_header = False
    for ln in lines:
        if ln.startswith("# Active Risks"):
            in_header = True
            continue
        if not in_header:
            continue
        if ln.startswith("## "):
            break
        s = ln.strip()
        if s.startswith("- "):
            bullets.append(s)
    return bullets


def _legacy_bullet_to_section(bullet: str) -> _RiskSection | None:
    fp = _risk_fingerprint_from_bullet(bullet)
    if not fp:
        return None
    title = _risk_display_title(bullet)
    m = _LEGACY_PACKET_TAIL.search(bullet.strip())
    link = m.group(1).strip() if m else ""
    if not link:
        return None
    pid = _extract_packet_id_from_cell(link) or ""
    hist = [(link, "Initial detection", pid)] if pid else [(link, "Initial detection", "")]
    return _RiskSection(
        fp=fp,
        title=title,
        first_seen=link,
        latest_seen=link,
        status="Active",
        history_rows=hist,
    )


def _serialize_risk_section(sec: _RiskSection) -> str:
    lines = [
        f"## {sec.title}",
        f"<!-- ct-risk-fp:{sec.fp} -->",
        "",
        f"- First Seen: {sec.first_seen}",
        f"- Latest Seen: {sec.latest_seen}",
        f"- Status: {sec.status}",
        "",
        "### History",
        "| Packet | Note |",
        "|---|---|",
    ]
    for link_cell, note_cell, _pid in sec.history_rows:
        lines.append(f"| {link_cell} | {note_cell} |")
    return "\n".join(lines)


def _merge_risk_register_longitudinal(
    existing_text: str,
    new_bullets: list[str],
    packet_stem: str,
    packet_id: str,
) -> str:
    fm, body = _split_frontmatter(existing_text)
    body = body.strip()
    if not body:
        body = "# Active Risks\n\nRunning register (deduplicated across packets).\n"
    elif not body.lstrip().startswith("#"):
        body = "# Active Risks\n\n" + body

    header_lines: list[str] = []
    rest_lines: list[str] = body.splitlines()
    for idx, ln in enumerate(rest_lines):
        if ln.startswith("# Active Risks"):
            header_lines = rest_lines[: idx + 1]
            rest_lines = rest_lines[idx + 1 :]
            break
    intro: list[str] = []
    for ln in rest_lines:
        if ln.startswith("## "):
            break
        intro.append(ln)
    rest_body = "\n".join(rest_lines[len(intro) :]).strip()

    sections = _parse_longitudinal_risk_sections(rest_body)
    if not sections:
        for leg in _collect_legacy_risk_bullets(body):
            sec = _legacy_bullet_to_section(leg)
            if sec and sec.fp not in sections:
                sections[sec.fp] = sec

    link = _wikilink_intel_from_risks(packet_stem)
    for bullet in new_bullets:
        fp = _risk_fingerprint_from_bullet(bullet)
        if not fp:
            continue
        title = _risk_display_title(bullet)
        if fp not in sections:
            sections[fp] = _RiskSection(
                fp=fp,
                title=title,
                first_seen=link,
                latest_seen=link,
                status="Active",
                history_rows=[(link, "Initial detection", packet_id)],
            )
            continue
        sec = sections[fp]
        if not sec.first_seen.strip():
            sec.first_seen = link
        sec.latest_seen = link
        if not any(r[2] == packet_id for r in sec.history_rows):
            note = "Initial detection" if len(sec.history_rows) == 0 else "Still active"
            sec.history_rows.append((link, note, packet_id))

    serialized = "\n\n".join(_serialize_risk_section(sections[k]) for k in sorted(sections.keys()))
    intro_txt = "\n".join(line for line in intro if line.strip()).strip()
    core_parts = ["\n".join(header_lines)]
    if intro_txt:
        core_parts.append(intro_txt)
    if serialized:
        core_parts.append(serialized)
    core = "\n\n".join(p for p in core_parts if p).rstrip() + "\n"
    return (fm + core).strip() + "\n" if fm else core.strip() + "\n"


_ACTION_HEAD = re.compile(r"^- \*\*(.+?)\*\*:\s*(.*)$")


def _parse_timing_line(line: str) -> tuple[str, str, str] | None:
    s = line.strip()
    m = re.search(
        r"_Timing:_\s*(.+?)\s*·\s*_Signal:_\s*(.+?)\s*·\s*_Continuity:_\s*(.+)$",
        s,
    )
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip(), m.group(3).strip()


def _action_fingerprint(role: str, action: str, timing: str, continuity: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        " | ".join(
            [
                role.strip().lower(),
                action.strip().lower(),
                timing.strip().lower(),
                continuity.strip().lower(),
            ]
        ),
    ).strip()


def _extract_actions_from_markdown(md: str, *, default_continuity: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        if raw.strip().startswith("### "):
            i += 1
            continue
        m = _ACTION_HEAD.match(raw.rstrip())
        if not m:
            i += 1
            continue
        role = m.group(1).strip()
        action_line = m.group(2).strip()
        timing = "—"
        signal = "—"
        continuity = default_continuity
        if i + 1 < len(lines):
            parsed = _parse_timing_line(lines[i + 1])
            if parsed:
                timing, signal, continuity = parsed
                i += 2
                items.append(
                    {
                        "role": role,
                        "action": action_line,
                        "timing": timing,
                        "signal": signal,
                        "continuity": continuity,
                    }
                )
                continue
        i += 1
        items.append(
            {
                "role": role,
                "action": action_line,
                "timing": timing,
                "signal": signal,
                "continuity": continuity,
            }
        )
    return items


def _action_display_title(action: str) -> str:
    one = re.sub(r"\s+", " ", action.strip())
    return (one[:100] if len(one) > 100 else one) or "Action"


def _parse_action_section_body(title: str, fp: str, chunk_lines: list[str]) -> _ActionSection:
    role = action = timing = continuity = ""
    first = latest = ""
    status = "Open"
    hist_start: int | None = None
    for i, ln in enumerate(chunk_lines):
        t = ln.strip()
        if t.startswith("- **Role:**"):
            role = t.replace("- **Role:**", "").strip()
        elif t.startswith("- **Action:**"):
            action = t.replace("- **Action:**", "").strip()
        elif t.startswith("- **Timing:**"):
            timing = t.replace("- **Timing:**", "").strip()
        elif t.startswith("- **Continuity:**"):
            continuity = t.replace("- **Continuity:**", "").strip()
        elif t.startswith("- First Seen:"):
            first = t.split(":", 1)[1].strip()
        elif t.startswith("- Latest Seen:"):
            latest = t.split(":", 1)[1].strip()
        elif t.startswith("- **Status:**") or t.startswith("- Status:"):
            status = t.split(":", 1)[1].strip() or "Open"
        elif t == "### History":
            hist_start = i
            break
    hist_lines = chunk_lines[hist_start:] if hist_start is not None else []
    history = _parse_risk_history_table(hist_lines)
    return _ActionSection(
        fp=fp,
        title=title,
        role=role,
        action=action,
        timing=timing,
        continuity=continuity,
        first_seen=first,
        latest_seen=latest,
        status=status,
        history_rows=history,
    )


def _parse_longitudinal_action_sections(body: str) -> dict[str, _ActionSection]:
    sections: dict[str, _ActionSection] = {}
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("## "):
            title = ln[3:].strip()
            i += 1
            if i >= len(lines):
                break
            mfp = _ACT_FP_MARK.search(lines[i])
            if not mfp:
                i += 1
                continue
            fp = mfp.group(1).strip()
            i += 1
            chunk: list[str] = []
            while i < len(lines) and not lines[i].startswith("## "):
                chunk.append(lines[i])
                i += 1
            sections[fp] = _parse_action_section_body(title, fp, chunk)
            continue
        i += 1
    return sections


def _action_line_fingerprint_legacy(md_line: str) -> str | None:
    s = md_line.strip()
    if not s.startswith("- **"):
        return None
    s = re.sub(r"\s*—\s*_Packet:_\s*\[\[[^\]]+\]\]\s*$", "", s)
    m = _ACTION_HEAD.match(s)
    if not m:
        return None
    role = m.group(1).strip()
    rest = m.group(2).strip()
    t_match = re.search(
        r"_Timing:_\s*(.+?)\s*·\s*_Signal:_\s*(.+?)\s*·\s*_Continuity:_\s*(.+?)(?:\s*—|\s*$)",
        rest,
    )
    if t_match:
        action_only = rest.split("_Timing:_")[0].strip().rstrip("—").strip()
        return _action_fingerprint(role, action_only, t_match.group(1), t_match.group(3))
    return _action_fingerprint(role, rest, "—", "—")


def _legacy_action_line_to_section(line: str) -> _ActionSection | None:
    fp = _action_line_fingerprint_legacy(line)
    if not fp:
        return None
    m = _ACTION_HEAD.match(line.strip())
    if not m:
        return None
    role = m.group(1).strip()
    rest = m.group(2).strip()
    timing, _sig, cont = "—", "—", "—"
    t_match = re.search(
        r"_Timing:_\s*(.+?)\s*·\s*_Signal:_\s*(.+?)\s*·\s*_Continuity:_\s*(.+?)(?:\s*—|\s*$)",
        rest,
    )
    if t_match:
        action_only = rest.split("_Timing:_")[0].strip().rstrip("—").strip()
        timing, _sig, cont = t_match.group(1), t_match.group(2), t_match.group(3)
    else:
        action_only = rest
    pkt_m = re.search(r"_Packet:_\s*(\[\[[^\]]+\]\])", line)
    link = pkt_m.group(1).strip() if pkt_m else ""
    if not link:
        return None
    pid = _extract_packet_id_from_cell(link) or ""
    title = _action_display_title(action_only)
    hist = [(link, "Logged", pid)] if pid else [(link, "Logged", "")]
    return _ActionSection(
        fp=fp,
        title=title,
        role=role,
        action=action_only,
        timing=timing,
        continuity=cont,
        first_seen=link,
        latest_seen=link,
        status="Open",
        history_rows=hist,
    )


def _collect_legacy_action_lines(body: str) -> list[str]:
    out: list[str] = []
    lines = body.splitlines()
    in_header = False
    for ln in lines:
        if ln.startswith("# Action Register"):
            in_header = True
            continue
        if not in_header:
            continue
        if ln.startswith("## "):
            break
        if ln.strip().startswith("- **"):
            out.append(ln.strip())
    return out


def _serialize_action_section(sec: _ActionSection) -> str:
    lines = [
        f"## {sec.title}",
        f"<!-- ct-act-fp:{sec.fp} -->",
        "",
        f"- **Role:** {sec.role}",
        f"- **Action:** {sec.action}",
        f"- **Timing:** {sec.timing}",
        f"- **Continuity:** {sec.continuity}",
        f"- First Seen: {sec.first_seen}",
        f"- Latest Seen: {sec.latest_seen}",
        f"- **Status:** {sec.status}",
        "",
        "### History",
        "| Packet | Note |",
        "|---|---|",
    ]
    for link_cell, note_cell, _pid in sec.history_rows:
        lines.append(f"| {link_cell} | {note_cell} |")
    return "\n".join(lines)


def _merge_action_register_longitudinal(
    existing_text: str,
    new_items: list[dict[str, str]],
    packet_stem: str,
    packet_id: str,
) -> str:
    fm, body = _split_frontmatter(existing_text)
    body = body.strip()
    if not body:
        body = "# Action Register\n\nRunning action register (deduplicated across packets).\n"
    elif not body.lstrip().startswith("#"):
        body = "# Action Register\n\n" + body

    header_lines: list[str] = []
    rest_lines: list[str] = body.splitlines()
    for idx, ln in enumerate(rest_lines):
        if ln.startswith("# Action Register"):
            header_lines = rest_lines[: idx + 1]
            rest_lines = rest_lines[idx + 1 :]
            break
    intro: list[str] = []
    for ln in rest_lines:
        if ln.startswith("## "):
            break
        intro.append(ln)
    rest_body = "\n".join(rest_lines[len(intro) :]).strip()

    sections = _parse_longitudinal_action_sections(rest_body)
    if not sections:
        for leg in _collect_legacy_action_lines(body):
            sec = _legacy_action_line_to_section(leg)
            if sec and sec.fp not in sections:
                sections[sec.fp] = sec

    link = _wikilink_intel_from_actions(packet_stem)
    for it in new_items:
        fp = _action_fingerprint(it["role"], it["action"], it["timing"], it["continuity"])
        title = _action_display_title(it["action"])
        if fp not in sections:
            sections[fp] = _ActionSection(
                fp=fp,
                title=title,
                role=it["role"],
                action=it["action"],
                timing=it["timing"],
                continuity=it["continuity"],
                first_seen=link,
                latest_seen=link,
                status="Open",
                history_rows=[(link, "Logged", packet_id)],
            )
            continue
        sec = sections[fp]
        sec.role = it["role"]
        sec.action = it["action"]
        sec.timing = it["timing"]
        sec.continuity = it["continuity"]
        if not sec.first_seen.strip():
            sec.first_seen = link
        sec.latest_seen = link
        if not any(r[2] == packet_id for r in sec.history_rows):
            note = "Logged" if len(sec.history_rows) == 0 else "Updated"
            sec.history_rows.append((link, note, packet_id))

    serialized = "\n\n".join(_serialize_action_section(sections[k]) for k in sorted(sections.keys()))
    intro_txt = "\n".join(line for line in intro if line.strip()).strip()
    core_parts = ["\n".join(header_lines)]
    if intro_txt:
        core_parts.append(intro_txt)
    if serialized:
        core_parts.append(serialized)
    core = "\n\n".join(p for p in core_parts if p).rstrip() + "\n"
    return (fm + core).strip() + "\n" if fm else core.strip() + "\n"


def _append_timeline(timeline_path: Path, packet_date: str, packet_stem: str, packet_id: str, status: str) -> None:
    marker = f"<!-- ct-packet:{packet_id} -->"
    wl = _wikilink_intel_from_timeline(packet_stem)
    line = f"- {packet_date} — {wl} — {status} {marker}"

    if timeline_path.exists():
        cur = timeline_path.read_text(encoding="utf-8")
        if marker in cur:
            updated_lines: list[str] = []
            for ln in cur.splitlines():
                if marker in ln:
                    updated_lines.append(line)
                else:
                    updated_lines.append(ln)
            timeline_path.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")
            return
        timeline_path.write_text(cur.rstrip() + "\n\n" + line + "\n", encoding="utf-8")
        return

    timeline_path.write_text("# Timeline\n\n" + line + "\n", encoding="utf-8")


def _finish_outlook_cell(record: IntelligencePacketRecord) -> str:
    body = _section_body(record, "finish_milestone_outlook")
    m = re.search(r"\*\*Projected finish:\*\*\s*(.+)", body)
    if m:
        return m.group(1).strip()
    return "—"


def _risk_posture_cell(record: IntelligencePacketRecord) -> str:
    body = _section_body(record, "executive_summary")
    m = re.search(r"risk\s+\*\*(\w+)\*\*", body, re.IGNORECASE)
    if m:
        return m.group(1).title()
    return "—"


def _list_intel_packet_stems(intel_dir: Path) -> list[str]:
    """Return packet note stems newest-first using file mtimes (ties: stem ascending)."""
    if not intel_dir.is_dir():
        return []
    entries: list[tuple[float, str]] = []
    for p in intel_dir.glob("*.md"):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        entries.append((mtime, p.stem))
    entries.sort(key=lambda t: (-t[0], t[1]))
    return [stem for _mtime, stem in entries]


def _write_project_index(
    path: Path,
    *,
    project_name: str,
    project_slug: str,
    packet_stems_desc: list[str],
    status_snippet: str,
    record: IntelligencePacketRecord,
    packet_date: str,
) -> None:
    idx_a, _risks_a, _act_a = _project_aliases(project_name)
    latest_stem = packet_stems_desc[0] if packet_stems_desc else ""
    fm = {
        "aliases": [idx_a],
        "project_name": project_name,
        "project_slug": project_slug,
        "latest_packet_stem": latest_stem,
        "finish_outlook": _finish_outlook_cell(record),
        "risk_posture": _risk_posture_cell(record),
        "portfolio_updated": packet_date,
    }
    fm_yaml = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n"
    history_block = ""
    if packet_stems_desc:
        hist_lines = [f"- {_wikilink(f'01 Intelligence/{s}')}" for s in packet_stems_desc]
        history_block = "## Packet History\n\n" + "\n".join(hist_lines) + "\n\n"
    latest_block = (
        f"## Latest Packet\n\n{_wikilink(f'01 Intelligence/{latest_stem}')}\n\n" if latest_stem else "## Latest Packet\n\n_No packets yet._\n\n"
    )
    finish_cell = _finish_outlook_cell(record)
    risk_cell = _risk_posture_cell(record)
    body = (
        fm_yaml
        + f"# {project_name}\n\n"
        + "## Current Status\n\n"
        + f"{status_snippet}\n\n"
        + "## Finish Outlook\n\n"
        + f"{finish_cell}\n\n"
        + "## Risk Posture\n\n"
        + f"{risk_cell}\n\n"
        + latest_block
        + history_block
        + "## Active Risks\n\n"
        + f"{_wikilink('02 Risks/Active Risks')}\n\n"
        + "## Actions\n\n"
        + f"{_wikilink('03 Actions/Action Register')}\n\n"
        + "## Timeline\n\n"
        + f"{_wikilink('04 History/Timeline')}\n"
    )
    path.write_text(body, encoding="utf-8")


def _rebuild_portfolio_index(vault: Path, projects_folder: str) -> Path:
    base = vault / projects_folder.strip().strip("/\\")
    base.mkdir(parents=True, exist_ok=True)
    index_path = base / "_Index.md"
    rows: list[str] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        slug = child.name
        if slug.startswith("_") or slug.startswith("."):
            continue
        pidx = child / "00 Project Index.md"
        if not pidx.is_file():
            continue
        raw = pidx.read_text(encoding="utf-8")
        fm, _body = _split_frontmatter(raw)
        meta = _parse_frontmatter_dict(fm)
        latest_stem = str(meta.get("latest_packet_stem") or "")
        finish = str(meta.get("finish_outlook") or "—")
        risk = str(meta.get("risk_posture") or "—")
        updated = str(meta.get("portfolio_updated") or "—")
        proj_link = f"[[{slug}/00 Project Index]]"
        if latest_stem:
            pkt_link = _wikilink(f"{slug}/01 Intelligence/{latest_stem}")
        else:
            pkt_link = "—"
        rows.append(f"| {proj_link} | {pkt_link} | {finish} | {risk} | {updated} |")

    table = "\n".join(rows) if rows else "| — | — | — | — | — |"
    content = (
        "# Control Tower Portfolio\n\n"
        "| Project | Latest Packet | Finish | Risk | Updated |\n"
        "|---|---|---|---|---|\n"
        f"{table}\n"
    )
    index_path.write_text(content, encoding="utf-8")
    return index_path


def _planned_export_paths(
    *,
    vault: Path,
    projects_folder: str,
    project_slug: str,
    packet_stem: str,
) -> dict[str, str]:
    base = vault / projects_folder.strip().strip("/\\") / project_slug
    intel_dir = base / "01 Intelligence"
    packet_path = intel_dir / f"{packet_stem}.md"
    index_path = base / "00 Project Index.md"
    risks_path = base / "02 Risks" / "Active Risks.md"
    actions_path = base / "03 Actions" / "Action Register.md"
    timeline_path = base / "04 History" / "Timeline.md"
    global_index = vault / projects_folder.strip().strip("/\\") / "_Index.md"
    return {
        "packet": str(packet_path),
        "project_index": str(index_path),
        "risks": str(risks_path),
        "actions": str(actions_path),
        "timeline": str(timeline_path),
        "global_index": str(global_index),
    }


def _write_export_evidence(
    state_root: Path,
    *,
    packet_id: str,
    project_slug: str,
    paths: dict[str, str],
    success: bool,
    error: str | None = None,
) -> None:
    ensure_runtime_layout(state_root)
    root = Path(state_root) / "obsidian_exports"
    root.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "success": success,
        "packet_id": packet_id,
        "project_slug": project_slug,
        "timestamp": utc_now_iso(),
        "paths_written": paths,
    }
    if not success:
        payload["error"] = error or "unknown error"
    write_json(root / f"{packet_id}.json", payload)


def sync_intelligence_packet_to_obsidian(
    obsidian: ObsidianConfig,
    record: IntelligencePacketRecord,
    *,
    state_root: Path | None = None,
) -> dict[str, str]:
    """
    Persist a published intelligence packet into the Obsidian vault layout under
    ``{vault}/Projects/{project_slug}/...`` and merge risks/actions registers (idempotent).
    """
    vault = Path(obsidian.vault_root)
    project_slug = project_slug_for_record(record)
    packet_date = _packet_iso_date(record)
    packet_stem = packet_note_stem(packet_date, record.packet_id)
    intelligence_vault_enabled = getattr(obsidian, "intelligence_vault_enabled", True)
    projects_folder = getattr(obsidian, "intelligence_vault_projects_folder", "Projects")
    planned = _planned_export_paths(
        vault=vault,
        projects_folder=projects_folder,
        project_slug=project_slug,
        packet_stem=packet_stem,
    )

    if not intelligence_vault_enabled:
        if state_root is not None:
            _write_export_evidence(
                Path(state_root),
                packet_id=record.packet_id,
                project_slug=project_slug,
                paths=planned,
                success=False,
                error="obsidian.intelligence_vault_enabled is false",
            )
        return {}
    if record.status != "published":
        if state_root is not None:
            _write_export_evidence(
                Path(state_root),
                packet_id=record.packet_id,
                project_slug=project_slug,
                paths=planned,
                success=False,
                error=f"packet status is {record.status!r} (expected 'published')",
            )
        return {}

    base = vault / projects_folder.strip().strip("/\\") / project_slug
    intel_dir = base / "01 Intelligence"
    risks_dir = base / "02 Risks"
    actions_dir = base / "03 Actions"
    history_dir = base / "04 History"

    for d in (intel_dir, risks_dir, actions_dir, history_dir):
        d.mkdir(parents=True, exist_ok=True)

    packet_path = Path(planned["packet"])
    _, risks_alias, act_alias = _project_aliases(record.project_name)

    packet_md = _build_obsidian_packet_markdown(
        record,
        packet_date,
        project_slug=project_slug,
    )
    packet_path.write_text(packet_md, encoding="utf-8")

    stems = _list_intel_packet_stems(intel_dir)
    index_path = Path(planned["project_index"])
    _write_project_index(
        index_path,
        project_name=record.project_name.strip(),
        project_slug=project_slug,
        packet_stems_desc=stems,
        status_snippet=_current_status_snippet(record),
        record=record,
        packet_date=packet_date,
    )

    risks_path = Path(planned["risks"])
    risks_fm = _alias_frontmatter([risks_alias])
    if risks_path.exists():
        existing = risks_path.read_text(encoding="utf-8")
        if not existing.strip().startswith("---"):
            existing = risks_fm + existing
    else:
        existing = risks_fm + "# Active Risks\n\nRunning register (deduplicated across packets).\n"

    new_risks = _extract_risk_bullets(_section_body(record, "near_term_risks"))
    merged_risks = _merge_risk_register_longitudinal(
        existing,
        new_risks,
        packet_stem,
        record.packet_id,
    )
    risks_path.write_text(merged_risks, encoding="utf-8")

    actions_path = Path(planned["actions"])
    act_fm = _alias_frontmatter([act_alias])
    if actions_path.exists():
        a_existing = actions_path.read_text(encoding="utf-8")
        if not a_existing.strip().startswith("---"):
            a_existing = act_fm + a_existing
    else:
        a_existing = act_fm + "# Action Register\n\nRunning action register (deduplicated across packets).\n"

    queue_actions = _extract_actions_from_markdown(
        _section_body(record, "action_register"),
        default_continuity="—",
    )
    decision_actions = _extract_actions_from_markdown(
        _section_body(record, "required_decisions"),
        default_continuity="new",
    )
    merged_actions = _merge_action_register_longitudinal(
        a_existing,
        queue_actions + decision_actions,
        packet_stem,
        record.packet_id,
    )
    actions_path.write_text(merged_actions, encoding="utf-8")

    timeline_path = Path(planned["timeline"])
    _append_timeline(timeline_path, packet_date, packet_stem, record.packet_id, record.status)

    global_path = _rebuild_portfolio_index(vault, projects_folder)

    final_paths = dict(planned)
    final_paths["global_index"] = str(global_path)

    if state_root is not None:
        _write_export_evidence(
            Path(state_root),
            packet_id=record.packet_id,
            project_slug=project_slug,
            paths=final_paths,
            success=True,
        )

    return final_paths


def try_sync_intelligence_packet_to_obsidian(
    obsidian: ObsidianConfig,
    record: IntelligencePacketRecord,
    *,
    state_root: Path | None = None,
) -> None:
    project_slug = project_slug_for_record(record)
    projects_folder = getattr(obsidian, "intelligence_vault_projects_folder", "Projects")
    planned = _planned_export_paths(
        vault=Path(obsidian.vault_root),
        projects_folder=projects_folder,
        project_slug=project_slug,
        packet_stem=packet_note_stem(_packet_iso_date(record), record.packet_id),
    )
    try:
        sync_intelligence_packet_to_obsidian(obsidian, record, state_root=state_root)
    except OSError as exc:
        logger.warning("Obsidian intelligence vault sync failed: %s", exc)
        if state_root is not None:
            _write_export_evidence(
                Path(state_root),
                packet_id=record.packet_id,
                project_slug=project_slug,
                paths=planned,
                success=False,
                error=str(exc),
            )
    except Exception as exc:
        logger.exception("Obsidian intelligence vault sync failed: %s", exc)
        if state_root is not None:
            _write_export_evidence(
                Path(state_root),
                packet_id=record.packet_id,
                project_slug=project_slug,
                paths=planned,
                success=False,
                error=str(exc),
            )

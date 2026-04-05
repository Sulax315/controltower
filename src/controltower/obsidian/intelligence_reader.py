from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from controltower.obsidian.intelligence_vault import (
    _collect_legacy_action_lines,
    _collect_legacy_risk_bullets,
    _legacy_action_line_to_section,
    _legacy_bullet_to_section,
    _parse_longitudinal_action_sections,
    _parse_longitudinal_risk_sections,
    _split_frontmatter,
    packet_note_stem,
)
from controltower.services.intelligence_packets import IntelligencePacketRecord

_NO_CONTENT = "_No content._"
_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MD_ITAL = re.compile(r"\*([^*]+)\*")


def packet_iso_date(record: IntelligencePacketRecord) -> str:
    raw = (record.created_at or "").strip()
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    return raw[:10] if raw else "unknown-date"


def _strip_md_light(text: str) -> str:
    s = text.replace("\u2014", "-").strip()
    s = _MD_BOLD.sub(r"\1", s)
    s = _MD_ITAL.sub(r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def _markdown_h2_section(body: str, heading_line: str) -> str:
    want = heading_line.strip()
    lines = body.splitlines()
    buf: list[str] = []
    inside = False
    for ln in lines:
        if ln.startswith("## "):
            title = ln[3:].strip()
            if inside:
                break
            inside = title == want
            continue
        if inside:
            buf.append(ln)
    return "\n".join(buf).strip()


def _markdown_h3_block(section: str, heading_line: str) -> str:
    want = heading_line.strip()
    lines = section.splitlines()
    buf: list[str] = []
    inside = False
    for ln in lines:
        if ln.startswith("### "):
            title = ln[4:].strip()
            if inside:
                break
            inside = title == want
            continue
        if inside:
            buf.append(ln)
    return "\n".join(buf).strip()


def _bullets(text: str, *, limit: int = 24) -> list[str]:
    out: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s.startswith("- "):
            continue
        item = _strip_md_light(s[2:])
        if not item or item == _strip_md_light(_NO_CONTENT):
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _safe_read(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return ""


def _intel_note_path(intel_dir: Path, packet_date: str, packet_id: str) -> Path:
    stem = packet_note_stem(packet_date, packet_id)
    direct = intel_dir / f"{stem}.md"
    if direct.is_file():
        return direct
    matches = sorted(intel_dir.glob(f"*{packet_id}*.md"))
    return matches[0] if matches else direct


def _risk_lines_for_packet(body: str, packet_id: str) -> list[str]:
    _, md_body = _split_frontmatter(body)
    md_body = md_body.strip()
    if not md_body:
        return []

    header_lines: list[str] = []
    rest_lines: list[str] = md_body.splitlines()
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
        for leg in _collect_legacy_risk_bullets(md_body):
            sec = _legacy_bullet_to_section(leg)
            if sec is None:
                continue
            sections[sec.fp] = sec

    tied: list[tuple[str, str]] = []
    general: list[tuple[str, str]] = []
    for fp in sorted(sections.keys()):
        sec = sections[fp]
        label = _strip_md_light(sec.title)
        row = (fp, f"{label} — {sec.status}")
        hit = any(pid == packet_id for _a, _b, pid in sec.history_rows)
        if hit:
            tied.append(row)
        else:
            general.append(row)
    ordered = [r[1] for r in sorted(tied)] + [r[1] for r in sorted(general)]
    return ordered[:12]


def _action_lines_for_packet(body: str, packet_id: str) -> list[str]:
    _, md_body = _split_frontmatter(body)
    md_body = md_body.strip()
    if not md_body:
        return []

    rest_lines: list[str] = md_body.splitlines()
    for idx, ln in enumerate(rest_lines):
        if ln.startswith("# Action Register"):
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
        for leg in _collect_legacy_action_lines(md_body):
            sec = _legacy_action_line_to_section(leg)
            if sec is None:
                continue
            sections[sec.fp] = sec

    tied: list[tuple[str, str]] = []
    general: list[tuple[str, str]] = []
    for fp in sorted(sections.keys()):
        sec = sections[fp]
        label = _strip_md_light(sec.action or sec.title)
        timing = _strip_md_light(sec.timing)
        row_txt = f"{sec.role}: {label}" + (f" ({timing})" if timing and timing != "—" else "")
        row = (fp, row_txt)
        hit = any(pid == packet_id for _a, _b, pid in sec.history_rows)
        if hit:
            tied.append(row)
        else:
            general.append(row)
    ordered = [r[1] for r in sorted(tied)] + [r[1] for r in sorted(general)]
    return ordered[:12]


def _clamp_sentence(text: str, max_len: int = 320) -> str:
    one = _strip_md_light(text)
    if not one:
        return ""
    if len(one) <= max_len:
        return one
    cut = one[: max_len - 1].rstrip()
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut + "…"


def load_intelligence_bundle(
    vault_root: Path,
    projects_folder: str,
    project_slug: str,
    packet_id: str,
    packet_date: str,
) -> dict[str, Any]:
    """
    Read Obsidian intelligence vault files for a packet (read-only, no side effects).

    Paths (relative to vault_root / projects_folder / project_slug):
      01 Intelligence / {packet_date} — {packet_id}.md
      02 Risks / Active Risks.md
      03 Actions / Action Register.md
    """
    pf = projects_folder.strip().strip("/\\")
    base = Path(vault_root) / pf / project_slug
    intel_dir = base / "01 Intelligence"
    risks_path = base / "02 Risks" / "Active Risks.md"
    actions_path = base / "03 Actions" / "Action Register.md"

    empty: dict[str, Any] = {
        "intelligence_summary": "",
        "key_points": [],
        "risks": [],
        "actions": [],
        "rail_changed": "",
        "rail_matters": "",
        "rail_do": "",
    }

    intel_raw = _safe_read(_intel_note_path(intel_dir, packet_date, packet_id))
    if not intel_raw.strip():
        risks_only = _risk_lines_for_packet(_safe_read(risks_path), packet_id)
        actions_only = _action_lines_for_packet(_safe_read(actions_path), packet_id)
        out = dict(empty)
        out["risks"] = risks_only
        out["actions"] = actions_only
        out["rail_do"] = "; ".join(actions_only[:3])
        return out

    _, body = _split_frontmatter(intel_raw)
    body = body.strip()

    exec_s = _markdown_h2_section(body, "Executive Summary")
    intel_summary = _clamp_sentence(exec_s.replace(_NO_CONTENT, "").strip(), 720)

    drivers = _markdown_h2_section(body, "Key Drivers")
    key_points = _bullets(drivers)

    finish = _markdown_h2_section(body, "Finish Outlook")
    movement = _markdown_h3_block(finish, "Movement vs prior")
    rail_changed = _clamp_sentence(movement or finish.replace(_NO_CONTENT, "").strip(), 400)

    risks = _risk_lines_for_packet(_safe_read(risks_path), packet_id)
    actions = _action_lines_for_packet(_safe_read(actions_path), packet_id)

    rail_matters = _clamp_sentence(" ".join(key_points[:4]) if key_points else intel_summary, 400)
    rail_do = _clamp_sentence("; ".join(actions[:4]) if actions else "", 400)

    return {
        "intelligence_summary": intel_summary,
        "key_points": key_points,
        "risks": risks,
        "actions": actions,
        "rail_changed": rail_changed,
        "rail_matters": rail_matters,
        "rail_do": rail_do,
    }

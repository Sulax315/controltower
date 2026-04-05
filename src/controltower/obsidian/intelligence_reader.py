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
_CHANGE_HINTS = re.compile(
    r"\b(prior|delta|movement|slip|shift|vs\.?|week|compared|change|updated?|moved|float)\b",
    re.IGNORECASE,
)

_EXEC_H2 = (
    "executive summary",
    "summary",
    "intel summary",
    "situation",
)
_FINISH_H2 = (
    "finish outlook",
    "finish",
    "milestone outlook",
    "schedule outlook",
)
_MOVEMENT_H3 = (
    "movement vs prior",
    "movement vs. prior",
    "delta vs prior",
    "delta vs. prior",
    "key changes",
    "changes vs prior",
    "changes vs. prior",
    "movement",
    "delta",
    "vs prior update",
)
_DRIVERS_H2 = (
    "key drivers",
    "drivers",
    "key driver",
    "primary drivers",
)
_RISKS_H2 = (
    "risks",
    "near-term risks",
    "near term risks",
    "risk posture",
)
_ACTIONS_H2 = (
    "required actions",
    "actions",
    "next actions",
    "decisions and actions",
)


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


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _h2_key(line: str) -> str | None:
    if not line.startswith("## ") or line.startswith("###"):
        return None
    return _collapse_ws(line[3:])


def _h3_key(line: str) -> str | None:
    if not line.startswith("### "):
        return None
    return _collapse_ws(line[4:])


def _find_h2_section(body: str, title_keys: tuple[str, ...]) -> str:
    want = {_collapse_ws(t) for t in title_keys}
    lines = body.splitlines()
    buf: list[str] = []
    inside = False
    for ln in lines:
        if _h2_key(ln) is not None:
            key = _h2_key(ln)
            if inside:
                break
            inside = key in want if key else False
            continue
        if inside:
            buf.append(ln)
    return "\n".join(buf).strip()


def _find_h3_section(scope: str, title_keys: tuple[str, ...]) -> str:
    want = {_collapse_ws(t) for t in title_keys}
    lines = scope.splitlines()
    buf: list[str] = []
    inside = False
    for ln in lines:
        k = _h3_key(ln)
        if k is not None:
            if inside:
                break
            inside = k in want
            continue
        if inside:
            buf.append(ln)
    return "\n".join(buf).strip()


def _find_h3_anywhere(body: str, title_keys: tuple[str, ...]) -> str:
    """First matching ### section in the whole note (not nested under a specific H2)."""
    return _find_h3_section(body, title_keys)


def _is_noise_line(s: str) -> bool:
    t = s.strip()
    if not t:
        return True
    if t == _NO_CONTENT or _strip_md_light(t) == _strip_md_light(_NO_CONTENT):
        return True
    if t.startswith("|") or t.startswith("|---"):
        return True
    if t.startswith("```"):
        return True
    if t.startswith("*Project:") or t.startswith("*Risks:") or t.startswith("*Actions:"):
        return True
    if re.match(r"^Date:\s*", t):
        return True
    if t.startswith("[[") and t.endswith("]]"):
        return True
    return False


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


def _first_global_bullets(body: str, *, limit: int = 8) -> list[str]:
    """First list bullets in the document (skips obvious table/header noise)."""
    out: list[str] = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s.startswith("- "):
            continue
        if s.startswith("|"):
            continue
        item = _strip_md_light(s[2:])
        if not item or _is_noise_line(s[2:]):
            continue
        if item == _strip_md_light(_NO_CONTENT):
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _paragraph_chunks(text: str) -> list[str]:
    """Non-empty prose blocks (split on blank lines), noise lines removed."""
    chunks: list[str] = []
    cur: list[str] = []
    for ln in text.splitlines():
        if not ln.strip():
            if cur:
                block = _strip_md_light(" ".join(cur))
                if block and not _is_noise_line(block):
                    chunks.append(block)
                cur = []
            continue
        if ln.startswith("#"):
            if cur:
                block = _strip_md_light(" ".join(cur))
                if block and not _is_noise_line(block):
                    chunks.append(block)
                cur = []
            continue
        if _is_noise_line(ln):
            continue
        cur.append(ln.strip())
    if cur:
        block = _strip_md_light(" ".join(cur))
        if block and not _is_noise_line(block):
            chunks.append(block)
    return [c for c in chunks if c and c != _strip_md_light(_NO_CONTENT)]


def _first_sentences(text: str, *, max_sentences: int = 2, max_len: int = 400) -> str:
    one = _strip_md_light(text)
    if not one:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", one)
    chunk = " ".join(parts[:max_sentences]).strip()
    return _clamp_sentence(chunk, max_len)


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

    rest_lines: list[str] = md_body.splitlines()
    for idx, ln in enumerate(rest_lines):
        if ln.startswith("# Active Risks"):
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


def _extract_intel_summary(body: str) -> str:
    exec_s = _find_h2_section(body, _EXEC_H2)
    cleaned = exec_s.replace(_NO_CONTENT, "").strip()
    if cleaned:
        chunks = _paragraph_chunks(cleaned)
        if chunks:
            return _clamp_sentence(" ".join(chunks[:3]), 720)
        return _clamp_sentence(cleaned, 720)
    # Fallback: first prose after H1 title / nav, before first ##
    lines = body.splitlines()
    buf: list[str] = []
    after_title = False
    for ln in lines:
        if ln.startswith("# ") and not ln.startswith("##"):
            after_title = True
            continue
        if not after_title:
            continue
        if ln.startswith("## "):
            break
        if _is_noise_line(ln):
            continue
        buf.append(ln.strip())
        if len(buf) > 14:
            break
    if buf:
        return _clamp_sentence(" ".join(buf), 720)
    chunks = _paragraph_chunks(body)
    if chunks:
        return _clamp_sentence(chunks[0], 720)
    return ""


def _extract_key_points(body: str) -> list[str]:
    drivers = _find_h2_section(body, _DRIVERS_H2)
    pts = _bullets(drivers)
    if pts:
        return pts
    risks_sec = _find_h2_section(body, _RISKS_H2)
    pts = _bullets(risks_sec)
    if pts:
        return pts
    exec_s = _find_h2_section(body, _EXEC_H2)
    pts = _bullets(exec_s)
    if pts:
        return pts
    return _first_global_bullets(body, limit=12)


def _compose_rail_changed(
    body: str,
    finish_section: str,
    intel_summary: str,
    key_points: list[str],
) -> str:
    # 1) Movement / delta headings (within finish, then anywhere in note)
    movement = _find_h3_section(finish_section, _MOVEMENT_H3)
    if not movement.strip() or movement.replace(_NO_CONTENT, "").strip() == "":
        movement = _find_h3_anywhere(body, _MOVEMENT_H3)
    m = movement.replace(_NO_CONTENT, "").strip()
    if m:
        ch = _paragraph_chunks(m)
        if ch:
            return _clamp_sentence(ch[0] if len(ch) == 1 else " ".join(ch[:2]), 400)
        return _clamp_sentence(m, 400)

    # 2) Finish section prose / bullets (schedule movement often lives here without H3)
    fs = finish_section.replace(_NO_CONTENT, "").strip()
    if fs:
        fb = _bullets(fs)
        if fb:
            return _clamp_sentence("; ".join(fb[:3]), 400)
        ch = _paragraph_chunks(fs)
        if ch:
            return _first_sentences("\n\n".join(ch[:2]), max_sentences=2, max_len=400)

    # 3) Executive / global bullets that smell like change
    for src in (_find_h2_section(body, _EXEC_H2), body):
        for b in _bullets(src)[:6]:
            if _CHANGE_HINTS.search(b):
                return _clamp_sentence(b, 400)
    if key_points:
        joined = "; ".join(key_points[:2])
        if _CHANGE_HINTS.search(joined):
            return _clamp_sentence(joined, 400)

    # 4) Summary sentences if change-related
    if intel_summary and _CHANGE_HINTS.search(intel_summary):
        return _first_sentences(intel_summary, max_sentences=2, max_len=400)

    # 5) Any first meaningful bullets in note
    gb = _first_global_bullets(body, limit=4)
    if gb:
        return _clamp_sentence("; ".join(gb[:3]), 400)

    # 6) Last resort: start of intel summary
    if intel_summary:
        return _first_sentences(intel_summary, max_sentences=1, max_len=400)
    ch = _paragraph_chunks(body)
    if ch:
        return _first_sentences(ch[0], max_sentences=2, max_len=400)
    return ""


def _compose_rail_matters(
    body: str,
    intel_summary: str,
    key_points: list[str],
    risk_lines: list[str],
) -> str:
    parts: list[str] = []
    if key_points:
        parts.append("; ".join(key_points[:4]))
    risks_sec = _find_h2_section(body, _RISKS_H2)
    rb = _bullets(risks_sec)
    if rb:
        parts.append("Risks: " + "; ".join(rb[:3]))
    elif risk_lines:
        parts.append("Risks: " + "; ".join(risk_lines[:3]))
    if parts:
        return _clamp_sentence(" | ".join(parts), 400)

    if intel_summary:
        fs = _first_sentences(intel_summary, max_sentences=2, max_len=400)
        if fs:
            return fs
        return _clamp_sentence(intel_summary, 400)

    ch = _paragraph_chunks(_find_h2_section(body, _EXEC_H2))
    if ch:
        return _clamp_sentence(ch[0], 400)
    ch2 = _paragraph_chunks(body)
    if ch2:
        return _clamp_sentence(ch2[0], 400)
    return ""


def _compose_rail_do(body: str, register_actions: list[str]) -> str:
    req = _find_h2_section(body, _ACTIONS_H2)
    cleaned = req.replace(_NO_CONTENT, "").strip()
    if cleaned:
        ab = _bullets(cleaned)
        if ab:
            return _clamp_sentence("; ".join(ab[:5]), 400)
        ch = _paragraph_chunks(cleaned)
        if ch:
            return _clamp_sentence("; ".join(ch[:3]), 400)

    if register_actions:
        return _clamp_sentence("; ".join(register_actions[:5]), 400)

    gb = _first_global_bullets(body, limit=10)
    # Prefer bullets that look like owner/action (**, colon, role words)
    scored: list[str] = []
    for b in gb:
        if "**" in b or ":" in b or re.search(r"\b(PM|GC|Owner|Approve|Hold|Expedite)\b", b, re.I):
            scored.append(b)
    if scored:
        return _clamp_sentence("; ".join(scored[:5]), 400)
    if gb:
        return _clamp_sentence("; ".join(gb[:4]), 400)

    ch = _paragraph_chunks(body)
    if len(ch) > 1:
        return _clamp_sentence(ch[-1], 400)
    return ""


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

    risks_file = _safe_read(risks_path)
    actions_file = _safe_read(actions_path)
    risks = _risk_lines_for_packet(risks_file, packet_id)
    actions = _action_lines_for_packet(actions_file, packet_id)

    intel_raw = _safe_read(_intel_note_path(intel_dir, packet_date, packet_id))
    if not intel_raw.strip():
        out = dict(empty)
        out["risks"] = risks
        out["actions"] = actions
        out["rail_matters"] = _clamp_sentence("; ".join(risks[:3]), 400) if risks else ""
        out["rail_do"] = _clamp_sentence("; ".join(actions[:5]), 400) if actions else ""
        if risks and not out["rail_changed"]:
            out["rail_changed"] = _first_sentences("; ".join(risks[:2]), max_sentences=1, max_len=400)
        return out

    _, body = _split_frontmatter(intel_raw)
    body = body.strip()

    intel_summary = _extract_intel_summary(body)
    key_points = _extract_key_points(body)
    finish_section = _find_h2_section(body, _FINISH_H2)

    rail_changed = _compose_rail_changed(body, finish_section, intel_summary, key_points)
    rail_matters = _compose_rail_matters(body, intel_summary, key_points, risks)
    rail_do = _compose_rail_do(body, actions)

    if not rail_matters and intel_summary:
        rail_matters = _clamp_sentence(intel_summary, 400)
    if not rail_do and actions:
        rail_do = _clamp_sentence("; ".join(actions[:5]), 400)
    if not rail_changed and intel_summary:
        rail_changed = _first_sentences(intel_summary, max_sentences=2, max_len=400)

    return {
        "intelligence_summary": intel_summary,
        "key_points": key_points,
        "risks": risks,
        "actions": actions,
        "rail_changed": rail_changed,
        "rail_matters": rail_matters,
        "rail_do": rail_do,
    }

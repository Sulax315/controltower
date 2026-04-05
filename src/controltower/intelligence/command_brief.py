from __future__ import annotations

import re
from typing import Any

from controltower.services.intelligence_packets import IntelligencePacketRecord

_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MD_ITAL = re.compile(r"\*([^*]+)\*")


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


def build_command_brief(packet: IntelligencePacketRecord, intelligence_data: dict[str, Any]) -> dict[str, str]:
    """
    Operator-facing five-field brief. Packet sections are authoritative; vault strings
    fill gaps only when packet text is empty.
    """
    finish_md = _section_md(packet, "finish_milestone_outlook")
    delta_md = _section_md(packet, "delta_vs_prior")
    drivers_md = _section_md(packet, "key_drivers")
    risks_md = _section_md(packet, "near_term_risks")
    need_md = _section_md(packet, "required_decisions")
    doing_md = _section_md(packet, "action_register")

    finish = _clamp(finish_md, 200)
    if delta_md.strip():
        d = _first_non_empty_line(delta_md) or _clamp(delta_md, 120)
        if d:
            finish = _clamp(f"{finish} Δ {d}" if finish else d, 220)

    driver = _first_bullet(drivers_md) or _first_non_empty_line(drivers_md)

    risks = _first_bullet(risks_md) or _first_non_empty_line(risks_md)
    if not risks:
        vr = intelligence_data.get("risks") or []
        if isinstance(vr, list) and vr:
            risks = _clamp(str(vr[0]), 200)

    need = _first_bullet(need_md) or _first_non_empty_line(need_md)
    if not need:
        kp = intelligence_data.get("key_points") or []
        if isinstance(kp, list) and kp:
            need = _clamp(str(kp[0]), 200)
        elif intelligence_data.get("intelligence_summary"):
            need = _clamp(str(intelligence_data["intelligence_summary"]), 200)

    doing = _first_bullet(doing_md) or _first_non_empty_line(doing_md)
    if not doing:
        va2 = intelligence_data.get("actions") or []
        if isinstance(va2, list) and va2:
            doing = _clamp(str(va2[0]), 200)

    return {
        "finish": finish,
        "driver": driver,
        "risks": risks,
        "need": need,
        "doing": doing,
    }

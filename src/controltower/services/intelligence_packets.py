from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from controltower.domain.models import SourceArtifactRef, utc_now_iso
from controltower.render.markdown import render_publish_markdown_preview
from controltower.services.controltower import ControlTowerService


PACKETS_DIR_NAME = "packets"

PacketStatus = Literal["generated", "published"]
SUPPORTED_PACKET_TYPES = frozenset({"weekly_schedule_intelligence"})

SECTION_DEFS: tuple[tuple[str, str], ...] = (
    ("executive_summary", "Executive Summary"),
    ("finish_milestone_outlook", "Finish / milestone outlook"),
    ("delta_vs_prior", "Delta vs prior update"),
    ("key_drivers", "Key drivers"),
    ("near_term_risks", "Near-term risks"),
    ("required_decisions", "Required decisions / asks"),
    ("action_register", "Action register"),
    ("source_evidence_appendix", "Source evidence appendix"),
)


def packets_root(state_root: Path) -> Path:
    return Path(state_root) / PACKETS_DIR_NAME


def new_packet_id() -> str:
    return f"pkt_{uuid.uuid4().hex}"


def _slug_fragment(text: str, *, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    if not slug:
        slug = "packet"
    return slug[:max_len]


class GeneratePacketRequest(BaseModel):
    project_code: str = Field(..., min_length=1)
    packet_type: str = Field(..., min_length=1)
    reporting_period: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    operator_notes: str = ""


class IntelligencePacketSection(BaseModel):
    key: str
    title: str
    body_markdown: str
    body_html: str = ""


class IntelligencePacketRecord(BaseModel):
    packet_id: str
    project_name: str
    canonical_project_code: str
    packet_type: str
    reporting_period: str
    title: str
    operator_notes: str
    status: PacketStatus
    sections: list[IntelligencePacketSection]
    source_artifacts: list[dict[str, Any]]
    created_at: str
    updated_at: str
    published_at: str | None = None

    def combined_markdown(self) -> str:
        lines = [
            f"# {self.title}",
            "",
            f"- **Project:** {self.project_name} (`{self.canonical_project_code}`)",
            f"- **Packet type:** {self.packet_type}",
            f"- **Reporting period:** {self.reporting_period}",
            f"- **Generated:** {self.created_at}",
            f"- **Status:** {self.status}",
            "",
        ]
        if self.operator_notes.strip():
            lines.extend(["## Operator notes / instructions", "", self.operator_notes.strip(), ""])
        for section in self.sections:
            lines.extend([f"## {section.title}", "", section.body_markdown.strip(), ""])
        return "\n".join(lines).strip() + "\n"


def _artifact_dicts(refs: list[SourceArtifactRef]) -> list[dict[str, Any]]:
    return [ref.model_dump(mode="json") for ref in refs]


def _format_action_queue_markdown(service: ControlTowerService, project_code: str) -> str:
    portfolio = service.build_portfolio()
    project = next((p for p in portfolio.project_rankings if p.canonical_project_code == project_code), None)
    if project is None:
        return "_Project not found._"
    _mp, action_queue, _cont = service.build_project_operational_views(project)
    if action_queue.item_count == 0:
        return "_No trackable actions in the current deterministic queue._"
    parts: list[str] = []
    for group in action_queue.groups:
        parts.append(f"### {group.label}")
        parts.append(group.summary)
        parts.append("")
        for item in group.items:
            pri = f" ({item.priority})" if item.priority else ""
            parts.append(
                f"- **{item.owner_role}{pri}:** {item.action_text}  \n"
                f"  _Timing:_ {item.timing} · _Signal:_ {item.reason_source_signal} · _Continuity:_ {item.continuity_label}"
            )
        parts.append("")
    return "\n".join(parts).strip()


def _build_weekly_schedule_sections(
    service: ControlTowerService,
    *,
    project_code: str,
    reporting_period: str,
    title: str,
    operator_notes: str,
) -> tuple[list[IntelligencePacketSection], list[dict[str, Any]]]:
    portfolio = service.build_portfolio()
    project = next((p for p in portfolio.project_rankings if p.canonical_project_code == project_code), None)
    if project is None:
        raise ValueError(f"Unknown project_code: {project_code}")

    comparison_trust = portfolio.comparison_trust
    cmd = service.build_project_command_view(project, comparison_trust)
    mp = project.meeting_packet
    provenance = _artifact_dicts(project.provenance)

    exec_lines = [
        f"{project.project_name} — {reporting_period}: schedule intelligence packet (deterministic Control Tower assembly).",
        f"Overall posture: **{project.health.tier.replace('_', ' ')}** tier, risk **{project.health.risk_level}**, health score **{project.health.health_score}**.",
    ]
    if project.executive_summary:
        exec_lines.append(project.executive_summary.strip())
    if operator_notes.strip():
        exec_lines.append(f"Operator instructions incorporated: {operator_notes.strip()[:500]}{'…' if len(operator_notes.strip()) > 500 else ''}")

    finish_lines = [
        f"**Projected finish:** {cmd.projected_finish_label or 'unavailable'}",
        f"**Authority / source:** {cmd.finish_source_label} — {cmd.finish_source_detail or 'n/a'}",
    ]
    if project.schedule and project.schedule.finish_detail:
        finish_lines.append(f"**Schedule detail:** {project.schedule.finish_detail}")
    if cmd.finish_driver and cmd.finish_driver.controlling_driver:
        finish_lines.append(f"**Finish driver (summary):** {cmd.finish_driver.controlling_driver}")

    delta_lines = [
        f"**Movement:** {cmd.movement_label or 'unavailable'} — {cmd.movement_reason or 'n/a'}",
        f"**Comparison trust:** {cmd.trust_label} — {cmd.trust_detail or 'n/a'}",
    ]
    if project.change_intelligence.finish.label:
        delta_lines.append(f"**Finish change signal:** {project.change_intelligence.finish.label}")
        if project.change_intelligence.finish.detail:
            delta_lines.append(project.change_intelligence.finish.detail)
    if mp.what_changed:
        delta_lines.append("**Meeting packet — what changed:**")
        delta_lines.extend([f"- {w}" for w in mp.what_changed[:12]])

    driver_lines: list[str] = []
    inv = cmd.finish_driver_investigation
    if inv.comparison_summary and inv.comparison_summary != "No trusted prior driver comparison is available for this project.":
        driver_lines.append(f"**Driver comparison:** {inv.comparison_summary}")
    elif inv.current_driver.driver_label and inv.current_driver.driver_label != "Driver unavailable":
        driver_lines.append(f"**Finish driver detail:** {inv.current_driver.driver_label} — {inv.current_driver.why_controlling_finish}")
    if mp.controlling_driver:
        driver_lines.append(f"**Controlling driver (meeting packet):** {mp.controlling_driver}")
    if mp.driver_reason:
        driver_lines.append(f"**Driver rationale:** {mp.driver_reason}")
    if project.schedule and project.schedule.top_drivers:
        driver_lines.append("**Top schedule drivers (published):**")
        for d in project.schedule.top_drivers[:5]:
            bit = f"{d.label}" + (f" — {d.rationale}" if d.rationale else "")
            driver_lines.append(f"- {bit}")

    risk_lines: list[str] = []
    if project.top_issues:
        for iss in project.top_issues[:8]:
            risk_lines.append(f"- **{iss.severity.upper()} ({iss.source}):** {iss.label} — {iss.detail}")
    else:
        risk_lines.append("_No elevated issue drivers surfaced in the current deterministic scan._")
    risk_lines.append(f"**Parser / data flags:** {', '.join(project.missing_data_flags) or 'none noted'}")

    decision_lines: list[str] = []
    if project.challenge_next:
        decision_lines.append(f"**Challenge / next focus:** {project.challenge_next}")
    if mp.challenge_next and mp.challenge_next != project.challenge_next:
        decision_lines.append(f"**Meeting packet challenge:** {mp.challenge_next}")
    high_actions = [a for a in project.recommended_actions if a.priority == "high"]
    if high_actions:
        decision_lines.append("**High-priority recommended actions:**")
        for a in high_actions[:6]:
            decision_lines.append(f"- **{a.owner_hint or 'Owner TBD'}:** {a.action}")
    if mp.required_actions:
        decision_lines.append("**Required actions (meeting packet):**")
        decision_lines.extend([f"- {r}" for r in mp.required_actions[:8]])
    if not decision_lines:
        decision_lines.append("_No explicit decisions encoded beyond standard operational tracking._")

    action_md = _format_action_queue_markdown(service, project_code)

    evidence_lines = [
        "Artifacts below are paths as resolved by Control Tower at generation time.",
        "",
    ]
    for ref in project.provenance[:25]:
        evidence_lines.append(
            f"- **{ref.source_system}** / {ref.artifact_type}: `{ref.path}` ({ref.status})"
        )
    if len(project.provenance) > 25:
        evidence_lines.append(f"- _…and {len(project.provenance) - 25} additional provenance entries._")

    bodies: dict[str, str] = {
        "executive_summary": "\n".join(exec_lines),
        "finish_milestone_outlook": "\n".join(finish_lines),
        "delta_vs_prior": "\n".join(delta_lines),
        "key_drivers": "\n".join(driver_lines) if driver_lines else "_No drivers enumerated._",
        "near_term_risks": "\n".join(risk_lines),
        "required_decisions": "\n".join(decision_lines),
        "action_register": action_md,
        "source_evidence_appendix": "\n".join(evidence_lines),
    }

    sections: list[IntelligencePacketSection] = []
    for key, sec_title in SECTION_DEFS:
        md = bodies[key]
        sections.append(
            IntelligencePacketSection(
                key=key,
                title=sec_title,
                body_markdown=md,
                body_html=render_publish_markdown_preview(md),
            )
        )

    return sections, provenance


def generate_weekly_schedule_intelligence_packet(
    service: ControlTowerService,
    req: GeneratePacketRequest,
) -> IntelligencePacketRecord:
    if req.packet_type not in SUPPORTED_PACKET_TYPES:
        raise ValueError(f"Unsupported packet_type: {req.packet_type}")

    now = utc_now_iso()
    packet_id = new_packet_id()
    sections, source_artifacts = _build_weekly_schedule_sections(
        service,
        project_code=req.project_code.strip(),
        reporting_period=req.reporting_period.strip(),
        title=req.title.strip(),
        operator_notes=req.operator_notes or "",
    )

    portfolio = service.build_portfolio()
    project = next((p for p in portfolio.project_rankings if p.canonical_project_code == req.project_code.strip()), None)
    assert project is not None

    record = IntelligencePacketRecord(
        packet_id=packet_id,
        project_name=project.project_name,
        canonical_project_code=project.canonical_project_code,
        packet_type=req.packet_type.strip(),
        reporting_period=req.reporting_period.strip(),
        title=req.title.strip(),
        operator_notes=(req.operator_notes or "").strip(),
        status="generated",
        sections=sections,
        source_artifacts=source_artifacts,
        created_at=now,
        updated_at=now,
        published_at=None,
    )
    return record


def packet_dir(state_root: Path, packet_id: str) -> Path:
    raw = packet_id.strip()
    if not raw or not re.fullmatch(r"pkt_[0-9a-f]{32}", raw):
        raise ValueError("Invalid packet_id")
    return packets_root(state_root) / raw


def write_packet_artifacts(state_root: Path, record: IntelligencePacketRecord) -> dict[str, str]:
    root = packet_dir(state_root, record.packet_id)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "packet.json"
    md_path = root / "packet.md"
    html_path = root / "packet.html"

    combined_md = record.combined_markdown()
    full_html = render_publish_markdown_preview(combined_md)

    json_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    md_path.write_text(combined_md, encoding="utf-8")
    html_doc = (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{_html_escape(record.title)}</title></head><body>\n"
        f"<article class=\"intelligence-packet-html\" data-packet-id=\"{_html_escape(record.packet_id)}\">\n"
        f"{full_html}\n</article></body></html>\n"
    )
    html_path.write_text(html_doc, encoding="utf-8")

    return {
        "packet_json": str(json_path),
        "packet_md": str(md_path),
        "packet_html": str(html_path),
    }


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def load_packet(state_root: Path, packet_id: str) -> IntelligencePacketRecord | None:
    path = packet_dir(state_root, packet_id) / "packet.json"
    if not path.exists():
        return None
    return IntelligencePacketRecord.model_validate_json(path.read_text(encoding="utf-8"))


def publish_packet(state_root: Path, packet_id: str) -> IntelligencePacketRecord | None:
    record = load_packet(state_root, packet_id)
    if record is None:
        return None
    if record.status == "published":
        return record
    now = utc_now_iso()
    updated = record.model_copy(
        update={"status": "published", "published_at": now, "updated_at": now},
    )
    write_packet_artifacts(state_root, updated)
    return updated


def export_markdown_bytes(state_root: Path, packet_id: str) -> tuple[str, bytes] | None:
    record = load_packet(state_root, packet_id)
    if record is None:
        return None
    body = record.combined_markdown().encode("utf-8")
    filename = f"{_slug_fragment(record.title)}-{record.packet_id}.md"
    return filename, body

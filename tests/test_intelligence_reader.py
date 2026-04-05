from __future__ import annotations

from pathlib import Path

from controltower.intelligence.command_brief import build_command_brief
from controltower.obsidian.intelligence_reader import load_intelligence_bundle, packet_iso_date
from controltower.services.intelligence_packets import IntelligencePacketSection, IntelligencePacketRecord


def test_load_intelligence_bundle_empty_when_missing_vault(tmp_path: Path):
    out = load_intelligence_bundle(
        tmp_path / "no_vault",
        "Projects",
        "any-slug",
        "pkt_" + "0" * 32,
        "2026-04-05",
    )
    assert out["intelligence_summary"] == ""
    assert out["key_points"] == []
    assert out["risks"] == []
    assert out["actions"] == []
    assert out["rail_changed"] == ""
    assert out["rail_matters"] == ""
    assert out["rail_do"] == ""


def test_load_intelligence_bundle_flexible_headings_and_rail_fallbacks(tmp_path: Path):
    """Headings differ from vault generator; rail fields still populate from movement + bullets."""
    vault = tmp_path / "vault"
    slug = "demo"
    base = vault / "Projects" / slug
    (base / "01 Intelligence").mkdir(parents=True)
    (base / "02 Risks").mkdir(parents=True)
    (base / "03 Actions").mkdir(parents=True)
    pid = "pkt_" + "f" * 32
    pdate = "2026-06-01"
    stem = f"{pdate} — {pid}"
    intel = base / "01 Intelligence" / f"{stem}.md"
    intel.write_text(
        "---\n---\n\n"
        "# Demo — Intelligence Packet\n\n"
        "## Summary\n\n"
        "Finish at risk from steel delays. Negative float on procurement path.\n\n"
        "## Finish\n\n"
        "### Key changes\n\n"
        "MEP coordination slipped one week; GC rebaselined lane owners.\n\n"
        "## Drivers\n\n"
        "- Long-lead steel\n"
        "- Submittal backlog\n\n"
        "## Risks\n\n"
        "- Fabricator capacity tight\n\n"
        "## Actions\n\n"
        "- **PM:** Chase submittals by Tuesday\n",
        encoding="utf-8",
    )
    (base / "02 Risks" / "Active Risks.md").write_text(
        "---\n---\n\n# Active Risks\n\n_No risks file._\n", encoding="utf-8"
    )
    (base / "03 Actions" / "Action Register.md").write_text(
        "---\n---\n\n# Action Register\n\n_No actions._\n", encoding="utf-8"
    )

    out = load_intelligence_bundle(vault, "Projects", slug, pid, pdate)
    assert "steel" in out["intelligence_summary"].lower() or "float" in out["intelligence_summary"].lower()
    assert out["key_points"]
    assert "slipped" in out["rail_changed"].lower() or "week" in out["rail_changed"].lower()
    assert out["rail_matters"]
    assert "submittals" in out["rail_do"].lower() or "PM" in out["rail_do"]


def test_load_intelligence_bundle_reads_intel_note_and_registers(tmp_path: Path):
    vault = tmp_path / "vault"
    slug = "aurora-hills"
    base = vault / "Projects" / slug
    (base / "01 Intelligence").mkdir(parents=True)
    (base / "02 Risks").mkdir(parents=True)
    (base / "03 Actions").mkdir(parents=True)
    pid = "pkt_" + "a" * 32
    pdate = "2026-04-05"
    stem = f"{pdate} — {pid}"
    intel = base / "01 Intelligence" / f"{stem}.md"
    intel.write_text(
        "---\ntype: controltower_packet\n---\n\n"
        "# Aurora Hills — Intelligence Packet\n\n"
        "## Executive Summary\n\n"
        "Executive line one.\n\n"
        "## Key Drivers\n\n"
        "- Driver alpha\n"
        "- Driver beta\n\n"
        "## Finish Outlook\n\n"
        "### Movement vs prior\n\n"
        "Concrete delta text here.\n",
        encoding="utf-8",
    )
    risks = base / "02 Risks" / "Active Risks.md"
    risks.write_text(
        "---\naliases: []\n---\n\n"
        "# Active Risks\n\n"
        "## Escalation coverage\n"
        "<!-- ct-risk-fp:r1 -->\n\n"
        "- First Seen: x\n- Latest Seen: y\n- Status: Active\n\n"
        "### History\n"
        "| Packet | Note |\n|---|---|\n"
        f"| _Packet:_ [[../01 Intelligence/{stem}]] | Initial detection |\n",
        encoding="utf-8",
    )
    actions = base / "03 Actions" / "Action Register.md"
    actions.write_text(
        "---\naliases: []\n---\n\n"
        "# Action Register\n\n"
        "## Track procurement\n"
        "<!-- ct-act-fp:a1 -->\n\n"
        "- **Role:** GC\n"
        "- **Action:** Expedite steel\n"
        "- **Timing:** this week · _Signal:_ float · _Continuity:_ open\n"
        "- First Seen: x\n- Latest Seen: y\n"
        "- **Status:** Open\n\n"
        "### History\n"
        "| Packet | Note |\n|---|---|\n"
        f"| _Packet:_ [[../01 Intelligence/{stem}]] | Logged |\n",
        encoding="utf-8",
    )

    out = load_intelligence_bundle(vault, "Projects", slug, pid, pdate)
    assert "Executive line one" in out["intelligence_summary"]
    assert out["key_points"] == ["Driver alpha", "Driver beta"]
    assert "delta text" in out["rail_changed"].lower()
    assert any("Escalation coverage" in r for r in out["risks"])
    assert any("Expedite steel" in a for a in out["actions"])
    assert out["rail_do"]


def test_packet_iso_date():
    r = IntelligencePacketRecord(
        packet_id="x",
        project_name="P",
        canonical_project_code="C",
        packet_type="weekly_schedule_intelligence",
        reporting_period="2026-W14",
        title="t",
        operator_notes="",
        status="generated",
        sections=[],
        source_artifacts=[],
        created_at="2026-04-05T12:00:00+00:00",
        updated_at="2026-04-05T12:00:00+00:00",
        published_at=None,
    )
    assert packet_iso_date(r) == "2026-04-05"


def test_build_command_brief_prefers_packet_sections():
    packet = IntelligencePacketRecord(
        packet_id="pkt_" + "b" * 32,
        project_name="P",
        canonical_project_code="C",
        packet_type="weekly_schedule_intelligence",
        reporting_period="2026-W14",
        title="t",
        operator_notes="",
        status="generated",
        sections=[
            IntelligencePacketSection(
                key="finish_milestone_outlook",
                title="Finish",
                body_markdown="**2026-08-01** target.",
                body_html="",
            ),
            IntelligencePacketSection(
                key="delta_vs_prior",
                title="Delta",
                body_markdown="- One week slip on steel.",
                body_html="",
            ),
            IntelligencePacketSection(
                key="key_drivers",
                title="Drivers",
                body_markdown="- Procurement lead time",
                body_html="",
            ),
            IntelligencePacketSection(
                key="near_term_risks",
                title="Risks",
                body_markdown="- Subcontractor capacity",
                body_html="",
            ),
            IntelligencePacketSection(
                key="required_decisions",
                title="Decisions",
                body_markdown="- Approve buyout",
                body_html="",
            ),
            IntelligencePacketSection(
                key="action_register",
                title="Actions",
                body_markdown="- **PM:** Hold daily stand-up",
                body_html="",
            ),
        ],
        source_artifacts=[],
        created_at="2026-04-05T12:00:00+00:00",
        updated_at="2026-04-05T12:00:00+00:00",
        published_at=None,
    )
    intel = {"risks": ["vault risk"], "actions": ["vault act"], "key_points": [], "intelligence_summary": ""}
    brief = build_command_brief(packet, intel)
    assert "2026-08-01" in brief["finish"]
    assert "Procurement" in brief["driver"]
    assert "Subcontractor" in brief["risks"]
    assert "buyout" in brief["need"].lower()
    assert "stand-up" in brief["doing"].lower()


def test_build_command_brief_falls_back_to_vault_strings():
    packet = IntelligencePacketRecord(
        packet_id="pkt_" + "c" * 32,
        project_name="P",
        canonical_project_code="C",
        packet_type="weekly_schedule_intelligence",
        reporting_period="2026-W14",
        title="t",
        operator_notes="",
        status="generated",
        sections=[
            IntelligencePacketSection(key="finish_milestone_outlook", title="F", body_markdown="", body_html=""),
            IntelligencePacketSection(key="key_drivers", title="D", body_markdown="", body_html=""),
            IntelligencePacketSection(key="near_term_risks", title="R", body_markdown="", body_html=""),
            IntelligencePacketSection(key="required_decisions", title="N", body_markdown="", body_html=""),
            IntelligencePacketSection(key="action_register", title="A", body_markdown="", body_html=""),
        ],
        source_artifacts=[],
        created_at="2026-04-05T12:00:00+00:00",
        updated_at="2026-04-05T12:00:00+00:00",
        published_at=None,
    )
    intel = {
        "risks": ["Vault risk line"],
        "actions": ["Vault action one"],
        "key_points": ["Vault key point"],
        "intelligence_summary": "Vault summary text",
    }
    brief = build_command_brief(packet, intel)
    assert brief["risks"].startswith("Vault risk")
    assert brief["need"].startswith("Vault key")
    assert brief["doing"].startswith("Vault action")

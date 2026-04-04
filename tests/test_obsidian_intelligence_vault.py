from __future__ import annotations

import json
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.obsidian.intelligence_vault import _merge_action_register_longitudinal, _rebuild_portfolio_index
from controltower.services.intelligence_packets import load_packet


def test_generate_does_not_export_obsidian_vault(sample_config_path):
    config = load_config(sample_config_path)
    app = create_app(str(sample_config_path))
    client = TestClient(app)

    gen = client.post(
        "/api/packets/generate",
        json={
            "project_code": "AURORA_HILLS",
            "packet_type": "weekly_schedule_intelligence",
            "reporting_period": "2026-W14",
            "title": "Weekly schedule intelligence — vault test",
            "operator_notes": "",
        },
    )
    assert gen.status_code == 200, gen.text
    vault = Path(config.obsidian.vault_root)
    projects = vault / "Projects"
    assert not projects.exists() or not any(projects.rglob("*.md"))


def test_publish_exports_obsidian_vault_with_slug_frontmatter_links_and_evidence(sample_config_path):
    config = load_config(sample_config_path)
    app = create_app(str(sample_config_path))
    client = TestClient(app)

    gen = client.post(
        "/api/packets/generate",
        json={
            "project_code": "AURORA_HILLS",
            "packet_type": "weekly_schedule_intelligence",
            "reporting_period": "2026-W14",
            "title": "Weekly schedule intelligence — vault test",
            "operator_notes": "",
        },
    )
    assert gen.status_code == 200, gen.text
    packet_id = gen.json()["packet_id"]

    vault = Path(config.obsidian.vault_root)
    project_root = vault / "Projects" / "aurora-hills"
    assert not project_root.is_dir()

    pub = client.post(f"/api/packets/{packet_id}/publish", json={})
    assert pub.status_code == 200
    assert project_root.is_dir()
    assert (project_root / "00 Project Index.md").is_file()
    assert (project_root / "02 Risks" / "Active Risks.md").is_file()
    assert (project_root / "03 Actions" / "Action Register.md").is_file()
    assert (project_root / "04 History" / "Timeline.md").is_file()

    intel_dir = project_root / "01 Intelligence"
    packets = list(intel_dir.glob("*.md"))
    assert len(packets) == 1
    assert packet_id in packets[0].name
    assert " — " in packets[0].name

    packet_md = packets[0].read_text(encoding="utf-8")
    assert packet_md.startswith("---\n")
    assert "type: controltower_packet" in packet_md
    assert f"packet_id: {packet_id}" in packet_md
    assert "project_slug: aurora-hills" in packet_md
    assert "status: published" in packet_md
    assert "# Aurora Hills — Intelligence Packet" in packet_md
    assert "[[../00 Project Index]]" in packet_md
    assert "[[../02 Risks/Active Risks]]" in packet_md
    assert "[[../03 Actions/Action Register]]" in packet_md
    assert "## Executive Summary" in packet_md
    assert "## Finish Outlook" in packet_md
    assert "## Required Actions" in packet_md

    index = (project_root / "00 Project Index.md").read_text(encoding="utf-8")
    assert "# Aurora Hills" in index
    assert "project_slug: aurora-hills" in index
    assert "[[02 Risks/Active Risks]]" in index
    assert "[[03 Actions/Action Register]]" in index
    assert "[[04 History/Timeline]]" in index
    stem = packets[0].stem
    assert f"[[01 Intelligence/{stem}]]" in index
    assert "## Packet History" in index

    timeline = (project_root / "04 History" / "Timeline.md").read_text(encoding="utf-8")
    assert "published" in timeline
    assert packet_id in timeline
    assert f"[[../01 Intelligence/{stem}]]" in timeline
    assert timeline.count("<!-- ct-packet:") == 1

    evidence = Path(config.runtime.state_root) / "obsidian_exports" / f"{packet_id}.json"
    assert evidence.is_file()
    ev = json.loads(evidence.read_text(encoding="utf-8"))
    assert ev.get("success") is True
    assert ev["packet_id"] == packet_id
    assert ev["project_slug"] == "aurora-hills"
    assert "timestamp" in ev
    for key in ("packet", "project_index", "risks", "actions", "timeline", "global_index"):
        assert key in ev["paths_written"]

    gidx = vault / "Projects" / "_Index.md"
    assert gidx.is_file()
    gtxt = gidx.read_text(encoding="utf-8")
    assert "Control Tower Portfolio" in gtxt
    assert "aurora-hills/00 Project Index" in gtxt
    assert "aurora-hills/01 Intelligence/" in gtxt


def test_same_project_same_calendar_date_two_distinct_packet_ids_both_notes_exist(sample_config_path, monkeypatch):
    config = load_config(sample_config_path)
    app = create_app(str(sample_config_path))
    client = TestClient(app)

    fixed_time = "2026-04-04T10:00:00+00:00"
    ids_cycle = iter(
        [
            "pkt_" + "a" * 32,
            "pkt_" + "b" * 32,
        ]
    )

    monkeypatch.setattr("controltower.services.intelligence_packets.new_packet_id", lambda: next(ids_cycle))
    monkeypatch.setattr("controltower.services.intelligence_packets.utc_now_iso", lambda: fixed_time)

    gen1 = client.post(
        "/api/packets/generate",
        json={
            "project_code": "AURORA_HILLS",
            "packet_type": "weekly_schedule_intelligence",
            "reporting_period": "2026-W14",
            "title": "Packet one",
            "operator_notes": "",
        },
    )
    assert gen1.status_code == 200
    id1 = gen1.json()["packet_id"]

    gen2 = client.post(
        "/api/packets/generate",
        json={
            "project_code": "AURORA_HILLS",
            "packet_type": "weekly_schedule_intelligence",
            "reporting_period": "2026-W15",
            "title": "Packet two",
            "operator_notes": "",
        },
    )
    assert gen2.status_code == 200
    id2 = gen2.json()["packet_id"]
    assert id1 != id2

    assert client.post(f"/api/packets/{id1}/publish", json={}).status_code == 200
    assert client.post(f"/api/packets/{id2}/publish", json={}).status_code == 200

    intel_dir = Path(config.obsidian.vault_root) / "Projects" / "aurora-hills" / "01 Intelligence"
    names = {p.name for p in intel_dir.glob("*.md")}
    assert f"2026-04-04 — {id1}.md" in names
    assert f"2026-04-04 — {id2}.md" in names


def test_risk_register_longitudinal_dedupes_republish(sample_config_path, monkeypatch):
    config = load_config(sample_config_path)
    app = create_app(str(sample_config_path))
    client = TestClient(app)

    monkeypatch.setattr("controltower.services.intelligence_packets.new_packet_id", lambda: "pkt_" + "c" * 32)
    monkeypatch.setattr("controltower.services.intelligence_packets.utc_now_iso", lambda: "2026-05-01T12:00:00+00:00")

    gen = client.post(
        "/api/packets/generate",
        json={
            "project_code": "AURORA_HILLS",
            "packet_type": "weekly_schedule_intelligence",
            "reporting_period": "2026-W14",
            "title": "Risk dedupe",
            "operator_notes": "",
        },
    )
    assert gen.status_code == 200
    pid = gen.json()["packet_id"]
    assert client.post(f"/api/packets/{pid}/publish", json={}).status_code == 200
    risks_path = Path(config.obsidian.vault_root) / "Projects" / "aurora-hills" / "02 Risks" / "Active Risks.md"
    first = risks_path.read_text(encoding="utf-8")
    assert "First Seen:" in first
    assert "Latest Seen:" in first
    assert "### History" in first
    assert first.count(pid) >= 1

    def _hist_line_count(text: str, packet: str) -> int:
        return len(
            [ln for ln in text.splitlines() if ln.startswith("| [[../01 Intelligence/") and packet in ln],
        )

    before = _hist_line_count(first, pid)
    assert client.post(f"/api/packets/{pid}/publish", json={}).status_code == 200
    second = risks_path.read_text(encoding="utf-8")
    assert _hist_line_count(second, pid) == before


def test_action_register_longitudinal_merge_stable_first_seen_and_history_dedupe():
    """Sample portfolio fixtures may emit an empty action queue; merge logic is tested directly."""
    act_fm = "---\naliases:\n- Test — Action Register\n---\n\n"
    base = act_fm + "# Action Register\n\nRunning action register (deduplicated across packets).\n"
    pid_a = "pkt_" + "d" * 32
    pid_b = "pkt_" + "e" * 32
    stem_a = f"2026-05-02 — {pid_a}"
    stem_b = f"2026-05-03 — {pid_b}"
    items = [
        {
            "role": "Superintendent",
            "action": "Confirm steel delivery window",
            "timing": "This week",
            "signal": "schedule",
            "continuity": "open",
        }
    ]
    m1 = _merge_action_register_longitudinal(base, items, stem_a, pid_a)
    assert "First Seen:" in m1
    assert "Latest Seen:" in m1
    assert "<!-- ct-act-fp:" in m1
    assert f"[[../01 Intelligence/{stem_a}]]" in m1

    def _hist_lines(text: str, packet: str) -> list[str]:
        return [ln for ln in text.splitlines() if ln.startswith("| [[../01 Intelligence/") and packet in ln]

    assert len(_hist_lines(m1, pid_a)) == 1
    m2 = _merge_action_register_longitudinal(m1, items, stem_a, pid_a)
    assert len(_hist_lines(m2, pid_a)) == 1

    m3 = _merge_action_register_longitudinal(m2, items, stem_b, pid_b)
    assert len(_hist_lines(m3, pid_a)) == 1
    assert len(_hist_lines(m3, pid_b)) == 1
    assert f"[[../01 Intelligence/{stem_b}]]" in m3
    assert m3.count("First Seen:") == 1


def test_portfolio_index_lists_multiple_projects(sample_config_path, monkeypatch):
    config = load_config(sample_config_path)
    app = create_app(str(sample_config_path))
    client = TestClient(app)

    monkeypatch.setattr("controltower.services.intelligence_packets.new_packet_id", lambda: "pkt_" + "e" * 32)
    monkeypatch.setattr("controltower.services.intelligence_packets.utc_now_iso", lambda: "2026-06-01T12:00:00+00:00")

    gen = client.post(
        "/api/packets/generate",
        json={
            "project_code": "AURORA_HILLS",
            "packet_type": "weekly_schedule_intelligence",
            "reporting_period": "2026-W14",
            "title": "Multi portfolio",
            "operator_notes": "",
        },
    )
    assert gen.status_code == 200
    packet_id = gen.json()["packet_id"]
    assert client.post(f"/api/packets/{packet_id}/publish", json={}).status_code == 200

    vault = Path(config.obsidian.vault_root)
    side = vault / "Projects" / "side-yard"
    side.mkdir(parents=True)
    (side / "00 Project Index.md").write_text(
        "\n".join(
            [
                "---",
                yaml.safe_dump(
                    {
                        "project_name": "Side Yard",
                        "project_slug": "side-yard",
                        "latest_packet_stem": "2026-01-01 — pkt_" + "f" * 32,
                        "finish_outlook": "Jan 1, 2026",
                        "risk_posture": "Low",
                        "portfolio_updated": "2026-01-01",
                    },
                    sort_keys=False,
                ).strip(),
                "---",
                "",
                "# Side Yard",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _rebuild_portfolio_index(vault, "Projects")
    idx = (vault / "Projects" / "_Index.md").read_text(encoding="utf-8")
    assert "side-yard/00 Project Index" in idx
    assert "aurora-hills/00 Project Index" in idx
    assert idx.count("| [[aurora-hills/01 Intelligence/") >= 1
    assert idx.count("| [[side-yard/01 Intelligence/") >= 1


def test_load_packet_after_publish_matches_obsidian_stem(sample_config_path):
    config = load_config(sample_config_path)
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    gen = client.post(
        "/api/packets/generate",
        json={
            "project_code": "AURORA_HILLS",
            "packet_type": "weekly_schedule_intelligence",
            "reporting_period": "2026-W14",
            "title": "stem check",
            "operator_notes": "",
        },
    )
    pid = gen.json()["packet_id"]
    client.post(f"/api/packets/{pid}/publish", json={})
    rec = load_packet(config.runtime.state_root, pid)
    assert rec is not None
    created = rec.created_at[:10]
    stem = f"{created} — {pid}"
    p = Path(config.obsidian.vault_root) / "Projects" / "aurora-hills" / "01 Intelligence" / f"{stem}.md"
    assert p.is_file()

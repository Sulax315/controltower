"""Locks stakeholder command brief presentation invariants (no routes/models)."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from controltower.api.app import create_app


def _generate_sample_packet(client: TestClient) -> str:
    gen = client.post(
        "/api/packets/generate",
        json={
            "project_code": "AURORA_HILLS",
            "packet_type": "weekly_schedule_intelligence",
            "reporting_period": "2026-W14",
            "title": "Weekly schedule intelligence — test",
            "operator_notes": "Focus procurement risk.",
        },
    )
    assert gen.status_code == 200, gen.text
    return gen.json()["packet_id"]


def test_command_brief_no_system_paths_snake_in_delta_evidence(sample_config_path):
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    packet_id = _generate_sample_packet(client)
    brief = client.get(f"/packets/{packet_id}/brief")
    assert brief.status_code == 200, brief.text
    html = brief.text
    low = html.lower()
    assert "/app/" not in low
    assert "logic_density" not in low
    assert "successor_count" not in low
    assert "predecessor_count" not in low

    m_delta = re.search(
        r"Delta &amp; movement</h2>\s*<ul[^>]*>(.*?)</ul>",
        html,
        re.DOTALL,
    )
    assert m_delta, "delta section missing"
    delta_inner = m_delta.group(1).lower()
    assert not re.search(r"[a-z]{2,}_[a-z]{2,}", delta_inner), f"snake_case in delta: {delta_inner[:200]}"

    m_ev = re.search(r"<tbody>(.*?)</tbody>", html, re.DOTALL)
    assert m_ev, "evidence tbody missing"
    ev_inner = m_ev.group(1).lower()
    assert not re.search(r"[a-z]{2,}_[a-z]{2,}", ev_inner), f"snake_case in evidence: {ev_inner[:200]}"


def test_command_brief_finish_line_is_iso_date_only(sample_config_path):
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    packet_id = _generate_sample_packet(client)
    brief = client.get(f"/packets/{packet_id}/brief")
    assert brief.status_code == 200
    m = re.search(
        r'class="cb-brief-strip__finish-value"[^>]*>([^<]+)<',
        brief.text,
    )
    assert m, "finish value span missing"
    finish_val = m.group(1).strip()
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", finish_val), f"finish not ISO-only: {finish_val!r}"


def test_command_brief_at_most_three_actions(sample_config_path):
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    packet_id = _generate_sample_packet(client)
    brief = client.get(f"/packets/{packet_id}/brief")
    assert brief.status_code == 200
    m = re.search(
        r'<h2 class="cb-brief-h2">Actions</h2>\s*<ul[^>]*>(.*?)</ul>',
        brief.text,
        re.DOTALL,
    )
    if not m:
        return
    assert len(re.findall(r"<li>", m.group(1))) <= 3


def test_command_brief_zone_order_and_hierarchy_hooks(sample_config_path):
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    packet_id = _generate_sample_packet(client)
    brief = client.get(f"/packets/{packet_id}/brief")
    assert brief.status_code == 200
    html = brief.text

    idx_header = html.find('id="cb-zone-command-header"')
    idx_verdict = html.find('id="cb-zone-verdict-band"')
    idx_core = html.find('id="cb-zone-core-grid"')
    idx_evidence = html.find('id="cb-zone-evidence"')
    assert -1 not in (idx_header, idx_verdict, idx_core, idx_evidence)
    assert idx_header < idx_verdict < idx_core < idx_evidence

    assert 'class="cb-brief-strip__finish-value"' in html
    assert "cb-brief-status-pill--dominant" in html
    assert "cb-brief-list--actions" in html
    assert "cb-brief-table--secondary" in html

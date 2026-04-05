from __future__ import annotations

import re

from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.services.intelligence_packets import load_packet, packets_root


def test_intelligence_packet_happy_path(sample_config_path):
    config = load_config(sample_config_path)
    app = create_app(str(sample_config_path))
    client = TestClient(app)

    assert client.get("/packets/new").status_code == 200
    body = client.get("/packets/new").text
    assert 'id="packet-intake-shell"' in body
    assert "Weekly Schedule Intelligence" in body

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
    gen_payload = gen.json()
    packet_id = gen_payload["packet_id"]
    assert packet_id.startswith("pkt_")
    assert gen_payload["status"] == "generated"
    assert gen_payload["detail_path"] == f"/packets/{packet_id}"

    root = packets_root(config.runtime.state_root)
    assert (root / packet_id / "packet.json").is_file()
    assert (root / packet_id / "packet.md").is_file()
    assert (root / packet_id / "packet.html").is_file()

    loaded = load_packet(config.runtime.state_root, packet_id)
    assert loaded is not None
    assert loaded.status == "generated"
    assert len(loaded.sections) == 8
    keys = [s.key for s in loaded.sections]
    assert keys[0] == "executive_summary"
    assert "action_register" in keys
    assert "source_evidence_appendix" in keys

    api_get = client.get(f"/api/packets/{packet_id}")
    assert api_get.status_code == 200
    assert api_get.json()["packet_id"] == packet_id

    detail = client.get(f"/packets/{packet_id}")
    assert detail.status_code == 200
    assert 'id="packet-detail-shell"' in detail.text
    assert "Weekly schedule intelligence — test" in detail.text
    assert 'id="pkt-command-strip"' in detail.text
    assert "pkt-section-card" in detail.text
    assert 'id="pkt-command-brief-bar"' in detail.text
    assert 'id="pkt-intelligence-rail"' in detail.text
    assert "Intelligence rail" in detail.text
    assert "What changed" in detail.text
    assert f'href="/packets/{packet_id}/brief"' in detail.text

    brief = client.get(f"/packets/{packet_id}/brief")
    assert brief.status_code == 200
    assert "cb-brief" in brief.text
    assert "Command brief" in brief.text

    export = client.get(f"/api/packets/{packet_id}/export/markdown")
    assert export.status_code == 200
    assert "text/markdown" in export.headers.get("content-type", "")
    assert "attachment" in export.headers.get("content-disposition", "").lower()
    assert b"# Weekly schedule intelligence" in export.content
    assert b"Executive Summary" in export.content

    pub = client.post(f"/api/packets/{packet_id}/publish", json={})
    assert pub.status_code == 200
    assert pub.json()["status"] == "published"
    assert pub.json()["published_at"]

    after = load_packet(config.runtime.state_root, packet_id)
    assert after is not None
    assert after.status == "published"


def test_packet_detail_404_and_invalid_id(sample_config_path):
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    assert client.get("/packets/not-a-real-id").status_code == 400
    assert client.get("/packets/not-a-real-id/brief").status_code == 400
    missing = "pkt_" + "0" * 32
    assert client.get(f"/packets/{missing}").status_code == 404
    assert client.get(f"/packets/{missing}/brief").status_code == 404


def test_api_invalid_packet_id_returns_400(sample_config_path):
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    bad = "not-a-packet"
    assert client.get(f"/api/packets/{bad}").status_code == 400
    assert client.get(f"/api/packets/{bad}/export/markdown").status_code == 400
    assert client.post(f"/api/packets/{bad}/publish").status_code == 400


def test_browser_post_packets_new_redirects(sample_config_path):
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    intake = client.get("/packets/new")
    assert intake.status_code == 200
    m = re.search(r'name="csrf_token" value="([^"]+)"', intake.text)
    assert m
    resp = client.post(
        "/packets/new",
        data={
            "csrf_token": m.group(1),
            "project_code": "AURORA_HILLS",
            "packet_type": "weekly_schedule_intelligence",
            "reporting_period": "2026-W14",
            "title": "Browser intake weekly packet",
            "operator_notes": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers.get("location", "").startswith("/packets/pkt_")

from __future__ import annotations

from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.services.intelligence_packets import (
    export_markdown_bytes,
    load_packet,
    packets_root,
    publish_packet,
)
from tests.packet_service_helpers import generate_and_write_packet


def _weekly_req(**overrides: str) -> dict[str, str]:
    base = {
        "project_code": "AURORA_HILLS",
        "packet_type": "weekly_schedule_intelligence",
        "reporting_period": "2026-W14",
        "title": "Weekly schedule intelligence — test",
        "operator_notes": "Focus procurement risk.",
    }
    base.update(overrides)
    return base


def test_intelligence_packet_service_happy_path(sample_config_path):
    config = load_config(sample_config_path)
    packet_id = generate_and_write_packet(config, **_weekly_req())

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

    updated = publish_packet(config.runtime.state_root, packet_id)
    assert updated is not None
    assert updated.status == "published"
    assert updated.published_at

    exported = export_markdown_bytes(config.runtime.state_root, packet_id)
    assert exported is not None
    filename, body = exported
    assert filename.endswith(f"{packet_id}.md")
    assert b"# Weekly schedule intelligence" in body
    assert b"Executive Summary" in body


def test_retired_packet_http_surface_returns_404(sample_config_path):
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    assert client.get("/packets/new").status_code == 404
    assert client.post("/api/packets/generate", json=_weekly_req()).status_code == 404
    missing = "pkt_" + "0" * 32
    assert client.get(f"/packets/{missing}").status_code == 404
    assert client.get(f"/api/packets/{missing}").status_code == 404
    assert client.get(f"/api/packets/{missing}/export/markdown").status_code == 404
    assert client.post(f"/api/packets/{missing}/publish", json={}).status_code == 404


def test_packet_detail_invalid_id_blocked(sample_config_path):
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    assert client.get("/packets/not-a-real-id").status_code == 404


def test_browser_post_packets_new_blocked(sample_config_path):
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    assert client.post("/packets/new", data={"project_code": "X"}).status_code == 404

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.obsidian.intelligence_vault import _list_intel_packet_stems
from controltower.services.intelligence_vault_bridge import (
    read_vault_markdown_html,
    relative_vault_path,
    resolve_project_index_path,
)


def test_relative_vault_path_under_root(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    f = vault / "Projects" / "x" / "note.md"
    f.parent.mkdir(parents=True)
    f.write_text("x", encoding="utf-8")
    assert relative_vault_path(vault, f) == "Projects/x/note.md"


def test_list_intel_packet_stems_prefers_newer_mtime(tmp_path):
    intel = tmp_path / "intel"
    intel.mkdir()
    older = intel / "2026-04-05 — pkt_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.md"
    newer = intel / "2026-04-05 — pkt_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.md"
    older.write_text("a", encoding="utf-8")
    newer.write_text("b", encoding="utf-8")
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))
    stems = _list_intel_packet_stems(intel)
    assert stems[0].endswith("pkt_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")


def test_packet_detail_renders_vault_bridge(sample_config_path):
    config = load_config(sample_config_path)
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    gen = client.post(
        "/api/packets/generate",
        json={
            "project_code": "AURORA_HILLS",
            "packet_type": "weekly_schedule_intelligence",
            "reporting_period": "2026-W23",
            "title": "bridge html",
            "operator_notes": "",
        },
    )
    pid = gen.json()["packet_id"]
    r = client.get(f"/packets/{pid}")
    assert r.status_code == 200
    assert "Intelligence vault" in r.text
    assert "Unknown" in r.text or "Not synced" in r.text or "Synced" in r.text

    assert client.post(f"/api/packets/{pid}/publish", json={}).status_code == 200
    r2 = client.get(f"/packets/{pid}")
    assert r2.status_code == 200
    assert "Synced" in r2.text
    assert f"/vault/intelligence/packets/{pid}/note" in r2.text


def test_vault_note_route_renders(sample_config_path):
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    gen = client.post(
        "/api/packets/generate",
        json={
            "project_code": "AURORA_HILLS",
            "packet_type": "weekly_schedule_intelligence",
            "reporting_period": "2026-W24",
            "title": "vault route",
            "operator_notes": "",
        },
    )
    pid = gen.json()["packet_id"]
    client.post(f"/api/packets/{pid}/publish", json={})
    r = client.get(f"/vault/intelligence/packets/{pid}/note")
    assert r.status_code == 200
    assert "Executive Summary" in r.text or "executive" in r.text.lower()


def test_vault_note_route_missing_file_graceful(sample_config_path):
    config = load_config(sample_config_path)
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    gen = client.post(
        "/api/packets/generate",
        json={
            "project_code": "AURORA_HILLS",
            "packet_type": "weekly_schedule_intelligence",
            "reporting_period": "2026-W25",
            "title": "missing",
            "operator_notes": "",
        },
    )
    pid = gen.json()["packet_id"]
    client.post(f"/api/packets/{pid}/publish", json={})
    record = __import__(
        "controltower.services.intelligence_packets",
        fromlist=["load_packet"],
    ).load_packet(config.runtime.state_root, pid)
    paths = __import__(
        "controltower.services.intelligence_vault_bridge",
        fromlist=["resolve_paths_for_packet"],
    ).resolve_paths_for_packet(record, config)
    Path(paths["packet"]).unlink()
    r = client.get(f"/vault/intelligence/packets/{pid}/note")
    assert r.status_code == 200
    assert "Artifact not found" in r.text


def test_resolve_project_index_path(sample_config_path):
    config = load_config(sample_config_path)
    p = resolve_project_index_path(config, "AURORA_HILLS")
    assert p is not None
    assert "aurora-hills" in str(p).replace("\\", "/")


def test_read_vault_rejects_path_outside_vault(sample_config_path):
    config = load_config(sample_config_path)
    ok, _body = read_vault_markdown_html(config, Path("/etc/passwd"))
    assert ok is False

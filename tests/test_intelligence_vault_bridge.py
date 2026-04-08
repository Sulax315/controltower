from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.obsidian.intelligence_vault import _list_intel_packet_stems
from controltower.services.intelligence_packets import load_packet
from controltower.services.intelligence_vault_bridge import (
    build_packet_bridge_context,
    read_vault_markdown_html,
    relative_vault_path,
    resolve_paths_for_packet,
    resolve_project_index_path,
)
from tests.packet_service_helpers import generate_and_write_packet, publish_packet_and_sync_obsidian


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


def test_vault_bridge_context_tracks_sync_status(sample_config_path):
    config = load_config(sample_config_path)
    pid = generate_and_write_packet(
        config,
        project_code="AURORA_HILLS",
        packet_type="weekly_schedule_intelligence",
        reporting_period="2026-W23",
        title="bridge html",
        operator_notes="",
    )
    record = load_packet(config.runtime.state_root, pid)
    assert record is not None
    before = build_packet_bridge_context(record, config)
    assert before["status"] in {"unknown", "not_synced"}

    publish_packet_and_sync_obsidian(config, pid)
    record2 = load_packet(config.runtime.state_root, pid)
    assert record2 is not None
    after = build_packet_bridge_context(record2, config)
    assert after["status"] == "synced"

    app = create_app(str(sample_config_path))
    client = TestClient(app)
    assert client.get(f"/vault/intelligence/packets/{pid}/note").status_code == 404


def test_vault_note_markdown_renders_after_sync(sample_config_path):
    config = load_config(sample_config_path)
    pid = generate_and_write_packet(
        config,
        project_code="AURORA_HILLS",
        packet_type="weekly_schedule_intelligence",
        reporting_period="2026-W24",
        title="vault route",
        operator_notes="",
    )
    publish_packet_and_sync_obsidian(config, pid)
    record = load_packet(config.runtime.state_root, pid)
    assert record is not None
    paths = resolve_paths_for_packet(record, config)
    ok, html = read_vault_markdown_html(config, Path(paths["packet"]))
    assert ok is True
    assert "executive" in html.lower()

    app = create_app(str(sample_config_path))
    client = TestClient(app)
    assert client.get(f"/vault/intelligence/packets/{pid}/note").status_code == 404


def test_vault_note_missing_file_graceful_via_reader(sample_config_path):
    config = load_config(sample_config_path)
    pid = generate_and_write_packet(
        config,
        project_code="AURORA_HILLS",
        packet_type="weekly_schedule_intelligence",
        reporting_period="2026-W25",
        title="missing",
        operator_notes="",
    )
    publish_packet_and_sync_obsidian(config, pid)
    record = load_packet(config.runtime.state_root, pid)
    assert record is not None
    paths = resolve_paths_for_packet(record, config)
    Path(paths["packet"]).unlink()
    ok, _html = read_vault_markdown_html(config, Path(paths["packet"]))
    assert ok is False

    app = create_app(str(sample_config_path))
    client = TestClient(app)
    assert client.get(f"/vault/intelligence/packets/{pid}/note").status_code == 404


def test_resolve_project_index_path(sample_config_path):
    config = load_config(sample_config_path)
    p = resolve_project_index_path(config, "AURORA_HILLS")
    assert p is not None
    assert "aurora-hills" in str(p).replace("\\", "/")


def test_read_vault_rejects_path_outside_vault(sample_config_path):
    config = load_config(sample_config_path)
    ok, _body = read_vault_markdown_html(config, Path("/etc/passwd"))
    assert ok is False

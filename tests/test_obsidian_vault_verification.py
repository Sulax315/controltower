from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from controltower.config import load_config
from controltower.services.obsidian_vault_verification import (
    verify_intelligence_vault_packets,
    write_intelligence_vault_verification_artifact,
)
from tests.packet_service_helpers import generate_and_write_packet, publish_packet_and_sync_obsidian


def test_verify_passes_when_obsidian_lacks_intel_vault_config_attrs(sample_config_path):
    """Published export + verifier must work when ``obsidian`` only exposes ``vault_root``."""
    config = load_config(sample_config_path)
    pid = generate_and_write_packet(
        config,
        project_code="AURORA_HILLS",
        packet_type="weekly_schedule_intelligence",
        reporting_period="2026-W30",
        title="legacy obsidian stub",
        operator_notes="",
    )
    publish_packet_and_sync_obsidian(config, pid)

    vault_root = Path(config.obsidian.vault_root)
    object.__setattr__(config, "obsidian", SimpleNamespace(vault_root=vault_root))

    result = verify_intelligence_vault_packets(config, [pid])
    assert result["result"] == "PASS"
    assert result["projects_folder"] == "Projects"
    assert result["intelligence_vault_enabled"] is True


def test_verify_passes_after_publish(sample_config_path):
    config = load_config(sample_config_path)
    pid = generate_and_write_packet(
        config,
        project_code="AURORA_HILLS",
        packet_type="weekly_schedule_intelligence",
        reporting_period="2026-W20",
        title="verify artifact",
        operator_notes="",
    )
    publish_packet_and_sync_obsidian(config, pid)

    result = verify_intelligence_vault_packets(config, [pid])
    assert result["result"] == "PASS"
    assert result["failure_reason"] is None
    assert result["content_checks"]["packet_markdown"] is True
    assert any(pid in p for p in result["files_verified_present"])

    latest, hist = write_intelligence_vault_verification_artifact(Path(config.runtime.state_root), result)
    assert latest.is_file()
    assert hist is not None and hist.is_file()


def test_verify_fails_without_publish(sample_config_path):
    config = load_config(sample_config_path)
    pid = generate_and_write_packet(
        config,
        project_code="AURORA_HILLS",
        packet_type="weekly_schedule_intelligence",
        reporting_period="2026-W21",
        title="draft only",
        operator_notes="",
    )
    result = verify_intelligence_vault_packets(config, [pid])
    assert result["result"] == "FAIL"
    assert "not_published" in (result.get("failure_reason") or "")


def test_verify_fails_on_missing_packet_file(sample_config_path):
    config = load_config(sample_config_path)
    pid = generate_and_write_packet(
        config,
        project_code="AURORA_HILLS",
        packet_type="weekly_schedule_intelligence",
        reporting_period="2026-W22",
        title="tamper",
        operator_notes="",
    )
    publish_packet_and_sync_obsidian(config, pid)

    ev_path = Path(config.runtime.state_root) / "obsidian_exports" / f"{pid}.json"
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    pkt_path = Path(ev["paths_written"]["packet"])
    pkt_path.unlink()

    result = verify_intelligence_vault_packets(config, [pid])
    assert result["result"] == "FAIL"
    assert "missing_file" in (result.get("failure_reason") or "")


def test_write_artifact_rejects_fail(tmp_path):
    with pytest.raises(ValueError, match="PASS"):
        write_intelligence_vault_verification_artifact(
            tmp_path,
            {"result": "FAIL"},
        )

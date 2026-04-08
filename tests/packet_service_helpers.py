"""Service-layer helpers for intelligence packet tests (HTTP packet routes are primary-surface blocked)."""

from __future__ import annotations

from typing import Any

from controltower.config import ControlTowerConfig
from controltower.obsidian.intelligence_vault import try_sync_intelligence_packet_to_obsidian
from controltower.services.controltower import ControlTowerService
from controltower.services.intelligence_packets import (
    GeneratePacketRequest,
    generate_weekly_schedule_intelligence_packet,
    load_packet,
    publish_packet,
    write_packet_artifacts,
)


def generate_and_write_packet(config: ControlTowerConfig, **req_fields: Any) -> str:
    service = ControlTowerService(config)
    req = GeneratePacketRequest(**req_fields)
    record = generate_weekly_schedule_intelligence_packet(service, req)
    write_packet_artifacts(config.runtime.state_root, record)
    return record.packet_id


def publish_packet_and_sync_obsidian(config: ControlTowerConfig, packet_id: str):
    updated = publish_packet(config.runtime.state_root, packet_id)
    assert updated is not None
    try_sync_intelligence_packet_to_obsidian(
        config.obsidian,
        updated,
        state_root=config.runtime.state_root,
    )
    return updated


def sync_obsidian_for_existing_packet(config: ControlTowerConfig, packet_id: str):
    """Re-run Obsidian sync for an already-published packet (matches legacy HTTP republish behavior)."""
    record = load_packet(config.runtime.state_root, packet_id)
    assert record is not None
    try_sync_intelligence_packet_to_obsidian(
        config.obsidian,
        record,
        state_root=config.runtime.state_root,
    )
    return record

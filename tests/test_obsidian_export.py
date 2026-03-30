from __future__ import annotations

from controltower.config import load_config
from controltower.obsidian.exporter import load_latest_export
from controltower.services.controltower import ControlTowerService


def test_export_writes_vault_and_manifest(sample_config_path):
    config = load_config(sample_config_path)
    service = ControlTowerService(config)
    record = service.export_notes(preview_only=False)

    assert record.notes
    assert all(note.output_path.exists() for note in record.notes)
    assert any(note.versioned_output_paths for note in record.notes)
    assert all(path.exists() for note in record.notes for path in note.versioned_output_paths)
    latest = load_latest_export(config.runtime.state_root)
    assert latest is not None
    assert latest["status"] in {"success", "partial"}
    assert (config.runtime.state_root / "history" / f"{record.run_id}.json").exists()

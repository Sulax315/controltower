from __future__ import annotations

from controltower.acceptance.harness import run_acceptance
from controltower.config import load_config


def test_acceptance_harness_passes(sample_config_path):
    config = load_config(sample_config_path)
    result = run_acceptance(config)

    assert result["status"] == "pass"
    assert result["note_count"] >= 3
    assert result["written_note_count"] >= 3
    assert result["route_checks"]["live_route_gate"] == "pass"
    assert result["route_checks"]["/api/portfolio"] == 404
    assert result["route_checks"]["/arena"] == 404
    assert result["coherence_checks"]["root_redirects_to_publish"] is True
    assert result["coherence_checks"]["publish_surface_authoritative"] is True
    assert result["coherence_checks"]["legacy_surfaces_blocked"] is True

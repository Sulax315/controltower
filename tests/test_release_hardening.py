from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest
import yaml

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.domain.models import ProjectIdentity
from controltower.services.controltower import ControlTowerService
from controltower.services.delta import build_project_delta
from controltower.services.release import build_release_readiness


def test_load_config_fails_for_missing_file(tmp_path: Path):
    missing_path = tmp_path / "missing.yaml"

    with pytest.raises(FileNotFoundError, match="config file is missing"):
        load_config(missing_path)


def test_registry_validation_rejects_ambiguous_aliases(
    tmp_path: Path,
    sample_schedulelab_root: Path,
    sample_profitintel_db: Path,
):
    registry_path = tmp_path / "project_registry.yaml"
    registry_path.write_text(
        yaml.safe_dump(
            {
                "projects": [
                    {
                        "canonical_project_id": "ALPHA_ONE",
                        "project_name": "Alpha One",
                        "project_code_aliases": ["ALPHA"],
                    },
                    {
                        "canonical_project_id": "ALPHA_TWO",
                        "project_name": "Alpha Two",
                        "project_code_aliases": ["ALPHA"],
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "controltower.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "sources": {
                    "schedulelab": {"published_root": str(sample_schedulelab_root)},
                    "profitintel": {"database_path": str(sample_profitintel_db), "validation_search_roots": []},
                },
                "identity": {"registry_path": str(registry_path)},
                "obsidian": {"vault_root": str(tmp_path / "vault")},
                "runtime": {"state_root": str(tmp_path / "state")},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ambiguous alias"):
        ControlTowerService(load_config(config_path))


def test_delta_handles_missing_prior_run_without_crashing():
    delta = build_project_delta(
        ProjectIdentity(
            canonical_project_id="AURORA_HILLS",
            canonical_project_code="AURORA_HILLS",
            project_name="Aurora Hills",
        ),
        schedule=None,
        financial=None,
        previous=None,
    )

    assert "No prior schedule baseline was available" in delta.schedule.summary
    assert "No prior financial baseline was available" in delta.financial.summary
    assert "No prior risk baseline was available" in delta.risk.summary


def test_required_actions_are_deterministic(sample_config_path: Path):
    config = load_config(sample_config_path)
    service = ControlTowerService(config)

    first_actions = [action.model_dump(mode="json") for action in service.build_projects()[0].health.required_actions]
    second_actions = [action.model_dump(mode="json") for action in service.build_projects()[0].health.required_actions]

    assert first_actions == second_actions


def test_release_readiness_writes_json_and_markdown_artifacts(sample_config_path: Path):
    config = load_config(sample_config_path)

    artifact = build_release_readiness(
        config,
        pytest_result={"status": "pass", "command": "pytest -q", "exit_code": 0},
        acceptance_result={"status": "pass", "executed_at": "2026-03-27T15:30:00Z"},
    )

    json_path = Path(artifact["artifact_paths"]["json"])
    markdown_path = Path(artifact["artifact_paths"]["markdown"])

    assert artifact["verdict"]["ready_for_live_operations"] is True
    assert artifact["schema_version"] == "2026-03-27"
    assert "gate_results" in artifact
    assert "latest_evidence" in artifact
    assert artifact["verdict"]["operator_recommendation"]
    assert artifact["route_checks"]["status"] == "pass"
    assert artifact["export_checks"]["status"] == "pass"
    assert artifact["route_checks"]["checks"]["/arena"] == 200
    assert artifact["route_checks"]["checks"]["/arena?selected=AURORA_HILLS"] == 200
    assert artifact["route_checks"]["checks"]["/arena/export?selected=AURORA_HILLS"] == 200
    assert artifact["route_checks"]["checks"]["/arena/export/artifact.md?selected=AURORA_HILLS"] == 200
    assert artifact["route_checks"]["visibility_checks"]["root_redirects_to_publish"] is True
    assert artifact["route_checks"]["visibility_checks"]["root_renders_publish_surface"] is True
    assert artifact["route_checks"]["visibility_checks"]["legacy_control_is_available"] is True
    assert artifact["route_checks"]["visibility_checks"]["arena_renders_trust_posture"] is True
    assert artifact["route_checks"]["visibility_checks"]["artifact_renders_selection_context"] is True
    assert artifact["route_checks"]["visibility_checks"]["artifact_renders_trust_state"] is True
    assert artifact["route_checks"]["meeting_readiness"]["status"] == "pass"
    assert artifact["route_checks"]["meeting_readiness"]["checks"]["root_execution_brief_first_screen"] is True
    assert artifact["route_checks"]["meeting_readiness"]["checks"]["root_finish_is_first"] is True
    assert artifact["route_checks"]["meeting_readiness"]["checks"]["root_sections_obey_project_decision_contract"] is True
    assert artifact["route_checks"]["meeting_readiness"]["checks"]["arena_execution_brief_leads_visible_surface"] is True
    assert artifact["route_checks"]["meeting_readiness"]["checks"]["artifact_preserves_finish_contract"] is True
    assert artifact["route_checks"]["meeting_readiness"]["checks"]["stale_vague_finish_language_absent"] is True
    assert json_path.exists()
    assert markdown_path.exists()
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Overall verdict: READY" in markdown
    assert "Operator recommendation:" in markdown
    assert "Latest Evidence References" in markdown


def test_diagnostics_surface_exposes_version_and_release_status(sample_config_path: Path):
    config = load_config(sample_config_path)
    build_release_readiness(
        config,
        pytest_result={"status": "pass", "command": "pytest -q", "exit_code": 0},
        acceptance_result={"status": "pass", "executed_at": "2026-03-27T15:30:00Z"},
    )

    client = TestClient(create_app(str(sample_config_path)))
    diagnostics = client.get("/api/diagnostics")

    assert diagnostics.status_code == 200
    payload = diagnostics.json()
    assert payload["product"]["version"] == "0.1.0"
    assert payload["release"]["status"] == "ready"
    assert payload["acceptance"]["last_successful_run_at"] == "2026-03-27T15:30:00Z"
    assert payload["artifacts"]["latest_export_status"] == "success"
    assert payload["templates"]["markdown"]["status"] == "ok"
    assert payload["registry"]["status"] == "loaded"
    assert payload["artifacts"]["presence_checks"]["latest_release_json"] is True
    assert payload["comparison_runtime"]["comparison_run_matches_surface"] is True
    assert payload["comparison_runtime"]["contained_blocks_authoritative_delta"] is True

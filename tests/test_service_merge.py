from __future__ import annotations

from controltower.config import load_config
from controltower.services.controltower import ControlTowerService


def test_service_builds_merged_snapshot(sample_config_path):
    config = load_config(sample_config_path)
    service = ControlTowerService(config)
    projects = service.build_projects()

    assert len(projects) == 1
    project = projects[0]
    assert project.canonical_project_id == "AURORA_HILLS"
    assert project.project_name == "Aurora Hills"
    assert project.schedule is not None
    assert project.financial is not None
    assert sorted(project.source_keys) == ["profitintel:219128", "schedulelab:AURORA_HILLS"]
    assert project.health.tier in {"watch", "at_risk"}
    assert project.health.required_actions

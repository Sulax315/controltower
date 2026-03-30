from __future__ import annotations

import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest
import yaml

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.domain.models import ProjectIdentity
from controltower.services.controltower import ControlTowerService
from controltower.services.delta import build_project_delta
from controltower.services.release import build_release_readiness, stamp_release_trace
from controltower.services.release_trace import collect_source_release_trace


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
    live_deployment_path = Path(config.runtime.state_root) / "release" / "latest_live_deployment.json"
    live_deployment_path.parent.mkdir(parents=True, exist_ok=True)
    live_deployment_path.write_text(
        '{"git_commit": "abc123", "deployed_at": "2026-03-30T22:00:00Z"}',
        encoding="utf-8",
    )

    client = TestClient(create_app(str(sample_config_path)))
    diagnostics = client.get("/api/diagnostics")

    assert diagnostics.status_code == 200
    payload = diagnostics.json()
    assert payload["product"]["version"] == "0.1.0"
    assert payload["product"]["build_metadata"]["asset_version"]
    assert payload["release"]["status"] == "ready"
    assert payload["release"]["live_deployment_present"] is True
    assert payload["release"]["live_git_commit"] == "abc123"
    assert payload["release"]["live_deployed_at"] == "2026-03-30T22:00:00Z"
    assert payload["acceptance"]["last_successful_run_at"] == "2026-03-27T15:30:00Z"
    assert payload["artifacts"]["latest_export_status"] == "success"
    assert payload["templates"]["markdown"]["status"] == "ok"
    assert payload["registry"]["status"] == "loaded"
    assert payload["artifacts"]["presence_checks"]["latest_release_json"] is True
    assert payload["comparison_runtime"]["comparison_run_matches_surface"] is True
    assert payload["comparison_runtime"]["contained_blocks_authoritative_delta"] is True


def test_release_readiness_route_checks_pass_with_prod_app_auth(sample_config_path: Path):
    config = load_config(sample_config_path)
    config.auth.mode = "prod"
    config.auth.session_secret = "prod-app-session-secret"
    config.auth.username = "operator"
    config.auth.password = "operator-pass"

    artifact = build_release_readiness(
        config,
        pytest_result={"status": "pass", "command": "pytest -q", "exit_code": 0},
        acceptance_result={"status": "pass", "executed_at": "2026-03-27T15:30:00Z"},
    )

    assert artifact["route_checks"]["status"] == "pass"
    assert artifact["route_checks"]["checks"]["/publish"] == 200
    assert artifact["route_checks"]["checks"]["/api/diagnostics"] == 200
    assert artifact["route_checks"]["auth_checks"]["login_returns_200"] is True
    assert artifact["route_checks"]["auth_checks"]["publish_requires_login"] is True
    assert artifact["route_checks"]["auth_checks"]["api_requires_auth"] is True
    assert artifact["route_checks"]["auth_checks"]["authenticated_publish_succeeds"] is True
    assert artifact["route_checks"]["auth_checks"]["authenticated_api_succeeds"] is True


def test_release_source_trace_fails_when_origin_is_missing(tmp_path: Path):
    repo_root = _init_git_repo(tmp_path / "repo")

    trace = collect_source_release_trace(repo_root)

    assert trace["status"] == "fail"
    assert trace["error"] == "Required Git remote 'origin' is missing."
    assert trace["checks"][2]["name"] == "origin_exists"
    assert trace["checks"][2]["status"] == "fail"
    assert trace["remediation_commands"] == [
        f"cd {repo_root.resolve()}",
        "git remote add origin <AUTHORITATIVE_REMOTE_URL>",
        "git fetch origin main",
        "git branch --set-upstream-to=origin/main main",
    ]


def test_release_source_trace_fails_when_fetch_fails(tmp_path: Path):
    repo_root = _init_git_repo(tmp_path / "repo")
    missing_remote = tmp_path / "missing-remote.git"
    subprocess.run(["git", "-C", str(repo_root), "remote", "add", "origin", str(missing_remote)], check=True)

    trace = collect_source_release_trace(repo_root)

    assert trace["status"] == "fail"
    assert trace["error"] == "Fetch from origin/main failed."
    assert any(check["name"] == "fetch_origin" and check["status"] == "fail" for check in trace["checks"])


def test_release_source_trace_fails_when_local_is_behind_origin_main(tmp_path: Path):
    remote_root = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(remote_root)], check=True)

    seeded_repo = _init_git_repo(tmp_path / "seed")
    subprocess.run(["git", "-C", str(seeded_repo), "remote", "add", "origin", str(remote_root)], check=True)
    subprocess.run(["git", "-C", str(seeded_repo), "push", "-u", "origin", "main"], check=True)

    working_repo = tmp_path / "working"
    subprocess.run(["git", "clone", str(remote_root), str(working_repo)], check=True)
    subprocess.run(["git", "-C", str(working_repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(working_repo), "config", "user.name", "Test User"], check=True)

    update_repo = tmp_path / "update"
    subprocess.run(["git", "clone", str(remote_root), str(update_repo)], check=True)
    subprocess.run(["git", "-C", str(update_repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(update_repo), "config", "user.name", "Test User"], check=True)
    (update_repo / "remote.txt").write_text("remote update\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(update_repo), "add", "remote.txt"], check=True)
    subprocess.run(["git", "-C", str(update_repo), "commit", "-m", "remote update"], check=True)
    subprocess.run(["git", "-C", str(update_repo), "push", "origin", "main"], check=True)

    trace = collect_source_release_trace(working_repo)

    assert trace["status"] == "fail"
    assert trace["push_status"] == "local_behind"
    assert trace["error"] == "Local branch is behind origin/main."
    assert any(check["name"] == "local_not_behind_origin_main" and check["status"] == "fail" for check in trace["checks"])


def test_release_artifact_records_local_remote_and_deployed_commit_metadata(sample_config_path: Path):
    config = load_config(sample_config_path)
    artifact = build_release_readiness(
        config,
        pytest_result={"status": "pass", "command": "pytest -q", "exit_code": 0},
        acceptance_result={"status": "pass", "executed_at": "2026-03-27T15:30:00Z"},
    )

    stamped = stamp_release_trace(
        Path(config.runtime.state_root),
        {
            "generated_at": "2026-03-30T21:20:00Z",
            "local_head_commit": "c8f3e5a",
            "remote_origin_main_commit": "c8f3e5a",
            "deployed_git_commit": "c8f3e5a",
            "verification_status": "pass",
            "push_status": "up_to_date",
        },
    )
    latest_json = Path(artifact["artifact_paths"]["latest_json"])
    latest_markdown = Path(artifact["artifact_paths"]["latest_markdown"])
    payload = json.loads(latest_json.read_text(encoding="utf-8"))
    markdown = latest_markdown.read_text(encoding="utf-8")

    assert stamped is not None
    assert payload["release_trace"]["local_head_commit"] == "c8f3e5a"
    assert payload["release_trace"]["remote_origin_main_commit"] == "c8f3e5a"
    assert payload["release_trace"]["deployed_git_commit"] == "c8f3e5a"
    assert payload["release_trace"]["verification_status"] == "pass"
    assert "## Release Trace" in markdown
    assert "- Local HEAD commit: c8f3e5a" in markdown
    assert "- Remote origin/main commit: c8f3e5a" in markdown
    assert "- Deployed GIT_COMMIT: c8f3e5a" in markdown
    assert "- Verification status: pass" in markdown


def test_release_entrypoints_delegate_to_single_authoritative_flow():
    repo_root = Path(__file__).resolve().parents[1]
    deploy_update = (repo_root / "infra" / "deploy" / "controltower" / "deploy_update.sh").read_text(encoding="utf-8")
    python_wrapper = (repo_root / "scripts" / "release_controltower.py").read_text(encoding="utf-8")
    linux_wrapper = (repo_root / "ops" / "linux" / "release_controltower.sh").read_text(encoding="utf-8")
    windows_wrapper = (repo_root / "ops" / "windows" / "Invoke-ControlTowerRelease.ps1").read_text(encoding="utf-8")

    assert "deploy_update_controltower.py" in deploy_update
    assert "release_source_controltower.py" not in deploy_update
    assert "rsync -a --delete" not in deploy_update
    assert "deprecated" in python_wrapper
    assert "deploy_update_controltower.py" in python_wrapper
    assert "deprecated" in linux_wrapper
    assert "infra/deploy/controltower/deploy_update.sh" in linux_wrapper
    assert "compatibility wrapper" in windows_wrapper
    assert "deploy_update_controltower.py" in windows_wrapper


def _init_git_repo(repo_root: Path) -> Path:
    repo_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--initial-branch=main", str(repo_root)], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "Test User"], check=True)
    (repo_root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "initial"], check=True)
    return repo_root

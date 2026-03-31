from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest
import yaml

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.domain.models import ProjectIdentity
from controltower.services.operations import run_release_gate
from controltower.services.controltower import ControlTowerService
from controltower.services.delta import build_project_delta
from controltower.services.release import build_release_readiness, run_pytest_suite, stamp_release_trace
from controltower.services.release_trace import collect_source_release_trace


def test_run_pytest_suite_invokes_subprocess(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    def _fake_run(command, cwd=None, capture_output=None, text=None, check=None):
        captured["command"] = command
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(command, 0, stdout="12 passed\n", stderr="")

    monkeypatch.setattr("controltower.services.release.subprocess.run", _fake_run)

    result = run_pytest_suite()

    assert result["status"] == "pass"
    assert result["exit_code"] == 0
    assert result["command"] == "pytest -q"
    assert captured["command"][1:] == ["-m", "pytest", "-q"]


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
    assert artifact["stage_results"]["readiness"]["status"] == "pass"
    assert artifact["stage_results"]["deploy"]["status"] == "pass"
    assert artifact["next_recommended_action"] == "Approve next Codex lane"
    assert artifact["awaiting_approval"] is True
    assert artifact["failure_reason"] is None
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
    assert artifact["diagnostics_snapshot"]["release"]["generated_at"] == artifact["generated_at"]
    persisted_diagnostics = json.loads(
        (Path(config.runtime.state_root) / "diagnostics" / "latest_diagnostics.json").read_text(encoding="utf-8")
    )
    assert persisted_diagnostics["release"]["generated_at"] == artifact["generated_at"]
    assert persisted_diagnostics["release"]["status"] == artifact["verdict"]["status"]
    orchestration_root = Path(config.runtime.state_root).resolve().parent / "ops" / "orchestration"
    pending = json.loads((orchestration_root / "pending_approval.json").read_text(encoding="utf-8"))
    run_state = json.loads((orchestration_root / "run_state.json").read_text(encoding="utf-8"))
    assert pending["status"] == "awaiting_approval"
    assert pending["latest_release_json_path"] == artifact["artifact_paths"]["latest_json"]
    assert run_state["status"] == "awaiting_approval"
    assert run_state["pending_run_id"] == pending["run_id"]


def test_release_gate_refreshes_diagnostics_after_writing_operation_summary(sample_config_path: Path):
    summary = run_release_gate(config_path=sample_config_path, run_pytest=False, run_acceptance=False)
    config = load_config(sample_config_path)

    latest_release = json.loads(
        (Path(config.runtime.state_root) / "release" / "latest_release_readiness.json").read_text(encoding="utf-8")
    )
    latest_diagnostics = json.loads(
        (Path(config.runtime.state_root) / "diagnostics" / "latest_diagnostics.json").read_text(encoding="utf-8")
    )

    assert summary["status"] == "success"
    assert latest_release["diagnostics_snapshot"]["release"]["generated_at"] == latest_release["generated_at"]
    assert latest_release["diagnostics_snapshot"]["operations"]["latest_run_timestamp"] == summary["completed_at"]
    assert latest_diagnostics["release"]["generated_at"] == latest_release["generated_at"]
    assert latest_diagnostics["operations"]["latest_run_timestamp"] == summary["completed_at"]


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
    powershell_wrapper = (repo_root / "scripts" / "release_controltower.ps1").read_text(encoding="utf-8")
    linux_wrapper = (repo_root / "ops" / "linux" / "release_controltower.sh").read_text(encoding="utf-8")
    windows_wrapper = (repo_root / "ops" / "windows" / "Invoke-ControlTowerRelease.ps1").read_text(encoding="utf-8")

    assert "deploy_update_controltower.py" in deploy_update
    assert "release_source_controltower.py" not in deploy_update
    assert "rsync -a --delete" not in deploy_update
    assert "deprecated" in python_wrapper
    assert "deploy_update_controltower.py" in python_wrapper
    assert "compatibility wrapper" in powershell_wrapper
    assert "release_controltower.py" in powershell_wrapper
    assert "controltower.services.notifications" in powershell_wrapper
    assert "Notification attempt:" in powershell_wrapper
    assert "deprecated" in linux_wrapper
    assert "infra/deploy/controltower/deploy_update.sh" in linux_wrapper
    assert "compatibility wrapper" in windows_wrapper
    assert "release_controltower.ps1" in windows_wrapper


def test_remote_release_copies_script_then_executes_absolute_bash_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "deploy_update_controltower.py"
    spec = importlib.util.spec_from_file_location("test_deploy_update_controltower", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    release_spec_path = tmp_path / "controltower.release.yaml"
    release_spec_path.write_text(
        yaml.safe_dump(
            {
                "release": {
                    "repository": {
                        "working_branch": "main",
                        "remote_name": "origin",
                    },
                    "deployment_target": {
                        "ssh_target": "deploy@controltower.bratek.io",
                        "public_ip": "161.35.177.158",
                        "app_root": "/srv/controltower/app",
                        "venv_python": "/srv/controltower/.venv/bin/python",
                        "runtime_root": "/srv/controltower/runtime",
                        "env_file": "/etc/controltower/controltower.env",
                        "config_path": "/etc/controltower/controltower.yaml",
                        "service_name": "controltower-web",
                        "backend_base_url": "http://127.0.0.1:8787",
                        "public_base_url": "https://controltower.bratek.io",
                    },
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    remote_script_path = tmp_path / "release_remote.sh"
    remote_script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    commands: list[list[str]] = []
    health_checks = iter(
        [
            {"reachable": True, "git_commit": "old-commit", "auth_mode": "prod", "public_base_url": "https://controltower.bratek.io"},
            {"reachable": True, "git_commit": "abc123", "auth_mode": "prod", "public_base_url": "https://controltower.bratek.io"},
        ]
    )

    monkeypatch.setattr(
        module,
        "validate_and_push_release_source",
        lambda release_spec, summary: {
            "branch": release_spec.working_branch,
            "working_branch_expected": release_spec.working_branch,
            "remote_name": release_spec.remote_name,
            "remote_url": "git@example.com:controltower.git",
            "head_commit": "abc123",
            "upstream_ref": f"{release_spec.remote_name}/{release_spec.working_branch}",
            "upstream_commit": "abc123",
            "ahead": 0,
            "behind": 0,
            "relationship": "in_sync",
            "dirty": False,
            "push_performed": False,
        },
    )
    monkeypatch.setattr(
        module,
        "collect_source_release_trace",
        lambda *args, **kwargs: {"status": "pass", "local_head_commit": "abc123"},
    )
    monkeypatch.setattr(module, "fetch_public_health", lambda *args, **kwargs: next(health_checks))
    monkeypatch.setattr(module, "maybe_notify", lambda *args, **kwargs: {"status": "not_configured"})
    monkeypatch.setattr(module, "maybe_write_summary", lambda *args, **kwargs: None)

    def _capture_run_checked(command: list[str], **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(module, "run_checked", _capture_run_checked)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy_update_controltower.py",
            "--spec",
            str(release_spec_path),
            "--remote-script",
            str(remote_script_path),
        ],
    )

    assert module.main() == 0
    assert commands == [
        [
            "scp",
            str(remote_script_path),
            "deploy@controltower.bratek.io:/tmp/release_remote.sh",
        ],
        [
            "ssh",
            "deploy@controltower.bratek.io",
            "chmod +x /tmp/release_remote.sh && /bin/bash /tmp/release_remote.sh --app-root /srv/controltower/app --branch main --commit abc123 --venv-python /srv/controltower/.venv/bin/python --runtime-root /srv/controltower/runtime --env-file /etc/controltower/controltower.env --config /etc/controltower/controltower.yaml --service-name controltower-web --backend-base-url http://127.0.0.1:8787 --public-base-url https://controltower.bratek.io --git-remote origin --source-trace-b64 "
            + module.encode_json_payload({"status": "pass", "local_head_commit": "abc123"}),
        ]
    ]


def test_remote_release_exec_command_shell_quotes_arguments(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "deploy_update_controltower.py"
    spec = importlib.util.spec_from_file_location("test_deploy_update_controltower_quote_args", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    command = module.build_remote_exec_command(
        "deploy@example.com",
        [
            "--service-name",
            "controltower web",
            "--source-trace-b64",
            "value'withquote",
        ],
    )

    assert command == [
        "ssh",
        "deploy@example.com",
        "chmod +x /tmp/release_remote.sh && /bin/bash /tmp/release_remote.sh --service-name 'controltower web' --source-trace-b64 'value'\"'\"'withquote'",
    ]


def _init_git_repo(repo_root: Path) -> Path:
    repo_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--initial-branch=main", str(repo_root)], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "Test User"], check=True)
    (repo_root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "initial"], check=True)
    return repo_root

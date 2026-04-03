from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from controltower.config import load_config
from controltower.services.approval_ingest import ingest_approval_inbox, sync_pending_release_approval
from controltower.services.codex_executor import execute_next_codex_lane
from controltower.services.orchestration import OrchestrationService


def test_codex_watcher_once_executes_launchable_lane_and_ingests_result(
    sample_config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config, run_id, review = _prepare_launchable_review(sample_config_path, monkeypatch)
    worker_script = sample_config_path.parent / "fake_codex_worker.py"
    worker_script.write_text(
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "prompt = Path(os.environ['CONTROLTOWER_CODEX_PROMPT_PATH']).read_text(encoding='utf-8')",
                "review_root = Path(os.environ['CONTROLTOWER_CODEX_REVIEW_ROOT'])",
                "artifact_path = review_root / 'codex_executor_output.txt'",
                "artifact_path.write_text('approved prompt length=' + str(len(prompt)), encoding='utf-8')",
                "payload = {",
                "    'status': 'succeeded',",
                "    'summary': 'Autonomous Codex execution completed from the approved prompt.',",
                "    'output_artifacts': [{'label': 'Codex Output', 'path': str(artifact_path), 'content_type': 'text/plain'}],",
                "    'external_reference': 'codex-worker-1'",
                "}",
                "Path(os.environ['CONTROLTOWER_CODEX_RESULT_PATH']).write_text(json.dumps(payload), encoding='utf-8')",
                "print('worker complete for ' + os.environ['CONTROLTOWER_CODEX_RUN_ID'])",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config.execution.codex_executor_command = f'"{sys.executable}" "{worker_script}"'
    config.execution.codex_executor_workdir = sample_config_path.parent

    result = execute_next_codex_lane(config, config_path=sample_config_path)

    assert result["status"] == "executed"
    assert result["reason"] == "execution_result_ingested"
    updated = OrchestrationService(config).get_review_run(run_id)
    assert updated is not None
    assert updated.execution_result.status == "succeeded"
    assert updated.execution_result.external_reference == "codex-worker-1"
    assert updated.execution_result.closeout_status == "succeeded"
    assert updated.continuity.strategic_checkin_written_at is not None
    assert updated.continuity.session_log_note_path is not None
    assert any(entry.event_type == "obsidian_checkin_written" for entry in updated.audit_trail)
    review_root = Path(config.runtime.state_root) / "orchestration" / "reviews" / run_id
    assert review_root.joinpath("codex_executor", "latest_status.json").exists()
    assert review_root.joinpath("codex_executor_output.txt").exists()
    assert review_root.joinpath("closeout", "closeout_latest.json").exists()
    assert review.execution_event.event_id == updated.execution_event.event_id


def test_codex_watcher_once_refuses_completed_lane(
    sample_config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config, run_id, _review = _prepare_launchable_review(sample_config_path, monkeypatch)
    worker_script = sample_config_path.parent / "fake_codex_worker.py"
    worker_script.write_text(
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "Path(os.environ['CONTROLTOWER_CODEX_RESULT_PATH']).write_text(",
                "    json.dumps({'status': 'succeeded', 'summary': 'done', 'external_reference': 'codex-worker-2'}),",
                "    encoding='utf-8',",
                ")",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config.execution.codex_executor_command = f'"{sys.executable}" "{worker_script}"'
    config.execution.codex_executor_workdir = sample_config_path.parent

    first = execute_next_codex_lane(config, config_path=sample_config_path)
    second = execute_next_codex_lane(config, config_path=sample_config_path)

    assert first["status"] == "executed"
    assert second["status"] == "skipped"
    assert second["reason"] == "execution_already_complete"
    assert second["run_id"] == run_id


def test_codex_watcher_once_stays_fail_closed_without_persisted_review_binding(
    sample_config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config, run_id = _prepare_launchable_artifacts_only(sample_config_path, monkeypatch)
    config.execution.codex_executor_command = f'"{sys.executable}" -c "print(1)"'
    config.execution.codex_executor_workdir = sample_config_path.parent

    result = execute_next_codex_lane(config, config_path=sample_config_path)

    assert result["status"] == "blocked"
    assert result["reason"] == "persisted_review_missing"
    assert result["run_id"] == run_id


def _prepare_launchable_review(sample_config_path: Path, monkeypatch: pytest.MonkeyPatch):
    config, run_id = _prepare_launchable_artifacts_only(sample_config_path, monkeypatch)
    orchestration = OrchestrationService(config)
    review = orchestration.materialize_approved_handoff_review(run_id)
    return config, run_id, review


def _prepare_launchable_artifacts_only(sample_config_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _enable_prompt_orchestration(sample_config_path)
    orchestration_root = sample_config_path.parent / "ops" / "orchestration"
    status_path = _write_release_status(sample_config_path.parent)
    _write_continuity_bundle(config)
    sync_pending_release_approval(status_path, orchestration_root=orchestration_root, config=config)
    (orchestration_root / "inbox" / "approve.json").write_text(
        json.dumps({"source_channel": "signal", "message": "APPROVE"}),
        encoding="utf-8",
    )
    monkeypatch.setattr("controltower.services.approval_ingest.send_operator_notification", lambda *args, **kwargs: None)
    monkeypatch.setattr("controltower.services.prompt_orchestration.urlopen", lambda request, timeout=0: _PromptResponse())
    ingest_approval_inbox(orchestration_root=orchestration_root, config=config)
    run_id = json.loads((orchestration_root / "pending_approval.json").read_text(encoding="utf-8"))["run_id"]
    return config, run_id


class _PromptResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        payload = {
            "model": "gpt-5-test",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(_fake_next_prompt_payload())}]}],
        }
        return json.dumps(payload).encode("utf-8")


def _enable_prompt_orchestration(config_path: Path):
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    payload["prompt_orchestration"] = {
        "enabled": True,
        "obsidian_gating_enabled": True,
        "model": "gpt-5-test",
        "openai_api_key": "test-key",
    }
    payload.setdefault("obsidian", {})
    payload["obsidian"]["continuity_root"] = "continuity"
    payload["obsidian"]["checkout_notes"] = ["active_control.md", "supplement.md"]
    payload["obsidian"]["active_control_note"] = "active_control.md"
    payload["obsidian"]["session_log_dir"] = "session_logs"
    payload["obsidian"]["active_control_section_heading"] = "## Active Lane Check-In"
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return load_config(config_path)


def _write_continuity_bundle(config) -> None:
    continuity_root = Path(config.obsidian.continuity_root)
    continuity_root.mkdir(parents=True, exist_ok=True)
    (continuity_root / "active_control.md").write_text(
        """---
phase: Prompt Orchestration
current_objective: Build the autonomous Codex executor without weakening approvals
why_this_matters: Approved launchable lanes must execute from artifacts instead of a manual shim.
in_scope:
  - approved watcher
  - deterministic execution
out_of_scope:
  - approval replay
known_risks:
  - missing strategic check-in
acceptance_bar:
  - execute only approved launchable lanes
last_accepted_release: 2026-04-01-ready
---
""",
        encoding="utf-8",
    )
    (continuity_root / "supplement.md").write_text(
        """## Next Strategic Target

- Close the lane through execution-result-ingest and write the strategic check-in before the next hop.
""",
        encoding="utf-8",
    )


def _write_release_status(tmp_root: Path) -> Path:
    release_root = tmp_root / "state" / "release"
    release_root.mkdir(parents=True, exist_ok=True)
    markdown_path = release_root / "latest_release_readiness.md"
    latest_json_path = release_root / "latest_release_readiness.json"
    diagnostics_path = tmp_root / "state" / "diagnostics" / "latest_diagnostics.json"
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_path.write_text("{}", encoding="utf-8")
    latest_run_path = tmp_root / "state" / "latest_run.json"
    latest_run_path.write_text("{}", encoding="utf-8")
    manifest_path = tmp_root / "state" / "runs" / "run_2026_04_01" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("{}", encoding="utf-8")
    live_deployment_path = release_root / "latest_live_deployment.json"
    live_deployment_path.write_text(
        json.dumps({"git_commit": "198126ad4f8cc0bbc695d80a99d3908769976b5c", "deployed_at": "2026-04-01T12:00:00Z"}),
        encoding="utf-8",
    )
    source_trace_path = release_root / "latest_release_source_trace.json"
    source_trace_path.write_text(
        json.dumps({"verification_status": "pass", "local_head_commit": "56533ac6539fa052144850f9d7cdd39263d4388f"}, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text("# release\n", encoding="utf-8")
    payload = {
        "generated_at": "2026-04-01T13:55:09Z",
        "awaiting_approval": True,
        "latest_export": {
            "run_id": "2026-04-01T13-55-09Z",
            "status": "success",
            "manifest_path": str(manifest_path),
        },
        "verdict": {
            "status": "ready",
            "summary": "Control Tower is ready for approved launchable next-lane execution.",
            "operator_recommendation": "Proceed with the approved launchable lane.",
            "ready_for_live_operations": True,
        },
        "artifact_paths": {
            "latest_json": str(latest_json_path),
            "latest_markdown": str(markdown_path),
        },
        "latest_evidence": {
            "latest_release_json_path": str(latest_json_path),
            "latest_release_markdown_path": str(markdown_path),
            "latest_diagnostics_path": str(diagnostics_path),
            "latest_run_path": str(latest_run_path),
            "latest_export_manifest_path": str(manifest_path),
            "diagnostics_snapshot_path": str(diagnostics_path),
        },
        "release_trace": {
            "verification_status": "pass",
            "local_head_commit": "56533ac6539fa052144850f9d7cdd39263d4388f",
            "source_trace_path": str(source_trace_path),
        },
        "next_recommended_action": "Approve next Codex lane",
        "operator_recommendation": "Proceed with the approved launchable lane.",
    }
    latest_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return latest_json_path


def _fake_next_prompt_payload() -> dict[str, object]:
    return {
        "objective": "Execute the approved release-review lane from the existing launchable artifacts.",
        "scope": ["Use the approved prompt and ingest the result through the existing closeout path."],
        "constraints": [
            "Do not regenerate orchestration for the approved lane.",
            "Do not change the approved run_id, event_id, or pack_id.",
        ],
        "stop_condition": "Stop when the execution result has been ingested and closeout artifacts are written.",
        "deliverable_format": ["UNDERSTANDING", "COMMANDS RUN", "FILES MODIFIED", "ARTIFACTS VERIFIED", "RESULT", "NEXT OPERATOR ACTION"],
        "recommended_commands": ["python run_controltower.py codex-watcher-once --config controltower.yaml"],
        "prompt_markdown": "Use the approved prompt from next_prompt.json, require Obsidian checkout before work starts, and require Obsidian check-in before closeout.",
        "requires_operator_approval_after_release": True,
        "continuation_mode": "manual_approval_after_release",
        "strategic_alignment_summary": "The autonomous executor must preserve approval truth, artifact truth, and strategic closeout discipline.",
    }

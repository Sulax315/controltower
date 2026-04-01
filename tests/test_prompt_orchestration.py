from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from controltower.config import load_config
from controltower.obsidian.continuity import (
    ObsidianContinuityError,
    ObsidianLaneCheckin,
    read_checkout_bundle,
    write_lane_checkin,
)
from controltower.services.approval_ingest import ingest_approval_inbox, sync_pending_release_approval
from controltower.services.orchestration import OrchestrationService
from controltower.services.prompt_orchestration import (
    OpenAIResponsesClient,
    build_prompt_context,
    orchestrate_next_prompt,
    write_placeholder_artifacts,
)


def test_obsidian_checkout_parses_bounded_note_bundle(tmp_path: Path):
    continuity_root = tmp_path / "continuity"
    continuity_root.mkdir(parents=True, exist_ok=True)
    (continuity_root / "active_control.md").write_text(
        """---
phase: Prompt Orchestration
current_objective: Build deterministic next-prompt generation
why_this_matters: Keep autonomous lanes aligned to strategy.
in_scope:
  - approval ingest integration
  - strict-schema prompt generation
out_of_scope:
  - release architecture redesign
known_risks:
  - missing continuity fields
acceptance_bar:
  - checkout is validated before prompt generation
last_accepted_release: 2026-03-31-ready
---
""",
        encoding="utf-8",
    )
    (continuity_root / "supplement.md").write_text(
        """## Next Strategic Target

- Close the loop with a required Obsidian check-in after each lane.
""",
        encoding="utf-8",
    )

    result = read_checkout_bundle(
        continuity_root=continuity_root,
        note_paths=["active_control.md", "supplement.md"],
    )

    assert result.checkout.phase == "Prompt Orchestration"
    assert result.checkout.current_objective == "Build deterministic next-prompt generation"
    assert result.checkout.in_scope == ["approval ingest integration", "strict-schema prompt generation"]
    assert result.checkout.next_strategic_target == "Close the loop with a required Obsidian check-in after each lane."


def test_obsidian_checkout_rejects_missing_required_fields(tmp_path: Path):
    continuity_root = tmp_path / "continuity"
    continuity_root.mkdir(parents=True, exist_ok=True)
    (continuity_root / "active_control.md").write_text(
        """## Phase

Prompt Orchestration

## Current Objective

Only one field is present here.
""",
        encoding="utf-8",
    )

    with pytest.raises(ObsidianContinuityError, match="missing required fields"):
        read_checkout_bundle(continuity_root=continuity_root, note_paths=["active_control.md"])


def test_write_lane_checkin_writes_session_log_and_updates_active_control(tmp_path: Path):
    continuity_root = tmp_path / "continuity"
    continuity_root.mkdir(parents=True, exist_ok=True)

    result = write_lane_checkin(
        continuity_root=continuity_root,
        active_control_note="active_control.md",
        session_log_dir="session_logs",
        active_control_section_heading="## Active Lane Check-In",
        payload=ObsidianLaneCheckin(
            run_id="review_123",
            lane_summary="Prompt orchestration shipped.",
            files_or_surfaces_changed=["src/controltower/services/prompt_orchestration.py"],
            release_result="succeeded: prompt generation is live.",
            approval_result="approved | pack=release_readiness_pack | provider=file",
            open_risks=["OpenAI credentials must be configured in production."],
            next_recommended_lane="Exercise the full approval-to-generation path against production-like artifacts.",
            strategic_alignment_note="The lane keeps Control Tower execution artifacts and Obsidian continuity in lockstep.",
            completed_at="2026-03-31T20:00:00Z",
        ),
    )

    session_log = Path(result.session_log_path).read_text(encoding="utf-8")
    active_control = Path(result.active_control_note_path).read_text(encoding="utf-8")

    assert "Prompt orchestration shipped." in session_log
    assert "## Active Lane Check-In" in active_control
    assert "review_123" in active_control
    assert "session_logs/2026-03-31T20-00-00Z_review_123.md" in active_control


def test_build_prompt_context_packs_release_and_obsidian_context(sample_config_path: Path):
    config = _enable_prompt_orchestration(sample_config_path)
    orchestration_root = sample_config_path.parent / "ops" / "orchestration"
    status_path = _write_release_status(sample_config_path.parent)
    sync_pending_release_approval(status_path, orchestration_root=orchestration_root, config=config)
    _write_continuity_bundle(config)
    checkout_result = read_checkout_bundle(
        continuity_root=config.obsidian.continuity_root,
        note_paths=config.obsidian.checkout_notes,
    )

    context = build_prompt_context(
        config,
        orchestration_root=orchestration_root,
        checkout_result=checkout_result,
        recent_approval_event={"normalized_command": "APPROVE", "applied": True},
    )

    packed = context["context_pack"]
    assert packed["latest_release_status"]["verdict"]["status"] == "ready"
    assert packed["latest_live_deployment"]["git_commit"] == "abc123"
    assert packed["latest_release_source_trace"]["verification_status"] == "pass"
    assert packed["pending_approval"]["status"] == "awaiting_approval"
    assert packed["run_state"]["status"] == "awaiting_approval"
    assert packed["trigger_next_run"]["ready_for_operator_launch"] is False
    assert packed["obsidian_checkout"]["phase"] == "Prompt Orchestration"
    assert packed["obsidian_checkout_context"]["normalized"] is True
    assert packed["obsidian_checkout_context"]["note_count"] == 2
    assert str((Path(config.obsidian.continuity_root) / "active_control.md").resolve()) in context["source_artifacts_used"]


def test_openai_responses_client_parses_structured_output(monkeypatch: pytest.MonkeyPatch):
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "gpt-5-test",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(_fake_next_prompt_payload()),
                                }
                            ],
                        }
                    ],
                }
            ).encode("utf-8")

    monkeypatch.setattr("controltower.services.prompt_orchestration.urlopen", lambda request, timeout=0: _Response())

    client = OpenAIResponsesClient(api_key="test-key", model_name="gpt-5-test")
    result = client.generate_next_prompt({"pending_approval": {"run_id": "review_123"}})

    assert result["model_name"] == "gpt-5-test"
    assert result["next_prompt"].objective == "Ship prompt orchestration with mandatory Obsidian gates."
    assert result["next_prompt"].requires_operator_approval_after_release is True


def test_orchestrate_next_prompt_writes_artifacts_and_trigger(
    sample_config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = _enable_prompt_orchestration(sample_config_path)
    orchestration_root = sample_config_path.parent / "ops" / "orchestration"
    status_path = _write_release_status(sample_config_path.parent)
    sync_pending_release_approval(status_path, orchestration_root=orchestration_root, config=config)
    pending = json.loads((orchestration_root / "pending_approval.json").read_text(encoding="utf-8"))
    pending["status"] = "approved"
    pending["applied_command"] = "APPROVE"
    pending["applied_at"] = "2026-03-31T19:05:00Z"
    (orchestration_root / "pending_approval.json").write_text(json.dumps(pending, indent=2), encoding="utf-8")
    _write_continuity_bundle(config)

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "gpt-5-test",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(_fake_next_prompt_payload())}]}],
                }
            ).encode("utf-8")

    monkeypatch.setattr("controltower.services.prompt_orchestration.urlopen", lambda request, timeout=0: _Response())

    result = orchestrate_next_prompt(config, orchestration_root=orchestration_root)

    next_prompt = json.loads((orchestration_root / "next_prompt.json").read_text(encoding="utf-8"))
    trigger = json.loads((orchestration_root / "trigger_next_run.json").read_text(encoding="utf-8"))
    markdown = (orchestration_root / "next_prompt.md").read_text(encoding="utf-8")

    assert result["status"] == "generated"
    assert next_prompt["orchestration_status"] == "generated"
    assert next_prompt["next_prompt"]["objective"] == "Ship prompt orchestration with mandatory Obsidian gates."
    assert next_prompt["obsidian_context_used"]["normalized"] is True
    assert trigger["ready_for_operator_launch"] is True
    assert trigger["orchestration_status"] == "generated"
    assert trigger["next_action"] == "launch_next_codex_lane"
    assert trigger["launch_gate_status"] == "launchable"
    assert trigger["continuity_context_normalized"] is True
    assert "Obsidian Context" in markdown
    assert "Prompt Markdown" in markdown


def test_orchestrate_next_prompt_fails_closed_when_checkout_is_missing(sample_config_path: Path):
    config = _enable_prompt_orchestration(sample_config_path)
    orchestration_root = sample_config_path.parent / "ops" / "orchestration"
    status_path = _write_release_status(sample_config_path.parent)
    sync_pending_release_approval(status_path, orchestration_root=orchestration_root, config=config)
    pending = json.loads((orchestration_root / "pending_approval.json").read_text(encoding="utf-8"))
    pending["status"] = "approved"
    pending["applied_command"] = "APPROVE"
    (orchestration_root / "pending_approval.json").write_text(json.dumps(pending, indent=2), encoding="utf-8")

    result = orchestrate_next_prompt(config, orchestration_root=orchestration_root)

    next_prompt = json.loads((orchestration_root / "next_prompt.json").read_text(encoding="utf-8"))
    trigger = json.loads((orchestration_root / "trigger_next_run.json").read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert next_prompt["gate_failure"]["gate"] == "obsidian_checkout"
    assert trigger["ready_for_operator_launch"] is False
    assert trigger["next_action"] == "await_gate_clearance"
    assert trigger["launch_gate_status"] == "blocked"
    assert "Obsidian checkout note is missing" in trigger["reason"]


def test_generated_artifacts_are_not_launchable_without_normalized_continuity_context(tmp_path: Path):
    orchestration_root = tmp_path / "ops" / "orchestration"
    payload = {
        "schema_version": "2026-03-31",
        "generated_at": "2026-03-31T20:10:00Z",
        "orchestration_status": "generated",
        "model_name": "gpt-5-test",
        "pending_run_id": "release_review_run_2026_03_31",
        "approval_status": "approved",
        "approval_command": "APPROVE",
        "approval_applied_at": "2026-03-31T20:09:00Z",
        "source_artifacts_used": [],
        "obsidian_context_used": {
            "status": "used",
            "normalized": False,
            "continuity_root": str(tmp_path / "continuity"),
            "note_paths": [],
        },
        "gate_failure": None,
        "next_prompt": _fake_next_prompt_payload(),
        "context_pack": {
            "obsidian_checkout_context": {
                "normalized": False,
                "continuity_root": str(tmp_path / "continuity"),
                "note_paths": [],
                "note_count": 0,
            }
        },
    }

    result = write_placeholder_artifacts(
        orchestration_root=orchestration_root,
        payload=payload,
        ready_for_operator_launch=True,
    )
    trigger = json.loads((orchestration_root / "trigger_next_run.json").read_text(encoding="utf-8"))

    assert result["ready_for_operator_launch"] is False
    assert trigger["ready_for_operator_launch"] is False
    assert trigger["next_action"] == "await_gate_clearance"
    assert trigger["launch_gate_status"] == "blocked"
    assert trigger["continuity_context_normalized"] is False
    assert "advisory only" in trigger["reason"]


def test_approval_ingest_triggers_prompt_generation_when_enabled(
    sample_config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = _enable_prompt_orchestration(sample_config_path)
    orchestration_root = sample_config_path.parent / "ops" / "orchestration"
    status_path = _write_release_status(sample_config_path.parent)
    sync_pending_release_approval(status_path, orchestration_root=orchestration_root, config=config)
    _write_continuity_bundle(config)
    (orchestration_root / "inbox" / "approve.json").write_text(
        json.dumps({"source_channel": "signal", "message": "APPROVE"}),
        encoding="utf-8",
    )

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "gpt-5-test",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(_fake_next_prompt_payload())}]}],
                }
            ).encode("utf-8")

    monkeypatch.setattr("controltower.services.prompt_orchestration.urlopen", lambda request, timeout=0: _Response())
    monkeypatch.setattr("controltower.services.approval_ingest.send_operator_notification", lambda *args, **kwargs: None)

    result = ingest_approval_inbox(orchestration_root=orchestration_root, config=config)
    next_prompt = json.loads((orchestration_root / "next_prompt.json").read_text(encoding="utf-8"))
    trigger = json.loads((orchestration_root / "trigger_next_run.json").read_text(encoding="utf-8"))

    assert result["events"][0]["prompt_orchestration_status"] == "generated"
    assert next_prompt["orchestration_status"] == "generated"
    assert next_prompt["next_prompt"]["continuation_mode"] == "manual_approval_after_release"
    assert trigger["ready_for_operator_launch"] is True
    assert trigger["next_action"] == "launch_next_codex_lane"
    assert trigger["launch_gate_status"] == "launchable"


def test_approval_ingest_gate_failure_keeps_trigger_non_launchable(
    sample_config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = _enable_prompt_orchestration(sample_config_path)
    orchestration_root = sample_config_path.parent / "ops" / "orchestration"
    status_path = _write_release_status(sample_config_path.parent)
    sync_pending_release_approval(status_path, orchestration_root=orchestration_root, config=config)
    (orchestration_root / "inbox" / "approve.json").write_text(
        json.dumps({"source_channel": "signal", "message": "APPROVE"}),
        encoding="utf-8",
    )
    monkeypatch.setattr("controltower.services.approval_ingest.send_operator_notification", lambda *args, **kwargs: None)

    result = ingest_approval_inbox(orchestration_root=orchestration_root, config=config)
    trigger = json.loads((orchestration_root / "trigger_next_run.json").read_text(encoding="utf-8"))

    assert result["events"][0]["prompt_orchestration_status"] == "blocked"
    assert result["events"][0]["prompt_orchestration_gate_failure"]["gate"] == "obsidian_checkout"
    assert trigger["ready_for_operator_launch"] is False
    assert trigger["next_action"] == "await_gate_clearance"
    assert trigger["launch_gate_status"] == "blocked"


def test_execution_result_closeout_fails_closed_when_obsidian_checkin_write_fails(
    sample_config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = _enable_prompt_orchestration(sample_config_path)
    _write_continuity_bundle(config)
    orchestration = OrchestrationService(config)
    review = orchestration.simulate_execution_event(profile="medium", provider_override="file", reviewer_identity="tester")

    def _boom(**kwargs):
        raise ObsidianContinuityError("active control note is read-only")

    monkeypatch.setattr("controltower.services.orchestration.write_lane_checkin", _boom)

    updated = orchestration.ingest_execution_result(
        {
            "event_id": review.execution_event.event_id,
            "run_id": review.run_id,
            "pack_id": review.execution_pack.pack_id,
            "status": "succeeded",
            "summary": "Lane completed.",
            "output_artifacts": [{"label": "result", "path": "ops/orchestration/next_prompt.json"}],
        }
    )

    assert updated.state == "failed"
    assert updated.last_error is not None
    assert updated.last_error.phase == "obsidian_checkin"
    assert updated.execution_result.closeout_status == "failed"
    assert "read-only" in (updated.execution_result.closeout_summary or "")


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
current_objective: Build prompt orchestration with hard Obsidian gates
why_this_matters: Autonomous lanes must stay aligned to operator strategy.
in_scope:
  - checkout parsing
  - prompt generation
out_of_scope:
  - release architecture redesign
known_risks:
  - missing active control updates
acceptance_bar:
  - lane launch is blocked when checkout is missing
last_accepted_release: 2026-03-31-ready
---
""",
        encoding="utf-8",
    )
    (continuity_root / "supplement.md").write_text(
        """## Next Strategic Target

- Close the lane back into Obsidian before allowing the next autonomous hop.
""",
        encoding="utf-8",
    )


def _write_release_status(tmp_path: Path) -> Path:
    release_root = tmp_path / "state" / "release"
    release_root.mkdir(parents=True, exist_ok=True)
    markdown_path = release_root / "latest_release_readiness.md"
    latest_json_path = release_root / "latest_release_readiness.json"
    diagnostics_path = tmp_path / "state" / "diagnostics" / "latest_diagnostics.json"
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_path.write_text("{}", encoding="utf-8")
    latest_run_path = tmp_path / "state" / "latest_run.json"
    latest_run_path.write_text("{}", encoding="utf-8")
    manifest_path = tmp_path / "state" / "runs" / "run_2026_03_31" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("{}", encoding="utf-8")
    live_deployment_path = release_root / "latest_live_deployment.json"
    live_deployment_path.write_text(json.dumps({"git_commit": "abc123", "deployed_at": "2026-03-31T18:00:00Z"}), encoding="utf-8")
    source_trace_path = release_root / "latest_release_source_trace.json"
    source_trace_path.write_text(
        json.dumps({"verification_status": "pass", "local_head_commit": "abc123"}, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text("# release\n", encoding="utf-8")

    payload = {
        "generated_at": "2026-03-31T12:34:56Z",
        "awaiting_approval": True,
        "next_recommended_action": "Approve next Codex lane",
        "failure_reason": None,
        "stage_results": {
            "pytest": {"status": "pass"},
            "readiness": {"status": "pass"},
            "acceptance": {"status": "pass"},
            "deploy": {"status": "pass"},
        },
        "latest_export": {
            "run_id": "run_2026_03_31",
            "manifest_path": str(manifest_path),
        },
        "latest_evidence": {
            "latest_diagnostics_path": str(diagnostics_path),
            "latest_run_path": str(latest_run_path),
        },
        "artifact_paths": {
            "json": str(latest_json_path),
            "latest_json": str(latest_json_path),
            "markdown": str(markdown_path),
            "latest_markdown": str(markdown_path),
        },
        "release_trace": {
            "source_trace_path": str(source_trace_path),
            "verification_status": "pass",
        },
        "verdict": {
            "status": "ready",
            "summary": "Control Tower is ready for the next lane.",
            "operator_recommendation": "Approve the next Codex lane after continuity checkout.",
            "ready_for_live_operations": True,
        },
    }
    latest_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return latest_json_path


def _fake_next_prompt_payload() -> dict[str, object]:
    return {
        "objective": "Ship prompt orchestration with mandatory Obsidian gates.",
        "scope": [
            "Integrate deterministic Obsidian checkout before next-lane launch.",
            "Write next prompt artifacts for operator launch.",
        ],
        "constraints": [
            "Do not redesign release or approval architecture.",
            "Keep everything artifact-backed and production-grade.",
        ],
        "stop_condition": "Stop after tests pass and the next prompt artifacts clearly report gate state.",
        "deliverable_format": [
            "UNDERSTANDING",
            "FILES MODIFIED",
            "FILES CREATED",
            "COMMANDS RUN",
            "TEST RESULTS",
            "OBSIDIAN CHECK-OUT DESIGN",
            "OBSIDIAN CHECK-IN DESIGN",
            "PROMPT ORCHESTRATION BEHAVIOR",
            "GATING / FAILURE MODES",
            "OPEN RISKS",
            "NEXT RECOMMENDED STEP",
        ],
        "recommended_commands": ["python .\\run_controltower.py prompt-orchestrate-next"],
        "prompt_markdown": "Require Obsidian checkout before any work starts and Obsidian check-in before closeout.",
        "requires_operator_approval_after_release": True,
        "continuation_mode": "manual_approval_after_release",
        "strategic_alignment_summary": "The next lane keeps execution truth and strategic continuity coupled.",
    }

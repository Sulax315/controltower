from __future__ import annotations

import json
import re
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient

from controltower.api.app import create_app_from_config
from controltower.config import load_config
from controltower.services.orchestration import OrchestrationService


def test_file_approval_transitions_and_is_idempotent(sample_config_path):
    config = load_config(sample_config_path)
    config.trigger.provider = "file"
    config.trigger.file_dir = config.runtime.state_root / "orchestration" / "trigger_queue"
    orchestration = OrchestrationService(config)
    review = _create_review(orchestration, config)

    result = orchestration.approve_review(
        review.run_id,
        approved_next_prompt="Updated downstream prompt",
        reviewer_identity="pytest",
        auth_mode="cli",
        source_ip="127.0.0.1",
        forwarded_for="127.0.0.1",
        user_agent="pytest-suite",
        request_id="req-123",
        correlation_id="corr-123",
    )

    assert result.status == "triggered"
    assert result.trigger_emitted is True
    persisted = orchestration.get_review_run(review.run_id)
    assert persisted is not None
    assert persisted.state == "triggered"
    assert persisted.reviewer.reviewer_action == "approved"
    assert persisted.reviewer.reviewed_at is not None
    assert persisted.reviewer.auth_mode == "cli"
    assert persisted.reviewer.source_ip == "127.0.0.1"
    assert persisted.reviewer.forwarded_for == "127.0.0.1"
    assert persisted.reviewer.user_agent == "pytest-suite"
    assert persisted.reviewer.request_id == "req-123"
    assert persisted.reviewer.correlation_id == "corr-123"
    assert persisted.reviewer.approved_next_prompt == "Updated downstream prompt"
    assert persisted.trigger.status == "emitted"
    assert persisted.trigger.delivery_status == "queued"
    assert persisted.trigger.emitted_at is not None
    assert persisted.trigger.attempt_count == 1
    assert persisted.last_error is None
    assert persisted.execution_pack.pack_type == "release_readiness_pack"
    assert persisted.execution_result.status == "queued"
    assert persisted.execution_result.closeout_status == "pending"
    assert persisted.execution_event.event_id is not None
    assert Path(persisted.execution_result.closeout_json_path).exists()
    assert Path(persisted.execution_result.closeout_markdown_path).exists()

    approved_payload = next(artifact for artifact in persisted.decision_artifacts if artifact.label == "Approved Payload")
    payload = json.loads(Path(approved_payload.path).read_text(encoding="utf-8"))
    assert payload["run_id"] == review.run_id
    assert payload["workspace"] == "controltower"
    assert payload["event_type"] == "codex_run.approved"
    assert payload["event_version"] == "v1"
    assert payload["event_id"] == persisted.execution_event.event_id
    assert payload["approved_next_prompt"] == "Updated downstream prompt"
    assert payload["source"] == "controltower_orchestration"
    assert payload["pack_id"] == "pack_release_readiness_v1"
    assert payload["pack_type"] == "release_readiness_pack"
    assert payload["review_url"].endswith(review.detail_path)
    assert payload["review"]["summary"] == review.summary
    assert payload["review"]["reviewer_identity"] == "pytest"
    assert payload["review"]["auth_mode"] == "cli"
    assert payload["review"]["source_ip"] == "127.0.0.1"
    assert [item["file_name"] for item in payload["artifacts"]] == [artifact.file_name for artifact in persisted.artifacts]

    queue_file = Path(persisted.trigger.payload_path)
    assert queue_file.exists()
    assert persisted.execution_event.event_id in queue_file.name
    assert queue_file.name.endswith(".json")

    continuity_path = Path(persisted.continuity.runtime_markdown_path)
    continuity_body = continuity_path.read_text(encoding="utf-8")
    assert review.run_id in continuity_body
    assert "Final Decision: APPROVED" in continuity_body
    assert "Pack Type: release_readiness_pack" in continuity_body
    assert f"Event ID: {persisted.execution_event.event_id}" in continuity_body
    assert "Auth Mode: cli" in continuity_body
    assert "Reviewer Identity: pytest" in continuity_body
    assert "Trigger Status: emitted" in continuity_body
    assert "Delivery Status: queued" in continuity_body
    assert "Updated downstream prompt" in continuity_body
    approved_audit = next(entry for entry in persisted.audit_trail if entry.event_type == "approved")
    assert approved_audit.details["reviewer_identity"] == "pytest"
    assert approved_audit.details["auth_mode"] == "cli"

    second = orchestration.approve_review(review.run_id, approved_next_prompt="Should not emit again")
    assert second.status == "already_triggered"
    assert len(list(config.trigger.file_dir.glob("*.json"))) == 1
    assert orchestration.get_review_run(review.run_id).trigger.attempt_count == 1


def test_medium_risk_run_remains_pending_review_with_policy_metadata(sample_config_path):
    config = load_config(sample_config_path)
    orchestration = OrchestrationService(config)
    review = _create_review(orchestration, config)

    persisted = orchestration.get_review_run(review.run_id)
    assert persisted is not None
    assert persisted.state == "pending_review"
    assert persisted.risk_level == "medium"
    assert persisted.decision_mode == "manual_review"
    assert persisted.policy_version == config.autonomy.policy_version
    assert persisted.policy_evaluated_at is not None
    assert persisted.auto_approved_at is None
    assert persisted.escalated_at is None
    assert "Release-readiness handling defaults to manual review." in persisted.decision_reasons
    assert persisted.notification.status == "sent"
    assert persisted.notification.signal_level == "normal"
    assert any(entry.event_type == "policy_evaluated" for entry in persisted.audit_trail)


def test_manual_review_emits_approval_required_notification(sample_config_path, monkeypatch):
    config = load_config(sample_config_path)
    orchestration = OrchestrationService(config)
    events: list[dict[str, object]] = []

    monkeypatch.setattr(
        "controltower.services.orchestration.notify_controltower_event",
        lambda event, **kwargs: events.append({"event": event, **kwargs})
        or {"message": "ok", "artifact_path": "artifact.json", "delivery": {"success": True, "selected_channel": "console"}},
    )

    review = _create_review(orchestration, config)

    assert review.state == "pending_review"
    assert events[0]["event"] == "APPROVAL_REQUIRED"
    assert events[0]["status"] == "ACTION_REQUIRED"
    assert events[0]["instruction"] == "Reply YES to approve or NO to reject"


def test_low_risk_run_auto_approves_once_and_writes_policy_to_continuity(sample_config_path):
    config = load_config(sample_config_path)
    config.trigger.provider = "file"
    config.trigger.file_dir = config.runtime.state_root / "orchestration" / "trigger_queue"
    orchestration = OrchestrationService(config)

    review = orchestration.simulate_completed_run(profile="low")
    persisted = orchestration.get_review_run(review.run_id)
    assert persisted is not None
    assert persisted.state == "triggered"
    assert persisted.risk_level == "low"
    assert persisted.decision_mode == "auto_approve"
    assert persisted.auto_approved_at is not None
    assert persisted.reviewer.reviewer_action == "approved"
    assert persisted.reviewer.reviewer_identity == "policy-engine"
    assert persisted.reviewer.auth_mode == "policy_auto"
    assert persisted.trigger.status == "emitted"
    assert persisted.trigger.delivery_status == "queued"
    assert persisted.trigger.attempt_count == 1
    assert len(list(config.trigger.file_dir.glob("*.json"))) == 1
    assert any(entry.event_type == "policy_auto_approve_started" for entry in persisted.audit_trail)
    assert any(entry.event_type == "continuity_written" for entry in persisted.audit_trail)
    assert persisted.notification.status == "suppressed"
    assert persisted.notification.signal_level == "quiet"

    continuity_body = Path(persisted.continuity.runtime_markdown_path).read_text(encoding="utf-8")
    assert "Risk Level: low" in continuity_body
    assert "Decision Mode: auto_approve" in continuity_body
    assert "Auto-Approved: yes" in continuity_body
    assert "Human Approval Recorded: no" in continuity_body
    assert "Downstream Result" in continuity_body
    assert "Documentation-only changed files were detected." in continuity_body

    approved_payload = next(artifact for artifact in persisted.decision_artifacts if artifact.label == "Approved Payload")
    payload = json.loads(Path(approved_payload.path).read_text(encoding="utf-8"))
    assert payload["review"]["auto_approved"] is True
    assert payload["risk_level"] == "low"
    assert payload["decision_mode"] == "auto_approve"
    assert payload["decision_reasons"]

    second = orchestration.approve_review(review.run_id)
    assert second.status == "already_triggered"
    assert len(list(config.trigger.file_dir.glob("*.json"))) == 1


def test_high_risk_run_escalates_and_sends_high_signal_notification(sample_config_path):
    config = load_config(sample_config_path)
    orchestration = OrchestrationService(config)

    review = orchestration.simulate_completed_run(profile="high")
    persisted = orchestration.get_review_run(review.run_id)
    assert persisted is not None
    assert persisted.state == "escalated"
    assert persisted.risk_level == "critical"
    assert persisted.decision_mode == "escalate"
    assert persisted.escalated_at is not None
    assert persisted.auto_approved_at is None
    assert persisted.notification.status == "sent"
    assert persisted.notification.signal_level == "high"
    assert any(entry.event_type == "policy_escalated" for entry in persisted.audit_trail)
    assert "Auth, security, or session scope was detected." in persisted.decision_reasons
    assert "Routing, domain, TLS, or ingress scope was detected." in persisted.decision_reasons
    assert "Production deploy or restart language was detected." in persisted.decision_reasons
    assert persisted.trigger.status == "not_started"


def test_reject_path_persists_metadata_and_writes_continuity(sample_config_path):
    config = load_config(sample_config_path)
    config.trigger.provider = "file"
    config.trigger.file_dir = config.runtime.state_root / "orchestration" / "trigger_queue"
    orchestration = OrchestrationService(config)
    review = _create_review(orchestration, config)

    result = orchestration.reject_review(
        review.run_id,
        rejection_note="Need another round of validation before release.",
        reviewer_identity="pytest",
        auth_mode="cli",
        request_id="req-reject",
        correlation_id="corr-reject",
    )

    assert result.status == "rejected"
    persisted = orchestration.get_review_run(review.run_id)
    assert persisted is not None
    assert persisted.state == "rejected"
    assert persisted.reviewer.reviewer_action == "rejected"
    assert persisted.reviewer.auth_mode == "cli"
    assert persisted.reviewer.rejection_note == "Need another round of validation before release."
    assert persisted.trigger.status == "skipped"
    assert not config.trigger.file_dir.exists() or not list(config.trigger.file_dir.glob("*.json"))
    assert any(entry.event_type == "rejected" for entry in persisted.audit_trail)
    continuity_body = Path(persisted.continuity.runtime_markdown_path).read_text(encoding="utf-8")
    assert "Final Decision: REJECTED" in continuity_body
    assert "Need another round of validation before release." in continuity_body
    assert "Decision Mode: manual_review" in continuity_body


def test_webhook_provider_records_response(sample_config_path, monkeypatch):
    config = load_config(sample_config_path)
    config.trigger.provider = "webhook"
    config.trigger.webhook_url = "https://example.test/hook"
    orchestration = OrchestrationService(config)
    review = _create_review(orchestration, config)
    captured = {}

    class _FakeResponse:
        status = 202

        def read(self):
            return b'{"accepted":true}'

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_urlopen(request, timeout=0):
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("controltower.services.orchestration.urlopen", _fake_urlopen)

    result = orchestration.approve_review(review.run_id, reviewer_identity="pytest")
    assert result.status == "triggered"
    persisted = orchestration.get_review_run(review.run_id)
    assert persisted is not None
    assert persisted.state == "triggered"
    assert persisted.trigger.provider == "webhook"
    assert persisted.trigger.response_status == 202
    assert '{"accepted":true}' in (persisted.trigger.response_excerpt or "")
    assert Path(persisted.trigger.result_path).exists()
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["idempotency-key"] == persisted.execution_event.event_id
    assert headers["x-controltower-event-id"] == persisted.execution_event.event_id
    assert headers["x-controltower-pack-id"] == persisted.execution_pack.pack_id
    assert captured["timeout"] == 5.0


def test_failed_trigger_does_not_mark_run_triggered(sample_config_path, monkeypatch):
    config = load_config(sample_config_path)
    config.trigger.provider = "webhook"
    config.trigger.webhook_url = "https://example.test/hook"
    orchestration = OrchestrationService(config)
    review = _create_review(orchestration, config)

    def _boom(request, timeout=0):
        raise URLError("downstream unavailable")

    monkeypatch.setattr("controltower.services.orchestration.urlopen", _boom)

    result = orchestration.approve_review(review.run_id, reviewer_identity="pytest")
    assert result.status == "trigger_failed"
    persisted = orchestration.get_review_run(review.run_id)
    assert persisted is not None
    assert persisted.state == "failed"
    assert persisted.trigger.status == "failed"
    assert persisted.trigger.delivery_status == "dead_lettered"
    assert persisted.trigger.emitted_at is None
    assert persisted.last_error is not None
    assert persisted.trigger.dead_letter_path is not None
    assert persisted.trigger.attempt_count == 3
    assert Path(persisted.trigger.dead_letter_path).exists()
    assert "downstream unavailable" in persisted.last_error.details["error"]
    assert any(entry.event_type == "trigger_failed" for entry in persisted.audit_trail)


def test_retryable_webhook_failure_retries_and_then_succeeds(sample_config_path, monkeypatch):
    config = load_config(sample_config_path)
    config.trigger.provider = "webhook"
    config.trigger.webhook_url = "https://example.test/hook"
    orchestration = OrchestrationService(config)
    review = _create_review(orchestration, config)
    attempts = {"count": 0}

    class _FakeResponse:
        status = 202

        def read(self):
            return b'{"accepted":true}'

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _flaky(request, timeout=0):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise URLError("temporary downstream outage")
        return _FakeResponse()

    monkeypatch.setattr("controltower.services.orchestration.urlopen", _flaky)
    monkeypatch.setattr("controltower.services.orchestration.time.sleep", lambda _: None)

    result = orchestration.approve_review(review.run_id, reviewer_identity="pytest")
    assert result.status == "triggered"
    persisted = orchestration.get_review_run(review.run_id)
    assert persisted is not None
    assert persisted.trigger.attempt_count == 3
    assert persisted.trigger.delivery_status == "acknowledged"
    assert persisted.trigger.attempts[0].retryable is True
    assert persisted.trigger.attempts[1].retryable is True
    assert persisted.trigger.attempts[2].status == "succeeded"


def test_permanent_webhook_failure_dead_letters_correctly(sample_config_path, monkeypatch):
    config = load_config(sample_config_path)
    config.trigger.provider = "webhook"
    config.trigger.webhook_url = "https://example.test/hook"
    orchestration = OrchestrationService(config)
    review = _create_review(orchestration, config)

    def _bad_request(request, timeout=0):
        raise HTTPError(
            url=config.trigger.webhook_url,
            code=400,
            msg="bad request",
            hdrs=None,
            fp=BytesIO(b'{"error":"invalid"}'),
        )

    monkeypatch.setattr("controltower.services.orchestration.urlopen", _bad_request)

    result = orchestration.approve_review(review.run_id, reviewer_identity="pytest")
    assert result.status == "trigger_failed"
    persisted = orchestration.get_review_run(review.run_id)
    assert persisted is not None
    assert persisted.trigger.attempt_count == 1
    assert persisted.trigger.delivery_status == "dead_lettered"
    dead_letters = orchestration.list_dead_letters()
    assert len(dead_letters) == 1
    assert dead_letters[0]["run_id"] == review.run_id
    assert dead_letters[0]["pack_type"] == persisted.execution_pack.pack_type


def test_pack_specific_validation_blocks_bad_payload(sample_config_path):
    config = load_config(sample_config_path)
    config.trigger.provider = "file"
    orchestration = OrchestrationService(config)
    review = _create_review(
        orchestration,
        config,
        title="Deployment Change",
        summary="Approved deployment follow-on work needs operator validation.",
        workspace="",
        proposed_next_prompt="Deploy prod immediately",
        include_default_artifacts=False,
    )

    result = orchestration.approve_review(review.run_id, reviewer_identity="pytest")
    assert result.status == "validation_failed"
    persisted = orchestration.get_review_run(review.run_id)
    assert persisted is not None
    assert persisted.execution_pack.pack_type == "deploy_pack"
    assert persisted.execution_pack.validation_status == "invalid"
    assert persisted.trigger.status == "validation_failed"
    assert persisted.trigger.delivery_status == "failed"
    assert persisted.execution_result.closeout_status == "failed"
    assert "deploy_pack requires a clear workspace target" in persisted.execution_pack.validation_errors[0]


def test_guarded_packs_block_in_prod_without_allow_flag(sample_config_path):
    config = load_config(sample_config_path)
    config.app.environment = "prod"
    config.review.mode = "prod"
    config.execution.allow_guarded_in_prod = False
    config.trigger.provider = "file"
    orchestration = OrchestrationService(config)
    review = _create_review(
        orchestration,
        config,
        title="Deployment Change",
        summary="Approved deployment follow-on work needs operator validation.",
        proposed_next_prompt="Deploy the approved release to production",
        include_default_artifacts=False,
    )

    result = orchestration.approve_review(review.run_id, reviewer_identity="pytest")
    assert result.status == "dispatch_blocked"
    persisted = orchestration.get_review_run(review.run_id)
    assert persisted is not None
    assert persisted.execution_pack.pack_type == "deploy_pack"
    assert persisted.execution_pack.pack_guard == "blocked"
    assert persisted.trigger.status == "blocked"
    assert persisted.trigger.delivery_status == "failed"


def test_guarded_packs_can_dispatch_when_explicitly_allowed(sample_config_path):
    config = load_config(sample_config_path)
    config.app.environment = "prod"
    config.review.mode = "prod"
    config.execution.allow_guarded_in_prod = True
    config.trigger.provider = "file"
    orchestration = OrchestrationService(config)
    review = _create_review(
        orchestration,
        config,
        title="Deployment Change",
        summary="Approved deployment follow-on work needs operator validation.",
        proposed_next_prompt="Deploy the approved release to production",
        include_default_artifacts=False,
    )

    result = orchestration.approve_review(review.run_id, reviewer_identity="pytest")
    assert result.status == "triggered"
    persisted = orchestration.get_review_run(review.run_id)
    assert persisted is not None
    assert persisted.execution_pack.pack_guard == "guarded"
    assert persisted.trigger.delivery_status == "queued"


def test_stub_provider_records_intended_execution(sample_config_path):
    config = load_config(sample_config_path)
    config.trigger.provider = "stub"
    orchestration = OrchestrationService(config)
    review = _create_review(orchestration, config)

    result = orchestration.approve_review(review.run_id, reviewer_identity="pytest")
    assert result.status == "triggered"
    persisted = orchestration.get_review_run(review.run_id)
    assert persisted is not None
    assert persisted.trigger.provider == "stub"
    assert persisted.trigger.response_status == 202
    assert "Stub provider recorded intended downstream execution" in (persisted.trigger.response_excerpt or "")
    assert Path(persisted.trigger.payload_path).exists()


def test_result_ingest_updates_originating_run(sample_config_path):
    config = load_config(sample_config_path)
    config.trigger.provider = "file"
    orchestration = OrchestrationService(config)
    review = orchestration.simulate_execution_event(profile="medium", provider_override="file")

    updated = orchestration.ingest_execution_result(
        {
            "event_id": review.execution_event.event_id,
            "run_id": review.run_id,
            "pack_id": review.execution_pack.pack_id,
            "status": "succeeded",
            "summary": "n8n completed the release-readiness pack and published the closeout bundle.",
            "output_artifacts": [{"label": "closeout", "path": "C:/tmp/closeout.md", "content_type": "text/markdown"}],
            "started_at": "2026-03-30T17:40:00Z",
            "completed_at": "2026-03-30T17:45:00Z",
            "external_reference": "n8n-exec-42",
            "logs_excerpt": "All readiness checks passed.",
        }
    )
    assert updated.execution_result.status == "succeeded"
    assert updated.execution_result.external_reference == "n8n-exec-42"
    assert updated.execution_result.output_artifacts[0].path == "C:/tmp/closeout.md"
    assert updated.execution_result.closeout_status == "succeeded"
    assert Path(updated.execution_result.closeout_json_path).exists()
    assert Path(updated.execution_result.closeout_markdown_path).exists()
    assert any(entry.event_type == "execution_result_recorded" for entry in updated.audit_trail)
    continuity_body = Path(updated.continuity.runtime_markdown_path).read_text(encoding="utf-8")
    assert "Status: succeeded" in continuity_body
    assert "closeout.md" in continuity_body


def test_result_ingest_emits_release_outcome_notification(sample_config_path, monkeypatch):
    config = load_config(sample_config_path)
    config.trigger.provider = "file"
    orchestration = OrchestrationService(config)
    review = orchestration.simulate_execution_event(profile="medium", provider_override="file")
    events: list[dict[str, object]] = []

    monkeypatch.setattr(
        "controltower.services.orchestration.notify_controltower_event",
        lambda event, **kwargs: events.append({"event": event, **kwargs})
        or {"message": "ok", "artifact_path": "artifact.json", "delivery": {"success": True, "selected_channel": "console"}},
    )

    orchestration.ingest_execution_result(
        {
            "event_id": review.execution_event.event_id,
            "run_id": review.run_id,
            "pack_id": review.execution_pack.pack_id,
            "status": "failed",
            "summary": "Downstream deploy verification failed.",
        }
    )

    assert events[-1]["event"] == "RELEASE_FAILURE"
    assert events[-1]["status"] == "FAIL"
    assert events[-1]["failing_step"] == "execution_result"
    assert events[-1]["error_summary"] == "Downstream deploy verification failed."


def test_result_ingest_rejects_event_run_mismatch(sample_config_path):
    config = load_config(sample_config_path)
    config.trigger.provider = "file"
    orchestration = OrchestrationService(config)
    review = orchestration.simulate_execution_event(profile="medium", provider_override="file")

    with pytest.raises(ValueError, match="event_id does not match"):
        orchestration.ingest_execution_result(
            {
                "event_id": "wrong-event",
                "run_id": review.run_id,
                "pack_id": review.execution_pack.pack_id,
                "status": "failed",
            }
        )


def test_list_execution_queue_returns_durable_events(sample_config_path):
    config = load_config(sample_config_path)
    config.trigger.provider = "file"
    orchestration = OrchestrationService(config)
    review = orchestration.simulate_execution_event(profile="medium", provider_override="file")

    queue = orchestration.list_execution_queue()
    assert len(queue) == 1
    assert queue[0]["event_id"] == review.execution_event.event_id
    assert queue[0]["pack_type"] == review.execution_pack.pack_type


def test_execution_closeout_payload_matches_persisted_state(sample_config_path):
    config = load_config(sample_config_path)
    config.trigger.provider = "file"
    orchestration = OrchestrationService(config)
    review = orchestration.simulate_execution_event(profile="medium", provider_override="file")

    closeout = orchestration.execution_closeout_payload(review.run_id)
    assert closeout["run_id"] == review.run_id
    assert closeout["final_dispatch_status"] == "queued"
    assert closeout["closeout_status"] == "pending"


def test_review_endpoints_render_and_mutate(sample_config_path):
    config = load_config(sample_config_path)
    config.trigger.provider = "file"
    config.trigger.file_dir = config.runtime.state_root / "orchestration" / "trigger_queue"
    orchestration = OrchestrationService(config)
    review = _create_review(orchestration, config)
    client = TestClient(create_app_from_config(config))

    detail = client.get(review.detail_path)
    assert detail.status_code == 200
    assert "Approval-gated orchestration review surface" in detail.text
    assert "Policy Decision" in detail.text
    assert "manual_review" in detail.text
    assert "medium" in detail.text
    assert "Editable Next Prompt" in detail.text
    assert "Execution Pack" in detail.text
    assert "Execution Dispatch" in detail.text
    assert "Pack guard:" in detail.text
    assert "Delivery status:" in detail.text
    assert "false negative caused" in detail.text
    assert "Dev mode keeps local approval flows friction-light" in detail.text

    approve = client.post(
        review.approve_path,
        data={"approved_next_prompt": "Route approval prompt"},
        follow_redirects=True,
    )
    assert approve.status_code == 200
    assert "Last action: triggered" in approve.text
    assert "Route approval prompt" in approve.text
    assert "review-state-triggered" in approve.text
    assert "release_readiness_pack" in approve.text
    assert "Closeout status: pending" in approve.text
    assert "Attempt count: 1" in approve.text
    assert "Last error: not recorded" in approve.text
    assert "Dead letter path: not recorded" in approve.text
    assert "Closeout recorded at:" in approve.text

    runs = client.get("/runs")
    assert runs.status_code == 200
    assert review.run_id in runs.text
    assert "review-state-triggered" in runs.text
    assert "review-risk-medium" in runs.text
    assert "review-decision-manual_review" in runs.text
    assert "queued" in runs.text
    assert "delivery_status: queued" in runs.text
    assert "attempt_count: 1" in runs.text
    assert "last_error: not recorded" in runs.text
    assert "dead_letter_path: not recorded" in runs.text
    assert "closeout_status: pending" in runs.text
    assert "closeout_recorded_at:" in runs.text

    rejected_review = _create_review(orchestration, config)
    reject = client.post(
        rejected_review.reject_path,
        data={"rejection_note": "Reject from UI"},
        follow_redirects=True,
    )
    assert reject.status_code == 200
    assert "Reject from UI" in reject.text
    runs_after_reject = client.get("/runs")
    assert runs_after_reject.status_code == 200
    assert "review-state-rejected" in runs_after_reject.text


def test_failed_dispatch_state_is_visible_in_review_ui(sample_config_path, monkeypatch):
    config = load_config(sample_config_path)
    config.trigger.provider = "webhook"
    config.trigger.webhook_url = "https://example.test/hook"
    orchestration = OrchestrationService(config)
    review = _create_review(orchestration, config)

    def _boom(request, timeout=0):
        raise URLError("downstream unavailable")

    monkeypatch.setattr("controltower.services.orchestration.urlopen", _boom)

    result = orchestration.approve_review(review.run_id, reviewer_identity="pytest")
    assert result.status == "trigger_failed"

    client = TestClient(create_app_from_config(config))
    detail = client.get(review.detail_path)
    assert detail.status_code == 200
    assert "Delivery status: dead_lettered" in detail.text
    assert "Attempt count: 3" in detail.text
    assert "Last error: Execution event emission exhausted its bounded retries." in detail.text
    assert "Dead letter path:" in detail.text
    assert ".json" in detail.text

    runs = client.get("/runs")
    assert runs.status_code == 200
    assert "delivery_status: dead_lettered" in runs.text
    assert "attempt_count: 3" in runs.text
    assert "last_error: Execution event emission exhausted its bounded retries." in runs.text
    assert "dead_letter_path:" in runs.text


def test_review_mutation_endpoints_require_auth_in_prod_and_hide_controls_when_anonymous(sample_config_path):
    config = load_config(sample_config_path)
    config.trigger.provider = "none"
    config.review.mode = "prod"
    config.review.session_secret = "prod-session-secret"
    config.review.operator_username = "operator"
    config.review.operator_password = "operator-pass"
    orchestration = OrchestrationService(config)
    review = _create_review(orchestration, config)
    client = TestClient(create_app_from_config(config), base_url="https://testserver")

    detail = client.get(review.detail_path)
    assert detail.status_code == 200
    assert "Production mode allows read-only review access to anonymous viewers" in detail.text
    assert "Sign In To Review" in detail.text
    assert review.approve_path not in detail.text
    assert review.reject_path not in detail.text
    assert ">Approve</button>" in detail.text
    assert ">Reject</button>" in detail.text

    denied = client.post(review.approve_path, data={"approved_next_prompt": "Denied"}, follow_redirects=False)
    assert denied.status_code == 401


def test_review_mutation_endpoints_allow_authorized_session_in_prod(sample_config_path):
    config = load_config(sample_config_path)
    config.trigger.provider = "none"
    config.review.mode = "prod"
    config.review.session_secret = "prod-session-secret"
    config.review.operator_username = "operator"
    config.review.operator_password = "operator-pass"
    orchestration = OrchestrationService(config)
    review = _create_review(orchestration, config)
    client = TestClient(create_app_from_config(config), base_url="https://testserver")

    detail = client.get(review.detail_path)
    csrf_token = _extract_csrf_token(detail.text)

    login = client.post(
        "/reviews/login",
        data={
            "operator_username": "operator",
            "operator_password": "operator-pass",
            "next_path": review.detail_path,
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert login.status_code == 303

    authenticated_detail = client.get(review.detail_path)
    assert authenticated_detail.status_code == 200
    assert "Signed in as <strong>operator</strong> using <code>session</code>." in authenticated_detail.text
    csrf_token = _extract_csrf_token(authenticated_detail.text)

    denied = client.post(review.approve_path, data={"approved_next_prompt": "Denied"}, follow_redirects=False)
    allowed = client.post(
        review.approve_path,
        data={"approved_next_prompt": "Allowed", "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert denied.status_code == 403
    assert allowed.status_code == 303
    persisted = orchestration.get_review_run(review.run_id)
    assert persisted is not None
    assert persisted.state == "approved"
    assert persisted.trigger.status == "skipped"
    assert persisted.reviewer.reviewer_identity == "operator"
    assert persisted.reviewer.auth_mode == "session"
    assert persisted.reviewer.source_ip == "testclient"
    assert persisted.reviewer.user_agent is not None

    final_detail = client.get(review.detail_path)
    assert "Reviewer identity: operator" in final_detail.text
    assert "Auth mode: session" in final_detail.text
    assert "Execution Event" in final_detail.text


def test_review_mutation_endpoints_fail_closed_without_prod_session_config(sample_config_path):
    config = load_config(sample_config_path)
    config.trigger.provider = "none"
    config.review.mode = "prod"
    config.review.session_secret = None
    config.review.operator_username = None
    config.review.operator_password = None
    review = _create_review(OrchestrationService(config), config)
    client = TestClient(create_app_from_config(config), base_url="https://testserver")

    detail = client.get(review.detail_path)
    assert detail.status_code == 200
    assert "Production mutation protection is enabled, but the operator session gate is misconfigured." in detail.text

    response = client.post(review.reject_path, data={"rejection_note": "blocked"}, follow_redirects=False)
    assert response.status_code == 503


def test_app_auth_protects_ui_and_api_routes_in_prod(sample_config_path):
    config = load_config(sample_config_path)
    config.auth.mode = "prod"
    config.auth.session_secret = "app-session-secret"
    config.auth.username = "operator"
    config.auth.password = "operator-pass"
    config.app.public_base_url = "https://controltower.example.com"
    client = TestClient(create_app_from_config(config), base_url="https://controltower.example.com")

    protected = client.get("/publish", follow_redirects=False)
    assert protected.status_code == 303
    assert protected.headers["location"].startswith("/login?next_path=/publish")

    api_denied = client.get("/api/portfolio")
    assert api_denied.status_code == 401
    assert api_denied.json()["detail"] == "Authentication is required for this Control Tower route."

    login_page = client.get("/login?next_path=/publish")
    assert login_page.status_code == 200
    assert "Control Tower is publicly reachable over HTTPS" in login_page.text
    csrf_token = _extract_csrf_token(login_page.text)

    login = client.post(
        "/login",
        data={
            "username": "operator",
            "password": "operator-pass",
            "next_path": "/publish",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"].startswith("/publish?")

    publish = client.get("/publish")
    assert publish.status_code == 200
    assert "Sign In" not in publish.text
    assert ">Sign Out</button>" in publish.text


def test_review_urls_use_public_base_url_when_configured(sample_config_path):
    config = load_config(sample_config_path)
    config.app.public_base_url = "https://controltower.example.com"
    review = _create_review(OrchestrationService(config), config)
    assert review.review_url == f"https://controltower.example.com/reviews/{review.run_id}"


def _create_review(
    orchestration: OrchestrationService,
    config,
    *,
    title: str = "Control Tower Release Readiness Passed",
    workspace: str = "controltower",
    summary: str | None = None,
    proposed_next_prompt: str | None = None,
    include_default_artifacts: bool = True,
) -> object:
    release_root = config.runtime.state_root / "release"
    release_root.mkdir(parents=True, exist_ok=True)
    artifact_a = release_root / "release_readiness_2026-03-30T17-32-56Z.json"
    artifact_b = release_root / "release_readiness_2026-03-30T17-36-32Z.json"
    artifact_a.write_text('{"status":"not_ready"}', encoding="utf-8")
    artifact_b.write_text('{"status":"ready"}', encoding="utf-8")
    return orchestration.ingest_release_readiness_pass(
        title=title,
        workspace=workspace,
        summary=summary
        or "Release readiness passed after correcting HTML entity comparison in finish-driver verifier. Prior failure was a false negative caused by '&' vs '&amp;' mismatch.",
        raw_output_excerpt=[
            "Prior failure: verifier compared raw HTML and produced a false negative on '&' vs '&amp;'.",
            "Fix: verifier now compares unescaped visible text instead of raw HTML.",
            "Confirmation: release_readiness_controltower completed with exit code 0.",
        ],
        proposed_next_prompt=proposed_next_prompt
        or (
            "Checkpoint fix, push to repo, and run full production validation:\n"
            "1. pytest -q\n"
            "2. acceptance harness\n"
            "3. verify publish surface rendering\n"
            "4. confirm execution brief output is stable\n"
            "5. generate final operator brief artifact"
        ),
        artifact_paths=[artifact_a, artifact_b] if include_default_artifacts else [],
        source_operation_id="release_readiness_2026-03-30T17-35-54Z",
        release_generated_at="2026-03-30T17:36:32Z",
    )


def _extract_csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)

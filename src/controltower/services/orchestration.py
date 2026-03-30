from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from controltower.config import ControlTowerConfig
from controltower.domain.models import (
    ExecutionEmissionAttempt,
    ExecutionEventArtifact,
    ExecutionPackRecord,
    ExecutionResultArtifact,
    ExecutionResultRecord,
    ReviewArtifactRef,
    ReviewAuditEntry,
    ReviewContinuityRecord,
    ReviewDecisionMetadata,
    ReviewFailure,
    ReviewNotification,
    ReviewRun,
    utc_now_iso,
)
from controltower.services.autonomy_policy import PolicyEvaluationInput, evaluate_review_policy
from controltower.services.runtime_state import read_json, write_json


ORCHESTRATION_ROOT_NAME = "orchestration"
REVIEWS_ROOT_NAME = "reviews"
NOTIFICATIONS_ROOT_NAME = "notifications"
CONTINUITY_ROOT_NAME = "continuity"
EXECUTION_EVENTS_ROOT_NAME = "execution_events"
EXECUTION_RESULTS_ROOT_NAME = "execution_results"
LATEST_REVIEW_NAME = "latest_review.json"
LATEST_PENDING_REVIEW_NAME = "latest_pending_review.json"
LATEST_NOTIFICATION_NAME = "latest_notification.json"

DEFAULT_DEMO_TITLE = "Control Tower Release Readiness Passed"
DEFAULT_DEMO_WORKSPACE = "controltower"
DEFAULT_DEMO_SUMMARY = (
    "Release readiness passed after correcting HTML entity comparison in finish-driver verifier. "
    "Prior failure was a false negative caused by '&' vs '&amp;' mismatch."
)
DEFAULT_DEMO_EXCERPT = [
    "Prior failure description: finish-driver verification produced a false negative because raw HTML encoded the visible ampersand as &amp;.",
    "Fix description: meeting_readiness.py now compares unescaped visible text instead of raw HTML for finish and finish-driver verification.",
    "Confirmation: release_readiness_2026-03-30T17-35-54Z completed with exit code 0 and the release verdict is ready.",
]
DEFAULT_DEMO_PROMPT = (
    "Checkpoint fix, push to repo, and run full production validation:\n"
    "1. pytest -q\n"
    "2. acceptance harness\n"
    "3. verify publish surface rendering\n"
    "4. confirm execution brief output is stable\n"
    "5. generate final operator brief artifact"
)
DEFAULT_DEMO_SOURCE_OPERATION_ID = "release_readiness_2026-03-30T17-35-54Z"
DEFAULT_DEMO_RELEASE_GENERATED_AT = "2026-03-30T17:36:32Z"
DEFAULT_DEMO_ARTIFACT_NAMES = (
    "release_readiness_2026-03-30T17-32-56Z.json",
    "release_readiness_2026-03-30T17-36-32Z.json",
)
DEMO_SCENARIO_CHANGED_FILES = {
    "low": ["docs/REVIEW_APPROVAL_RUNBOOK.md", "README.md"],
    "medium": ["src/controltower/api/templates/publish.html", "src/controltower/api/static/site.css"],
    "high": ["src/controltower/api/app.py", "infra/nginx/controltower.conf", "src/controltower/services/orchestration.py"],
}


@dataclass(slots=True)
class ReviewActionResult:
    status: str
    message: str
    review: ReviewRun | None
    trigger_emitted: bool = False


@dataclass(slots=True)
class ReviewActorContext:
    identity: str | None = None
    auth_mode: str | None = None
    source_ip: str | None = None
    forwarded_for: str | None = None
    user_agent: str | None = None


class TriggerEmissionError(RuntimeError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class OrchestrationService:
    def __init__(self, config: ControlTowerConfig) -> None:
        self.config = config

    def list_review_runs(self) -> list[ReviewRun]:
        reviews_root = self._reviews_root()
        runs: list[ReviewRun] = []
        for path in sorted(reviews_root.glob("*/run.json")):
            payload = read_json(path)
            if payload is None:
                continue
            runs.append(ReviewRun.model_validate(payload))
        return sorted(runs, key=lambda item: item.created_at, reverse=True)

    def get_review_run(self, run_id: str) -> ReviewRun | None:
        payload = read_json(self._review_run_path(run_id))
        if payload is None:
            return None
        return ReviewRun.model_validate(payload)

    def update_review_state(self, run_id: str, *, state: str) -> ReviewRun | None:
        review = self.get_review_run(run_id)
        if review is None:
            return None
        updated = review.model_copy(update={"state": state})
        self._write_review(updated)
        return updated

    def approve_review(
        self,
        run_id: str,
        *,
        approved_next_prompt: str | None = None,
        reviewer_identity: str | None = None,
        auth_mode: str | None = None,
        source_ip: str | None = None,
        forwarded_for: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        provider_override: str | None = None,
    ) -> ReviewActionResult:
        review = self.get_review_run(run_id)
        if review is None:
            return ReviewActionResult(status="not_found", message="Review run not found.", review=None)

        if review.state == "triggered" or review.trigger.status == "emitted":
            if review.state != "triggered":
                review = review.model_copy(update={"state": "triggered"})
                self._write_review(review)
            return ReviewActionResult(
                status="already_triggered",
                message="Review was already triggered. No additional trigger was emitted.",
                review=review,
            )

        if review.state == "rejected":
            return ReviewActionResult(
                status="already_rejected",
                message="Rejected review runs cannot be approved without creating a new review run.",
                review=review,
            )

        reviewed_at = utc_now_iso()
        approved_prompt = (approved_next_prompt or "").strip() or review.reviewer.approved_next_prompt or review.proposed_next_prompt
        configured_provider = review.trigger.provider if review.trigger.provider not in {"", "none"} else None
        provider = (provider_override or configured_provider or self.config.execution.provider or "file").lower()
        if provider not in {"file", "webhook", "stub", "none"}:
            raise ValueError(f"Unsupported execution provider: {provider}")

        reviewer = ReviewDecisionMetadata(
            reviewed_at=reviewed_at,
            reviewer_action="approved",
            approved_next_prompt=approved_prompt,
            rejection_note=None,
            reviewer_identity=reviewer_identity,
            auth_mode=auth_mode,
            source_ip=source_ip,
            forwarded_for=forwarded_for,
            user_agent=user_agent,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        existing_trigger = review.trigger
        trigger_id = existing_trigger.trigger_id or self._deterministic_trigger_id(review.run_id)
        event_id = existing_trigger.event_id or self._deterministic_event_id(review.run_id)
        review = review.model_copy(
            update={
                "state": "approved",
                "reviewer": reviewer,
                "last_error": None,
            }
        )
        execution_pack = self._apply_pack_policies(
            review,
            self._select_execution_pack(review, approved_next_prompt=approved_prompt, selected_at=reviewed_at),
        )
        trigger = existing_trigger.model_copy(
            update={
                "provider": provider,
                "execution_event_id": event_id,
                "trigger_id": trigger_id,
                "event_id": event_id,
                "pack_id": execution_pack.pack_id,
                "pack_type": execution_pack.pack_type,
                "event_version": self.config.execution.event_version,
                "status": "skipped" if provider == "none" else "pending",
                "delivery_status": None if provider == "none" else "queued",
                "requested_at": existing_trigger.requested_at or reviewed_at,
                "target": self._trigger_target(provider),
                "response_status": None,
                "response_excerpt": None,
                "error_message": None,
                "last_error": None,
                "dead_letter_path": None,
                "closeout_status": "pending",
                "downstream_reference": review.execution_result.external_reference,
            }
        )
        review = review.model_copy(
            update={
                "trigger": trigger,
                "execution_pack": execution_pack,
                "execution_result": review.execution_result.model_copy(
                    update={
                        "event_id": event_id,
                        "run_id": review.run_id,
                        "pack_id": execution_pack.pack_id,
                        "pack_type": execution_pack.pack_type,
                        "closeout_status": "pending",
                    }
                ),
            }
        )
        review = review.model_copy(update={"execution_event": self._build_execution_event(review)})
        review = review.model_copy(
            update={"trigger": review.trigger.model_copy(update={"execution_event_id": review.execution_event.event_id})}
        )
        review = self._append_audit(
            review,
            event_type="approved",
            message="Approval recorded and normalized execution event prepared.",
            request_id=request_id,
            correlation_id=correlation_id,
            details={
                "provider": provider,
                "event_id": event_id,
                "pack_id": execution_pack.pack_id,
                "pack_type": execution_pack.pack_type,
                "approved_next_prompt_changed": approved_prompt != review.proposed_next_prompt,
                **self._actor_audit_details(reviewer),
            },
        )
        review = self._write_approved_payload(review)
        self._write_review(review)

        if provider == "none":
            review = self._append_audit(
                review,
                event_type="trigger_skipped",
                message="Approval recorded without downstream emission because execution provider is set to none.",
                request_id=request_id,
                correlation_id=correlation_id,
                details={"provider": provider, **self._actor_audit_details(review.reviewer)},
            )
            review = self._write_closeout(review)
            review = self._write_continuity(review)
            self._write_review(review)
            return ReviewActionResult(
                status="approved_no_trigger",
                message="Approval was recorded. Trigger emission is disabled because the provider is set to 'none'.",
                review=review,
            )

        if review.execution_pack.validation_status != "valid":
            validation_message = "; ".join(review.execution_pack.validation_errors) or "Pack validation blocked downstream dispatch."
            failure = ReviewFailure(
                recorded_at=utc_now_iso(),
                phase="pack_validation",
                message=validation_message,
                details={
                    "pack_id": review.execution_pack.pack_id,
                    "pack_type": review.execution_pack.pack_type,
                    "validation_errors": review.execution_pack.validation_errors,
                },
            )
            review = review.model_copy(
                update={
                    "state": "failed",
                    "last_error": failure,
                    "trigger": review.trigger.model_copy(
                        update={
                            "status": "validation_failed",
                            "delivery_status": "failed",
                            "error_message": validation_message,
                            "last_error": validation_message,
                        }
                    ),
                    "execution_result": review.execution_result.model_copy(
                        update={
                            "status": "failed",
                            "summary": validation_message,
                        }
                    ),
                }
            )
            review = self._append_audit(
                review,
                event_type="pack_validation_failed",
                message="Downstream dispatch was blocked by pack-specific validation.",
                request_id=request_id,
                correlation_id=correlation_id,
                details={
                    "pack_id": review.execution_pack.pack_id,
                    "pack_type": review.execution_pack.pack_type,
                    "validation_errors": review.execution_pack.validation_errors,
                },
            )
            review = self._write_closeout(review)
            review = self._write_continuity(review)
            self._write_review(review)
            return ReviewActionResult(
                status="validation_failed",
                message=validation_message,
                review=review,
            )

        if review.execution_pack.pack_guard == "blocked":
            guard_message = "; ".join(review.execution_pack.guard_reasons) or "Pack guard blocked downstream dispatch."
            failure = ReviewFailure(
                recorded_at=utc_now_iso(),
                phase="pack_guard",
                message=guard_message,
                details={
                    "pack_id": review.execution_pack.pack_id,
                    "pack_type": review.execution_pack.pack_type,
                    "guard_reasons": review.execution_pack.guard_reasons,
                },
            )
            review = review.model_copy(
                update={
                    "state": "failed",
                    "last_error": failure,
                    "trigger": review.trigger.model_copy(
                        update={
                            "status": "blocked",
                            "delivery_status": "failed",
                            "error_message": guard_message,
                            "last_error": guard_message,
                        }
                    ),
                    "execution_result": review.execution_result.model_copy(
                        update={
                            "status": "failed",
                            "summary": guard_message,
                        }
                    ),
                }
            )
            review = self._append_audit(
                review,
                event_type="pack_guard_blocked",
                message="Downstream dispatch was blocked by guarded execution policy.",
                request_id=request_id,
                correlation_id=correlation_id,
                details={
                    "pack_id": review.execution_pack.pack_id,
                    "pack_type": review.execution_pack.pack_type,
                    "guard_reasons": review.execution_pack.guard_reasons,
                },
            )
            review = self._write_closeout(review)
            review = self._write_continuity(review)
            self._write_review(review)
            return ReviewActionResult(
                status="dispatch_blocked",
                message=guard_message,
                review=review,
            )

        try:
            trigger = self._emit_trigger(review)
        except TriggerEmissionError as exc:
            failure = ReviewFailure(
                recorded_at=utc_now_iso(),
                phase="trigger_emission",
                message=str(exc),
                details=exc.details,
            )
            review = self.get_review_run(run_id) or review
            review = review.model_copy(
                update={
                    "state": "failed",
                    "last_error": failure,
                    "trigger": review.trigger.model_copy(
                        update={
                            "status": "failed",
                            "delivery_status": exc.details.get("delivery_status") or "failed",
                            "last_attempt_at": failure.recorded_at,
                            "last_attempted_at": failure.recorded_at,
                            "error_message": str(exc),
                            "last_error": str(exc),
                            "dead_letter_path": exc.details.get("dead_letter_path"),
                            "first_attempted_at": exc.details.get("first_attempted_at") or review.trigger.first_attempted_at,
                            "attempt_count": len(exc.details.get("attempts") or review.trigger.attempts),
                            "attempts": [
                                ExecutionEmissionAttempt.model_validate(item)
                                for item in (exc.details.get("attempts") or review.trigger.attempts)
                            ],
                        }
                    ),
                    "execution_result": review.execution_result.model_copy(
                        update={
                            "status": "failed",
                            "summary": str(exc),
                        }
                    ),
                }
            )
            review = self._append_audit(
                review,
                event_type="trigger_failed",
                message="Approval persisted, but trigger emission failed and the run remains untriggered.",
                request_id=request_id,
                correlation_id=correlation_id,
                details=exc.details | {"error": str(exc), "event_id": review.trigger.event_id, **self._actor_audit_details(review.reviewer)},
            )
            review = self._write_closeout(review)
            review = self._write_continuity(review)
            self._write_review(review)
            return ReviewActionResult(
                status="trigger_failed",
                message=f"Approval was recorded, but trigger emission failed: {exc}",
                review=review,
            )

        review = self.get_review_run(run_id) or review
        review = review.model_copy(
            update={
                "state": "triggered",
                "trigger": trigger,
                "execution_result": review.execution_result.model_copy(
                    update={
                        "event_id": review.execution_event.event_id,
                        "run_id": review.run_id,
                        "pack_id": review.execution_pack.pack_id,
                        "pack_type": review.execution_pack.pack_type,
                        "status": "queued",
                        "summary": review.execution_result.summary,
                    }
                ),
                "last_error": None,
            }
        )
        review = self._append_audit(
            review,
            event_type="trigger_emitted",
            message="Approval trigger emitted exactly once and the run is now triggered.",
            request_id=request_id,
            correlation_id=correlation_id,
            details={
                "provider": trigger.provider,
                "target": trigger.target,
                "event_id": trigger.event_id,
                "pack_id": review.execution_pack.pack_id,
                "pack_type": review.execution_pack.pack_type,
                "payload_path": trigger.payload_path,
                "response_status": trigger.response_status,
                **self._actor_audit_details(review.reviewer),
            },
        )
        review = self._write_closeout(review)
        review = self._write_continuity(review)
        self._write_review(review)
        return ReviewActionResult(
            status="triggered",
            message="Approval recorded and downstream trigger emitted successfully.",
            review=review,
            trigger_emitted=True,
        )

    def reject_review(
        self,
        run_id: str,
        *,
        rejection_note: str | None = None,
        reviewer_identity: str | None = None,
        auth_mode: str | None = None,
        source_ip: str | None = None,
        forwarded_for: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ReviewActionResult:
        review = self.get_review_run(run_id)
        if review is None:
            return ReviewActionResult(status="not_found", message="Review run not found.", review=None)

        if review.state == "triggered":
            return ReviewActionResult(
                status="already_triggered",
                message="Triggered review runs cannot be rejected retroactively.",
                review=review,
            )

        if review.state == "rejected":
            return ReviewActionResult(
                status="already_rejected",
                message="Review run is already rejected.",
                review=review,
            )

        reviewed_at = utc_now_iso()
        reviewer = ReviewDecisionMetadata(
            reviewed_at=reviewed_at,
            reviewer_action="rejected",
            approved_next_prompt=review.reviewer.approved_next_prompt,
            rejection_note=(rejection_note or "").strip() or None,
            reviewer_identity=reviewer_identity,
            auth_mode=auth_mode,
            source_ip=source_ip,
            forwarded_for=forwarded_for,
            user_agent=user_agent,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        review = review.model_copy(
            update={
                "state": "rejected",
                "reviewer": reviewer,
                "last_error": None,
                "trigger": review.trigger.model_copy(update={"status": "skipped", "error_message": None}),
            }
        )
        review = self._append_audit(
            review,
            event_type="rejected",
            message="Review was rejected. No trigger was emitted.",
            request_id=request_id,
            correlation_id=correlation_id,
            details={"rejection_note_present": reviewer.rejection_note is not None, **self._actor_audit_details(reviewer)},
        )
        review = self._write_continuity(review)
        self._write_review(review)
        return ReviewActionResult(
            status="rejected",
            message="Rejection recorded without trigger emission.",
            review=review,
        )

    def emit_trigger_to_file(
        self,
        run_id: str,
        *,
        approved_next_prompt: str | None = None,
        reviewer_identity: str | None = None,
        auth_mode: str | None = None,
        source_ip: str | None = None,
        forwarded_for: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ReviewActionResult:
        review = self.get_review_run(run_id)
        if review is None:
            return ReviewActionResult(status="not_found", message="Review run not found.", review=None)
        if review.state == "approved":
            return self.approve_review(
                run_id,
                approved_next_prompt=approved_next_prompt or review.reviewer.approved_next_prompt,
                reviewer_identity=reviewer_identity or review.reviewer.reviewer_identity,
                auth_mode=auth_mode or review.reviewer.auth_mode,
                source_ip=source_ip or review.reviewer.source_ip,
                forwarded_for=forwarded_for or review.reviewer.forwarded_for,
                user_agent=user_agent or review.reviewer.user_agent,
                request_id=request_id or review.reviewer.request_id,
                correlation_id=correlation_id or review.reviewer.correlation_id,
                provider_override="file",
            )
        return self.approve_review(
            run_id,
            approved_next_prompt=approved_next_prompt,
            reviewer_identity=reviewer_identity,
            auth_mode=auth_mode,
            source_ip=source_ip,
            forwarded_for=forwarded_for,
            user_agent=user_agent,
            request_id=request_id,
            correlation_id=correlation_id,
            provider_override="file",
        )

    def create_review_run(
        self,
        *,
        title: str,
        workspace: str,
        summary: str,
        raw_output_excerpt: list[str],
        proposed_next_prompt: str,
        artifact_paths: list[Path | str],
        source_operation_id: str | None = None,
        release_generated_at: str | None = None,
        changed_files: list[str] | None = None,
        tests_passed: bool | None = None,
        acceptance_passed: bool | None = None,
    ) -> ReviewRun:
        created_at = utc_now_iso()
        run_id = self._next_review_run_id(created_at)
        policy = evaluate_review_policy(
            self.config,
            PolicyEvaluationInput(
                workspace=workspace,
                title=title,
                summary=summary,
                proposed_next_prompt=proposed_next_prompt,
                raw_output_excerpt=raw_output_excerpt,
                artifact_paths=artifact_paths,
                changed_files=changed_files,
                tests_passed=tests_passed,
                acceptance_passed=acceptance_passed,
            ),
        )
        initial_state = "escalated" if policy.decision_mode == "escalate" else "pending_review"
        review = ReviewRun(
            run_id=run_id,
            title=title,
            workspace=workspace,
            summary=summary,
            raw_output_excerpt=raw_output_excerpt,
            proposed_next_prompt=proposed_next_prompt,
            state=initial_state,
            created_at=created_at,
            review_url=self._review_url(run_id),
            detail_path=f"/reviews/{run_id}",
            approve_path=f"/reviews/{run_id}/approve",
            reject_path=f"/reviews/{run_id}/reject",
            source_operation_id=source_operation_id,
            release_generated_at=release_generated_at,
            artifacts=self._attach_artifacts(run_id, artifact_paths),
            risk_level=policy.risk_level,
            decision_mode=policy.decision_mode,
            decision_reasons=policy.decision_reasons,
            policy_version=policy.policy_version,
            auto_approved_at=policy.auto_approved_at,
            escalated_at=policy.escalated_at,
            policy_evaluated_at=policy.policy_evaluated_at,
        )
        review = self._append_audit(
            review,
            event_type="created",
            message="Review run created and attached artifacts copied into orchestration storage.",
            details={"artifact_count": len(review.artifacts)},
        )
        review = self._append_audit(
            review,
            event_type="policy_evaluated",
            message=f"Deterministic autonomy policy classified the completed run as {review.risk_level}/{review.decision_mode}.",
            details={
                "risk_level": review.risk_level,
                "decision_mode": review.decision_mode,
                "decision_reasons": list(review.decision_reasons),
                "policy_version": review.policy_version,
                "tests_passed": policy.evidence.get("tests_passed"),
                "acceptance_passed": policy.evidence.get("acceptance_passed"),
                "changed_files": policy.evidence.get("changed_files"),
            },
        )
        self._write_review(review)
        review = self._apply_post_creation_flow(review)
        self._write_review(review)
        return review

    def ingest_release_readiness_pass(
        self,
        *,
        title: str,
        workspace: str,
        summary: str,
        raw_output_excerpt: list[str],
        proposed_next_prompt: str,
        artifact_paths: list[Path | str],
        source_operation_id: str | None = None,
        release_generated_at: str | None = None,
        changed_files: list[str] | None = None,
        tests_passed: bool | None = None,
        acceptance_passed: bool | None = None,
    ) -> ReviewRun:
        return self.create_review_run(
            title=title,
            workspace=workspace,
            summary=summary,
            raw_output_excerpt=raw_output_excerpt,
            proposed_next_prompt=proposed_next_prompt,
            artifact_paths=artifact_paths,
            source_operation_id=source_operation_id,
            release_generated_at=release_generated_at,
            changed_files=changed_files,
            tests_passed=tests_passed,
            acceptance_passed=acceptance_passed,
        )

    def simulate_completed_run(
        self,
        *,
        profile: str = "medium",
        artifact_paths: list[Path | str] | None = None,
        title: str = DEFAULT_DEMO_TITLE,
        workspace: str = DEFAULT_DEMO_WORKSPACE,
        summary: str = DEFAULT_DEMO_SUMMARY,
        raw_output_excerpt: list[str] | None = None,
        proposed_next_prompt: str = DEFAULT_DEMO_PROMPT,
        source_operation_id: str | None = DEFAULT_DEMO_SOURCE_OPERATION_ID,
        release_generated_at: str | None = DEFAULT_DEMO_RELEASE_GENERATED_AT,
    ) -> ReviewRun:
        scenario = self._demo_scenario(profile)
        resolved_artifacts = artifact_paths or scenario["artifact_paths"] or self.default_demo_artifact_paths()
        if not resolved_artifacts:
            raise FileNotFoundError(
                "No review artifact files were found. Provide --artifact-path values or create the canonical release artifacts first."
            )
        return self.create_review_run(
            title=scenario["title"] if title == DEFAULT_DEMO_TITLE else title,
            workspace=workspace,
            summary=scenario["summary"] if summary == DEFAULT_DEMO_SUMMARY else summary,
            raw_output_excerpt=raw_output_excerpt or scenario["raw_output_excerpt"],
            proposed_next_prompt=scenario["proposed_next_prompt"] if proposed_next_prompt == DEFAULT_DEMO_PROMPT else proposed_next_prompt,
            artifact_paths=resolved_artifacts,
            source_operation_id=source_operation_id if profile == "medium" else f"demo_{profile}_{utc_now_iso().replace(':', '-')}",
            release_generated_at=release_generated_at,
            changed_files=scenario["changed_files"],
            tests_passed=scenario["tests_passed"],
            acceptance_passed=scenario["acceptance_passed"],
        )

    def default_demo_artifact_paths(self) -> list[Path]:
        release_root = Path(self.config.runtime.state_root) / "release"
        return [path for path in (release_root / name for name in DEFAULT_DEMO_ARTIFACT_NAMES) if path.exists()]

    def _apply_post_creation_flow(self, review: ReviewRun) -> ReviewRun:
        if review.decision_mode == "auto_approve":
            review = self._append_audit(
                review,
                event_type="policy_auto_approve_started",
                message="Policy engine selected auto-approval, so Control Tower is routing this run through the standard approval path.",
                details={"policy_version": review.policy_version},
            )
            self._write_review(review)
            result = self.approve_review(
                review.run_id,
                reviewer_identity="policy-engine",
                auth_mode="policy_auto",
                request_id=f"policy-auto-{review.run_id}",
                correlation_id=f"policy-auto-{review.run_id}",
            )
            review = result.review or self.get_review_run(review.run_id) or review
            if self.config.autonomy.notify_on_auto_approve:
                return self._record_notification(
                    review,
                    title="Control Tower Run Auto-Approved",
                    body="Low-risk run auto-approved through deterministic policy and fully audited.",
                    signal_level="quiet",
                    event_type="notification_sent",
                )
            return self._record_notification(
                review,
                title="Control Tower Run Auto-Approved",
                body="Auto-approved runs can suppress operator notification when configured to stay quiet.",
                signal_level="quiet",
                suppressed=True,
            )

        if review.decision_mode == "escalate":
            review = self._append_audit(
                review,
                event_type="policy_escalated",
                message="Policy engine escalated this run for operator attention.",
                details={"policy_version": review.policy_version},
            )
            return self._record_notification(
                review,
                title="Control Tower Run Escalated",
                body="High-risk or critical scope detected. Operator review should treat this run as escalated.",
                signal_level="high",
                event_type="notification_sent",
            )

        return self._record_notification(
            review,
            title="Control Tower Run Ready for Review",
            body="Deterministic policy kept this completed run in manual review.",
            signal_level="normal",
            event_type="notification_sent",
        )

    def _demo_scenario(self, profile: str) -> dict[str, Any]:
        normalized = (profile or "medium").strip().lower()
        if normalized not in {"low", "medium", "high"}:
            raise ValueError("Unsupported demo profile. Use low, medium, or high.")
        if normalized == "low":
            artifact_path = self._write_demo_artifact(
                normalized,
                {
                    "profile": "low",
                    "tests_passed": True,
                    "acceptance_passed": True,
                    "changed_files": DEMO_SCENARIO_CHANGED_FILES["low"],
                    "summary": "Updated review/autonomy runbook wording and documentation only.",
                },
            )
            return {
                "title": "Control Tower Review Docs Refresh",
                "summary": "Documentation-only update for the operator selective-autonomy guide and review runbook.",
                "raw_output_excerpt": [
                    "Scope: review runbook wording refresh only.",
                    "Evidence: only markdown documentation files changed.",
                    "Verification: docs lint / lightweight checks passed.",
                ],
                "proposed_next_prompt": "Publish the refreshed docs and note the updated selective-autonomy guidance for operators.",
                "artifact_paths": [artifact_path],
                "changed_files": DEMO_SCENARIO_CHANGED_FILES["low"],
                "tests_passed": True,
                "acceptance_passed": True,
            }
        if normalized == "high":
            artifact_path = self._write_demo_artifact(
                normalized,
                {
                    "profile": "high",
                    "tests_passed": False,
                    "acceptance_passed": False,
                    "changed_files": DEMO_SCENARIO_CHANGED_FILES["high"],
                    "summary": "Touched prod review auth/session handling and nginx routing with a restart step.",
                },
            )
            return {
                "title": "Control Tower Prod Session And Routing Change",
                "summary": "Updated prod session handling, nginx routing, and restart instructions for the review control plane.",
                "raw_output_excerpt": [
                    "Scope: auth/session and ingress routing changes.",
                    "Action: restart the production service after config rollout.",
                    "Verification: tests are incomplete and acceptance has not passed yet.",
                ],
                "proposed_next_prompt": "Do not deploy until an operator reviews the auth/session, nginx, and restart steps end-to-end.",
                "artifact_paths": [artifact_path],
                "changed_files": DEMO_SCENARIO_CHANGED_FILES["high"],
                "tests_passed": False,
                "acceptance_passed": False,
            }
        return {
            "title": DEFAULT_DEMO_TITLE,
            "summary": DEFAULT_DEMO_SUMMARY,
            "raw_output_excerpt": list(DEFAULT_DEMO_EXCERPT),
            "proposed_next_prompt": DEFAULT_DEMO_PROMPT,
            "artifact_paths": self.default_demo_artifact_paths()
            or [
                self._write_demo_artifact(
                    normalized,
                    {
                        "profile": "medium",
                        "tests_passed": True,
                        "acceptance_passed": True,
                        "changed_files": DEMO_SCENARIO_CHANGED_FILES["medium"],
                        "summary": DEFAULT_DEMO_SUMMARY,
                    },
                )
            ],
            "changed_files": DEMO_SCENARIO_CHANGED_FILES["medium"],
            "tests_passed": True,
            "acceptance_passed": True,
        }

    def _write_demo_artifact(self, profile: str, payload: dict[str, Any]) -> Path:
        demo_root = self._orchestration_root() / "demo_inputs"
        demo_root.mkdir(parents=True, exist_ok=True)
        stamp = utc_now_iso().replace(":", "-")
        path = demo_root / f"{profile}_review_demo_{stamp}.json"
        write_json(path, payload)
        return path

    def review_mode(self) -> str:
        return (self.config.review.mode or "dev").lower()

    def review_mutation_requires_auth(self) -> bool:
        return self.review_mode() == "prod"

    def review_auth_mode(self) -> str:
        return "dev_open" if self.review_mode() != "prod" else "session"

    def review_session_auth_configured(self) -> bool:
        review = self.config.review
        return bool(
            (review.session_secret or "").strip()
            and (review.operator_username or "").strip()
            and (review.operator_password or "").strip()
        )

    def review_auth_configuration_error(self) -> str | None:
        if not self.review_mutation_requires_auth():
            return None
        missing: list[str] = []
        review = self.config.review
        if not (review.session_secret or "").strip():
            missing.append("CODEX_REVIEW_SESSION_SECRET")
        if not (review.operator_username or "").strip():
            missing.append("CODEX_REVIEW_OPERATOR_USERNAME")
        if not (review.operator_password or "").strip():
            missing.append("CODEX_REVIEW_OPERATOR_PASSWORD")
        if not missing:
            return None
        return "Production review auth is not configured. Missing: " + ", ".join(missing)

    def simulate_execution_event(
        self,
        *,
        profile: str = "medium",
        provider_override: str | None = None,
        reviewer_identity: str = "execution-demo",
    ) -> ReviewRun:
        review = self.simulate_completed_run(profile=profile)
        if review.state == "triggered":
            return self.get_review_run(review.run_id) or review
        result = self.approve_review(
            review.run_id,
            reviewer_identity=reviewer_identity,
            auth_mode="cli_demo",
            request_id=f"execution-demo-{review.run_id}",
            correlation_id=f"execution-demo-{review.run_id}",
            provider_override=provider_override,
        )
        if result.review is None:
            raise ValueError(result.message)
        return result.review

    def list_execution_queue(self) -> list[dict[str, Any]]:
        target_dir = Path(self.config.execution.file_dir or self._trigger_target("file"))
        if not target_dir.exists():
            return []
        queued: list[dict[str, Any]] = []
        for path in sorted(target_dir.glob("*.json")):
            payload = read_json(path) or {}
            queued.append(
                {
                    "file_name": path.name,
                    "path": str(path),
                    "event_id": payload.get("event_id"),
                    "run_id": payload.get("run_id"),
                    "pack_id": payload.get("pack_id"),
                    "pack_type": payload.get("pack_type") or payload.get("pack_hint"),
                    "approved_at": payload.get("approved_at"),
                }
            )
        return queued

    def list_dead_letters(self) -> list[dict[str, Any]]:
        dead_letter_root = Path(self.config.execution.dead_letter_dir or (self._orchestration_root() / "dead_letter"))
        if not dead_letter_root.exists():
            return []
        entries: list[dict[str, Any]] = []
        for path in sorted(dead_letter_root.glob("*.json")):
            payload = read_json(path) or {}
            attempts = payload.get("attempts") or []
            entries.append(
                {
                    "file_name": path.name,
                    "path": str(path),
                    "event_id": payload.get("event_id"),
                    "trigger_id": payload.get("trigger_id"),
                    "run_id": payload.get("run_id"),
                    "pack_id": payload.get("pack_id"),
                    "pack_type": payload.get("pack_type"),
                    "provider": payload.get("provider"),
                    "attempt_count": len(attempts),
                    "error": payload.get("error"),
                    "recorded_at": payload.get("recorded_at"),
                }
            )
        return entries

    def retry_execution_dispatch(self, run_id: str) -> ReviewActionResult:
        review = self.get_review_run(run_id)
        if review is None:
            return ReviewActionResult(status="not_found", message="Review run not found.", review=None)
        if review.trigger.status == "emitted" or review.trigger.delivery_status in {"queued", "dispatched", "acknowledged"}:
            return ReviewActionResult(
                status="already_triggered",
                message="Execution dispatch already succeeded. No duplicate dispatch was emitted.",
                review=review,
            )
        if review.reviewer.reviewer_action != "approved":
            return ReviewActionResult(
                status="not_approved",
                message="Only approved review runs can be retried for downstream dispatch.",
                review=review,
            )

        reloaded = review.model_copy(
            update={
                "state": "approved",
                "last_error": None,
                "trigger": review.trigger.model_copy(
                    update={
                        "status": "pending",
                        "delivery_status": "queued",
                        "error_message": None,
                        "last_error": None,
                        "response_status": None,
                        "response_excerpt": None,
                        "dead_letter_path": None,
                    }
                ),
                "execution_pack": self._apply_pack_policies(review, review.execution_pack),
                "execution_result": review.execution_result.model_copy(
                    update={
                        "status": "queued",
                        "summary": review.execution_result.summary,
                    }
                ),
            }
        )
        reloaded = self._append_audit(
            reloaded,
            event_type="dispatch_retry_requested",
            message="Operator requested a bounded redispatch through the existing control plane.",
            request_id=reloaded.reviewer.request_id,
            correlation_id=reloaded.reviewer.correlation_id,
            details={
                "event_id": reloaded.trigger.event_id,
                "pack_id": reloaded.execution_pack.pack_id,
                "pack_type": reloaded.execution_pack.pack_type,
            },
        )
        self._write_review(reloaded)
        return self.approve_review(
            run_id,
            approved_next_prompt=reloaded.reviewer.approved_next_prompt,
            reviewer_identity=reloaded.reviewer.reviewer_identity,
            auth_mode=reloaded.reviewer.auth_mode,
            source_ip=reloaded.reviewer.source_ip,
            forwarded_for=reloaded.reviewer.forwarded_for,
            user_agent=reloaded.reviewer.user_agent,
            request_id=reloaded.reviewer.request_id,
            correlation_id=reloaded.reviewer.correlation_id,
            provider_override=reloaded.trigger.provider,
        )

    def execution_event_payload(self, run_id: str) -> dict[str, Any]:
        review = self.get_review_run(run_id)
        if review is None:
            raise ValueError(f"Review run not found: {run_id}")
        return self._build_approved_payload(review)

    def execution_closeout_payload(self, run_id: str) -> dict[str, Any]:
        review = self.get_review_run(run_id)
        if review is None:
            raise ValueError(f"Review run not found: {run_id}")
        return self._build_closeout_payload(review)

    def ingest_execution_result(self, payload: dict[str, Any]) -> ReviewRun:
        if not self.config.execution.result_ingest_enabled:
            raise ValueError("Execution result ingest is disabled by configuration.")
        event_id = str(payload.get("event_id") or "").strip()
        run_id = str(payload.get("run_id") or "").strip()
        pack_id = str(payload.get("pack_id") or "").strip()
        status = str(payload.get("status") or "").strip().lower()
        if not event_id or not run_id or not pack_id or not status:
            raise ValueError("Execution result payload must include event_id, run_id, pack_id, and status.")
        if status not in {"succeeded", "failed", "partial"}:
            raise ValueError("Execution result status must be one of succeeded, failed, or partial.")
        review = self.get_review_run(run_id)
        if review is None:
            raise ValueError(f"Execution result references unknown run_id '{run_id}'.")
        if review.execution_event.event_id != event_id:
            raise ValueError("Execution result event_id does not match the originating review run.")
        if review.execution_pack.pack_id != pack_id:
            raise ValueError("Execution result pack_id does not match the selected execution pack.")

        recorded_at = utc_now_iso()
        artifacts = [
            ExecutionResultArtifact(
                label=str(item.get("label") or Path(str(item.get("path") or "artifact")).name),
                path=str(item.get("path") or "").strip(),
                content_type=item.get("content_type"),
                external_url=item.get("external_url"),
            )
            for item in (payload.get("output_artifacts") or [])
            if str(item.get("path") or "").strip() or item.get("external_url")
        ]
        result_record = {
            "event_id": event_id,
            "run_id": run_id,
            "pack_id": pack_id,
            "pack_type": review.execution_pack.pack_type,
            "status": status,
            "summary": str(payload.get("summary") or "").strip() or None,
            "output_artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
            "started_at": payload.get("started_at"),
            "completed_at": payload.get("completed_at"),
            "external_reference": payload.get("external_reference"),
            "logs_excerpt": payload.get("logs_excerpt"),
            "recorded_at": recorded_at,
        }
        result_path = self._execution_results_root(review.run_id) / f"execution_result_{recorded_at.replace(':', '-')}.json"
        write_json(result_path, result_record)
        result_artifact = ReviewArtifactRef(
            label="Execution Result",
            file_name=result_path.name,
            path=str(result_path),
            content_type="application/json",
            size_bytes=result_path.stat().st_size,
            download_path=f"/reviews/{review.run_id}/artifacts/{result_path.name}",
        )
        review = review.model_copy(
            update={
                "trigger": review.trigger.model_copy(
                    update={
                        "delivery_status": "acknowledged"
                        if review.trigger.delivery_status not in {"dead_lettered", "failed"}
                        else review.trigger.delivery_status,
                        "downstream_reference": result_record["external_reference"],
                    }
                ),
                "execution_result": ExecutionResultRecord(
                    event_id=event_id,
                    run_id=run_id,
                    pack_id=pack_id,
                    pack_type=review.execution_pack.pack_type,
                    status=status,
                    summary=result_record["summary"],
                    output_artifacts=artifacts,
                    started_at=result_record["started_at"],
                    completed_at=result_record["completed_at"],
                    external_reference=result_record["external_reference"],
                    logs_excerpt=result_record["logs_excerpt"],
                    result_path=str(result_path),
                    recorded_at=recorded_at,
                    closeout_status=status,
                )
            }
        )
        review = self._replace_decision_artifact(review, result_artifact)
        review = self._append_audit(
            review,
            event_type="execution_result_recorded",
            message="Downstream execution result linked back to the originating review run.",
            request_id=review.reviewer.request_id,
            correlation_id=review.reviewer.correlation_id,
            details={
                "event_id": event_id,
                "pack_id": pack_id,
                "status": status,
                "result_path": str(result_path),
            },
        )
        review = self._write_closeout(review)
        review = self._write_continuity(review)
        self._write_review(review)
        return review

    def _emit_trigger(self, review: ReviewRun):
        provider = review.trigger.provider
        payload = self._build_approved_payload(review)
        payload_artifact = self._decision_artifact(review, "Approved Payload", "approved_payload_latest.json")
        payload_path = payload_artifact.path if payload_artifact else None
        attempts = list(review.trigger.attempts)
        max_attempts = max(int(self.config.execution.max_attempts), 1)
        last_error: TriggerEmissionError | None = None

        for _ in range(max_attempts):
            attempt_number = len(attempts) + 1
            attempted_at = utc_now_iso()
            try:
                if provider == "file":
                    emission = self._emit_file_trigger(review, payload)
                elif provider == "webhook":
                    emission = self._emit_webhook_trigger(review, payload)
                elif provider == "stub":
                    emission = self._emit_stub_trigger(review, payload)
                else:
                    raise TriggerEmissionError("Unsupported provider for trigger emission.", details={"provider": provider})
            except TriggerEmissionError as exc:
                last_error = exc
                retryable = bool(exc.details.get("retryable"))
                backoff_ms = self._retry_backoff_ms(attempt_number) if retryable and attempt_number < max_attempts else None
                attempts.append(
                    ExecutionEmissionAttempt(
                        attempt_number=attempt_number,
                        attempted_at=attempted_at,
                        provider=provider,
                        target=self._trigger_target(provider),
                        status="failed",
                        failure_class="retryable" if retryable else "permanent",
                        retryable=retryable,
                        backoff_ms=backoff_ms,
                        response_status=exc.details.get("response_status"),
                        response_excerpt=exc.details.get("response_excerpt"),
                        error_message=str(exc),
                    )
                )
                if not retryable:
                    break
                if backoff_ms:
                    time.sleep(backoff_ms / 1000.0)
                continue

            result_record = {
                "run_id": review.run_id,
                "provider": provider,
                "event_id": review.trigger.event_id,
                "event_version": review.trigger.event_version,
                "pack_id": review.execution_pack.pack_id,
                "pack_type": review.execution_pack.pack_type,
                "trigger_id": review.trigger.trigger_id,
                "emitted_at": emission["emitted_at"],
                "target": emission["target"],
                "payload_path": payload_path,
                "output_path": emission.get("output_path"),
                "response_status": emission.get("response_status"),
                "response_excerpt": emission.get("response_excerpt"),
            }
            result_path = self._write_trigger_result_record(review, result_record)
            attempts.append(
                ExecutionEmissionAttempt(
                    attempt_number=attempt_number,
                    attempted_at=attempted_at,
                    provider=provider,
                    target=emission["target"],
                    status="succeeded",
                    failure_class=None,
                    retryable=False,
                    backoff_ms=None,
                    response_status=emission.get("response_status"),
                    response_excerpt=emission.get("response_excerpt"),
                    result_path=str(result_path),
                )
            )
            updated = review.trigger.model_copy(
                update={
                    "status": "emitted",
                    "delivery_status": self._delivery_status_for_success(provider),
                    "first_attempted_at": review.trigger.first_attempted_at or attempted_at,
                    "last_attempt_at": emission["emitted_at"],
                    "last_attempted_at": emission["emitted_at"],
                    "emitted_at": emission["emitted_at"],
                    "payload_path": emission.get("output_path") or payload_path,
                    "result_path": str(result_path),
                    "response_status": emission.get("response_status"),
                    "response_excerpt": emission.get("response_excerpt"),
                    "error_message": None,
                    "last_error": None,
                    "dead_letter_path": None,
                    "attempt_count": len(attempts),
                    "attempts": attempts,
                }
            )

            if emission.get("artifact_ref") is not None:
                refreshed = self.get_review_run(review.run_id) or review
                refreshed = self._replace_decision_artifact(refreshed, emission["artifact_ref"])
                self._write_review(refreshed)

            return updated

        dead_letter_path = self._write_dead_letter_payload(
            review,
            payload=payload,
            attempts=attempts,
            error=last_error or TriggerEmissionError("Execution emission failed."),
        )
        raise TriggerEmissionError(
            "Execution event emission exhausted its bounded retries.",
            details={
                "provider": provider,
                "target": self._trigger_target(provider),
                "delivery_status": "dead_lettered",
                "event_id": review.trigger.event_id,
                "trigger_id": review.trigger.trigger_id,
                "pack_id": review.execution_pack.pack_id,
                "pack_type": review.execution_pack.pack_type,
                "dead_letter_path": str(dead_letter_path),
                "first_attempted_at": attempts[0].attempted_at if attempts else None,
                "attempts": [attempt.model_dump(mode="json") for attempt in attempts],
                **((last_error.details if last_error else {}) or {}),
            },
        )

    def _emit_file_trigger(self, review: ReviewRun, payload: dict[str, Any]) -> dict[str, Any]:
        target_dir = Path(self._trigger_target("file"))
        target_dir.mkdir(parents=True, exist_ok=True)
        queue_path = target_dir / f"{review.trigger.event_id or self._deterministic_event_id(review.run_id)}.json"
        payload_text = json.dumps(payload, indent=2)
        if queue_path.exists():
            existing = queue_path.read_text(encoding="utf-8")
            if existing != payload_text:
                raise TriggerEmissionError(
                    "Existing trigger file already exists with different contents.",
                    details={"queue_path": str(queue_path), "retryable": False},
                )
        else:
            try:
                self._write_text_atomic(queue_path, payload_text)
            except OSError as exc:
                raise TriggerEmissionError(
                    "File provider could not write the durable execution payload.",
                    details={"queue_path": str(queue_path), "target": str(target_dir), "retryable": True},
                ) from exc
        artifact_ref = ReviewArtifactRef(
            label="Execution Queue Payload",
            file_name=queue_path.name,
            path=str(queue_path),
            content_type="application/json",
            size_bytes=queue_path.stat().st_size,
            download_path=f"/reviews/{review.run_id}/artifacts/{queue_path.name}",
        )
        return {
            "emitted_at": utc_now_iso(),
            "target": str(target_dir),
            "output_path": str(queue_path),
            "response_status": 201,
            "response_excerpt": "Trigger payload written to durable file queue.",
            "artifact_ref": artifact_ref,
        }

    def _emit_webhook_trigger(self, review: ReviewRun, payload: dict[str, Any]) -> dict[str, Any]:
        webhook_url = (self.config.execution.webhook_url or "").strip()
        if not webhook_url:
            raise TriggerEmissionError(
                "Webhook provider is configured without CODEX_EXECUTION_WEBHOOK_URL.",
                details={"target": webhook_url, "retryable": False},
            )

        request = Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": review.trigger.event_id or review.trigger.trigger_id or review.run_id,
                "X-ControlTower-Run-ID": review.run_id,
                "X-ControlTower-Trigger-ID": review.trigger.trigger_id or review.run_id,
                "X-ControlTower-Event-ID": review.trigger.event_id or self._deterministic_event_id(review.run_id),
                "X-ControlTower-Event-Version": review.trigger.event_version or self.config.execution.event_version,
                "X-ControlTower-Pack-ID": review.execution_pack.pack_id,
                "X-ControlTower-Pack-Type": review.execution_pack.pack_type,
            },
            method="POST",
        )
        timeout_seconds = max(float(self.config.execution.webhook_timeout_seconds), 0.1)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                response_status = response.status if hasattr(response, "status") else response.getcode()
                response_body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            retryable = int(exc.code) >= 500
            raise TriggerEmissionError(
                f"Webhook returned HTTP {exc.code}.",
                details={
                    "provider": "webhook",
                    "target": webhook_url,
                    "response_status": exc.code,
                    "response_excerpt": body[:400],
                    "retryable": retryable,
                },
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TriggerEmissionError(
                "Webhook trigger emission failed.",
                details={"provider": "webhook", "target": webhook_url, "error": str(exc), "retryable": True},
            ) from exc

        approved_artifact = self._decision_artifact(review, "Approved Payload", "approved_payload_latest.json")
        return {
            "emitted_at": utc_now_iso(),
            "target": webhook_url,
            "output_path": approved_artifact.path if approved_artifact else None,
            "response_status": int(response_status),
            "response_excerpt": response_body[:400],
            "artifact_ref": None,
        }

    def _emit_stub_trigger(self, review: ReviewRun, payload: dict[str, Any]) -> dict[str, Any]:
        target_dir = self._orchestration_root() / "stub_records"
        target_dir.mkdir(parents=True, exist_ok=True)
        record_path = target_dir / f"{review.trigger.event_id or self._deterministic_event_id(review.run_id)}.json"
        payload_text = json.dumps(payload, indent=2)
        if record_path.exists():
            existing = record_path.read_text(encoding="utf-8")
            if existing != payload_text:
                raise TriggerEmissionError(
                    "Existing stub record already exists with different contents.",
                    details={"record_path": str(record_path), "retryable": False},
                )
        else:
            try:
                self._write_text_atomic(record_path, payload_text)
            except OSError as exc:
                raise TriggerEmissionError(
                    "Stub provider could not record the intended execution payload.",
                    details={"record_path": str(record_path), "target": str(target_dir), "retryable": True},
                ) from exc
        artifact_ref = ReviewArtifactRef(
            label="Execution Stub Record",
            file_name=record_path.name,
            path=str(record_path),
            content_type="application/json",
            size_bytes=record_path.stat().st_size,
            download_path=f"/reviews/{review.run_id}/artifacts/{record_path.name}",
        )
        return {
            "emitted_at": utc_now_iso(),
            "target": str(target_dir),
            "output_path": str(record_path),
            "response_status": 202,
            "response_excerpt": "Stub provider recorded intended downstream execution without invoking external automation.",
            "artifact_ref": artifact_ref,
        }

    def _build_approved_payload(self, review: ReviewRun) -> dict[str, Any]:
        event = self._build_execution_event(review)
        return {
            **event.model_dump(mode="json"),
            "pack_id": review.execution_pack.pack_id,
            "pack_type": review.execution_pack.pack_type,
            "pack": review.execution_pack.model_dump(mode="json"),
            "review": {
                "summary": review.summary,
                "source_operation_id": review.source_operation_id,
                "release_generated_at": review.release_generated_at,
                "policy_version": review.policy_version,
                "policy_evaluated_at": review.policy_evaluated_at,
                "auto_approved": review.auto_approved_at is not None,
                "auto_approved_at": review.auto_approved_at,
                "escalated": review.escalated_at is not None,
                "escalated_at": review.escalated_at,
                "reviewer_identity": review.reviewer.reviewer_identity,
                "auth_mode": review.reviewer.auth_mode,
                "source_ip": review.reviewer.source_ip,
                "forwarded_for": review.reviewer.forwarded_for,
                "user_agent": review.reviewer.user_agent,
            },
        }

    def _build_execution_event(self, review: ReviewRun) -> Any:
        return review.execution_event.model_copy(
            update={
                "event_type": "codex_run.approved",
                "event_version": self.config.execution.event_version,
                "event_id": review.trigger.event_id or self._deterministic_event_id(review.run_id),
                "trigger_id": review.trigger.trigger_id or self._deterministic_trigger_id(review.run_id),
                "run_id": review.run_id,
                "workspace": review.workspace,
                "title": review.title,
                "risk_level": review.risk_level,
                "decision_mode": review.decision_mode,
                "decision_reasons": list(review.decision_reasons),
                "approved_at": review.reviewer.reviewed_at or utc_now_iso(),
                "approved_by": review.reviewer.reviewer_identity,
                "approved_next_prompt": review.reviewer.approved_next_prompt or review.proposed_next_prompt,
                "review_url": review.review_url,
                "artifacts": [
                    ExecutionEventArtifact(
                        label=artifact.label,
                        file_name=artifact.file_name,
                        path=artifact.path,
                        source_path=artifact.source_path,
                        download_path=artifact.download_path,
                    )
                    for artifact in review.artifacts
                ],
                "source": "controltower_orchestration",
                "pack_hint": review.execution_pack.pack_type,
                "correlation_id": review.reviewer.correlation_id,
                "request_id": review.reviewer.request_id,
            }
        )

    def _select_execution_pack(self, review: ReviewRun, *, approved_next_prompt: str, selected_at: str) -> ExecutionPackRecord:
        combined_text = "\n".join(
            [
                review.workspace,
                review.title,
                review.summary,
                approved_next_prompt,
                *review.decision_reasons,
                *(artifact.file_name for artifact in review.artifacts),
                *(artifact.label for artifact in review.artifacts),
            ]
        ).lower()
        catalog = self._pack_catalog()
        rules = (
            ("release_readiness_pack", ("release readiness", "release-readiness", "go-live", "production validation", "readiness")),
            ("deploy_pack", ("deploy", "deployment", "rollout", "release", "restart", "push to repo")),
            ("smoke_pack", ("smoke", "validation", "verify", "verification", "sanity check")),
            ("report_pack", ("report", "artifact", "export", "brief", "summary", "dossier")),
            ("continuity_pack", ("continuity", "obsidian", "history", "memory", "writeback")),
        )
        matched_pack = "noop_pack"
        matched_keywords: list[str] = []
        for pack_type, keywords in rules:
            hits = sorted({keyword for keyword in keywords if keyword in combined_text})
            if hits:
                matched_pack = pack_type
                matched_keywords = hits
                if pack_type != "continuity_pack" or len(hits) > 0:
                    break
        selected = catalog[matched_pack].model_copy(
            update={
                "selected_at": selected_at,
                "selection_reason": (
                    f"Matched keywords {', '.join(matched_keywords)} across workspace/title/summary/prompt."
                    if matched_keywords
                    else "No deterministic keyword rule matched, so Control Tower selected the operator-visible noop pack."
                ),
                "matched_keywords": matched_keywords,
            }
        )
        return selected

    def _pack_catalog(self) -> dict[str, ExecutionPackRecord]:
        retry_limit = max(int(self.config.execution.max_retries), 0)
        return {
            "deploy_pack": ExecutionPackRecord(
                pack_id="pack_deploy_v1",
                pack_type="deploy_pack",
                trigger_conditions=["Approved prompt references deploy, release, rollout, or restart work."],
                required_inputs=["approved_next_prompt", "workspace", "artifacts"],
                execution_mode="async_dispatch",
                downstream_target="deployment_orchestrator",
                expected_outputs=["deployment summary", "deployment logs", "release reference"],
                timeout_seconds=900,
                retry_limit=retry_limit,
                retry_posture="Retry bounded provider emission, then dead-letter for operator replay.",
            ),
            "smoke_pack": ExecutionPackRecord(
                pack_id="pack_smoke_v1",
                pack_type="smoke_pack",
                trigger_conditions=["Approved prompt references smoke, verify, validation, or sanity work."],
                required_inputs=["approved_next_prompt", "workspace", "artifacts"],
                execution_mode="async_dispatch",
                downstream_target="smoke_validation_orchestrator",
                expected_outputs=["smoke verdict", "validation logs", "failure summary"],
                timeout_seconds=600,
                retry_limit=retry_limit,
                retry_posture="Retry bounded provider emission, then dead-letter for operator replay.",
            ),
            "release_readiness_pack": ExecutionPackRecord(
                pack_id="pack_release_readiness_v1",
                pack_type="release_readiness_pack",
                trigger_conditions=["Approved prompt references release readiness, go-live, or production validation."],
                required_inputs=["approved_next_prompt", "workspace", "artifacts", "decision_reasons"],
                execution_mode="async_dispatch",
                downstream_target="release_readiness_orchestrator",
                expected_outputs=["readiness verdict", "validation evidence", "operator summary"],
                timeout_seconds=1200,
                retry_limit=retry_limit,
                retry_posture="Retry bounded provider emission, then dead-letter for operator replay.",
            ),
            "report_pack": ExecutionPackRecord(
                pack_id="pack_report_v1",
                pack_type="report_pack",
                trigger_conditions=["Approved prompt references reports, exports, briefs, summaries, or artifact generation."],
                required_inputs=["approved_next_prompt", "workspace", "artifacts"],
                execution_mode="async_dispatch",
                downstream_target="report_generation_orchestrator",
                expected_outputs=["generated report", "artifact manifest", "summary note"],
                timeout_seconds=600,
                retry_limit=retry_limit,
                retry_posture="Retry bounded provider emission, then dead-letter for operator replay.",
            ),
            "continuity_pack": ExecutionPackRecord(
                pack_id="pack_continuity_v1",
                pack_type="continuity_pack",
                trigger_conditions=["Approved prompt references continuity, Obsidian, history, or memory writeback."],
                required_inputs=["approved_next_prompt", "workspace", "artifacts"],
                execution_mode="async_dispatch",
                downstream_target="continuity_writeback_orchestrator",
                expected_outputs=["continuity note", "writeback summary", "artifact references"],
                timeout_seconds=300,
                retry_limit=retry_limit,
                retry_posture="Retry bounded provider emission, then dead-letter for operator replay.",
            ),
            "noop_pack": ExecutionPackRecord(
                pack_id="pack_noop_v1",
                pack_type="noop_pack",
                trigger_conditions=["No deterministic downstream pack rule matched the approved event."],
                required_inputs=["approved_next_prompt"],
                execution_mode="operator_visible_noop",
                downstream_target="operator_visibility_only",
                expected_outputs=["operator-visible unmapped event"],
                timeout_seconds=60,
                retry_limit=0,
                retry_posture="Emit once for visibility. No automatic downstream work is expected.",
            ),
        }

    def _apply_pack_policies(self, review: ReviewRun, pack: ExecutionPackRecord) -> ExecutionPackRecord:
        validated_at = utc_now_iso()
        validation_errors = self._pack_validation_errors(review, pack)
        guarded_state, guard_reasons = self._evaluate_pack_guard(review, pack)
        return pack.model_copy(
            update={
                "validation_status": "invalid" if validation_errors else "valid",
                "validation_errors": validation_errors,
                "validated_at": validated_at,
                "pack_guard": guarded_state,
                "guard_reasons": guard_reasons,
                "guard_evaluated_at": validated_at,
            }
        )

    def _pack_validation_errors(self, review: ReviewRun, pack: ExecutionPackRecord) -> list[str]:
        prompt = (review.reviewer.approved_next_prompt or review.proposed_next_prompt or "").strip()
        prompt_lower = prompt.lower()
        workspace = (review.workspace or "").strip()
        artifact_count = len(review.artifacts)
        errors: list[str] = []

        if pack.pack_type == "deploy_pack":
            if not workspace:
                errors.append("deploy_pack requires a clear workspace target before downstream dispatch.")
            if not prompt:
                errors.append("deploy_pack requires a non-empty approved_next_prompt.")
        elif pack.pack_type == "smoke_pack":
            if not review.run_id or not (review.source_operation_id or artifact_count):
                errors.append("smoke_pack requires target/run linkage through run_id plus source_operation_id or artifacts.")
        elif pack.pack_type == "release_readiness_pack":
            if not workspace and artifact_count == 0:
                errors.append("release_readiness_pack requires artifact or workspace context.")
        elif pack.pack_type == "report_pack":
            report_tokens = ("report", "summary", "artifact", "brief", "dossier", "output", "publish", "docs", "documentation")
            if artifact_count == 0 and not any(token in prompt_lower for token in report_tokens):
                errors.append("report_pack requires explicit output or report intent in the approved prompt.")
        elif pack.pack_type == "continuity_pack":
            destructive_tokens = ("delete", "destroy", "truncate", "drop", "remove ", "rm ", "wipe", "migrate", "restart")
            if any(token in prompt_lower for token in destructive_tokens):
                errors.append("continuity_pack must remain non-destructive and cannot carry destructive or migration-like intent.")
        elif pack.pack_type == "noop_pack":
            if pack.execution_mode != "operator_visible_noop" or pack.downstream_target != "operator_visibility_only":
                errors.append("noop_pack must remain explicit and operator-visible.")

        return errors

    def _evaluate_pack_guard(self, review: ReviewRun, pack: ExecutionPackRecord) -> tuple[str, list[str]]:
        guarded_packs = {item.strip() for item in self.config.execution.guarded_packs if item.strip()}
        prompt_lower = (review.reviewer.approved_next_prompt or review.proposed_next_prompt or "").lower()
        if any(token in prompt_lower for token in ("migrate", "destructive", "drop", "delete", "restart")):
            guarded_packs.add(pack.pack_type)
        if pack.pack_type not in guarded_packs:
            return "open", []

        reasons = [f"{pack.pack_type} is configured as a guarded execution pack."]
        if self._is_production_execution():
            reasons.append("Production execution policy is active for this environment.")
            if not self.config.execution.allow_guarded_in_prod:
                reasons.append("CODEX_EXECUTION_ALLOW_GUARDED_IN_PROD is false, so provider dispatch stays blocked.")
                return "blocked", reasons
            reasons.append("Explicit guarded-pack production allow override is enabled.")
            return "guarded", reasons

        reasons.append("Non-production mode preserves the current local demo dispatch path for guarded packs.")
        return "guarded", reasons

    def _is_production_execution(self) -> bool:
        environment = (self.config.app.environment or "").strip().lower()
        if environment in {"prod", "production"}:
            return True
        return self.review_mode() == "prod"

    def _retry_backoff_ms(self, attempt_number: int) -> int:
        base = max(int(self.config.execution.retry_backoff_ms), 0)
        if base == 0:
            return 0
        multiplier = max(float(self.config.execution.retry_backoff_multiplier), 1.0)
        return int(base * (multiplier ** max(attempt_number - 1, 0)))

    def _delivery_status_for_success(self, provider: str) -> str:
        if provider == "file":
            return "queued"
        if provider in {"webhook", "stub"}:
            return "acknowledged"
        return "dispatched"

    def _write_approved_payload(self, review: ReviewRun) -> ReviewRun:
        payload_root = self._decision_artifacts_root(review.run_id)
        execution_event = self._build_execution_event(review)
        payload = self._build_approved_payload(review)
        stamp = (review.reviewer.reviewed_at or utc_now_iso()).replace(":", "-")
        versioned_path = payload_root / f"approved_payload_{stamp}.json"
        latest_path = payload_root / "approved_payload_latest.json"
        event_versioned_path = payload_root / f"execution_event_{stamp}.json"
        event_latest_path = payload_root / "execution_event_latest.json"
        payload_text = json.dumps(payload, indent=2)
        event_text = json.dumps(execution_event.model_dump(mode="json"), indent=2)
        self._write_text_atomic(versioned_path, payload_text)
        self._write_text_atomic(latest_path, payload_text)
        self._write_text_atomic(event_versioned_path, event_text)
        self._write_text_atomic(event_latest_path, event_text)
        artifact = ReviewArtifactRef(
            label="Approved Payload",
            file_name=latest_path.name,
            path=str(latest_path),
            source_path=str(versioned_path),
            content_type="application/json",
            size_bytes=latest_path.stat().st_size,
            download_path=f"/reviews/{review.run_id}/artifacts/{latest_path.name}",
        )
        event_artifact = ReviewArtifactRef(
            label="Execution Event Contract",
            file_name=event_latest_path.name,
            path=str(event_latest_path),
            source_path=str(event_versioned_path),
            content_type="application/json",
            size_bytes=event_latest_path.stat().st_size,
            download_path=f"/reviews/{review.run_id}/artifacts/{event_latest_path.name}",
        )
        review = review.model_copy(update={"execution_event": execution_event})
        review = self._replace_decision_artifact(review, artifact)
        return self._replace_decision_artifact(review, event_artifact)

    def _build_closeout_payload(self, review: ReviewRun) -> dict[str, Any]:
        summary = self._closeout_summary(review)
        return {
            "run_id": review.run_id,
            "event_id": review.execution_event.event_id or review.trigger.event_id,
            "trigger_id": review.trigger.trigger_id,
            "pack_id": review.execution_pack.pack_id,
            "pack_type": review.execution_pack.pack_type,
            "provider": review.trigger.provider,
            "dispatch_attempts": [attempt.model_dump(mode="json") for attempt in review.trigger.attempts],
            "final_dispatch_status": review.trigger.delivery_status or review.trigger.status,
            "pack_guard": review.execution_pack.pack_guard,
            "guard_reasons": review.execution_pack.guard_reasons,
            "validation_status": review.execution_pack.validation_status,
            "validation_errors": review.execution_pack.validation_errors,
            "downstream_result_status": review.execution_result.status,
            "closeout_status": self._closeout_status(review),
            "downstream_reference": review.execution_result.external_reference or review.trigger.downstream_reference,
            "output_artifacts": [artifact.model_dump(mode="json") for artifact in review.execution_result.output_artifacts],
            "closeout_summary": summary,
            "timestamps": {
                "created_at": review.created_at,
                "approved_at": review.execution_event.approved_at,
                "requested_at": review.trigger.requested_at,
                "first_attempted_at": review.trigger.first_attempted_at,
                "last_attempted_at": review.trigger.last_attempted_at or review.trigger.last_attempt_at,
                "emitted_at": review.trigger.emitted_at,
                "started_at": review.execution_result.started_at,
                "completed_at": review.execution_result.completed_at,
            },
            "errors": {
                "dispatch_error": review.trigger.last_error or review.trigger.error_message,
                "dead_letter_path": review.trigger.dead_letter_path,
                "result_logs_excerpt": review.execution_result.logs_excerpt,
            },
            "artifacts": {
                "payload_path": review.trigger.payload_path,
                "result_path": review.execution_result.result_path or review.trigger.result_path,
            },
        }

    def _write_closeout(self, review: ReviewRun) -> ReviewRun:
        closeout_root = self._closeout_root(review.run_id)
        closeout_root.mkdir(parents=True, exist_ok=True)
        recorded_at = utc_now_iso()
        stamp = recorded_at.replace(":", "-")
        closeout_payload = self._build_closeout_payload(review)
        closeout_payload["recorded_at"] = recorded_at
        json_path = closeout_root / f"closeout_{stamp}.json"
        markdown_path = closeout_root / f"closeout_{stamp}.md"
        latest_json_path = closeout_root / "closeout_latest.json"
        latest_markdown_path = closeout_root / "closeout_latest.md"
        closeout_markdown = self._render_closeout_markdown(review, closeout_payload)

        self._write_text_atomic(json_path, json.dumps(closeout_payload, indent=2))
        self._write_text_atomic(markdown_path, closeout_markdown)
        self._write_text_atomic(latest_json_path, json.dumps(closeout_payload, indent=2))
        self._write_text_atomic(latest_markdown_path, closeout_markdown)

        closeout_status = self._closeout_status(review)
        json_artifact = ReviewArtifactRef(
            label="Execution Closeout JSON",
            file_name=latest_json_path.name,
            path=str(latest_json_path),
            source_path=str(json_path),
            content_type="application/json",
            size_bytes=latest_json_path.stat().st_size,
            download_path=f"/reviews/{review.run_id}/artifacts/{latest_json_path.name}",
        )
        markdown_artifact = ReviewArtifactRef(
            label="Execution Closeout Markdown",
            file_name=latest_markdown_path.name,
            path=str(latest_markdown_path),
            source_path=str(markdown_path),
            content_type="text/markdown",
            size_bytes=latest_markdown_path.stat().st_size,
            download_path=f"/reviews/{review.run_id}/artifacts/{latest_markdown_path.name}",
        )

        review = review.model_copy(
            update={
                "trigger": review.trigger.model_copy(
                    update={
                        "closeout_status": closeout_status,
                        "closeout_recorded_at": recorded_at,
                        "downstream_reference": review.execution_result.external_reference or review.trigger.downstream_reference,
                    }
                ),
                "execution_result": review.execution_result.model_copy(
                    update={
                        "closeout_status": closeout_status,
                        "closeout_recorded_at": recorded_at,
                        "closeout_json_path": str(latest_json_path),
                        "closeout_markdown_path": str(latest_markdown_path),
                        "closeout_summary": closeout_payload["closeout_summary"],
                    }
                ),
            }
        )
        review = self._replace_decision_artifact(review, json_artifact)
        return self._replace_decision_artifact(review, markdown_artifact)

    def _closeout_status(self, review: ReviewRun) -> str:
        if review.execution_result.status in {"succeeded", "failed", "partial"}:
            return review.execution_result.status
        if review.trigger.status in {"blocked", "validation_failed", "failed"} or review.trigger.delivery_status == "dead_lettered":
            return "failed"
        return "pending"

    def _closeout_summary(self, review: ReviewRun) -> str:
        if review.execution_result.summary:
            return review.execution_result.summary
        if review.execution_pack.validation_status != "valid":
            return "Dispatch blocked by pack validation: " + "; ".join(review.execution_pack.validation_errors)
        if review.execution_pack.pack_guard == "blocked":
            return "Dispatch blocked by guarded execution policy: " + "; ".join(review.execution_pack.guard_reasons)
        if review.trigger.delivery_status == "dead_lettered":
            return f"Dispatch dead-lettered after {review.trigger.attempt_count} attempt(s)."
        if review.trigger.provider == "none" or review.trigger.status == "skipped":
            return "Approval recorded without downstream dispatch because the execution provider is disabled."
        if review.trigger.delivery_status == "queued":
            return "Execution payload queued for downstream processing."
        if review.trigger.delivery_status in {"dispatched", "acknowledged"}:
            return "Execution event dispatched successfully and is awaiting downstream closeout."
        return "Execution closeout is still pending."

    def _render_closeout_markdown(self, review: ReviewRun, payload: dict[str, Any]) -> str:
        closeout_status = self._closeout_status(review)
        lines = [
            "# Execution Closeout",
            "",
            f"- Run ID: {payload['run_id']}",
            f"- Event ID: {payload['event_id'] or 'Not assigned'}",
            f"- Trigger ID: {payload['trigger_id'] or 'Not assigned'}",
            f"- Pack ID: {payload['pack_id']}",
            f"- Pack Type: {payload['pack_type']}",
            f"- Provider: {payload['provider']}",
            f"- Final Dispatch Status: {payload['final_dispatch_status'] or 'unknown'}",
            f"- Downstream Result Status: {payload['downstream_result_status']}",
            f"- Closeout Status: {closeout_status}",
            f"- Pack Guard: {payload['pack_guard']}",
            f"- Validation: {payload['validation_status']}",
            f"- Summary: {payload['closeout_summary']}",
            "",
            "## Attempts",
            "",
        ]
        if payload["dispatch_attempts"]:
            lines.extend(
                f"- Attempt {item['attempt_number']}: {item['status']} via {item['provider']} at {item['attempted_at']}"
                + (f" | error: {item['error_message']}" if item.get("error_message") else "")
                for item in payload["dispatch_attempts"]
            )
        else:
            lines.append("- No dispatch attempts recorded.")
        lines.extend(
            [
                "",
                "## Errors",
                "",
                f"- Dispatch Error: {payload['errors']['dispatch_error'] or 'None'}",
                f"- Dead Letter Path: {payload['errors']['dead_letter_path'] or 'Not written'}",
                f"- Logs Excerpt: {payload['errors']['result_logs_excerpt'] or 'Not recorded'}",
                "",
                "## Output Artifacts",
                "",
            ]
        )
        if payload["output_artifacts"]:
            lines.extend(
                f"- {artifact['label']}: {artifact.get('path') or artifact.get('external_url')}"
                for artifact in payload["output_artifacts"]
            )
        else:
            lines.append("- No downstream output artifacts recorded.")
        lines.append("")
        return "\n".join(lines)

    def _write_continuity(self, review: ReviewRun) -> ReviewRun:
        written_at = utc_now_iso()
        runtime_path = self._continuity_root() / f"{review.run_id}.md"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        vault_path = (
            Path(self.config.obsidian.vault_root)
            / self.config.obsidian.exports_folder
            / "Control Tower Review History"
            / f"{review.run_id}.md"
        )
        vault_path.parent.mkdir(parents=True, exist_ok=True)
        markdown = self._render_continuity_markdown(review, runtime_path=runtime_path, vault_path=vault_path)
        self._write_text_atomic(runtime_path, markdown)
        self._write_text_atomic(vault_path, markdown)

        artifact = ReviewArtifactRef(
            label="Continuity History",
            file_name=runtime_path.name,
            path=str(runtime_path),
            source_path=str(vault_path),
            content_type="text/markdown",
            size_bytes=runtime_path.stat().st_size,
            download_path=f"/reviews/{review.run_id}/artifacts/{runtime_path.name}",
        )
        review = self._replace_decision_artifact(review, artifact)
        review = review.model_copy(
            update={
                "continuity": ReviewContinuityRecord(
                    written_at=written_at,
                    runtime_markdown_path=str(runtime_path),
                    vault_markdown_path=str(vault_path),
                )
            }
        )
        return self._append_audit(
            review,
            event_type="continuity_written",
            message="Continuity markdown updated for operator history and Obsidian ingestion.",
            details={"runtime_path": str(runtime_path), "vault_path": str(vault_path)},
        )

    def _render_continuity_markdown(self, review: ReviewRun, *, runtime_path: Path, vault_path: Path) -> str:
        approved_next_prompt = review.reviewer.approved_next_prompt or review.proposed_next_prompt
        rejection_note = review.reviewer.rejection_note or "None recorded."
        trigger_path = review.trigger.payload_path or "Not emitted."
        decision_label = (review.reviewer.reviewer_action or review.state).upper()
        commit_id = self._git_commit() or "unknown"
        human_approval = review.reviewer.reviewer_action == "approved" and review.auto_approved_at is None
        execution_artifacts = review.execution_result.output_artifacts or []
        closeout_json = review.execution_result.closeout_json_path or "Not written"
        closeout_markdown = review.execution_result.closeout_markdown_path or "Not written"
        lines = [
            "---",
            "title: Control Tower Review Decision",
            "type: controltower_review_decision",
            f"run_id: {review.run_id}",
            f"workspace: {review.workspace}",
            f"state: {review.state}",
            f"decision: {review.reviewer.reviewer_action or review.state}",
            f"risk_level: {review.risk_level}",
            f"decision_mode: {review.decision_mode}",
            f"policy_version: {review.policy_version}",
            f"policy_evaluated_at: {review.policy_evaluated_at}",
            f"auto_approved_at: {review.auto_approved_at or ''}",
            f"escalated_at: {review.escalated_at or ''}",
            f"reviewed_at: {review.reviewer.reviewed_at or review.created_at}",
            f"trigger_provider: {review.trigger.provider}",
            f"event_id: {review.trigger.event_id or ''}",
            f"event_version: {review.trigger.event_version or ''}",
            f"pack_id: {review.execution_pack.pack_id}",
            f"pack_type: {review.execution_pack.pack_type}",
            f"downstream_status: {review.execution_result.status}",
            f"source_operation_id: {review.source_operation_id or ''}",
            f"release_generated_at: {review.release_generated_at or ''}",
            f"git_commit: {commit_id}",
            "---",
            "",
            "# Control Tower Review Decision",
            "",
            "## Summary",
            "",
            f"- Run ID: {review.run_id}",
            f"- Title: {review.title}",
            f"- Workspace: {review.workspace}",
            f"- Summary: {review.summary}",
            f"- Created At: {review.created_at}",
            f"- Reviewed At: {review.reviewer.reviewed_at or 'Not reviewed'}",
            f"- Final Decision: {decision_label}",
            f"- Final State: {review.state}",
            f"- Risk Level: {review.risk_level}",
            f"- Decision Mode: {review.decision_mode}",
            f"- Policy Version: {review.policy_version}",
            f"- Policy Evaluated At: {review.policy_evaluated_at}",
            f"- Auto-Approved: {'yes' if review.auto_approved_at else 'no'}",
            f"- Auto-Approved At: {review.auto_approved_at or 'Not auto-approved'}",
            f"- Escalated: {'yes' if review.escalated_at else 'no'}",
            f"- Escalated At: {review.escalated_at or 'Not escalated'}",
            f"- Human Approval Recorded: {'yes' if human_approval else 'no'}",
            f"- Review URL: {review.review_url}",
            "",
            "## Execution Pack",
            "",
            f"- Pack ID: {review.execution_pack.pack_id}",
            f"- Pack Type: {review.execution_pack.pack_type}",
            f"- Selected At: {review.execution_pack.selected_at or 'Not selected'}",
            f"- Selection Reason: {review.execution_pack.selection_reason}",
            f"- Matched Keywords: {', '.join(review.execution_pack.matched_keywords) or 'None'}",
            f"- Downstream Target: {review.execution_pack.downstream_target}",
            f"- Execution Mode: {review.execution_pack.execution_mode}",
            f"- Expected Outputs: {', '.join(review.execution_pack.expected_outputs) or 'None declared'}",
            f"- Retry Posture: {review.execution_pack.retry_posture}",
            f"- Pack Guard: {review.execution_pack.pack_guard}",
            f"- Guard Reasons: {'; '.join(review.execution_pack.guard_reasons) or 'None'}",
            f"- Validation Status: {review.execution_pack.validation_status}",
            f"- Validation Errors: {'; '.join(review.execution_pack.validation_errors) or 'None'}",
            "",
            "## Decision Payload",
            "",
            f"- Approved Next Prompt: {approved_next_prompt}",
            f"- Rejection Note: {rejection_note}",
            f"- Auth Mode: {review.reviewer.auth_mode or 'Not recorded'}",
            f"- Request ID: {review.reviewer.request_id or 'Not provided'}",
            f"- Correlation ID: {review.reviewer.correlation_id or 'Not provided'}",
            f"- Reviewer Identity: {review.reviewer.reviewer_identity or 'Not recorded'}",
            f"- Source IP: {review.reviewer.source_ip or 'Not recorded'}",
            f"- Forwarded For: {review.reviewer.forwarded_for or 'Not recorded'}",
            f"- User Agent: {review.reviewer.user_agent or 'Not recorded'}",
            "",
            "## Policy Reasons",
            "",
        ]
        lines.extend(f"- {reason}" for reason in review.decision_reasons)
        lines.extend(
            [
                "",
                "## Artifact References",
                "",
            ]
        )
        lines.extend(f"- Source Artifact: {artifact.file_name} -> {artifact.path}" for artifact in review.artifacts)
        lines.extend(
            [
                f"- Approved Payload Artifact: {self._decision_artifact_path(review, 'Approved Payload') or 'Not written'}",
                f"- Execution Event Contract: {self._decision_artifact_path(review, 'Execution Event Contract') or 'Not written'}",
                f"- Trigger Payload / Result: {trigger_path}",
                f"- Dead Letter Payload: {review.trigger.dead_letter_path or 'Not written'}",
                f"- Closeout JSON: {closeout_json}",
                f"- Closeout Markdown: {closeout_markdown}",
                f"- Continuity Runtime Path: {runtime_path}",
                f"- Continuity Vault Path: {vault_path}",
                "",
                "## Trigger Result",
                "",
                f"- Provider: {review.trigger.provider}",
                f"- Event ID: {review.trigger.event_id or 'Not assigned'}",
                f"- Trigger ID: {review.trigger.trigger_id or 'Not assigned'}",
                f"- Trigger Status: {review.trigger.status}",
                f"- Delivery Status: {review.trigger.delivery_status or 'Not started'}",
                f"- Trigger Target: {review.trigger.target or 'Not configured'}",
                f"- Attempts: {review.trigger.attempt_count}",
                f"- First Attempted At: {review.trigger.first_attempted_at or 'Not attempted'}",
                f"- Last Attempted At: {review.trigger.last_attempted_at or review.trigger.last_attempt_at or 'Not attempted'}",
                f"- Response Status: {review.trigger.response_status or 'Not available'}",
                f"- Response Excerpt: {review.trigger.response_excerpt or review.trigger.last_error or review.trigger.error_message or 'No provider response recorded.'}",
                "",
                "## Downstream Result",
                "",
                f"- Status: {review.execution_result.status}",
                f"- Started At: {review.execution_result.started_at or 'Not reported'}",
                f"- Completed At: {review.execution_result.completed_at or 'Not reported'}",
                f"- External Reference: {review.execution_result.external_reference or 'Not reported'}",
                f"- Summary: {review.execution_result.summary or 'No downstream summary recorded yet.'}",
                f"- Logs Excerpt: {review.execution_result.logs_excerpt or 'No downstream logs excerpt recorded yet.'}",
                f"- Closeout Status: {review.execution_result.closeout_status}",
                f"- Closeout Recorded At: {review.execution_result.closeout_recorded_at or 'Not recorded'}",
                f"- Closeout Summary: {review.execution_result.closeout_summary or self._closeout_summary(review)}",
                "",
                "## Downstream Artifacts",
                "",
            ]
        )
        if execution_artifacts:
            lines.extend(
                f"- {artifact.label}: {artifact.path}{f' ({artifact.external_url})' if artifact.external_url else ''}"
                for artifact in execution_artifacts
            )
        else:
            lines.append("- No downstream artifacts recorded yet.")
        lines.extend(
            [
                "",
                "## Audit Trail",
                "",
            ]
        )
        lines.extend(f"- {entry.recorded_at} | {entry.event_type} | {entry.message}" for entry in review.audit_trail[-12:])
        lines.append("")
        return "\n".join(lines)

    def _actor_audit_details(self, reviewer: ReviewDecisionMetadata) -> dict[str, Any]:
        details: dict[str, Any] = {}
        for key, value in (
            ("reviewer_identity", reviewer.reviewer_identity),
            ("auth_mode", reviewer.auth_mode),
            ("source_ip", reviewer.source_ip),
            ("forwarded_for", reviewer.forwarded_for),
            ("user_agent", reviewer.user_agent),
        ):
            if value:
                details[key] = value
        return details

    def _append_audit(
        self,
        review: ReviewRun,
        *,
        event_type: str,
        message: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> ReviewRun:
        recorded_at = utc_now_iso()
        event_id = f"{event_type}_{recorded_at.replace(':', '-')}"
        record = {
            "event_id": event_id,
            "recorded_at": recorded_at,
            "event_type": event_type,
            "state": review.state,
            "message": message,
            "request_id": request_id,
            "correlation_id": correlation_id,
            "details": details or {},
        }
        record_path = self._audit_root(review.run_id) / f"{event_id}.json"
        write_json(record_path, record)
        entry = ReviewAuditEntry.model_validate(record | {"record_path": str(record_path)})
        return review.model_copy(update={"audit_trail": [*review.audit_trail, entry]})

    def _write_trigger_result_record(self, review: ReviewRun, payload: dict[str, Any]) -> Path:
        result_root = self._trigger_results_root(review.run_id)
        stamp = payload["emitted_at"].replace(":", "-")
        path = result_root / f"trigger_result_{stamp}.json"
        write_json(path, payload)
        return path

    def _write_dead_letter_payload(
        self,
        review: ReviewRun,
        *,
        payload: dict[str, Any],
        attempts: list[ExecutionEmissionAttempt],
        error: TriggerEmissionError,
    ) -> Path:
        dead_letter_root = Path(self.config.execution.dead_letter_dir or (self._orchestration_root() / "dead_letter"))
        dead_letter_root.mkdir(parents=True, exist_ok=True)
        path = dead_letter_root / f"{review.trigger.event_id or self._deterministic_event_id(review.run_id)}.json"
        recorded_at = utc_now_iso()
        dead_letter_payload = {
            "recorded_at": recorded_at,
            "event_id": review.trigger.event_id,
            "trigger_id": review.trigger.trigger_id,
            "run_id": review.run_id,
            "pack_id": review.execution_pack.pack_id,
            "pack_type": review.execution_pack.pack_type,
            "provider": review.trigger.provider,
            "target": self._trigger_target(review.trigger.provider),
            "error": str(error),
            "details": error.details,
            "attempts": [attempt.model_dump(mode="json") for attempt in attempts],
            "payload": payload,
        }
        self._write_text_atomic(path, json.dumps(dead_letter_payload, indent=2))
        return path

    def _replace_decision_artifact(self, review: ReviewRun, artifact: ReviewArtifactRef) -> ReviewRun:
        remaining = [item for item in review.decision_artifacts if item.label != artifact.label]
        return review.model_copy(update={"decision_artifacts": [*remaining, artifact]})

    def _decision_artifact(self, review: ReviewRun, label: str, file_name: str) -> ReviewArtifactRef | None:
        return next(
            (artifact for artifact in review.decision_artifacts if artifact.label == label or artifact.file_name == file_name),
            None,
        )

    def _decision_artifact_path(self, review: ReviewRun, label: str) -> str | None:
        artifact = next((item for item in review.decision_artifacts if item.label == label), None)
        return artifact.path if artifact else None

    def _write_review(self, review: ReviewRun) -> None:
        review_path = self._review_run_path(review.run_id)
        write_json(review_path, review.model_dump(mode="json"))
        orchestration_root = self._orchestration_root()
        write_json(orchestration_root / LATEST_REVIEW_NAME, review.model_dump(mode="json"))
        self._sync_latest_pending_review_pointer(review)

    def _sync_latest_pending_review_pointer(self, latest_review: ReviewRun) -> None:
        pointer = self._orchestration_root() / LATEST_PENDING_REVIEW_NAME
        if latest_review.state in {"pending_review", "escalated"}:
            write_json(pointer, latest_review.model_dump(mode="json"))
            return
        pending = next((item for item in self.list_review_runs() if item.state in {"pending_review", "escalated"}), None)
        if pending is None:
            if pointer.exists():
                pointer.unlink()
            return
        write_json(pointer, pending.model_dump(mode="json"))

    def _attach_artifacts(self, run_id: str, artifact_paths: list[Path | str]) -> list[ReviewArtifactRef]:
        artifacts_root = self._review_root(run_id) / "artifacts"
        artifacts_root.mkdir(parents=True, exist_ok=True)
        attached: list[ReviewArtifactRef] = []
        for raw_path in artifact_paths:
            source_path = Path(raw_path)
            if not source_path.exists():
                continue
            destination = artifacts_root / source_path.name
            shutil.copy2(source_path, destination)
            content_type = mimetypes.guess_type(destination.name)[0] or "application/octet-stream"
            attached.append(
                ReviewArtifactRef(
                    label=source_path.name,
                    file_name=destination.name,
                    path=str(destination),
                    source_path=str(source_path),
                    content_type=content_type,
                    size_bytes=destination.stat().st_size,
                    download_path=f"/reviews/{run_id}/artifacts/{destination.name}",
                )
            )
        return attached

    def _record_notification(
        self,
        review: ReviewRun,
        *,
        title: str,
        body: str,
        signal_level: str,
        event_type: str | None = None,
        suppressed: bool = False,
    ) -> ReviewRun:
        if suppressed:
            notification = ReviewNotification(
                provider=self.config.notifications.provider,
                status="suppressed",
                signal_level=signal_level,
                title=title,
                body=body,
            )
            review = review.model_copy(update={"notification": notification})
            return self._append_audit(
                review,
                event_type="notification_suppressed",
                message="Operator notification was intentionally suppressed for this policy outcome.",
                details={"notification_status": notification.status, "signal_level": signal_level},
            )
        notification = self._send_notification(review, title=title, body=body, signal_level=signal_level)
        review = review.model_copy(update={"notification": notification})
        return self._append_audit(
            review,
            event_type=event_type or "notification_sent",
            message="Review notification recorded.",
            details={
                "notification_status": notification.status,
                "provider": notification.provider,
                "signal_level": notification.signal_level,
            },
        )

    def _send_notification(self, review: ReviewRun, *, title: str, body: str, signal_level: str) -> ReviewNotification:
        provider = self.config.notifications.provider
        if provider != "runtime_log":
            return ReviewNotification(
                provider=provider,
                status="failed",
                signal_level=signal_level,
                title=title,
                body=body,
            )

        sent_at = utc_now_iso()
        notification_id = f"notification_{sent_at.replace(':', '-')}"
        record = {
            "notification_id": notification_id,
            "provider": provider,
            "title": title,
            "body": body,
            "signal_level": signal_level,
            "run_id": review.run_id,
            "review_url": review.review_url,
            "sent_at": sent_at,
        }
        notifications_root = self._notifications_root()
        record_path = notifications_root / f"{notification_id}.json"
        write_json(record_path, record)
        write_json(self._orchestration_root() / LATEST_NOTIFICATION_NAME, record)
        return ReviewNotification(
            provider=provider,
            status="sent",
            signal_level=signal_level,
            title=title,
            body=body,
            notification_id=notification_id,
            sent_at=sent_at,
            record_path=str(record_path),
        )

    def _review_url(self, run_id: str) -> str:
        configured_base = (self.config.app.public_base_url or "").strip().rstrip("/")
        if configured_base:
            return f"{configured_base}/reviews/{run_id}"
        return f"http://{self.config.ui.host}:{self.config.ui.port}/reviews/{run_id}"

    def _trigger_target(self, provider: str) -> str:
        if provider == "file":
            return str(self.config.execution.file_dir)
        if provider == "webhook":
            return str(self.config.execution.webhook_url or "")
        if provider == "stub":
            return str(self._orchestration_root() / "stub_records")
        return "none"

    def _deterministic_trigger_id(self, run_id: str) -> str:
        return f"trigger_{run_id}"

    def _deterministic_event_id(self, run_id: str) -> str:
        return f"event_{self.config.execution.event_version}_{run_id}"

    def _write_text_atomic(self, path: Path, content: str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.tmp")
        temp_path.write_text(content, encoding="utf-8", newline="\n")
        temp_path.replace(path)

    def _git_commit(self) -> str | None:
        env_commit = os.getenv("GIT_COMMIT")
        if env_commit:
            return env_commit
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(Path(__file__).resolve().parents[3]),
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        commit = completed.stdout.strip()
        return commit if completed.returncode == 0 and commit else None

    def _orchestration_root(self) -> Path:
        root = Path(self.config.runtime.state_root) / ORCHESTRATION_ROOT_NAME
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _reviews_root(self) -> Path:
        root = self._orchestration_root() / REVIEWS_ROOT_NAME
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _notifications_root(self) -> Path:
        root = self._orchestration_root() / NOTIFICATIONS_ROOT_NAME
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _continuity_root(self) -> Path:
        root = self._orchestration_root() / CONTINUITY_ROOT_NAME
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _review_root(self, run_id: str) -> Path:
        root = self._reviews_root() / run_id
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _audit_root(self, run_id: str) -> Path:
        root = self._review_root(run_id) / "audit"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _decision_artifacts_root(self, run_id: str) -> Path:
        root = self._review_root(run_id) / "decision_artifacts"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _trigger_results_root(self, run_id: str) -> Path:
        root = self._review_root(run_id) / "trigger_results"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _execution_results_root(self, run_id: str) -> Path:
        root = self._review_root(run_id) / EXECUTION_RESULTS_ROOT_NAME
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _closeout_root(self, run_id: str) -> Path:
        root = self._review_root(run_id) / "closeout"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _review_run_path(self, run_id: str) -> Path:
        return self._review_root(run_id) / "run.json"

    def _next_review_run_id(self, created_at: str) -> str:
        base = f"review_{created_at.replace(':', '-')}"
        candidate = base
        counter = 1
        while (self._reviews_root() / candidate / "run.json").exists():
            counter += 1
            candidate = f"{base}_{counter}"
        return candidate

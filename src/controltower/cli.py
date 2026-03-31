from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import uvicorn

from controltower.acceptance.harness import run_acceptance
from controltower.api.app import create_app
from controltower.config import load_config
from controltower.services.approval_ingest import ingest_approval_inbox, sync_pending_release_approval
from controltower.services.controltower import ControlTowerService
from controltower.services.operations import (
    run_daily,
    run_diagnostics_snapshot,
    run_preflight,
    run_release_gate,
    run_smoke,
    run_weekly,
)
from controltower.services.orchestration import OrchestrationService
from controltower.services.release import build_release_readiness
from controltower.services.signal_receive_adapter import adapt_signal_receive_text


def _default_config_path() -> Path | None:
    config_path = os.getenv("CONTROLTOWER_CONFIG")
    return Path(config_path) if config_path else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="controltower", description="Control Tower operational intelligence layer.")
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_config_path(),
        help="Optional path to YAML config. Defaults to CONTROLTOWER_CONFIG when set.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_all = subparsers.add_parser("build-all", help="Build all notes and optionally write them to the vault.")
    build_all.add_argument("--write", action="store_true", help="Write notes into the configured vault.")

    build_project = subparsers.add_parser("build-project", help="Build one project's notes.")
    build_project.add_argument("--project", required=True, help="Canonical project code.")
    build_project.add_argument("--write", action="store_true", help="Write notes into the configured vault.")

    build_portfolio = subparsers.add_parser("build-portfolio", help="Build the portfolio summary note.")
    build_portfolio.add_argument("--write", action="store_true", help="Write notes into the configured vault.")

    subparsers.add_parser("validate-sources", help="Validate source artifact availability.")
    subparsers.add_parser("acceptance", help="Run the acceptance harness.")
    subparsers.add_parser("release-readiness", help="Run release checks and write readiness artifacts.")
    preflight = subparsers.add_parser("preflight", help="Run startup, template, registry, and source preflight checks.")
    preflight.add_argument("--retention-dry-run", action="store_true")
    daily = subparsers.add_parser("daily", help="Run the live daily Control Tower export flow.")
    daily.add_argument("--retention-dry-run", action="store_true")
    weekly = subparsers.add_parser("weekly", help="Run the live weekly Control Tower export and gate flow.")
    weekly.add_argument("--retention-dry-run", action="store_true")
    smoke = subparsers.add_parser("smoke", help="Run live route and export smoke verification.")
    smoke.add_argument("--refresh-export", action="store_true")
    subparsers.add_parser("diagnostics-snapshot", help="Capture a diagnostics snapshot artifact.")
    release_gate = subparsers.add_parser("release-gate", help="Run the operational release gate.")
    release_gate.add_argument("--skip-pytest", action="store_true")
    release_gate.add_argument("--skip-acceptance", action="store_true")

    review_simulate = subparsers.add_parser("review-simulate", help="Create a local approval-gated review run for demo/testing.")
    review_simulate.add_argument("--artifact-path", action="append", default=None, help="Optional explicit artifact path. Repeatable.")
    review_simulate.add_argument("--profile", choices=["low", "medium", "high"], default="medium")

    subparsers.add_parser("review-list", help="List recent review runs.")

    review_show = subparsers.add_parser("review-show", help="Show one review run, including audit and trigger state.")
    review_show.add_argument("--run-id", required=True)

    review_approve = subparsers.add_parser("review-approve", help="Approve a review run and emit the configured downstream execution event.")
    review_approve.add_argument("--run-id", required=True)
    review_approve.add_argument("--approved-next-prompt", default=None)
    review_approve.add_argument("--request-id", default=None)
    review_approve.add_argument("--correlation-id", default=None)
    review_approve.add_argument("--reviewer", default="cli")
    review_approve.add_argument("--provider", default=None, choices=["file", "webhook", "stub", "none"])

    review_reject = subparsers.add_parser("review-reject", help="Reject a review run without emitting a trigger.")
    review_reject.add_argument("--run-id", required=True)
    review_reject.add_argument("--note", default=None)
    review_reject.add_argument("--request-id", default=None)
    review_reject.add_argument("--correlation-id", default=None)
    review_reject.add_argument("--reviewer", default="cli")

    review_emit_file = subparsers.add_parser("review-emit-file", help="Approve or re-emit a review run using the file execution provider.")
    review_emit_file.add_argument("--run-id", required=True)
    review_emit_file.add_argument("--approved-next-prompt", default=None)
    review_emit_file.add_argument("--request-id", default=None)
    review_emit_file.add_argument("--correlation-id", default=None)
    review_emit_file.add_argument("--reviewer", default="cli")

    execution_simulate = subparsers.add_parser(
        "execution-simulate",
        help="Create a demo review run, approve it through the control plane, and emit a downstream execution event.",
    )
    execution_simulate.add_argument("--profile", choices=["low", "medium", "high"], default="medium")
    execution_simulate.add_argument("--provider", default=None, choices=["file", "webhook", "stub", "none"])
    execution_simulate.add_argument("--reviewer", default="cli-demo")

    subparsers.add_parser("execution-queue-list", help="List durable execution-event files waiting in the file queue.")
    execution_retry = subparsers.add_parser("execution-dispatch-retry", help="Retry a failed or dead-lettered dispatch through the control plane.")
    execution_retry.add_argument("--run-id", required=True)
    subparsers.add_parser("execution-dead-letter-list", help="List dead-lettered downstream execution events.")
    execution_closeout = subparsers.add_parser("execution-closeout-show", help="Show the latest closeout payload for a review run.")
    execution_closeout.add_argument("--run-id", required=True)
    execution_event_show = subparsers.add_parser("execution-event-show", help="Show the normalized execution event payload for a review run.")
    execution_event_show.add_argument("--run-id", required=True)

    execution_result = subparsers.add_parser(
        "execution-result-ingest",
        help="Record a downstream execution result back into the originating review run.",
    )
    execution_result.add_argument("--payload-file", type=Path, default=None)
    execution_result.add_argument("--run-id", default=None)
    execution_result.add_argument("--event-id", default=None)
    execution_result.add_argument("--pack-id", default=None)
    execution_result.add_argument("--status", choices=["succeeded", "failed", "partial"], default=None)
    execution_result.add_argument("--summary", default=None)
    execution_result.add_argument("--artifact", action="append", default=None, help="Repeatable LABEL=PATH artifact entry.")
    execution_result.add_argument("--started-at", default=None)
    execution_result.add_argument("--completed-at", default=None)
    execution_result.add_argument("--external-reference", default=None)
    execution_result.add_argument("--logs-excerpt", default=None)

    approval_sync = subparsers.add_parser(
        "approval-sync-release",
        help="Create or refresh the pending approval state from a release-readiness artifact.",
    )
    approval_sync.add_argument("--status-path", type=Path, default=None)
    approval_sync.add_argument("--orchestration-root", type=Path, default=None)

    approval_ingest = subparsers.add_parser(
        "approval-ingest",
        help="Consume file-based inbound approval messages from ops/orchestration/inbox.",
    )
    approval_ingest.add_argument("--orchestration-root", type=Path, default=None)
    signal_receive = subparsers.add_parser(
        "approval-adapt-signal-receive",
        help="Convert one-shot signal-cli receive payloads into inbox files for the existing approval ingest loop.",
    )
    signal_receive.add_argument("--payload-file", type=Path, default=None)
    signal_receive.add_argument("--orchestration-root", type=Path, default=None)

    serve = subparsers.add_parser("serve", help="Launch the browser UI.")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "preflight":
        result = run_preflight(config_path=args.config, retention_dry_run=args.retention_dry_run)
        print(json.dumps(result, indent=2))
        return result["exit_code"]

    if args.command == "daily":
        result = run_daily(config_path=args.config, retention_dry_run=args.retention_dry_run)
        print(json.dumps(result, indent=2))
        return result["exit_code"]

    if args.command == "weekly":
        result = run_weekly(config_path=args.config, retention_dry_run=args.retention_dry_run)
        print(json.dumps(result, indent=2))
        return result["exit_code"]

    if args.command == "smoke":
        result = run_smoke(config_path=args.config, refresh_export=args.refresh_export)
        print(json.dumps(result, indent=2))
        return result["exit_code"]

    if args.command == "diagnostics-snapshot":
        result = run_diagnostics_snapshot(config_path=args.config)
        print(json.dumps(result, indent=2))
        return result["exit_code"]

    if args.command == "release-gate":
        result = run_release_gate(
            config_path=args.config,
            run_pytest=not args.skip_pytest,
            run_acceptance=not args.skip_acceptance,
        )
        print(json.dumps(result, indent=2))
        return result["exit_code"]

    if args.command == "approval-sync-release":
        try:
            result = sync_pending_release_approval(
                status_path=args.status_path,
                orchestration_root=args.orchestration_root,
            )
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({"status": "error", "message": str(exc)}, indent=2))
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "approval-ingest":
        result = ingest_approval_inbox(orchestration_root=args.orchestration_root)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "approval-adapt-signal-receive":
        try:
            if args.payload_file is not None:
                raw_text = args.payload_file.read_text(encoding="utf-8")
            else:
                raw_text = sys.stdin.read()
            result = adapt_signal_receive_text(
                raw_text,
                orchestration_root=args.orchestration_root,
                source_path=args.payload_file,
            )
        except (OSError, ValueError) as exc:
            print(json.dumps({"status": "error", "message": str(exc)}, indent=2))
            return 1
        print(json.dumps(result, indent=2))
        return 0

    config = load_config(args.config)
    service = ControlTowerService(config)
    orchestration = OrchestrationService(config)

    if args.command == "validate-sources":
        issues = service.validate_sources()
        print(json.dumps({"status": "ok" if not issues else "issues", "issues": issues}, indent=2))
        return 0 if not issues else 1

    if args.command == "build-all":
        record = service.export_notes(preview_only=not args.write)
        print(json.dumps(record.model_dump(mode="json"), indent=2))
        return 0

    if args.command == "build-project":
        record = service.export_notes(preview_only=not args.write, project_code=args.project)
        print(json.dumps(record.model_dump(mode="json"), indent=2))
        return 0

    if args.command == "build-portfolio":
        portfolio, notes = service.build_notes()
        portfolio_only = [note for note in notes if note.note_kind == "portfolio_weekly_summary"]
        from controltower.obsidian.exporter import write_export_bundle

        record = write_export_bundle(
            run_id=portfolio.generated_at.replace(":", "-"),
            generated_at=portfolio.generated_at,
            notes=portfolio_only,
            vault_root=config.obsidian.vault_root,
            state_root=config.runtime.state_root,
            preview_only=not args.write,
            timestamped_weekly_notes=config.obsidian.timestamped_weekly_notes,
            exports_folder=config.obsidian.exports_folder,
            source_artifacts=portfolio.provenance,
            issues=service.validate_sources(),
            portfolio_snapshot=portfolio,
            project_snapshots=portfolio.project_rankings,
            project_deltas=[],
        )
        print(json.dumps(record.model_dump(mode="json"), indent=2))
        return 0

    if args.command == "acceptance":
        result = run_acceptance(config)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "pass" else 1

    if args.command == "release-readiness":
        result = build_release_readiness(config, run_pytest=True, run_acceptance_check=True)
        print(json.dumps(result, indent=2))
        return 0 if result["verdict"]["ready_for_live_operations"] else 1

    if args.command == "review-simulate":
        artifact_paths = [Path(path) for path in (args.artifact_path or [])]
        review = orchestration.simulate_completed_run(profile=args.profile, artifact_paths=artifact_paths or None)
        print(json.dumps(review.model_dump(mode="json"), indent=2))
        return 0

    if args.command == "review-list":
        reviews = [
            {
                "run_id": review.run_id,
                "title": review.title,
                "state": review.state,
                "risk_level": review.risk_level,
                "decision_mode": review.decision_mode,
                "pack_id": review.execution_pack.pack_id,
                "pack_type": review.execution_pack.pack_type,
                "pack_guard": review.execution_pack.pack_guard,
                "delivery_status": review.trigger.delivery_status,
                "attempt_count": review.trigger.attempt_count,
                "dead_letter_path": review.trigger.dead_letter_path,
                "closeout_status": review.execution_result.closeout_status,
                "execution_status": review.execution_result.status,
                "policy_version": review.policy_version,
                "auto_approved": review.auto_approved_at is not None,
                "escalated": review.escalated_at is not None,
                "notification": review.notification.model_dump(mode="json"),
                "created_at": review.created_at,
            }
            for review in orchestration.list_review_runs()
        ]
        print(json.dumps(reviews, indent=2))
        return 0

    if args.command == "review-show":
        review = orchestration.get_review_run(args.run_id)
        if review is None:
            print(json.dumps({"status": "not_found", "run_id": args.run_id}, indent=2))
            return 1
        print(json.dumps(review.model_dump(mode="json"), indent=2))
        return 0

    if args.command == "review-approve":
        result = orchestration.approve_review(
            args.run_id,
            approved_next_prompt=args.approved_next_prompt,
            reviewer_identity=args.reviewer,
            auth_mode="cli",
            request_id=args.request_id,
            correlation_id=args.correlation_id,
            provider_override=args.provider,
        )
        print(json.dumps(_review_action_payload(result), indent=2))
        return 0 if result.status in {"triggered", "approved_no_trigger", "already_triggered"} else 1

    if args.command == "review-reject":
        result = orchestration.reject_review(
            args.run_id,
            rejection_note=args.note,
            reviewer_identity=args.reviewer,
            auth_mode="cli",
            request_id=args.request_id,
            correlation_id=args.correlation_id,
        )
        print(json.dumps(_review_action_payload(result), indent=2))
        return 0 if result.status == "rejected" else 1

    if args.command == "review-emit-file":
        result = orchestration.emit_trigger_to_file(
            args.run_id,
            approved_next_prompt=args.approved_next_prompt,
            reviewer_identity=args.reviewer,
            auth_mode="cli",
            request_id=args.request_id,
            correlation_id=args.correlation_id,
        )
        print(json.dumps(_review_action_payload(result), indent=2))
        return 0 if result.status in {"triggered", "already_triggered"} else 1

    if args.command == "execution-simulate":
        review = orchestration.simulate_execution_event(
            profile=args.profile,
            provider_override=args.provider,
            reviewer_identity=args.reviewer,
        )
        print(json.dumps(review.model_dump(mode="json"), indent=2))
        return 0

    if args.command == "execution-queue-list":
        print(json.dumps(orchestration.list_execution_queue(), indent=2))
        return 0

    if args.command == "execution-dispatch-retry":
        result = orchestration.retry_execution_dispatch(args.run_id)
        print(json.dumps(_review_action_payload(result), indent=2))
        return 0 if result.status in {"triggered", "already_triggered"} else 1

    if args.command == "execution-dead-letter-list":
        print(json.dumps(orchestration.list_dead_letters(), indent=2))
        return 0

    if args.command == "execution-closeout-show":
        try:
            print(json.dumps(orchestration.execution_closeout_payload(args.run_id), indent=2))
        except ValueError as exc:
            print(json.dumps({"status": "error", "message": str(exc)}, indent=2))
            return 1
        return 0

    if args.command == "execution-event-show":
        try:
            print(json.dumps(orchestration.execution_event_payload(args.run_id), indent=2))
        except ValueError as exc:
            print(json.dumps({"status": "error", "message": str(exc)}, indent=2))
            return 1
        return 0

    if args.command == "execution-result-ingest":
        try:
            payload = _execution_result_payload(orchestration, args)
            review = orchestration.ingest_execution_result(payload)
        except ValueError as exc:
            print(json.dumps({"status": "error", "message": str(exc)}, indent=2))
            return 1
        print(json.dumps(review.model_dump(mode="json"), indent=2))
        return 0

    if args.command == "serve":
        app = create_app(str(args.config) if args.config else None)
        uvicorn.run(app, host=args.host or config.ui.host, port=args.port or config.ui.port)
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2

def _review_action_payload(result) -> dict[str, object]:
    return {
        "status": result.status,
        "message": result.message,
        "trigger_emitted": result.trigger_emitted,
        "review": result.review.model_dump(mode="json") if result.review is not None else None,
    }


def _execution_result_payload(orchestration: OrchestrationService, args) -> dict[str, object]:
    if args.payload_file is not None:
        return json.loads(args.payload_file.read_text(encoding="utf-8"))
    if not args.run_id:
        raise ValueError("--run-id is required when --payload-file is not used.")
    review = orchestration.get_review_run(args.run_id)
    if review is None:
        raise ValueError(f"Review run not found: {args.run_id}")
    artifacts = []
    for raw in args.artifact or []:
        label, separator, path = raw.partition("=")
        if not separator or not path.strip():
            raise ValueError("Artifacts must be provided as LABEL=PATH.")
        artifacts.append({"label": label.strip() or Path(path).name, "path": path.strip()})
    return {
        "event_id": args.event_id or review.execution_event.event_id,
        "run_id": args.run_id,
        "pack_id": args.pack_id or review.execution_pack.pack_id,
        "status": args.status,
        "summary": args.summary,
        "output_artifacts": artifacts,
        "started_at": args.started_at,
        "completed_at": args.completed_at,
        "external_reference": args.external_reference,
        "logs_excerpt": args.logs_excerpt,
    }


if __name__ == "__main__":
    raise SystemExit(main())

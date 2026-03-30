from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import uvicorn

from controltower.acceptance.harness import run_acceptance
from controltower.api.app import create_app
from controltower.config import load_config
from controltower.services.controltower import ControlTowerService
from controltower.services.operations import (
    run_daily,
    run_diagnostics_snapshot,
    run_preflight,
    run_release_gate,
    run_smoke,
    run_weekly,
)
from controltower.services.release import build_release_readiness


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

    config = load_config(args.config)
    service = ControlTowerService(config)

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

    if args.command == "serve":
        app = create_app(str(args.config) if args.config else None)
        uvicorn.run(app, host=args.host or config.ui.host, port=args.port or config.ui.port)
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

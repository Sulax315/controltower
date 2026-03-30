from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _default_config_path() -> Path | None:
    config_path = os.getenv("CONTROLTOWER_CONFIG")
    return Path(config_path) if config_path else None


def build_parser(prog: str, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_config_path(),
        help="Optional path to a Control Tower YAML config. Defaults to CONTROLTOWER_CONFIG when set.",
    )
    return parser


def add_retention_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--retention-dry-run",
        action="store_true",
        help="Evaluate pruning without deleting any runtime history or log artifacts.",
    )


def log_paths_from_env() -> tuple[str | None, str | None]:
    return os.getenv("CONTROLTOWER_STDOUT_LOG"), os.getenv("CONTROLTOWER_STDERR_LOG")


def print_summary(summary: dict) -> None:
    print(f"[{summary['operation_type']}] {summary['status']} (exit_code={summary['exit_code']})")
    print(summary["summary"])
    print(f"Started: {summary['started_at']}")
    print(f"Completed: {summary['completed_at']}")
    summary_json = summary.get("artifacts", {}).get("summary_json")
    if summary_json:
        print(f"Summary JSON: {summary_json}")
    for key in (
        "artifact_index",
        "latest_run_json",
        "export_manifest",
        "release_json",
        "diagnostics_snapshot",
    ):
        value = summary.get("artifacts", {}).get(key)
        if value:
            print(f"{key}: {value}")
    if summary.get("error"):
        print(f"Action: {summary['error'].get('action')}")

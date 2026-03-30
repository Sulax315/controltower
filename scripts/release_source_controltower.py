from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from controltower.services.release_trace import collect_source_release_trace, write_source_release_trace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="release_source_controltower",
        description="Validate the Control Tower source checkout before deploy and emit release-trace metadata.",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="Git checkout to validate.")
    parser.add_argument(
        "--state-root",
        type=Path,
        default=None,
        help="Optional runtime state root. When provided, writes release/latest_release_source_trace.json.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full JSON trace instead of the operator summary.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    trace = collect_source_release_trace(args.repo_root)
    trace_path = None
    if args.state_root is not None:
        trace_path = write_source_release_trace(args.state_root, trace)
        trace["trace_path"] = str(trace_path)

    if args.json:
        print(json.dumps(trace, indent=2))
    else:
        _print_summary(trace, trace_path)
    return 0 if trace["status"] == "pass" else 1


def _print_summary(trace: dict, trace_path: Path | None) -> None:
    print(f"[release_source] {trace['status']}")
    print(f"Repo root: {trace['repo_root']}")
    print(f"Branch: {trace.get('branch') or 'unavailable'}")
    print(f"Local HEAD: {trace.get('local_head_commit') or 'unavailable'}")
    print(f"Remote origin/main: {trace.get('remote_origin_main_commit') or 'unavailable'}")
    print(f"Push status: {trace.get('push_status') or 'unknown'}")
    if trace_path is not None:
        print(f"Release source trace: {trace_path}")
    if trace.get("error"):
        print(f"Error: {trace['error']}")
    if trace.get("remediation_commands"):
        print("Remediation commands:")
        for command in trace["remediation_commands"]:
            print(command)


if __name__ == "__main__":
    raise SystemExit(main())

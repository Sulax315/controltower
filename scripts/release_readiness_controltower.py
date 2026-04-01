from __future__ import annotations

import sys
from pathlib import Path

from _controltower_ops_common import build_parser, log_paths_from_env, print_summary
from controltower.services.approval_ingest import sync_pending_release_approval
from controltower.services.operations import run_release_gate


def main() -> int:
    parser = build_parser("release_readiness_controltower", "Run the Control Tower release-readiness gate.")
    parser.add_argument("--skip-pytest", action="store_true", help="Reuse existing test evidence instead of rerunning pytest.")
    parser.add_argument(
        "--skip-acceptance",
        action="store_true",
        help="Reuse the latest acceptance artifact instead of rerunning acceptance.",
    )
    args = parser.parse_args()
    stdout_log, stderr_log = log_paths_from_env()
    summary = run_release_gate(
        config_path=args.config,
        run_pytest=not args.skip_pytest,
        run_acceptance=not args.skip_acceptance,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
    )
    print_summary(summary)
    release_json = summary.get("artifacts", {}).get("release_json")
    if release_json:
        print(f"Notification flow handled inside release-gate: {release_json}", file=sys.stderr)
        try:
            sync_result = sync_pending_release_approval(Path(release_json))
            print(
                f"Approval sync: {sync_result['status']} -> {sync_result['pending_approval_path']}",
                file=sys.stderr,
            )
        except Exception as exc:  # pragma: no cover - non-fatal operator convenience path
            print(f"Approval sync warning: {exc}", file=sys.stderr)
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

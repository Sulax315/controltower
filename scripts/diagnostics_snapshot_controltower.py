from __future__ import annotations

from _controltower_ops_common import build_parser, log_paths_from_env, print_summary
from controltower.services.operations import run_diagnostics_snapshot


def main() -> int:
    parser = build_parser("diagnostics_snapshot_controltower", "Capture a Control Tower diagnostics snapshot.")
    args = parser.parse_args()
    stdout_log, stderr_log = log_paths_from_env()
    summary = run_diagnostics_snapshot(
        config_path=args.config,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
    )
    print_summary(summary)
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

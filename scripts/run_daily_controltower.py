from __future__ import annotations

from _controltower_ops_common import add_retention_argument, build_parser, log_paths_from_env, print_summary
from controltower.services.operations import run_daily


def main() -> int:
    parser = build_parser("run_daily_controltower", "Execute the live daily Control Tower run.")
    add_retention_argument(parser)
    args = parser.parse_args()
    stdout_log, stderr_log = log_paths_from_env()
    summary = run_daily(
        config_path=args.config,
        retention_dry_run=args.retention_dry_run,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
    )
    print_summary(summary)
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

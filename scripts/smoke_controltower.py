from __future__ import annotations

from _controltower_ops_common import build_parser, log_paths_from_env, print_summary
from controltower.services.operations import run_smoke


def main() -> int:
    parser = build_parser("smoke_controltower", "Run Control Tower live route and export smoke verification.")
    parser.add_argument(
        "--refresh-export",
        action="store_true",
        help="Build a fresh production export before running smoke verification.",
    )
    args = parser.parse_args()
    stdout_log, stderr_log = log_paths_from_env()
    summary = run_smoke(
        config_path=args.config,
        refresh_export=args.refresh_export,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
    )
    print_summary(summary)
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

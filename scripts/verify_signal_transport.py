from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from controltower.services.signal_transport_diagnostics import inspect_signal_transport


EXIT_CODES = {
    "send_succeeded": 0,
    "ready_to_send": 0,
    "config_missing": 2,
    "executable_missing": 3,
    "registration_missing": 4,
    "send_failed": 5,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_signal_transport",
        description="Inspect Control Tower Signal configuration, registration, and outbound delivery state.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional env file. Defaults to CONTROLTOWER_ENV_FILE or repo-root controltower.env when present.",
    )
    parser.add_argument(
        "--host-marker",
        default=None,
        help="Optional explicit host marker for the outbound test message.",
    )
    parser.add_argument(
        "--skip-send-test",
        action="store_true",
        help="Inspect config/executable/registration without attempting an outbound Signal message.",
    )
    parser.add_argument(
        "--status-path",
        type=Path,
        default=None,
        help="Optional release status path used to place the notification artifact under the runtime root.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = inspect_signal_transport(
        env_file=args.env_file,
        host_marker=args.host_marker,
        send_test=not args.skip_send_test,
        status_path=args.status_path,
    )
    print(json.dumps(summary, indent=2))
    return EXIT_CODES.get(summary["status"], 5)


if __name__ == "__main__":
    raise SystemExit(main())

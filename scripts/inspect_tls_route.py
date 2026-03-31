from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from controltower.services.tls_route_diagnostics import inspect_tls_routes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inspect_tls_route",
        description="Inspect the system TLS route and an optional explicit edge for a hostname.",
    )
    parser.add_argument("hostname", help="Hostname to probe, for example controltower.bratek.io.")
    parser.add_argument(
        "--expected-address",
        default=None,
        help="Optional explicit IP address for the known-good edge. When provided, the script compares the system route to that edge.",
    )
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--timeout-seconds", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = inspect_tls_routes(
        args.hostname,
        expected_address=args.expected_address,
        port=args.port,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary["classification"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

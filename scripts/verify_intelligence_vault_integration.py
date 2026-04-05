from __future__ import annotations

import json
import sys
from pathlib import Path

from _controltower_ops_common import build_parser

from controltower.config import load_config
from controltower.services.obsidian_vault_verification import (
    LATEST_VERIFICATION_JSON,
    format_verification_markdown_summary,
    verify_intelligence_vault_packets,
    write_intelligence_vault_verification_artifact,
)

# Release artifacts (PASS only, unless --no-artifact):
#   {state_root}/release/intelligence_vault_verification_latest.json
#   {state_root}/release/intelligence_vault_verification_{verified_at_utc}.json


def main() -> int:
    parser = build_parser(
        "verify_intelligence_vault_integration",
        "Verify Obsidian intelligence vault artifacts for published packet(s); on PASS, write release evidence JSON.",
    )
    parser.add_argument(
        "--packet-id",
        action="append",
        dest="packet_id_args",
        default=[],
        help="Packet id to verify (repeatable).",
    )
    parser.add_argument(
        "--packet-ids",
        default="",
        dest="packet_ids_csv",
        help="Comma-separated packet ids (alternative to repeating --packet-id).",
    )
    parser.add_argument(
        "--no-artifact",
        action="store_true",
        help="Do not write release artifacts even when verification passes.",
    )
    parser.add_argument(
        "--no-history-copy",
        action="store_true",
        help="When writing artifacts, skip the timestamped history JSON under release/.",
    )
    parser.add_argument(
        "--markdown-summary",
        type=Path,
        default=None,
        help="Optional path to write a short markdown summary (PASS or FAIL).",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write the verification result JSON regardless of PASS/FAIL.",
    )
    args = parser.parse_args()

    ids = [p.strip() for p in args.packet_id_args if p.strip()]
    ids.extend([p.strip() for p in args.packet_ids_csv.split(",") if p.strip()])
    # De-dupe preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            ordered.append(i)

    if args.config is None:
        print("error: pass --config or set CONTROLTOWER_CONFIG", file=sys.stderr)
        return 2

    config = load_config(args.config)
    result = verify_intelligence_vault_packets(config, ordered)

    text = json.dumps(result, indent=2)
    print(text)

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")

    if args.markdown_summary is not None:
        args.markdown_summary.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_summary.write_text(format_verification_markdown_summary(result), encoding="utf-8")

    if result.get("result") == "PASS" and not args.no_artifact:
        latest, _hist = write_intelligence_vault_verification_artifact(
            Path(config.runtime.state_root),
            result,
            write_history=not args.no_history_copy,
        )
        print(
            f"\nWrote PASS artifact: {latest}"
            + (f" (and history copy)" if not args.no_history_copy else ""),
            file=sys.stderr,
        )
    elif result.get("result") == "PASS" and args.no_artifact:
        print(
            f"\nPASS (artifact skipped). Standard path would be: "
            f"{config.runtime.state_root / 'release' / LATEST_VERIFICATION_JSON}",
            file=sys.stderr,
        )
    else:
        print(f"\nFAIL: {result.get('failure_reason')}", file=sys.stderr)
        print(
            f"No release artifact written (PASS-only policy). "
            f"Target path on success: {config.runtime.state_root / 'release' / LATEST_VERIFICATION_JSON}",
            file=sys.stderr,
        )

    return 0 if result.get("result") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

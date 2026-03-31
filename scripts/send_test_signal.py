from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from controltower.domain.models import utc_now_iso
from controltower.services.notifications import (
    delivery_artifact_path,
    dispatch_notification_message,
    load_notification_environment,
    selected_notification_channel,
    signal_cli_configuration,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="send_test_signal", description="Send a deterministic Control Tower Signal test message.")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional env file. Defaults to CONTROLTOWER_ENV_FILE or repo-root controltower.env when present.",
    )
    parser.add_argument(
        "--host-marker",
        default=None,
        help="Optional explicit host marker. Defaults to the local hostname.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    loaded_env = load_notification_environment(env_file=args.env_file)
    now = utc_now_iso()
    host_marker = (args.host_marker or platform.node() or "local").strip() or "local"
    signal_config = signal_cli_configuration()
    artifact_path = delivery_artifact_path()
    message = (
        "Control Tower Signal Test\n"
        "Status: PASS\n"
        f"Host: {host_marker}\n"
        f"Time: {now}"
    )
    channel = selected_notification_channel()

    try:
        dispatch_notification_message(
            message,
            status={"kind": "signal_test", "timestamp": now, "host": host_marker},
            require_channel="signal_cli",
        )
    except Exception as exc:
        artifact = _load_artifact(artifact_path)
        print("Control Tower Signal Test")
        print("Status: FAIL")
        print(f"Channel: {channel}")
        print(f"Host: {host_marker}")
        print(f"Time: {now}")
        if artifact and artifact.get("delivery_state"):
            print(f"Delivery State: {artifact['delivery_state']}")
        print(f"Reason: {artifact.get('failure_reason') if artifact else exc}")
        if signal_config["missing_env"]:
            print(f"Missing: {', '.join(signal_config['missing_env'])}")
        print(f"Delivery Artifact: {artifact_path}")
        if loaded_env is not None:
            print(f"Env File: {loaded_env}")
        return 1

    artifact = _load_artifact(artifact_path)
    print("Control Tower Signal Test")
    print("Status: PASS")
    print(f"Channel: {channel}")
    print(f"Host: {host_marker}")
    print(f"Time: {now}")
    if artifact and artifact.get("delivery_state"):
        print(f"Delivery State: {artifact['delivery_state']}")
    print(f"Delivery Artifact: {artifact_path}")
    if loaded_env is not None:
        print(f"Env File: {loaded_env}")
    return 0


def _load_artifact(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())

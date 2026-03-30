from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from controltower.config import load_config
from controltower.services.meeting_readiness import verify_meeting_readiness


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Control Tower meeting-grade narrative and disclosure behavior.")
    parser.add_argument("--config", type=Path, default=Path("controltower.example.yaml"), help="Control Tower config file to evaluate.")
    args = parser.parse_args()

    result = verify_meeting_readiness(load_config(args.config))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

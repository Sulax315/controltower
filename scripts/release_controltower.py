from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AUTHORITATIVE_SCRIPT = REPO_ROOT / "scripts" / "deploy_update_controltower.py"


def main() -> int:
    print(
        "release_controltower.py is deprecated; use infra/deploy/controltower/deploy_update.sh instead.",
        file=sys.stderr,
    )
    completed = subprocess.run([sys.executable, str(AUTHORITATIVE_SCRIPT), *sys.argv[1:]], cwd=str(REPO_ROOT), check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

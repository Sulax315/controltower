from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from controltower import __version__


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def current_git_commit() -> str | None:
    if commit := _git_head(workspace_root()):
        return commit
    env_commit = (os.getenv("GIT_COMMIT") or "").strip()
    if env_commit:
        return env_commit
    return None


def _git_head(root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    commit = completed.stdout.strip()
    return commit if completed.returncode == 0 and commit else None


def current_build_info() -> dict[str, object]:
    git_commit = current_git_commit()
    short_commit = git_commit[:12] if git_commit else None
    return {
        "version": __version__,
        "git_commit": git_commit,
        "git_commit_available": git_commit is not None,
        "git_commit_short": short_commit,
        "asset_version": short_commit or __version__,
        "python_version": sys.version.split()[0],
    }

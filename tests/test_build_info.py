from __future__ import annotations

import subprocess

from controltower.services import build_info


def test_current_git_commit_prefers_checkout_head_over_env_override(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "stale-env-commit")
    monkeypatch.setattr(
        build_info.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="fresh-checkout-commit\n", stderr=""),
    )

    assert build_info.current_git_commit() == "fresh-checkout-commit"


def test_current_git_commit_falls_back_to_env_when_git_is_unavailable(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "env-only-commit")

    def _missing_git(*args, **kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(build_info.subprocess, "run", _missing_git)

    assert build_info.current_git_commit() == "env-only-commit"

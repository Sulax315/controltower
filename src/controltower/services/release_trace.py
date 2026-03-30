from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RELEASE_SOURCE_TRACE_NAME = "latest_release_source_trace.json"
RELEASE_SOURCE_TRACE_SCHEMA_VERSION = "2026-03-30"


def collect_source_release_trace(
    repo_root: Path,
    *,
    remote_name: str = "origin",
    branch: str = "main",
) -> dict[str, Any]:
    resolved_root = Path(repo_root).resolve()
    generated_at = _utc_now_iso()
    trace: dict[str, Any] = {
        "schema_version": RELEASE_SOURCE_TRACE_SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "fail",
        "repo_root": str(resolved_root),
        "remote_name": remote_name,
        "branch": None,
        "origin_remote_url": None,
        "local_head_commit": None,
        "remote_origin_main_commit": None,
        "push_status": "unknown",
        "checks": [],
        "remediation_commands": [],
    }

    git_dir = _run_git(resolved_root, "rev-parse", "--git-dir")
    if not git_dir["ok"]:
        trace["checks"].append(
            {
                "name": "git_checkout_present",
                "status": "fail",
                "detail": git_dir["error"],
            }
        )
        trace["remediation_commands"] = [
            f"cd {resolved_root}",
            "git clone <AUTHORITATIVE_REMOTE_URL> .",
        ]
        trace["error"] = "Source root is not a Git checkout."
        return trace

    local_head = _run_git(resolved_root, "rev-parse", "HEAD")
    if local_head["ok"]:
        trace["local_head_commit"] = local_head["stdout"]

    worktree = _run_git(resolved_root, "status", "--porcelain")
    clean_worktree = worktree["ok"] and not worktree["stdout"]
    trace["checks"].append(
        {
            "name": "clean_worktree",
            "status": "pass" if clean_worktree else "fail",
            "detail": None if clean_worktree else "Worktree has uncommitted or untracked changes.",
            "entries": worktree["stdout"].splitlines() if worktree["ok"] else [],
        }
    )
    if not clean_worktree:
        trace["remediation_commands"] = [
            f"cd {resolved_root}",
            "git status --short",
            'git add -A && git commit -m "<describe release changes>"',
        ]
        trace["error"] = "Release source must be a clean Git worktree."
        return trace

    branch_result = _run_git(resolved_root, "branch", "--show-current")
    current_branch = branch_result["stdout"] if branch_result["ok"] else None
    trace["branch"] = current_branch
    trace["checks"].append(
        {
            "name": "current_branch_main",
            "status": "pass" if current_branch == branch else "fail",
            "detail": None if current_branch == branch else f"Current branch was {current_branch!r}.",
        }
    )
    if current_branch != branch:
        trace["remediation_commands"] = [
            f"cd {resolved_root}",
            f"git switch {branch}",
        ]
        trace["error"] = f"Release source must be on {branch}."
        return trace

    origin_url = _run_git(resolved_root, "remote", "get-url", remote_name)
    if origin_url["ok"]:
        trace["origin_remote_url"] = origin_url["stdout"]
    trace["checks"].append(
        {
            "name": "origin_exists",
            "status": "pass" if origin_url["ok"] else "fail",
            "detail": None if origin_url["ok"] else origin_url["error"],
        }
    )
    if not origin_url["ok"]:
        trace["remediation_commands"] = [
            f"cd {resolved_root}",
            f"git remote add {remote_name} <AUTHORITATIVE_REMOTE_URL>",
            f"git fetch {remote_name} {branch}",
            f"git branch --set-upstream-to={remote_name}/{branch} {branch}",
        ]
        trace["error"] = f"Required Git remote {remote_name!r} is missing."
        return trace

    fetch_result = _run_git(resolved_root, "fetch", remote_name, branch)
    trace["checks"].append(
        {
            "name": "fetch_origin",
            "status": "pass" if fetch_result["ok"] else "fail",
            "detail": None if fetch_result["ok"] else fetch_result["error"],
        }
    )
    if not fetch_result["ok"]:
        trace["remediation_commands"] = [
            f"cd {resolved_root}",
            "git remote -v",
            f"git fetch {remote_name} {branch}",
        ]
        trace["error"] = f"Fetch from {remote_name}/{branch} failed."
        return trace

    remote_head = _run_git(resolved_root, "rev-parse", f"{remote_name}/{branch}")
    if remote_head["ok"]:
        trace["remote_origin_main_commit"] = remote_head["stdout"]

    relation = _run_git(resolved_root, "rev-list", "--left-right", "--count", f"{remote_name}/{branch}...HEAD")
    behind = ahead = None
    push_status = "unknown"
    if relation["ok"]:
        parts = relation["stdout"].split()
        if len(parts) == 2:
            behind = int(parts[0])
            ahead = int(parts[1])
            if behind == 0 and ahead == 0:
                push_status = "up_to_date"
            elif behind == 0 and ahead > 0:
                push_status = "local_ahead"
            elif behind > 0 and ahead == 0:
                push_status = "local_behind"
            else:
                push_status = "diverged"
    trace["push_status"] = push_status

    local_not_behind = relation["ok"] and behind == 0
    trace["checks"].append(
        {
            "name": "local_not_behind_origin_main",
            "status": "pass" if local_not_behind else "fail",
            "detail": None if local_not_behind else f"Local branch is behind {remote_name}/{branch}.",
            "behind_by": behind,
            "ahead_by": ahead,
        }
    )
    trace["checks"].append(
        {
            "name": "push_status_validated",
            "status": "pass" if relation["ok"] else "fail",
            "detail": None if relation["ok"] else relation["error"],
            "push_status": push_status,
            "behind_by": behind,
            "ahead_by": ahead,
        }
    )
    trace["checks"].append(
        {
            "name": "remote_origin_main_matches_local_head",
            "status": "pass" if push_status == "up_to_date" else "fail",
            "detail": None if push_status == "up_to_date" else f"Push status is {push_status}.",
        }
    )

    if not relation["ok"]:
        trace["remediation_commands"] = [
            f"cd {resolved_root}",
            f"git fetch {remote_name} {branch}",
            f"git rev-list --left-right --count {remote_name}/{branch}...HEAD",
        ]
        trace["error"] = "Push status could not be validated."
        return trace

    if push_status == "local_behind":
        trace["remediation_commands"] = [
            f"cd {resolved_root}",
            f"git pull --ff-only {remote_name} {branch}",
        ]
        trace["error"] = f"Local branch is behind {remote_name}/{branch}."
        return trace

    if push_status == "diverged":
        trace["remediation_commands"] = [
            f"cd {resolved_root}",
            f"git fetch {remote_name} {branch}",
            f"git log --oneline --left-right {remote_name}/{branch}...HEAD",
        ]
        trace["error"] = f"Local branch diverged from {remote_name}/{branch}."
        return trace

    if push_status == "local_ahead":
        trace["remediation_commands"] = [
            f"cd {resolved_root}",
            f"git push {remote_name} {branch}",
        ]
        trace["error"] = f"Local HEAD is ahead of {remote_name}/{branch}; push is required before deploy."
        return trace

    trace["status"] = "pass"
    return trace


def release_source_trace_path(state_root: Path) -> Path:
    return Path(state_root) / "release" / RELEASE_SOURCE_TRACE_NAME


def write_source_release_trace(state_root: Path, trace: dict[str, Any]) -> Path:
    path = release_source_trace_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace, indent=2), encoding="utf-8")
    return path


def load_source_release_trace(state_root: Path) -> dict[str, Any] | None:
    path = release_source_trace_path(state_root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _run_git(repo_root: Path, *args: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return {"ok": False, "stdout": "", "stderr": "", "error": str(exc)}
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    return {
        "ok": completed.returncode == 0,
        "stdout": stdout,
        "stderr": stderr,
        "error": stderr or stdout or f"git {' '.join(args)} failed with exit code {completed.returncode}",
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

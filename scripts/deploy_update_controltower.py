from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from controltower.services.release_trace import collect_source_release_trace

DEFAULT_SPEC_PATH = REPO_ROOT / "infra" / "deploy" / "controltower" / "controltower.release.yaml"
DEFAULT_REMOTE_SCRIPT_PATH = REPO_ROOT / "infra" / "deploy" / "controltower" / "release_remote.sh"


@dataclass(frozen=True)
class ReleaseSpec:
    working_branch: str
    remote_name: str
    ssh_target: str
    public_ip: str
    app_root: str
    venv_python: str
    runtime_root: str
    env_file: str
    config_path: str
    service_name: str
    backend_base_url: str
    public_base_url: str


class ReleaseFailure(RuntimeError):
    def __init__(
        self,
        *,
        step: str,
        command: str,
        reason: str,
        action: str,
        summary: dict[str, Any],
    ) -> None:
        super().__init__(reason)
        self.step = step
        self.command = command
        self.reason = reason
        self.action = action
        self.summary = summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deploy_update_controltower",
        description="Authoritative Control Tower production release handoff.",
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=DEFAULT_SPEC_PATH,
        help="Release spec YAML containing the exact production target.",
    )
    parser.add_argument(
        "--remote-script",
        type=Path,
        default=DEFAULT_REMOTE_SCRIPT_PATH,
        help="Checked-in remote deployment script that will be piped over SSH.",
    )
    parser.add_argument(
        "--notify-webhook-url",
        default=None,
        help="Optional webhook URL that receives the final release summary JSON.",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=None,
        help="Optional path to write the final release summary JSON.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summary: dict[str, Any] = {
        "status": "failed",
        "repo_root": str(REPO_ROOT),
        "steps": [],
        "spec_path": str(args.spec.resolve()),
        "remote_script_path": str(args.remote_script.resolve()),
        "git": {},
        "deployment_target": {},
        "source_trace": None,
        "public_before": None,
        "public_after": None,
        "notification": {"status": "not_configured"},
    }

    try:
        spec = load_spec(args.spec)
        summary["deployment_target"] = {
            "ssh_target": spec.ssh_target,
            "public_ip": spec.public_ip,
            "app_root": spec.app_root,
            "service_name": spec.service_name,
            "backend_base_url": spec.backend_base_url,
            "public_base_url": spec.public_base_url,
        }
        remote_script = args.remote_script.resolve()
        if not remote_script.exists():
            raise ReleaseFailure(
                step="load_remote_script",
                command=str(remote_script),
                reason=f"Remote release script is missing: {remote_script}",
                action="Restore the checked-in remote release script before retrying.",
                summary=summary,
            )

        summary["public_before"] = fetch_public_health(spec.public_base_url)
        summary["git"] = validate_and_push_release_source(spec, summary)
        source_trace = collect_source_release_trace(REPO_ROOT, remote_name=spec.remote_name, branch=spec.working_branch)
        summary["source_trace"] = source_trace
        if source_trace.get("status") != "pass":
            raise ReleaseFailure(
                step="source_trace",
                command="collect_source_release_trace",
                reason=source_trace.get("error") or "Release source trace validation failed.",
                action="Use the remediation commands from the source trace, then rerun the authoritative deploy_update handoff.",
                summary=summary,
            )

        remote_command = [
            "ssh",
            spec.ssh_target,
            "bash",
            "-s",
            "--",
            "--app-root",
            spec.app_root,
            "--branch",
            spec.working_branch,
            "--commit",
            str(source_trace["local_head_commit"]),
            "--venv-python",
            spec.venv_python,
            "--runtime-root",
            spec.runtime_root,
            "--env-file",
            spec.env_file,
            "--config",
            spec.config_path,
            "--service-name",
            spec.service_name,
            "--backend-base-url",
            spec.backend_base_url,
            "--public-base-url",
            spec.public_base_url,
            "--git-remote",
            spec.remote_name,
            "--source-trace-b64",
            encode_json_payload(source_trace),
        ]
        run_checked(
            remote_command,
            step="remote_release",
            action="Inspect the remote release output, verifier JSON, and service journal before retrying.",
            summary=summary,
            input_text=remote_script.read_text(encoding="utf-8"),
        )

        summary["public_after"] = fetch_public_health(spec.public_base_url)
        assert_public_freshness(summary["public_after"], spec, str(source_trace["local_head_commit"]), summary)

        summary["status"] = "accepted"
        summary["intended_commit"] = source_trace["local_head_commit"]
        summary["acceptance_summary"] = (
            f"Released {source_trace['local_head_commit']} to {spec.public_base_url}; "
            "public /healthz now reports the intended commit and prod auth posture."
        )
    except ReleaseFailure as exc:
        summary["status"] = "failed"
        summary["failure"] = {
            "step": exc.step,
            "command": exc.command,
            "reason": exc.reason,
            "action": exc.action,
        }
        summary["public_after"] = summary.get("public_after") or fetch_public_health(summary["deployment_target"].get("public_base_url"))
        summary["live_state"] = classify_live_state(summary.get("public_before"), summary.get("public_after"))
    finally:
        summary["notification"] = maybe_notify(args.notify_webhook_url, summary)
        maybe_write_summary(args.summary_path, summary)
        print(json.dumps(summary, indent=2))

    return 0 if summary["status"] == "accepted" else 1


def load_spec(path: Path) -> ReleaseSpec:
    resolved = path.resolve()
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    release = raw.get("release") or {}
    repository = release.get("repository") or {}
    target = release.get("deployment_target") or {}
    return ReleaseSpec(
        working_branch=str(repository["working_branch"]),
        remote_name=str(repository["remote_name"]),
        ssh_target=str(target["ssh_target"]),
        public_ip=str(target["public_ip"]),
        app_root=str(target["app_root"]),
        venv_python=str(target["venv_python"]),
        runtime_root=str(target["runtime_root"]),
        env_file=str(target["env_file"]),
        config_path=str(target["config_path"]),
        service_name=str(target["service_name"]),
        backend_base_url=str(target["backend_base_url"]).rstrip("/"),
        public_base_url=str(target["public_base_url"]).rstrip("/"),
    )


def validate_and_push_release_source(spec: ReleaseSpec, summary: dict[str, Any]) -> dict[str, Any]:
    repo_branch = git_stdout(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    dirty_entries = git_stdout(["git", "status", "--porcelain"]).splitlines()
    dirty = bool(dirty_entries)
    if dirty:
        raise ReleaseFailure(
            step="git_state",
            command="git status --porcelain",
            reason="Working tree is dirty.",
            action="Commit or stash local changes before running the authoritative release handoff.",
            summary=summary,
        )

    if repo_branch != spec.working_branch:
        raise ReleaseFailure(
            step="git_branch",
            command="git rev-parse --abbrev-ref HEAD",
            reason=f"Current branch is {repo_branch!r}, expected {spec.working_branch!r}.",
            action=f"Switch to {spec.working_branch!r} before retrying the release.",
            summary=summary,
        )

    remote_url = git_stdout(["git", "remote", "get-url", spec.remote_name]).strip()
    run_checked(
        ["git", "fetch", spec.remote_name, spec.working_branch],
        step="git_fetch",
        action="Configure the authoritative git remote and ensure fetch access before retrying.",
        summary=summary,
    )
    head_commit = git_stdout(["git", "rev-parse", "HEAD"]).strip()
    upstream_ref = f"{spec.remote_name}/{spec.working_branch}"
    upstream_commit = git_stdout(["git", "rev-parse", upstream_ref]).strip()
    ahead, behind = parse_ahead_behind(git_stdout(["git", "rev-list", "--left-right", "--count", f"{upstream_ref}...HEAD"]))
    relationship = classify_relationship(ahead=ahead, behind=behind)

    if relationship == "behind":
        raise ReleaseFailure(
            step="git_relationship",
            command=f"git rev-list --left-right --count {upstream_ref}...HEAD",
            reason=f"Local branch is behind {upstream_ref}.",
            action=f"Fast-forward {spec.working_branch!r} to {upstream_ref} before retrying.",
            summary=summary,
        )
    if relationship == "diverged":
        raise ReleaseFailure(
            step="git_relationship",
            command=f"git rev-list --left-right --count {upstream_ref}...HEAD",
            reason=f"Local branch diverged from {upstream_ref}.",
            action=f"Reconcile the divergence and rerun the authoritative release handoff from a clean {spec.working_branch!r} checkout.",
            summary=summary,
        )

    push_performed = False
    if relationship == "ahead":
        run_checked(
            ["git", "push", spec.remote_name, f"HEAD:{spec.working_branch}"],
            step="git_push",
            action="Resolve the push rejection before retrying the release.",
            summary=summary,
        )
        push_performed = True
        upstream_commit = git_stdout(["git", "rev-parse", upstream_ref]).strip()
        ahead = 0
        behind = 0
        relationship = "in_sync"

    return {
        "branch": repo_branch,
        "working_branch_expected": spec.working_branch,
        "remote_name": spec.remote_name,
        "remote_url": remote_url,
        "head_commit": head_commit,
        "upstream_ref": upstream_ref,
        "upstream_commit": upstream_commit,
        "ahead": ahead,
        "behind": behind,
        "relationship": relationship,
        "dirty": dirty,
        "push_performed": push_performed,
    }


def assert_public_freshness(
    public_health: dict[str, Any] | None,
    spec: ReleaseSpec,
    expected_commit: str,
    summary: dict[str, Any],
) -> None:
    if not public_health or public_health.get("reachable") is False:
        raise ReleaseFailure(
            step="public_healthz",
            command=f"GET {spec.public_base_url}/healthz",
            reason="Public /healthz was not reachable after the remote release completed.",
            action="Inspect the host verifier output, nginx route, and service logs before retrying.",
            summary=summary,
        )

    if public_health.get("git_commit") != expected_commit:
        raise ReleaseFailure(
            step="public_freshness",
            command=f"GET {spec.public_base_url}/healthz",
            reason=(
                f"Public health endpoint reported git_commit={public_health.get('git_commit')!r} "
                f"instead of the intended commit {expected_commit!r}."
            ),
            action="Treat production as ambiguous and inspect the remote verifier output before announcing the release as live.",
            summary=summary,
        )

    if public_health.get("auth_mode") != "prod":
        raise ReleaseFailure(
            step="public_auth_posture",
            command=f"GET {spec.public_base_url}/healthz",
            reason=f"Public health endpoint reported auth_mode={public_health.get('auth_mode')!r}, expected 'prod'.",
            action="Restore the production auth posture before retrying the release.",
            summary=summary,
        )

    if public_health.get("public_base_url") not in {None, spec.public_base_url}:
        raise ReleaseFailure(
            step="public_base_url",
            command=f"GET {spec.public_base_url}/healthz",
            reason=(
                f"Public health endpoint reported public_base_url={public_health.get('public_base_url')!r}, "
                f"expected {spec.public_base_url!r}."
            ),
            action="Inspect the production config/env overrides before retrying.",
            summary=summary,
        )


def git_stdout(command: list[str]) -> str:
    completed = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise ReleaseFailure(
            step="git_command",
            command=" ".join(command),
            reason=(completed.stderr or completed.stdout or "Git command failed.").strip(),
            action="Fix the local git state or remote configuration before retrying the release.",
            summary={"status": "failed", "steps": []},
        )
    return completed.stdout


def run_checked(
    command: list[str],
    *,
    step: str,
    action: str,
    summary: dict[str, Any],
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )
    summary["steps"].append(
        {
            "step": step,
            "command": " ".join(command),
            "exit_code": completed.returncode,
            "stdout_tail": tail_lines(completed.stdout),
            "stderr_tail": tail_lines(completed.stderr),
        }
    )
    if completed.returncode != 0:
        raise ReleaseFailure(
            step=step,
            command=" ".join(command),
            reason=(completed.stderr or completed.stdout or "Command failed.").strip(),
            action=action,
            summary=summary,
        )
    return completed


def parse_ahead_behind(raw: str) -> tuple[int, int]:
    left, right = raw.strip().split()
    return int(right), int(left)


def classify_relationship(*, ahead: int, behind: int) -> str:
    if ahead > 0 and behind > 0:
        return "diverged"
    if behind > 0:
        return "behind"
    if ahead > 0:
        return "ahead"
    return "in_sync"


def encode_json_payload(payload: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def fetch_public_health(base_url: str | None) -> dict[str, Any] | None:
    if not base_url:
        return None
    url = base_url.rstrip("/") + "/healthz"
    request = Request(url, headers={"User-Agent": "controltower-deploy-update/1.0"})
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return {
                "reachable": True,
                "status_code": response.status,
                "git_commit": payload.get("git_commit"),
                "auth_mode": payload.get("auth_mode"),
                "asset_version": payload.get("asset_version"),
                "public_base_url": payload.get("public_base_url"),
            }
    except HTTPError as exc:
        return {"reachable": False, "status_code": exc.code, "error": str(exc)}
    except (URLError, OSError, json.JSONDecodeError) as exc:
        return {"reachable": False, "error": str(exc)}


def classify_live_state(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    before_commit = (before or {}).get("git_commit")
    after_commit = (after or {}).get("git_commit")
    if before_commit and after_commit and before_commit == after_commit:
        return {
            "status": "previous_version_still_live",
            "detail": f"Public /healthz stayed on commit {before_commit}.",
        }
    if after_commit and before_commit and after_commit != before_commit:
        return {
            "status": "ambiguous_live_change",
            "detail": f"Public /healthz moved from {before_commit} to {after_commit} during the failed release.",
        }
    if after and after.get("reachable") is False:
        return {
            "status": "public_unreachable",
            "detail": after.get("error") or f"HTTP {after.get('status_code')}",
        }
    return {
        "status": "ambiguous",
        "detail": "Could not prove whether production stayed on the previous live version.",
    }


def maybe_notify(webhook_url: str | None, summary: dict[str, Any]) -> dict[str, Any]:
    if not webhook_url:
        return {"status": "not_configured"}
    payload = json.dumps(summary).encode("utf-8")
    request = Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "controltower-deploy-update/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            return {"status": "sent", "status_code": response.status}
    except (HTTPError, URLError, OSError) as exc:
        return {"status": "failed", "error": str(exc)}


def maybe_write_summary(path: Path | None, summary: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def tail_lines(text: str, count: int = 20) -> list[str]:
    return [line for line in text.splitlines()[-count:] if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from controltower.config import ControlTowerConfig
from controltower.domain.models import ExecutionResultArtifact, utc_now_iso
from controltower.services.orchestration import OrchestrationService
from controltower.services.runtime_state import read_json, write_json


COMPLETE_EXECUTION_STATUSES = {"succeeded", "failed", "partial"}
INFLIGHT_NAME = "inflight.json"
LATEST_STATUS_NAME = "latest_status.json"


def execute_next_codex_lane(
    config: ControlTowerConfig,
    *,
    config_path: Path | None = None,
    orchestration_root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    root = Path(orchestration_root or _default_orchestration_root(config)).resolve()
    gate = _load_launch_gate(
        root=root,
        expected_run_id=run_id,
        review_root_base=Path(config.runtime.state_root).resolve() / "orchestration" / "reviews",
    )
    if gate["status"] != "launchable":
        return gate
    resolved_config_path = _resolved_config_path(config_path)
    if resolved_config_path is None:
        return _status_payload(
            "blocked",
            "config_path_missing",
            "Control Tower requires an explicit config path or CONTROLTOWER_CONFIG before the executor can ingest results safely.",
            run_id=gate["run_id"],
            review_root=gate["review_root"],
        )

    orchestration = OrchestrationService(config)
    review = orchestration.get_review_run(gate["run_id"])
    if review is None:
        return _status_payload(
            "blocked",
            "persisted_review_missing",
            "No persisted review binding exists for the approved launchable lane.",
            run_id=gate["run_id"],
            event_id=gate["event_id"],
            pack_id=gate["pack_id"],
            review_root=gate["review_root"],
        )

    authoritative_event_id = str(review.execution_event.event_id or "").strip()
    authoritative_pack_id = str(review.execution_pack.pack_id or "").strip()
    if not authoritative_event_id or not authoritative_pack_id:
        return _status_payload(
            "blocked",
            "review_tuple_missing",
            "Persisted review binding is missing the authoritative event_id or pack_id tuple required for execution-result-ingest.",
            run_id=gate["run_id"],
            review_root=gate["review_root"],
            details={
                "review_event_id": review.execution_event.event_id,
                "review_pack_id": review.execution_pack.pack_id,
            },
        )

    if authoritative_event_id != gate["event_id"]:
        return _status_payload(
            "blocked",
            "event_id_mismatch",
            "Persisted review binding does not match the authoritative event_id for the launchable lane.",
            run_id=gate["run_id"],
            event_id=authoritative_event_id,
            pack_id=authoritative_pack_id,
            review_root=gate["review_root"],
            details={
                "review_event_id": review.execution_event.event_id,
                "expected_event_id": gate["event_id"],
            },
        )

    if gate.get("pack_id") and authoritative_pack_id != gate["pack_id"]:
        return _status_payload(
            "blocked",
            "pack_id_mismatch",
            "Persisted review binding does not match the authoritative pack_id for the launchable lane.",
            run_id=gate["run_id"],
            event_id=authoritative_event_id,
            pack_id=authoritative_pack_id,
            review_root=gate["review_root"],
            details={
                "review_pack_id": review.execution_pack.pack_id,
                "expected_pack_id": gate["pack_id"],
            },
        )
    gate["event_id"] = authoritative_event_id
    gate["pack_id"] = authoritative_pack_id

    executor_root = gate["review_root"] / "codex_executor"
    executor_root.mkdir(parents=True, exist_ok=True)

    if review.execution_result.status in COMPLETE_EXECUTION_STATUSES:
        status = _status_payload(
            "skipped",
            "execution_already_complete",
            "Control Tower refused to launch because this lane already has a completed execution result.",
            run_id=gate["run_id"],
            event_id=gate["event_id"],
            pack_id=gate["pack_id"],
            review_root=gate["review_root"],
            details={
                "execution_status": review.execution_result.status,
                "result_path": review.execution_result.result_path,
                "closeout_status": review.execution_result.closeout_status,
            },
        )
        _write_latest_status(executor_root, status)
        return status

    inflight_path = executor_root / INFLIGHT_NAME
    if inflight_path.exists():
        inflight = read_json(inflight_path) or {}
        status = _status_payload(
            "skipped",
            "execution_in_flight",
            "Control Tower refused to launch because an execution is already in flight for this lane.",
            run_id=gate["run_id"],
            event_id=gate["event_id"],
            pack_id=gate["pack_id"],
            review_root=gate["review_root"],
            details={"inflight_path": str(inflight_path), "inflight": inflight},
        )
        _write_latest_status(executor_root, status)
        return status

    command_text = config.execution.codex_executor_command
    if not command_text:
        status = _status_payload(
            "blocked",
            "executor_command_missing",
            "CODEX_EXECUTOR_COMMAND is required before the autonomous Codex executor can run.",
            run_id=gate["run_id"],
            event_id=gate["event_id"],
            pack_id=gate["pack_id"],
            review_root=gate["review_root"],
        )
        _write_latest_status(executor_root, status)
        return status

    workdir = Path(config.execution.codex_executor_workdir or Path(__file__).resolve().parents[3]).resolve()
    if not workdir.exists() or not workdir.is_dir():
        status = _status_payload(
            "blocked",
            "executor_workdir_unreadable",
            "Configured Codex executor working directory is missing or unreadable.",
            run_id=gate["run_id"],
            event_id=gate["event_id"],
            pack_id=gate["pack_id"],
            review_root=gate["review_root"],
            details={"workdir": str(workdir)},
        )
        _write_latest_status(executor_root, status)
        return status

    started_at = utc_now_iso()
    stamp = started_at.replace(":", "-")
    attempt_root = executor_root / "attempts" / f"attempt_{stamp}"
    attempt_root.mkdir(parents=True, exist_ok=True)
    prompt_path = attempt_root / "approved_prompt.md"
    request_path = attempt_root / "request.json"
    stdout_path = attempt_root / "stdout.log"
    stderr_path = attempt_root / "stderr.log"
    contract_path = attempt_root / "result_contract.json"
    subprocess_path = attempt_root / "subprocess_result.json"
    ingest_payload_path = attempt_root / "execution_result_ingest_payload.json"
    ingest_receipt_path = attempt_root / "execution_result_ingest_receipt.json"

    prompt_path.write_text(gate["prompt_markdown"], encoding="utf-8")
    request_payload = {
        "recorded_at": started_at,
        "run_id": gate["run_id"],
        "event_id": gate["event_id"],
        "pack_id": gate["pack_id"],
        "pack_type": review.execution_pack.pack_type,
        "command": command_text,
        "workdir": str(workdir),
        "config_path": str(resolved_config_path),
        "orchestration_root": str(root),
        "runtime_root": str(Path(config.runtime.state_root).resolve()),
        "review_root": str(gate["review_root"]),
        "prompt_path": str(prompt_path),
        "result_contract_path": str(contract_path),
        "timeout_seconds": config.execution.codex_executor_timeout_seconds,
    }
    write_json(request_path, request_payload)

    inflight_payload = {
        "started_at": started_at,
        "run_id": gate["run_id"],
        "event_id": gate["event_id"],
        "pack_id": gate["pack_id"],
        "attempt_root": str(attempt_root),
        "prompt_path": str(prompt_path),
    }
    try:
        _write_json_exclusive(inflight_path, inflight_payload)
    except FileExistsError:
        status = _status_payload(
            "skipped",
            "execution_in_flight",
            "Control Tower refused to launch because another executor already claimed this lane.",
            run_id=gate["run_id"],
            event_id=gate["event_id"],
            pack_id=gate["pack_id"],
            review_root=gate["review_root"],
            details={"inflight_path": str(inflight_path)},
        )
        _write_latest_status(executor_root, status)
        return status

    try:
        command = shlex.split(command_text, posix=True)
        if not command:
            raise ValueError("Executor command resolved to an empty argv list.")
        env = os.environ.copy()
        env.update(
            {
                "CONTROLTOWER_CODEX_RUN_ID": gate["run_id"],
                "CONTROLTOWER_CODEX_EVENT_ID": gate["event_id"],
                "CONTROLTOWER_CODEX_PACK_ID": gate["pack_id"],
                "CONTROLTOWER_CODEX_PROMPT_PATH": str(prompt_path),
                "CONTROLTOWER_CODEX_RESULT_PATH": str(contract_path),
                "CONTROLTOWER_CODEX_REVIEW_ROOT": str(gate["review_root"]),
                "CONTROLTOWER_CODEX_ORCHESTRATION_ROOT": str(root),
                "CONTROLTOWER_CODEX_RUNTIME_ROOT": str(Path(config.runtime.state_root).resolve()),
            }
        )

        timed_out = False
        timeout_seconds = int(config.execution.codex_executor_timeout_seconds)
        started_monotonic = time.monotonic()
        try:
            with stdout_path.open("w", encoding="utf-8", newline="\n") as stdout_handle, stderr_path.open(
                "w",
                encoding="utf-8",
                newline="\n",
            ) as stderr_handle:
                completed = subprocess.run(
                    command,
                    cwd=str(workdir),
                    env=env,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    text=True,
                    check=False,
                    timeout=timeout_seconds,
                )
            returncode = int(completed.returncode)
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = None
        completed_at = utc_now_iso()
        elapsed_seconds = round(time.monotonic() - started_monotonic, 3)
        subprocess_payload = {
            "started_at": started_at,
            "completed_at": completed_at,
            "elapsed_seconds": elapsed_seconds,
            "timed_out": timed_out,
            "returncode": returncode,
            "command": command,
            "workdir": str(workdir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "result_contract_path": str(contract_path),
        }
        write_json(subprocess_path, subprocess_payload)

        ingest_payload = _build_ingest_payload(
            review=review,
            contract_path=contract_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            subprocess_payload=subprocess_payload,
        )
        write_json(ingest_payload_path, ingest_payload)

        ingest_receipt = _invoke_execution_result_ingest(
            config_path=resolved_config_path,
            payload_path=ingest_payload_path,
            cwd=workdir,
        )
        write_json(ingest_receipt_path, ingest_receipt)

        status = _status_payload(
            "executed",
            "execution_result_ingested",
            "Control Tower executed the approved Codex lane and ingested the result through execution-result-ingest.",
            run_id=gate["run_id"],
            event_id=gate["event_id"],
            pack_id=gate["pack_id"],
            review_root=gate["review_root"],
            details={
                "attempt_root": str(attempt_root),
                "prompt_path": str(prompt_path),
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
                "result_contract_path": str(contract_path),
                "execution_result_ingest_payload_path": str(ingest_payload_path),
                "execution_result_ingest_receipt_path": str(ingest_receipt_path),
                "subprocess_result_path": str(subprocess_path),
                "ingest_status": ingest_receipt.get("status"),
                "ingest_exit_code": ingest_receipt.get("exit_code"),
            },
        )
        _write_latest_status(executor_root, status)
        return status
    finally:
        if inflight_path.exists():
            inflight_path.unlink()


def watch_codex_lane_loop(
    config: ControlTowerConfig,
    *,
    config_path: Path | None = None,
    orchestration_root: Path | None = None,
    run_id: str | None = None,
    max_iterations: int | None = None,
    sleep_seconds: int | None = None,
) -> dict[str, Any]:
    interval = max(int(sleep_seconds or config.execution.codex_executor_poll_interval_seconds), 1)
    iterations: list[dict[str, Any]] = []
    count = 0
    while max_iterations is None or count < max_iterations:
        iterations.append(
            execute_next_codex_lane(
                config,
                config_path=config_path,
                orchestration_root=orchestration_root,
                run_id=run_id,
            )
        )
        count += 1
        if max_iterations is not None and count >= max_iterations:
            break
        time.sleep(interval)
    return {
        "status": "ok",
        "iterations": iterations,
        "iteration_count": len(iterations),
        "sleep_seconds": interval,
    }


def _load_launch_gate(*, root: Path, expected_run_id: str | None, review_root_base: Path) -> dict[str, Any]:
    pending = read_json(root / "pending_approval.json") or {}
    run_state = read_json(root / "run_state.json") or {}
    trigger = read_json(root / "trigger_next_run.json") or {}
    next_prompt = read_json(root / "next_prompt.json") or {}
    run_id = str(pending.get("run_id") or "").strip()
    details = {
        "pending_status": pending.get("status"),
        "run_state_status": run_state.get("status"),
        "trigger_next_action": trigger.get("next_action"),
        "trigger_ready_for_operator_launch": trigger.get("ready_for_operator_launch"),
        "next_prompt_approval_status": next_prompt.get("approval_status"),
    }
    if not run_id:
        return _status_payload("blocked", "run_id_missing", "pending_approval.json does not define an active run_id.", details=details)
    if expected_run_id and expected_run_id != run_id:
        return _status_payload(
            "blocked",
            "run_id_mismatch",
            "The authoritative launchable lane does not match the requested run_id.",
            run_id=run_id,
            details={**details, "expected_run_id": expected_run_id},
        )
    if pending.get("status") != "approved":
        return _status_payload("blocked", "pending_approval_not_approved", "pending_approval.json is not approved.", run_id=run_id, details=details)
    if run_state.get("status") != "approved" or run_state.get("active_run_id") != run_id:
        return _status_payload("blocked", "run_state_not_approved", "run_state.json does not confirm the approved active run.", run_id=run_id, details=details)
    if trigger.get("target_run_id") != run_id:
        return _status_payload("blocked", "trigger_target_mismatch", "trigger_next_run.json does not target the approved run.", run_id=run_id, details=details)
    if trigger.get("next_action") != "launch_next_codex_lane":
        return _status_payload("blocked", "trigger_not_launchable", "trigger_next_run.json is not set to launch_next_codex_lane.", run_id=run_id, details=details)
    if trigger.get("ready_for_operator_launch") is not True:
        return _status_payload("blocked", "trigger_not_ready", "trigger_next_run.json is not ready for operator launch.", run_id=run_id, details=details)
    if trigger.get("gate_failure") is not None:
        return _status_payload("blocked", "trigger_gate_failure", "trigger_next_run.json records a gate failure.", run_id=run_id, details={**details, "gate_failure": trigger.get("gate_failure")})
    if next_prompt.get("pending_run_id") != run_id:
        return _status_payload("blocked", "next_prompt_run_mismatch", "next_prompt.json does not bind to the approved run.", run_id=run_id, details=details)
    if next_prompt.get("approval_status") != "approved":
        return _status_payload("blocked", "next_prompt_not_approved", "next_prompt.json is not approved.", run_id=run_id, details=details)
    if next_prompt.get("gate_failure") is not None:
        return _status_payload("blocked", "next_prompt_gate_failure", "next_prompt.json records a gate failure.", run_id=run_id, details={**details, "gate_failure": next_prompt.get("gate_failure")})

    prompt_payload = next_prompt.get("next_prompt") or {}
    prompt_markdown = str(prompt_payload.get("prompt_markdown") or "").strip()
    if not prompt_markdown:
        markdown_path = root / "next_prompt.md"
        if markdown_path.exists():
            prompt_markdown = markdown_path.read_text(encoding="utf-8").strip()
    if not prompt_markdown:
        return _status_payload("blocked", "prompt_markdown_missing", "No approved prompt markdown could be loaded for the launchable lane.", run_id=run_id, details=details)

    review_root = review_root_base / run_id
    return {
        "status": "launchable",
        "reason": "launchable",
        "message": "Approved launchable lane detected.",
        "run_id": run_id,
        "event_id": f"event_{trigger.get('event_version') or 'v1'}_{run_id}",
        "pack_id": "pack_release_readiness_v1",
        "prompt_markdown": prompt_markdown,
        "review_root": review_root,
        "details": details,
    }


def _build_ingest_payload(
    *,
    review,
    contract_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    subprocess_payload: dict[str, Any],
) -> dict[str, Any]:
    contract = read_json(contract_path) if contract_path.exists() else None
    output_artifacts: list[ExecutionResultArtifact] = []
    if isinstance(contract, dict):
        for item in contract.get("output_artifacts") or []:
            path = str(item.get("path") or "").strip()
            external_url = str(item.get("external_url") or "").strip() or None
            if not path and not external_url:
                continue
            output_artifacts.append(
                ExecutionResultArtifact(
                    label=str(item.get("label") or Path(path or external_url or "artifact").name),
                    path=path,
                    content_type=item.get("content_type"),
                    external_url=external_url,
                )
            )

    output_artifacts.extend(
        [
            ExecutionResultArtifact(label="Codex Executor Stdout", path=str(stdout_path), content_type="text/plain"),
            ExecutionResultArtifact(label="Codex Executor Stderr", path=str(stderr_path), content_type="text/plain"),
            ExecutionResultArtifact(label="Codex Executor Subprocess Result", path=str(Path(subprocess_payload["stdout_path"]).parent / "subprocess_result.json"), content_type="application/json"),
        ]
    )
    if contract_path.exists():
        output_artifacts.append(
            ExecutionResultArtifact(
                label="Codex Executor Result Contract",
                path=str(contract_path),
                content_type="application/json",
            )
        )
    output_artifacts = _dedupe_artifacts(output_artifacts)

    if isinstance(contract, dict) and str(contract.get("status") or "").strip().lower() in COMPLETE_EXECUTION_STATUSES:
        status = str(contract.get("status")).strip().lower()
        summary = str(contract.get("summary") or "").strip() or f"Codex executor reported {status}."
        started_at = contract.get("started_at") or subprocess_payload.get("started_at")
        completed_at = contract.get("completed_at") or subprocess_payload.get("completed_at")
        external_reference = contract.get("external_reference") or f"codex-executor:{review.run_id}"
        logs_excerpt = str(contract.get("logs_excerpt") or "").strip() or _log_excerpt(stdout_path, stderr_path)
    else:
        if subprocess_payload.get("timed_out"):
            status = "failed"
            summary = (
                "Codex executor timed out before writing a valid result contract."
                f" Timeout seconds: {subprocess_payload.get('elapsed_seconds')}."
            )
        else:
            returncode = subprocess_payload.get("returncode")
            status = "failed"
            summary = (
                "Codex executor exited without a valid result contract."
                if returncode == 0
                else f"Codex executor exited with code {returncode} before a valid result contract was produced."
            )
        started_at = subprocess_payload.get("started_at")
        completed_at = subprocess_payload.get("completed_at")
        external_reference = f"codex-executor:{review.run_id}"
        logs_excerpt = _log_excerpt(stdout_path, stderr_path)

    return {
        "event_id": review.execution_event.event_id,
        "run_id": review.run_id,
        "pack_id": review.execution_pack.pack_id,
        "status": status,
        "summary": summary,
        "output_artifacts": [artifact.model_dump(mode="json") for artifact in output_artifacts],
        "started_at": started_at,
        "completed_at": completed_at,
        "external_reference": external_reference,
        "logs_excerpt": logs_excerpt,
    }


def _invoke_execution_result_ingest(*, config_path: Path | None, payload_path: Path, cwd: Path) -> dict[str, Any]:
    command = [sys.executable, str(Path(__file__).resolve().parents[3] / "run_controltower.py")]
    if config_path is not None:
        command.extend(["--config", str(Path(config_path).resolve())])
    command.extend(["execution-result-ingest", "--payload-file", str(payload_path)])
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    parsed = None
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            parsed = None
    receipt = {
        "status": "accepted" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "parsed_stdout": parsed,
    }
    if completed.returncode != 0:
        raise RuntimeError(
            "execution-result-ingest failed for the Codex executor result payload: "
            + (stderr or stdout or f"exit={completed.returncode}")
        )
    return receipt


def _dedupe_artifacts(artifacts: list[ExecutionResultArtifact]) -> list[ExecutionResultArtifact]:
    deduped: list[ExecutionResultArtifact] = []
    seen: set[tuple[str, str]] = set()
    for artifact in artifacts:
        key = (artifact.label, artifact.path or artifact.external_url or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return deduped


def _log_excerpt(stdout_path: Path, stderr_path: Path) -> str:
    parts: list[str] = []
    for label, path in (("stdout", stdout_path), ("stderr", stderr_path)):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            continue
        tail = "\n".join(text.splitlines()[-20:])
        parts.append(f"[{label}]\n{tail}")
    excerpt = "\n\n".join(parts).strip()
    return excerpt[:4000] if excerpt else "No executor logs were captured."


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _write_latest_status(executor_root: Path, payload: dict[str, Any]) -> None:
    executor_root.mkdir(parents=True, exist_ok=True)
    write_json(executor_root / LATEST_STATUS_NAME, payload)


def _status_payload(
    status: str,
    reason: str,
    message: str,
    *,
    run_id: str | None = None,
    event_id: str | None = None,
    pack_id: str | None = None,
    review_root: Path | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "message": message,
        "run_id": run_id,
        "event_id": event_id,
        "pack_id": pack_id,
        "review_root": str(review_root) if review_root is not None else None,
        "recorded_at": utc_now_iso(),
        "details": details or {},
    }


def _default_orchestration_root(config: ControlTowerConfig) -> Path:
    return Path(config.runtime.state_root).resolve().parent / "ops" / "orchestration"


def _resolved_config_path(config_path: Path | None) -> Path | None:
    if config_path is not None:
        return Path(config_path).resolve()
    from_env = (os.getenv("CONTROLTOWER_CONFIG") or "").strip()
    if from_env:
        return Path(from_env).resolve()
    return None

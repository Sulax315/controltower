from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from controltower.config import ControlTowerConfig
from controltower.domain.models import utc_now_iso
from controltower.obsidian.continuity import (
    ObsidianCheckout,
    ObsidianContinuityError,
    ObsidianCheckoutResult,
    read_checkout_bundle,
)
from controltower.services.runtime_state import read_json


APPROVAL_EVENT_LOG_NAME = "approval_events.jsonl"
NEXT_PROMPT_JSON_NAME = "next_prompt.json"
NEXT_PROMPT_MARKDOWN_NAME = "next_prompt.md"
PENDING_APPROVAL_NAME = "pending_approval.json"
RUN_STATE_NAME = "run_state.json"
TRIGGER_NEXT_RUN_NAME = "trigger_next_run.json"

_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
_NEXT_PROMPT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "objective": {"type": "string", "minLength": 1},
        "scope": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
        "constraints": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
        "stop_condition": {"type": "string", "minLength": 1},
        "deliverable_format": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
        "recommended_commands": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
        "prompt_markdown": {"type": "string", "minLength": 1},
        "requires_operator_approval_after_release": {"type": "boolean"},
        "continuation_mode": {"type": "string", "minLength": 1},
        "strategic_alignment_summary": {"type": "string", "minLength": 1},
    },
    "required": [
        "objective",
        "scope",
        "constraints",
        "stop_condition",
        "deliverable_format",
        "recommended_commands",
        "prompt_markdown",
        "requires_operator_approval_after_release",
        "continuation_mode",
        "strategic_alignment_summary",
    ],
}


class PromptOrchestrationError(RuntimeError):
    def __init__(self, message: str, *, gate: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.gate = gate
        self.details = details or {}


class GeneratedNextPrompt(BaseModel):
    objective: str
    scope: list[str] = Field(min_length=1)
    constraints: list[str] = Field(min_length=1)
    stop_condition: str
    deliverable_format: list[str] = Field(min_length=1)
    recommended_commands: list[str] = Field(min_length=1)
    prompt_markdown: str
    requires_operator_approval_after_release: bool
    continuation_mode: str
    strategic_alignment_summary: str


def orchestrate_next_prompt(
    config: ControlTowerConfig,
    *,
    orchestration_root: Path | None = None,
    recent_approval_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(orchestration_root or _default_orchestration_root()).resolve()
    pending = read_json(root / PENDING_APPROVAL_NAME) or {}
    trigger = read_json(root / TRIGGER_NEXT_RUN_NAME) or {}
    generated_at = utc_now_iso()

    if not config.prompt_orchestration.enabled:
        payload = _build_orchestration_payload(
            generated_at=generated_at,
            orchestration_status="disabled",
            model_name=None,
            source_artifacts_used=[],
            obsidian_context_used={
                "status": "disabled",
                "normalized": False,
                "continuity_root": str(config.obsidian.continuity_root),
                "note_paths": [],
            },
            pending_approval=pending,
            next_prompt=None,
            gate_failure={"gate": "prompt_orchestration_disabled", "reason": "Prompt orchestration is disabled in config."},
        )
        return _write_orchestration_artifacts(root=root, payload=payload, trigger=trigger, ready_for_operator_launch=False)

    try:
        checkout_result = _load_obsidian_checkout(config)
    except PromptOrchestrationError as exc:
        payload = _build_orchestration_payload(
            generated_at=generated_at,
            orchestration_status="blocked",
            model_name=None,
            source_artifacts_used=[],
            obsidian_context_used={
                "status": "blocked",
                "normalized": False,
                "continuity_root": str(config.obsidian.continuity_root),
                "note_paths": list(config.obsidian.checkout_notes),
            },
            pending_approval=pending,
            next_prompt=None,
            gate_failure={"gate": exc.gate or "obsidian_checkout", "reason": str(exc), "details": exc.details},
        )
        return _write_orchestration_artifacts(root=root, payload=payload, trigger=trigger, ready_for_operator_launch=False)

    context = build_prompt_context(
        config,
        orchestration_root=root,
        checkout_result=checkout_result,
        recent_approval_event=recent_approval_event,
    )
    source_artifacts_used = list(context["source_artifacts_used"])
    obsidian_context_used = _build_obsidian_context_used(checkout_result)

    api_key = (config.prompt_orchestration.openai_api_key or "").strip()
    if not api_key:
        payload = _build_orchestration_payload(
            generated_at=generated_at,
            orchestration_status="blocked",
            model_name=config.prompt_orchestration.model,
            source_artifacts_used=source_artifacts_used,
            obsidian_context_used=obsidian_context_used,
            pending_approval=pending,
            next_prompt=None,
            gate_failure={
                "gate": "openai_configuration",
                "reason": "OPENAI_API_KEY is required when prompt orchestration is enabled.",
            },
        )
        return _write_orchestration_artifacts(root=root, payload=payload, trigger=trigger, ready_for_operator_launch=False)

    client = OpenAIResponsesClient(api_key=api_key, model_name=config.prompt_orchestration.model)
    try:
        response = client.generate_next_prompt(context["context_pack"])
    except PromptOrchestrationError as exc:
        payload = _build_orchestration_payload(
            generated_at=generated_at,
            orchestration_status="failed",
            model_name=config.prompt_orchestration.model,
            source_artifacts_used=source_artifacts_used,
            obsidian_context_used=obsidian_context_used,
            pending_approval=pending,
            next_prompt=None,
            gate_failure={"gate": exc.gate or "openai_generation", "reason": str(exc), "details": exc.details},
        )
        return _write_orchestration_artifacts(root=root, payload=payload, trigger=trigger, ready_for_operator_launch=False)

    payload = _build_orchestration_payload(
        generated_at=generated_at,
        orchestration_status="generated",
        model_name=response["model_name"],
        source_artifacts_used=source_artifacts_used,
        obsidian_context_used=obsidian_context_used,
        pending_approval=pending,
        next_prompt=response["next_prompt"].model_dump(mode="json"),
        context_pack=context["context_pack"],
        gate_failure=None,
    )
    return _write_orchestration_artifacts(root=root, payload=payload, trigger=trigger, ready_for_operator_launch=True)


def build_prompt_context(
    config: ControlTowerConfig,
    *,
    orchestration_root: Path,
    checkout_result: ObsidianCheckoutResult,
    recent_approval_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(orchestration_root).resolve()
    pending_approval = read_json(root / PENDING_APPROVAL_NAME) or {}
    run_state = read_json(root / RUN_STATE_NAME) or {}
    trigger_next_run = read_json(root / TRIGGER_NEXT_RUN_NAME) or {}
    release_status_path = Path(pending_approval.get("source_release_status_path") or config.runtime.state_root / "release" / "latest_release_readiness.json")
    latest_release_status = _read_json_if_exists(release_status_path)
    latest_live_deployment_path = Path(config.runtime.state_root) / "release" / "latest_live_deployment.json"
    latest_live_deployment = _read_json_if_exists(latest_live_deployment_path)
    latest_release_source_trace, release_source_trace_path = _load_latest_release_source_trace(latest_release_status)
    approval_event_path = root / APPROVAL_EVENT_LOG_NAME
    approval_event_summary = recent_approval_event or _latest_approval_event_summary(approval_event_path)

    source_artifacts_used = [
        str(path.resolve())
        for path in [release_status_path, latest_live_deployment_path, release_source_trace_path]
        if path is not None and Path(path).exists()
    ]
    source_artifacts_used.extend(
        str(path.resolve())
        for path in [root / PENDING_APPROVAL_NAME, root / RUN_STATE_NAME, root / TRIGGER_NEXT_RUN_NAME, approval_event_path]
        if path.exists()
    )
    source_artifacts_used.extend(str(Path(path).resolve()) for path in checkout_result.note_paths)

    checkout_context = _checkout_context_metadata(checkout_result)

    context_pack = {
        "latest_release_status": latest_release_status,
        "latest_live_deployment": latest_live_deployment,
        "latest_release_source_trace": latest_release_source_trace,
        "pending_approval": pending_approval,
        "run_state": run_state,
        "trigger_next_run": trigger_next_run,
        "recent_approval_event_summary": approval_event_summary,
        "obsidian_checkout": checkout_result.checkout.model_dump(mode="json"),
        "obsidian_checkout_context": checkout_context,
    }
    return {
        "context_pack": context_pack,
        "source_artifacts_used": source_artifacts_used,
    }


def build_next_prompt_placeholder(
    *,
    generated_at: str,
    orchestration_status: str,
    pending_approval: dict[str, Any] | None,
    reason: str,
    source_artifacts_used: list[str] | None = None,
    obsidian_context_used: dict[str, Any] | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    return _build_orchestration_payload(
        generated_at=generated_at,
        orchestration_status=orchestration_status,
        model_name=model_name,
        source_artifacts_used=list(source_artifacts_used or []),
        obsidian_context_used=obsidian_context_used or {"status": "not_run", "normalized": False, "note_paths": []},
        pending_approval=pending_approval or {},
        next_prompt=None,
        gate_failure={"gate": orchestration_status, "reason": reason},
    )


def write_placeholder_artifacts(
    *,
    orchestration_root: Path,
    payload: dict[str, Any],
    trigger: dict[str, Any] | None = None,
    ready_for_operator_launch: bool = False,
) -> dict[str, Any]:
    return _write_orchestration_artifacts(
        root=Path(orchestration_root).resolve(),
        payload=payload,
        trigger=trigger or {},
        ready_for_operator_launch=ready_for_operator_launch,
    )


class OpenAIResponsesClient:
    def __init__(self, *, api_key: str, model_name: str) -> None:
        self.api_key = api_key
        self.model_name = model_name

    def generate_next_prompt(self, context_pack: dict[str, Any]) -> dict[str, Any]:
        request_payload = {
            "model": self.model_name,
            "input": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": json.dumps(context_pack, indent=2)},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "controltower_next_prompt",
                    "schema": _NEXT_PROMPT_SCHEMA,
                    "strict": True,
                }
            },
        }
        request = Request(
            _RESPONSES_ENDPOINT,
            data=json.dumps(request_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise PromptOrchestrationError(
                f"OpenAI Responses API returned HTTP {exc.code}.",
                gate="openai_generation",
                details={"response_body": body},
            ) from exc
        except URLError as exc:
            raise PromptOrchestrationError(
                "OpenAI Responses API request failed.",
                gate="openai_generation",
                details={"reason": str(exc.reason)},
            ) from exc

        payload = json.loads(raw)
        text = _extract_output_text(payload)
        try:
            next_prompt = GeneratedNextPrompt.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValueError) as exc:
            raise PromptOrchestrationError(
                "OpenAI Responses API returned an invalid structured prompt payload.",
                gate="openai_generation",
                details={"response_text": text},
            ) from exc
        return {
            "model_name": str(payload.get("model") or self.model_name),
            "next_prompt": next_prompt,
        }


def _load_obsidian_checkout(config: ControlTowerConfig) -> ObsidianCheckoutResult:
    try:
        return read_checkout_bundle(
            continuity_root=Path(config.obsidian.continuity_root),
            note_paths=list(config.obsidian.checkout_notes),
        )
    except ObsidianContinuityError as exc:
        if config.prompt_orchestration.obsidian_gating_enabled:
            raise PromptOrchestrationError(str(exc), gate="obsidian_checkout") from exc
        return ObsidianCheckoutResult(
            parsed_at=utc_now_iso(),
            continuity_root=str(Path(config.obsidian.continuity_root).resolve()),
            note_paths=[],
            checkout=ObsidianCheckout(
                phase="gate_disabled_override",
                current_objective="Proceed using Control Tower execution artifacts because Obsidian gating was explicitly disabled.",
                why_this_matters="This is an emergency bypass and strategic continuity must be restored before steady-state autonomous use.",
                in_scope=["Honor the approved Control Tower artifacts without redesigning the release or approval architecture."],
                out_of_scope=["Do not treat this override as normal operating posture.", "Do not expand scope beyond the approved lane."],
                known_risks=["Strategic continuity could drift while Obsidian gating is disabled."],
                acceptance_bar=["Complete the approved lane and re-enable Obsidian gating immediately afterward."],
                last_accepted_release="override_not_from_obsidian",
                next_strategic_target="Re-enable Obsidian gating and restore a validated checkout note bundle.",
            ),
        )


def _build_obsidian_context_used(checkout_result: ObsidianCheckoutResult) -> dict[str, Any]:
    return {
        "status": "used",
        "normalized": _is_normalized_checkout(checkout_result),
        "parsed_at": checkout_result.parsed_at,
        "continuity_root": checkout_result.continuity_root,
        "note_paths": list(checkout_result.note_paths),
        "checkout": checkout_result.checkout.model_dump(mode="json"),
    }


def _checkout_context_metadata(checkout_result: ObsidianCheckoutResult) -> dict[str, Any]:
    return {
        "normalized": _is_normalized_checkout(checkout_result),
        "parsed_at": checkout_result.parsed_at,
        "continuity_root": checkout_result.continuity_root,
        "note_paths": list(checkout_result.note_paths),
        "note_count": len(checkout_result.note_paths),
    }


def _is_normalized_checkout(checkout_result: ObsidianCheckoutResult) -> bool:
    return bool(checkout_result.note_paths)


def _read_json_if_exists(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return read_json(path)


def _load_latest_release_source_trace(latest_release_status: dict[str, Any] | None) -> tuple[dict[str, Any] | None, Path | None]:
    release_trace = (latest_release_status or {}).get("release_trace")
    if not isinstance(release_trace, dict):
        return None, None
    source_trace_path = release_trace.get("source_trace_path")
    if source_trace_path:
        path = Path(source_trace_path)
        payload = _read_json_if_exists(path)
        if payload is not None:
            return payload, path
    return release_trace, None


def _latest_approval_event_summary(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    last_line = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last_line = line
    if not last_line:
        return None
    payload = json.loads(last_line)
    return {
        "event_id": payload.get("event_id"),
        "timestamp": payload.get("timestamp"),
        "normalized_command": payload.get("normalized_command"),
        "applied": payload.get("applied"),
        "reason": payload.get("reason"),
        "referenced_run_id": payload.get("referenced_run_id"),
        "source_channel": payload.get("source_channel"),
    }


def _launchable_with_normalized_context(payload: dict[str, Any], ready_for_operator_launch: bool) -> bool:
    obsidian_context = payload.get("obsidian_context_used") or {}
    return bool(
        ready_for_operator_launch
        and payload.get("orchestration_status") == "generated"
        and payload.get("next_prompt")
        and payload.get("gate_failure") is None
        and obsidian_context.get("normalized") is True
    )


def _next_action_for_payload(payload: dict[str, Any], launchable: bool) -> str:
    command = str(payload.get("approval_command") or "").upper()
    if launchable:
        if command == "APPROVE":
            return "launch_next_codex_lane"
        if command == "RETRY":
            return "rerun_release_lane"
    if command == "HOLD":
        return "hold"
    if command in {"APPROVE", "RETRY"}:
        return "await_gate_clearance"
    if payload.get("approval_status") == "awaiting_approval":
        return "await_operator_input"
    return "idle"


def _launch_gate_status(payload: dict[str, Any], launchable: bool) -> str:
    if launchable:
        return "launchable"
    if payload.get("gate_failure") or str(payload.get("approval_command") or "").upper() in {"APPROVE", "RETRY"}:
        return "blocked"
    if payload.get("approval_status") == "awaiting_approval":
        return "awaiting_approval"
    return "idle"


def _build_orchestration_payload(
    *,
    generated_at: str,
    orchestration_status: str,
    model_name: str | None,
    source_artifacts_used: list[str],
    obsidian_context_used: dict[str, Any],
    pending_approval: dict[str, Any],
    next_prompt: dict[str, Any] | None,
    gate_failure: dict[str, Any] | None,
    context_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "2026-03-31",
        "generated_at": generated_at,
        "orchestration_status": orchestration_status,
        "model_name": model_name,
        "pending_run_id": pending_approval.get("run_id"),
        "approval_status": pending_approval.get("status"),
        "approval_command": pending_approval.get("applied_command"),
        "approval_applied_at": pending_approval.get("applied_at"),
        "source_artifacts_used": source_artifacts_used,
        "obsidian_context_used": obsidian_context_used,
        "gate_failure": gate_failure,
        "next_prompt": next_prompt,
        "context_pack": context_pack,
    }


def _write_orchestration_artifacts(
    *,
    root: Path,
    payload: dict[str, Any],
    trigger: dict[str, Any],
    ready_for_operator_launch: bool,
) -> dict[str, Any]:
    json_path = root / NEXT_PROMPT_JSON_NAME
    markdown_path = root / NEXT_PROMPT_MARKDOWN_NAME
    _write_json_atomic(json_path, payload)
    _write_text_atomic(markdown_path, _render_next_prompt_markdown(payload))

    launchable = _launchable_with_normalized_context(payload, ready_for_operator_launch)
    updated_trigger = dict(trigger)
    updated_trigger.update(
        {
            "next_prompt_path": str(markdown_path.resolve()),
            "next_prompt_json_path": str(json_path.resolve()),
            "ready_for_operator_launch": launchable,
            "generated_at": payload["generated_at"],
            "source_artifacts_used": payload["source_artifacts_used"],
            "obsidian_context_used": payload["obsidian_context_used"],
            "continuity_context_normalized": bool((payload.get("obsidian_context_used") or {}).get("normalized")),
            "model_name": payload["model_name"],
            "orchestration_status": payload["orchestration_status"],
            "gate_failure": payload["gate_failure"],
            "command": payload.get("approval_command") or updated_trigger.get("command"),
            "target_run_id": payload.get("pending_run_id") or updated_trigger.get("target_run_id"),
            "approved_at": payload.get("approval_applied_at") or updated_trigger.get("approved_at"),
            "next_action": _next_action_for_payload(payload, launchable),
            "launch_gate_status": _launch_gate_status(payload, launchable),
        }
    )
    if payload["gate_failure"]:
        updated_trigger["reason"] = payload["gate_failure"].get("reason")
    elif not launchable and ready_for_operator_launch:
        updated_trigger["reason"] = "Next prompt is advisory only until normalized Obsidian continuity context is restored."
    else:
        updated_trigger["reason"] = None
    _write_json_atomic(root / TRIGGER_NEXT_RUN_NAME, updated_trigger)
    return {
        "status": payload["orchestration_status"],
        "next_prompt_json_path": str(json_path.resolve()),
        "next_prompt_path": str(markdown_path.resolve()),
        "trigger_path": str((root / TRIGGER_NEXT_RUN_NAME).resolve()),
        "ready_for_operator_launch": launchable,
        "gate_failure": payload["gate_failure"],
    }


def _render_next_prompt_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Control Tower Next Prompt",
        "",
        f"- Generated At: {payload['generated_at']}",
        f"- Orchestration Status: {payload['orchestration_status']}",
        f"- Pending Run ID: {payload.get('pending_run_id') or 'unknown'}",
        f"- Approval Status: {payload.get('approval_status') or 'unknown'}",
        f"- Model: {payload.get('model_name') or 'not_used'}",
        "",
    ]
    gate_failure = payload.get("gate_failure")
    if gate_failure:
        lines.extend(
            [
                "## Gate Failure",
                "",
                f"- Gate: {gate_failure.get('gate') or 'unknown'}",
                f"- Reason: {gate_failure.get('reason') or 'No reason recorded.'}",
                "",
                "No next lane may be launched until this gate is cleared.",
                "",
            ]
        )
    next_prompt = payload.get("next_prompt") or {}
    if next_prompt:
        lines.extend(
            [
                "## Strategic Alignment",
                "",
                next_prompt["strategic_alignment_summary"],
                "",
                "## Objective",
                "",
                next_prompt["objective"],
                "",
                "## Scope",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in next_prompt["scope"])
        lines.extend(["", "## Constraints", ""])
        lines.extend(f"- {item}" for item in next_prompt["constraints"])
        lines.extend(
            [
                "",
                "## Stop Condition",
                "",
                next_prompt["stop_condition"],
                "",
                "## Deliverable Format",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in next_prompt["deliverable_format"])
        lines.extend(["", "## Recommended Commands", ""])
        lines.extend(f"- {item}" for item in next_prompt["recommended_commands"])
        lines.extend(
            [
                "",
                "## Prompt Markdown",
                "",
                next_prompt["prompt_markdown"],
                "",
                f"Requires operator approval after release: {next_prompt['requires_operator_approval_after_release']}",
                f"Continuation mode: {next_prompt['continuation_mode']}",
                "",
            ]
        )
    else:
        lines.extend(["No machine-generated next prompt is available yet.", ""])

    lines.extend(["## Source Artifacts Used", ""])
    for artifact in payload.get("source_artifacts_used") or []:
        lines.append(f"- {artifact}")
    if not payload.get("source_artifacts_used"):
        lines.append("- No source artifacts were recorded.")

    obsidian_context = payload.get("obsidian_context_used") or {}
    lines.extend(["", "## Obsidian Context", ""])
    lines.append(f"- Status: {obsidian_context.get('status') or 'unknown'}")
    lines.append(f"- Normalized: {obsidian_context.get('normalized') is True}")
    lines.append(f"- Parsed At: {obsidian_context.get('parsed_at') or 'unknown'}")
    lines.append(f"- Continuity Root: {obsidian_context.get('continuity_root') or 'unknown'}")
    for note_path in obsidian_context.get("note_paths") or []:
        lines.append(f"- Note: {note_path}")
    return "\n".join(lines) + "\n"


def _extract_output_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    for item in payload.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text
            if isinstance(text, dict) and isinstance(text.get("value"), str) and text.get("value", "").strip():
                return str(text["value"])
            if isinstance(content.get("value"), str) and content.get("value", "").strip():
                return str(content["value"])
    raise PromptOrchestrationError(
        "OpenAI Responses API response did not contain structured text output.",
        gate="openai_generation",
        details={"payload_keys": sorted(payload.keys())},
    )


def _system_prompt() -> str:
    return (
        "Generate the next Control Tower lane prompt.\n"
        "Rules:\n"
        "- Control Tower artifacts are the authoritative execution truth.\n"
        "- Obsidian checkout is the authoritative strategic continuity and operator intent.\n"
        "- Consume both sources together and do not ignore either.\n"
        "- Do not redesign release, approval, notification, or downstream execution architecture.\n"
        "- Stay inside V1 and V2 scope only.\n"
        "- Keep the next lane deterministic, artifact-backed, and production-grade.\n"
        "- The prompt_markdown must explicitly require successful Obsidian checkout before work starts.\n"
        "- The prompt_markdown must explicitly require successful Obsidian check-in before closeout.\n"
        "- deliverable_format must align to these headings: UNDERSTANDING, FILES MODIFIED, FILES CREATED, COMMANDS RUN, TEST RESULTS, OBSIDIAN CHECK-OUT DESIGN, OBSIDIAN CHECK-IN DESIGN, PROMPT ORCHESTRATION BEHAVIOR, GATING / FAILURE MODES, OPEN RISKS, NEXT RECOMMENDED STEP.\n"
        "- recommended_commands must be concrete repository commands.\n"
        "- Return only the strict schema payload."
    )


def _default_orchestration_root() -> Path:
    return Path(__file__).resolve().parents[3] / "ops" / "orchestration"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(path, json.dumps(payload, indent=2))


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(content, encoding="utf-8", newline="\n")
    temp_path.replace(path)

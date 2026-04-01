from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from controltower.domain.models import utc_now_iso


CHECKOUT_MAX_NOTES = 5
CHECKOUT_MAX_NOTE_CHARS = 12000
CHECKOUT_MAX_TOTAL_CHARS = 40000
ACTIVE_CONTROL_START_MARKER = "<!-- controltower:active-lane-checkin:start -->"
ACTIVE_CONTROL_END_MARKER = "<!-- controltower:active-lane-checkin:end -->"

_FIELD_SPECS: dict[str, dict[str, Any]] = {
    "phase": {"aliases": {"phase"}, "list": False},
    "current_objective": {"aliases": {"current objective", "current_objective"}, "list": False},
    "why_this_matters": {"aliases": {"why this matters", "why_this_matters"}, "list": False},
    "in_scope": {"aliases": {"in scope", "in_scope"}, "list": True},
    "out_of_scope": {"aliases": {"out of scope", "out_of_scope"}, "list": True},
    "known_risks": {"aliases": {"known risks", "known_risks"}, "list": True},
    "acceptance_bar": {"aliases": {"acceptance bar", "acceptance_bar"}, "list": True},
    "last_accepted_release": {"aliases": {"last accepted release", "last_accepted_release"}, "list": False},
    "next_strategic_target": {"aliases": {"next strategic target", "next_strategic_target"}, "list": False},
}


class ObsidianContinuityError(ValueError):
    pass


class ObsidianCheckout(BaseModel):
    phase: str
    current_objective: str
    why_this_matters: str
    in_scope: list[str] = Field(min_length=1)
    out_of_scope: list[str] = Field(min_length=1)
    known_risks: list[str] = Field(min_length=1)
    acceptance_bar: list[str] = Field(min_length=1)
    last_accepted_release: str
    next_strategic_target: str


class ObsidianCheckoutResult(BaseModel):
    parsed_at: str
    continuity_root: str
    note_paths: list[str]
    checkout: ObsidianCheckout


class ObsidianLaneCheckin(BaseModel):
    run_id: str
    lane_summary: str
    files_or_surfaces_changed: list[str]
    release_result: str
    approval_result: str
    open_risks: list[str]
    next_recommended_lane: str
    strategic_alignment_note: str
    completed_at: str | None = None


class ObsidianCheckinResult(BaseModel):
    written_at: str
    continuity_root: str
    session_log_path: str
    active_control_note_path: str


def read_checkout_bundle(*, continuity_root: Path, note_paths: list[str]) -> ObsidianCheckoutResult:
    root = Path(continuity_root).resolve()
    normalized_note_paths = [str(item).strip().replace("\\", "/") for item in note_paths if str(item).strip()]
    if not normalized_note_paths:
        raise ObsidianContinuityError("Obsidian checkout note paths are not configured.")
    if len(normalized_note_paths) > CHECKOUT_MAX_NOTES:
        raise ObsidianContinuityError(f"Obsidian checkout bundle exceeds the limit of {CHECKOUT_MAX_NOTES} notes.")

    merged: dict[str, Any] = {}
    resolved_paths: list[str] = []
    total_chars = 0

    for relative_path in normalized_note_paths:
        note_path = _resolve_within_root(root, relative_path)
        if not note_path.exists():
            raise ObsidianContinuityError(f"Obsidian checkout note is missing: {note_path}")
        text = note_path.read_text(encoding="utf-8")
        if len(text) > CHECKOUT_MAX_NOTE_CHARS:
            raise ObsidianContinuityError(f"Obsidian checkout note exceeds {CHECKOUT_MAX_NOTE_CHARS} characters: {note_path}")
        total_chars += len(text)
        if total_chars > CHECKOUT_MAX_TOTAL_CHARS:
            raise ObsidianContinuityError("Obsidian checkout bundle exceeds the maximum combined size.")
        resolved_paths.append(str(note_path))
        parsed = _parse_checkout_note(text)
        for field_name in _FIELD_SPECS:
            if field_name not in merged and parsed.get(field_name):
                merged[field_name] = parsed[field_name]

    missing = [field_name for field_name in _FIELD_SPECS if not merged.get(field_name)]
    if missing:
        raise ObsidianContinuityError(
            "Obsidian checkout is missing required fields: " + ", ".join(sorted(missing))
        )

    checkout = ObsidianCheckout.model_validate(merged)
    return ObsidianCheckoutResult(
        parsed_at=utc_now_iso(),
        continuity_root=str(root),
        note_paths=resolved_paths,
        checkout=checkout,
    )


def write_lane_checkin(
    *,
    continuity_root: Path,
    active_control_note: str,
    session_log_dir: str,
    active_control_section_heading: str,
    payload: ObsidianLaneCheckin,
) -> ObsidianCheckinResult:
    root = Path(continuity_root).resolve()
    written_at = utc_now_iso()
    safe_run_id = _sanitize_filename(payload.run_id)
    completed_at = (payload.completed_at or written_at).replace(":", "-")
    session_log_path = _resolve_within_root(root, f"{session_log_dir}/{completed_at}_{safe_run_id}.md")
    active_control_path = _resolve_within_root(root, active_control_note)

    session_log_markdown = _render_session_log_markdown(payload, written_at=written_at)
    active_control_block = _render_active_control_block(
        payload,
        written_at=written_at,
        section_heading=active_control_section_heading,
        session_log_path=session_log_path,
        continuity_root=root,
    )

    _write_text_atomic(session_log_path, session_log_markdown)
    existing = active_control_path.read_text(encoding="utf-8") if active_control_path.exists() else ""
    updated = _replace_active_control_block(
        existing,
        block=active_control_block,
        section_heading=active_control_section_heading,
    )
    _write_text_atomic(active_control_path, updated)

    return ObsidianCheckinResult(
        written_at=written_at,
        continuity_root=str(root),
        session_log_path=str(session_log_path),
        active_control_note_path=str(active_control_path),
    )


def _parse_checkout_note(text: str) -> dict[str, Any]:
    frontmatter, body = _split_frontmatter(text)
    parsed: dict[str, Any] = {}
    for field_name, spec in _FIELD_SPECS.items():
        value = _frontmatter_value(frontmatter, spec["aliases"])
        if value is not None:
            parsed[field_name] = _normalize_field_value(value, list_expected=spec["list"])

    parsed.update(_parse_markdown_sections(body))
    return parsed


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text
    lines = stripped.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    closing_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        raise ObsidianContinuityError("Obsidian checkout frontmatter is not closed with '---'.")
    raw_frontmatter = "\n".join(lines[1:closing_index])
    body = "\n".join(lines[closing_index + 1 :])
    loaded = yaml.safe_load(raw_frontmatter) or {}
    if not isinstance(loaded, dict):
        raise ObsidianContinuityError("Obsidian checkout frontmatter must be a mapping.")
    return loaded, body


def _parse_markdown_sections(body: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    active_field: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal active_field, buffer
        if active_field is None:
            buffer = []
            return
        spec = _FIELD_SPECS[active_field]
        value = _normalize_field_value("\n".join(buffer), list_expected=spec["list"])
        if value:
            parsed.setdefault(active_field, value)
        buffer = []

    for line in body.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*$", line)
        if match:
            flush()
            active_field = _canonical_field(match.group(1))
            continue
        if active_field is not None:
            buffer.append(line)
    flush()
    return parsed


def _frontmatter_value(frontmatter: dict[str, Any], aliases: set[str]) -> Any | None:
    for key, value in frontmatter.items():
        if _normalize_key(key) in aliases:
            return value
    return None


def _canonical_field(raw_heading: str) -> str | None:
    normalized = _normalize_key(raw_heading)
    for field_name, spec in _FIELD_SPECS.items():
        if normalized in spec["aliases"]:
            return field_name
    return None


def _normalize_key(value: Any) -> str:
    return " ".join(str(value).strip().lower().replace("-", " ").replace("_", " ").split())


def _normalize_field_value(value: Any, *, list_expected: bool) -> Any:
    if list_expected:
        return _normalize_list(value)
    return _normalize_text(value)


def _normalize_text(value: Any) -> str | None:
    if isinstance(value, list):
        value = " ".join(str(item).strip() for item in value if str(item).strip())
    if value is None:
        return None
    parts: list[str] = []
    for line in str(value).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^[-*]\s+", "", stripped)
        stripped = re.sub(r"^\d+\.\s+", "", stripped)
        parts.append(stripped)
    text = " ".join(parts)
    return text or None


def _normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        items = []
        for line in str(value or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            stripped = re.sub(r"^[-*]\s+", "", stripped)
            stripped = re.sub(r"^\d+\.\s+", "", stripped)
            items.append(stripped)
    return items


def _render_session_log_markdown(payload: ObsidianLaneCheckin, *, written_at: str) -> str:
    lines = [
        "---",
        "title: Control Tower Lane Session Log",
        "type: controltower_lane_session_log",
        f"run_id: {payload.run_id}",
        f"written_at: {written_at}",
        f"completed_at: {payload.completed_at or written_at}",
        "---",
        "",
        "# Control Tower Lane Session Log",
        "",
        f"- Run ID: {payload.run_id}",
        f"- Written At: {written_at}",
        f"- Completed At: {payload.completed_at or written_at}",
        f"- Release Result: {payload.release_result}",
        f"- Approval Result: {payload.approval_result}",
        "",
        "## Lane Summary",
        "",
        payload.lane_summary,
        "",
        "## Files / Surfaces Changed",
        "",
    ]
    lines.extend(f"- {item}" for item in payload.files_or_surfaces_changed or ["No changed files or surfaces were reported."])
    lines.extend(
        [
            "",
            "## Open Risks",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in payload.open_risks or ["No open risks were recorded."])
    lines.extend(
        [
            "",
            "## Next Recommended Lane",
            "",
            payload.next_recommended_lane,
            "",
            "## Strategic Alignment Note",
            "",
            payload.strategic_alignment_note,
            "",
        ]
    )
    return "\n".join(lines)


def _render_active_control_block(
    payload: ObsidianLaneCheckin,
    *,
    written_at: str,
    section_heading: str,
    session_log_path: Path,
    continuity_root: Path,
) -> str:
    try:
        session_log_reference = session_log_path.relative_to(continuity_root).as_posix()
    except ValueError:
        session_log_reference = session_log_path.name
    lines = [
        section_heading,
        "",
        ACTIVE_CONTROL_START_MARKER,
        f"- Updated At: {written_at}",
        f"- Run ID: {payload.run_id}",
        f"- Release Result: {payload.release_result}",
        f"- Approval Result: {payload.approval_result}",
        f"- Lane Summary: {payload.lane_summary}",
        f"- Next Recommended Lane: {payload.next_recommended_lane}",
        f"- Strategic Alignment: {payload.strategic_alignment_note}",
        f"- Session Log Note: {session_log_reference}",
        "",
        "### Open Risks",
        "",
    ]
    lines.extend(f"- {item}" for item in payload.open_risks or ["No open risks were recorded."])
    lines.extend(["", ACTIVE_CONTROL_END_MARKER, ""])
    return "\n".join(lines)


def _replace_active_control_block(existing: str, *, block: str, section_heading: str) -> str:
    if ACTIVE_CONTROL_START_MARKER in existing and ACTIVE_CONTROL_END_MARKER in existing:
        pattern = re.compile(
            rf"{re.escape(section_heading)}\s*\n.*?{re.escape(ACTIVE_CONTROL_END_MARKER)}\s*",
            re.DOTALL,
        )
        if pattern.search(existing):
            return pattern.sub(block, existing, count=1).rstrip() + "\n"
        range_pattern = re.compile(
            rf"{re.escape(ACTIVE_CONTROL_START_MARKER)}.*?{re.escape(ACTIVE_CONTROL_END_MARKER)}\s*",
            re.DOTALL,
        )
        return range_pattern.sub(block, existing, count=1).rstrip() + "\n"
    content = existing.rstrip()
    if content:
        content += "\n\n"
    return content + block.strip() + "\n"


def _resolve_within_root(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ObsidianContinuityError(f"Configured Obsidian continuity path escapes the continuity root: {relative_path}") from exc
    return candidate


def _sanitize_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value) or "lane"


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(content, encoding="utf-8", newline="\n")
    temp_path.replace(path)

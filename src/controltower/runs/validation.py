from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from controltower.domain.models import utc_now_iso

VALIDATION_JSON_FILENAME = "operator_validation.json"
VALIDATION_MD_FILENAME = "operator_validation.md"
VALIDATION_SCHEMA_VERSION = "operator_validation_v1"
VALIDATION_CATEGORIES = (
    "entry_upload_flow",
    "command_brief_clarity",
    "evidence_precision",
    "graph_comprehension",
    "interaction_flow",
    "export_usefulness",
    "stakeholder_readability",
)


def validation_artifact_paths(state_root: Path, run_id: str) -> tuple[Path, Path]:
    artifacts = Path(state_root) / "runs" / run_id / "artifacts"
    return artifacts / VALIDATION_JSON_FILENAME, artifacts / VALIDATION_MD_FILENAME


def load_validation_note(state_root: Path, run_id: str) -> dict[str, Any] | None:
    json_path, _ = validation_artifact_paths(state_root, run_id)
    if not json_path.exists() or not json_path.is_file():
        return None
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def save_validation_note(
    state_root: Path,
    *,
    run_id: str,
    reviewer: str,
    schedule_source: str,
    meeting_context: str,
    category_scores: dict[str, int],
    category_notes: dict[str, str],
    open_friction: str,
    high_value_hardening: str,
) -> dict[str, Any]:
    now = utc_now_iso()
    scores = {k: int(max(1, min(5, int(category_scores.get(k, 3))))) for k in VALIDATION_CATEGORIES}
    notes = {k: str(category_notes.get(k, "")).strip()[:600] for k in VALIDATION_CATEGORIES}
    payload: dict[str, Any] = {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "run_id": run_id,
        "saved_at": now,
        "reviewer": reviewer.strip()[:120],
        "schedule_source": schedule_source.strip()[:240],
        "meeting_context": meeting_context.strip()[:240],
        "category_scores": scores,
        "category_notes": notes,
        "open_friction": open_friction.strip()[:2000],
        "high_value_hardening": high_value_hardening.strip()[:2000],
    }
    json_path, md_path = validation_artifact_paths(state_root, run_id)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    md_path.write_text(_render_validation_markdown(payload), encoding="utf-8")
    return payload


def _render_validation_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Operator Validation",
        "",
        f"- Run ID: `{payload.get('run_id', '')}`",
        f"- Saved At: `{payload.get('saved_at', '')}`",
        f"- Reviewer: {payload.get('reviewer', '') or 'n/a'}",
        f"- Schedule Source: {payload.get('schedule_source', '') or 'n/a'}",
        f"- Meeting Context: {payload.get('meeting_context', '') or 'n/a'}",
        "",
        "## Friction Scores",
    ]
    scores = payload.get("category_scores") or {}
    notes = payload.get("category_notes") or {}
    for key in VALIDATION_CATEGORIES:
        lines.append(f"- `{key}`: {scores.get(key, 3)}/5")
        note = str(notes.get(key, "")).strip()
        if note:
            lines.append(f"  - note: {note}")
    lines.extend(
        [
            "",
            "## Open Friction",
            str(payload.get("open_friction", "")).strip() or "None recorded.",
            "",
            "## High-Value Hardening",
            str(payload.get("high_value_hardening", "")).strip() or "None recorded.",
            "",
        ]
    )
    return "\n".join(lines)

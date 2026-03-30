from __future__ import annotations

import json
from pathlib import Path

from controltower.domain.models import ExportRecord, GeneratedNote, PortfolioSummary, ProjectDelta, ProjectSnapshot, SourceArtifactRef
from controltower.services.runtime_state import ensure_runtime_layout, refresh_artifact_index


def write_export_bundle(
    *,
    run_id: str,
    generated_at: str,
    notes: list[GeneratedNote],
    vault_root: Path,
    state_root: Path,
    preview_only: bool,
    timestamped_weekly_notes: bool = False,
    exports_folder: str = "10 Exports",
    source_artifacts: list[SourceArtifactRef],
    issues: list[str] | None = None,
    previous_run_id: str | None = None,
    portfolio_snapshot: PortfolioSummary | None = None,
    project_snapshots: list[ProjectSnapshot] | None = None,
    project_deltas: list[ProjectDelta] | None = None,
) -> ExportRecord:
    ensure_runtime_layout(state_root)
    state_root.mkdir(parents=True, exist_ok=True)
    run_root = state_root / "runs" / run_id
    previews_root = run_root / "previews"
    history_root = state_root / "history"
    previews_root.mkdir(parents=True, exist_ok=True)
    history_root.mkdir(parents=True, exist_ok=True)

    written_notes: list[GeneratedNote] = []
    for note in notes:
        preview_path = previews_root / note.output_path
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_text(note.body, encoding="utf-8", newline="\n")
        output_path = vault_root / note.output_path
        versioned_paths = _versioned_paths(
            note=note,
            generated_at=generated_at,
            enabled=timestamped_weekly_notes,
            exports_folder=exports_folder,
            vault_root=vault_root,
        )
        if not preview_only:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(note.body, encoding="utf-8", newline="\n")
            for extra_path in versioned_paths:
                extra_path.parent.mkdir(parents=True, exist_ok=True)
                extra_path.write_text(note.body, encoding="utf-8", newline="\n")
        written_notes.append(
            note.model_copy(update={"preview_path": preview_path, "output_path": output_path, "versioned_output_paths": versioned_paths})
        )

    status = "success" if not (issues or []) else "partial"
    record = ExportRecord(
        run_id=run_id,
        generated_at=generated_at,
        preview_only=preview_only,
        notes=written_notes,
        vault_root=str(vault_root),
        status=status,
        issues=list(issues or []),
        source_artifacts=source_artifacts,
        previous_run_id=previous_run_id,
        portfolio_snapshot=portfolio_snapshot,
        project_snapshots=list(project_snapshots or []),
        project_deltas=list(project_deltas or []),
    )

    manifest_path = run_root / "manifest.json"
    manifest_path.write_text(json.dumps(record.model_dump(mode="json"), indent=2), encoding="utf-8")
    history_path = history_root / f"{run_id}.json"
    history_path.write_text(json.dumps(record.model_dump(mode="json"), indent=2), encoding="utf-8")
    latest_path = state_root / "latest_run.json"
    latest_path.write_text(json.dumps(record.model_dump(mode="json"), indent=2), encoding="utf-8")
    refresh_artifact_index(state_root)
    return record


def load_latest_export(state_root: Path) -> dict | None:
    latest_path = Path(state_root) / "latest_run.json"
    if not latest_path.exists():
        return None
    return json.loads(latest_path.read_text(encoding="utf-8"))


def _versioned_paths(
    *,
    note: GeneratedNote,
    generated_at: str,
    enabled: bool,
    exports_folder: str,
    vault_root: Path,
) -> list[Path]:
    if not enabled:
        return []
    run_date = generated_at[:10]
    weekly_root = vault_root / "Weekly" / run_date
    safe_title = note.title.replace("/", "_").replace("\\", "_")
    if note.note_kind == "portfolio_weekly_summary":
        return [
            weekly_root / f"{safe_title}.md",
            vault_root / exports_folder / f"{run_date} - {safe_title}.md",
        ]
    if note.canonical_project_code:
        safe_project = note.canonical_project_code.replace("/", "_").replace("\\", "_")
        return [weekly_root / "Projects" / safe_project / f"{safe_title}.md"]
    return [weekly_root / f"{safe_title}.md"]

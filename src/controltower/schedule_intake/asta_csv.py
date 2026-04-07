from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .models import Activity


# Exact CSV headers for the current authoritative Asta export
ASTA_EXPORT_HEADERS: tuple[str, ...] = (
    "Task ID",
    "Task name",
    "Unique task ID",
    "Duration",
    "Duration remaining",
    "Start",
    "Finish",
    "Early start",
    "Early finish",
    "Late start",
    "Late finish",
    "Total float",
    "Free float",
    "Critical",
    "Predecessors",
    "Successors",
    "Critical path drag",
    "Phase Exec",
    "Control Account",
    "Area Zone",
    "Level",
    "CSI",
    "System",
    "Percent complete",
    "Original start",
    "Original finish",
)


@dataclass
class AstaParseResult:
    activities: list[Activity] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _normalize_scalar_cell(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = raw.strip()
    if s == "" or s.upper() == "<NONE>":
        return None
    return s


def _parse_days_optional(raw: str | None, *, row_label: str, field_name: str, warnings: list[str]) -> float | None:
    cell = _normalize_scalar_cell(raw)
    if cell is None:
        return None
    lowered = cell.strip().lower()
    if lowered.endswith("d"):
        lowered = lowered[:-1].strip()
    try:
        return float(lowered)
    except ValueError:
        warnings.append(f"{row_label}: cannot parse {field_name!r} as day value ({cell!r})")
        return None


def _parse_date_optional(raw: str | None, *, row_label: str, field_name: str, warnings: list[str]) -> datetime | None:
    cell = _normalize_scalar_cell(raw)
    if cell is None:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(cell, fmt)
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            continue
    warnings.append(f"{row_label}: cannot parse {field_name!r} as date ({cell!r})")
    return None


def _parse_bool_optional(raw: str | None, *, row_label: str, field_name: str, warnings: list[str]) -> bool | None:
    cell = _normalize_scalar_cell(raw)
    if cell is None:
        return None
    up = cell.upper()
    if up in {"TRUE", "T", "YES", "Y", "1"}:
        return True
    if up in {"FALSE", "F", "NO", "N", "0"}:
        return False
    warnings.append(f"{row_label}: cannot parse {field_name!r} as boolean ({cell!r})")
    return None


def _parse_percent_optional(raw: str | None, *, row_label: str, field_name: str, warnings: list[str]) -> float | None:
    cell = _normalize_scalar_cell(raw)
    if cell is None:
        return None
    cleaned = cell.replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        warnings.append(f"{row_label}: cannot parse {field_name!r} as percent ({cell!r})")
        return None


def _parse_id_list(raw: str | None) -> list[str] | None:
    """Blank or <None> field -> None; otherwise split comma-separated IDs (trimmed)."""
    if raw is None:
        return None
    s = raw.strip()
    if s == "" or s.upper() == "<NONE>":
        return None
    parts = [p.strip() for p in s.split(",")]
    out = [p for p in parts if p and p.upper() != "<NONE>"]
    return out


def parse_asta_export_csv(path: Path | str, *, encoding: str = "utf-8-sig") -> AstaParseResult:
    """
    Read an Asta CSV export and return activities plus row-level warnings.

    Rows without a usable Task ID are skipped.
    """
    csv_path = Path(path)
    warnings: list[str] = []
    activities: list[Activity] = []

    with csv_path.open(newline="", encoding=encoding) as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            warnings.append("CSV has no header row")
            return AstaParseResult(activities=[], warnings=warnings)

        header_set = set(reader.fieldnames)
        missing = [h for h in ASTA_EXPORT_HEADERS if h not in header_set]
        if missing:
            warnings.append(f"Missing expected column(s): {', '.join(missing)}")

        for i, row in enumerate(reader, start=2):
            task_raw = row.get("Task ID")
            task_id_norm = _normalize_scalar_cell(task_raw)
            row_label = f"row {i}"
            if task_id_norm is None:
                warnings.append(f"{row_label}: skipped - missing Task ID")
                continue

            preds = _parse_id_list(row.get("Predecessors"))
            succs = _parse_id_list(row.get("Successors"))

            try:
                act = Activity(
                    task_id=task_id_norm,
                    task_name=_normalize_scalar_cell(row.get("Task name")),
                    unique_task_id=_normalize_scalar_cell(row.get("Unique task ID")),
                    duration_days=_parse_days_optional(
                        row.get("Duration"), row_label=row_label, field_name="Duration", warnings=warnings
                    ),
                    duration_remaining_days=_parse_days_optional(
                        row.get("Duration remaining"),
                        row_label=row_label,
                        field_name="Duration remaining",
                        warnings=warnings,
                    ),
                    start=_parse_date_optional(
                        row.get("Start"), row_label=row_label, field_name="Start", warnings=warnings
                    ),
                    finish=_parse_date_optional(
                        row.get("Finish"), row_label=row_label, field_name="Finish", warnings=warnings
                    ),
                    early_start=_parse_date_optional(
                        row.get("Early start"), row_label=row_label, field_name="Early start", warnings=warnings
                    ),
                    early_finish=_parse_date_optional(
                        row.get("Early finish"), row_label=row_label, field_name="Early finish", warnings=warnings
                    ),
                    late_start=_parse_date_optional(
                        row.get("Late start"), row_label=row_label, field_name="Late start", warnings=warnings
                    ),
                    late_finish=_parse_date_optional(
                        row.get("Late finish"), row_label=row_label, field_name="Late finish", warnings=warnings
                    ),
                    total_float_days=_parse_days_optional(
                        row.get("Total float"), row_label=row_label, field_name="Total float", warnings=warnings
                    ),
                    free_float_days=_parse_days_optional(
                        row.get("Free float"), row_label=row_label, field_name="Free float", warnings=warnings
                    ),
                    critical=_parse_bool_optional(
                        row.get("Critical"), row_label=row_label, field_name="Critical", warnings=warnings
                    ),
                    predecessors=preds,
                    successors=succs,
                    critical_path_drag_days=_parse_days_optional(
                        row.get("Critical path drag"),
                        row_label=row_label,
                        field_name="Critical path drag",
                        warnings=warnings,
                    ),
                    phase_exec=_normalize_scalar_cell(row.get("Phase Exec")),
                    control_account=_normalize_scalar_cell(row.get("Control Account")),
                    area_zone=_normalize_scalar_cell(row.get("Area Zone")),
                    level=_normalize_scalar_cell(row.get("Level")),
                    csi=_normalize_scalar_cell(row.get("CSI")),
                    system=_normalize_scalar_cell(row.get("System")),
                    percent_complete=_parse_percent_optional(
                        row.get("Percent complete"),
                        row_label=row_label,
                        field_name="Percent complete",
                        warnings=warnings,
                    ),
                    original_start=_parse_date_optional(
                        row.get("Original start"),
                        row_label=row_label,
                        field_name="Original start",
                        warnings=warnings,
                    ),
                    original_finish=_parse_date_optional(
                        row.get("Original finish"),
                        row_label=row_label,
                        field_name="Original finish",
                        warnings=warnings,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 — intake must not crash the whole file
                warnings.append(f"{row_label}: skipped - could not build Activity ({exc})")
                continue

            activities.append(act)

    return AstaParseResult(activities=activities, warnings=warnings)

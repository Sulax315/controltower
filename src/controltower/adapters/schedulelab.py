from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from controltower.domain.models import ScheduleDriver, ScheduleSummary, SourceArtifactRef, TrustIndicator


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class ScheduleLabAdapter:
    def __init__(self, published_root: Path) -> None:
        self.published_root = Path(published_root)

    def validate(self) -> list[str]:
        issues: list[str] = []
        if not self.published_root.exists():
            issues.append(f"ScheduleLab published root is missing: {self.published_root}")
            return issues
        feed = self.published_root / "portfolio_outputs" / "portfolio_feed.json"
        if not feed.exists():
            issues.append(f"ScheduleLab portfolio feed is missing: {feed}")
        runs_root = self.published_root / "runs"
        if not runs_root.exists():
            issues.append(f"ScheduleLab runs root is missing: {runs_root}")
        return issues

    def list_projects(self) -> list[ScheduleSummary]:
        feed_path = self.published_root / "portfolio_outputs" / "portfolio_feed.json"
        if feed_path.exists():
            payload = _read_json(feed_path)
            items = payload.get("projects") or []
            summaries: list[ScheduleSummary] = []
            for item in items:
                project_code = str(item.get("project_code") or "").strip()
                if not project_code:
                    continue
                summaries.append(self.load_project(project_code))
            if summaries:
                return summaries
        runs_root = self.published_root / "runs"
        if not runs_root.exists():
            return []
        return [self.load_project(path.name) for path in sorted(runs_root.iterdir()) if path.is_dir()]

    def load_project(self, project_code: str) -> ScheduleSummary:
        outputs_dir = self.published_root / "runs" / project_code / "outputs"
        return load_schedule_from_outputs(outputs_dir, relative_root=self.published_root, project_code_hint=project_code)


def load_schedule_from_outputs(
    outputs_dir: Path,
    *,
    relative_root: Path | None = None,
    project_code_hint: str = "",
) -> ScheduleSummary:
    dashboard_path = outputs_dir / "dashboard_feed.json"
    summary_path = outputs_dir / "summary.json"
    run_manifest_path = outputs_dir / "run_manifest.json"
    actions_path = outputs_dir / "management_actions.json"
    brief_path = outputs_dir / "management_brief.md"
    milestone_drift_path = outputs_dir / "milestone_drift_log.csv"

    dashboard = _read_json(dashboard_path) if dashboard_path.exists() else {}
    summary = _read_json(summary_path) if summary_path.exists() else {}
    run_manifest = _read_json(run_manifest_path) if run_manifest_path.exists() else {}
    actions = _read_json(actions_path) if actions_path.exists() else {}

    project = dashboard.get("project") or run_manifest.get("project") or {}
    summary_block = dashboard.get("summary") or summary
    management = dashboard.get("management") or {}
    trend = dashboard.get("trend") or {}
    current = trend.get("current") or {}
    finish_metadata = _resolve_finish_metadata(
        project=project,
        summary_block=summary_block,
        current=current,
        outputs_dir=outputs_dir,
    )
    total_float_days = _safe_float(
        summary_block.get("total_float_days")
        or summary_block.get("critical_path_float_days")
        or current.get("total_float_days")
    )
    critical_path_activity_count = _safe_int(
        summary_block.get("critical_path_activity_count")
        or management.get("critical_path_activity_count")
        or current.get("critical_path_activity_count")
        or current.get("critical_path_count")
    )

    top_drivers_input = dashboard.get("top_drivers") or actions.get("top_10_driver_activities") or []
    top_drivers = [
        ScheduleDriver(
            label=f"{item.get('activity_id')} - {item.get('activity_name')}".strip(" -"),
            activity_id=_optional_str(item.get("activity_id")),
            activity_name=_optional_str(item.get("activity_name")),
            score=_safe_float(item.get("driver_score") or item.get("risk_score")),
            rationale=str(item.get("driver_reasons") or item.get("why_it_matters") or ""),
        )
        for item in top_drivers_input[:5]
    ]

    missing: list[str] = []
    if not dashboard_path.exists():
        missing.append("dashboard_feed")
    if not summary_path.exists():
        missing.append("summary")
    if not run_manifest_path.exists():
        missing.append("run_manifest")

    parser_warning_count = _safe_int(summary_block.get("parser_warning_count"))
    trust_status = "high"
    trust_rationale: list[str] = []
    if missing:
        trust_status = "partial"
        trust_rationale.append("Missing published schedule artifacts: " + ", ".join(missing))
    if parser_warning_count and parser_warning_count > 100:
        trust_status = "partial"
        trust_rationale.append(f"Parser warnings are elevated at {parser_warning_count}.")
    if not outputs_dir.exists():
        trust_status = "low"
        trust_rationale.append("Project outputs directory is missing.")

    provenance = [
        _artifact("schedulelab", "schedule_dashboard_feed", dashboard_path, relative_root),
        _artifact("schedulelab", "schedule_summary", summary_path, relative_root),
        _artifact("schedulelab", "schedule_run_manifest", run_manifest_path, relative_root),
        _artifact("schedulelab", "schedule_management_actions", actions_path, relative_root),
        _artifact("schedulelab", "schedule_management_brief", brief_path, relative_root),
        _artifact("schedulelab", "schedule_milestone_drift_log", milestone_drift_path, relative_root),
    ]

    return ScheduleSummary(
        project_code=str(project.get("project_code") or project_code_hint),
        project_name=str(project.get("project_name") or summary_block.get("project_name") or project_code_hint),
        run_timestamp=str((dashboard.get("run") or {}).get("run_timestamp") or run_manifest.get("run_timestamp") or current.get("run_timestamp") or ""),
        schedule_date=_optional_str(project.get("schedule_date") or summary_block.get("schedule_date")),
        finish_date=finish_metadata["finish_date"],
        finish_source=finish_metadata["finish_source"],
        finish_source_label=finish_metadata["finish_source_label"],
        finish_detail=finish_metadata["finish_detail"],
        finish_artifact_path=finish_metadata["finish_artifact_path"],
        finish_activity_id=finish_metadata["finish_activity_id"],
        finish_activity_name=finish_metadata["finish_activity_name"],
        health_score=_safe_float(dashboard.get("health_score") or summary_block.get("overall_health_score")),
        issues_total=_safe_int(dashboard.get("issues_total") or current.get("issues_total")),
        activity_count=_safe_int(summary_block.get("activity_count")),
        relationship_count=_safe_int(summary_block.get("relationship_count")),
        negative_float_count=_safe_int(summary_block.get("negative_float_count")),
        open_start_count=_safe_int(summary_block.get("open_start_count")),
        open_finish_count=_safe_int(summary_block.get("open_finish_count")),
        cycle_count=_safe_int(summary_block.get("cycle_count")),
        top_driver_count=_safe_int(current.get("top_driver_count") or len(top_drivers)),
        risk_path_count=_safe_int((management or {}).get("risk_paths") or current.get("risk_path_count")),
        milestone_count=_safe_int((management or {}).get("milestones") or current.get("milestone_count")),
        recovery_lever_count=_safe_int((management or {}).get("recovery_levers") or current.get("recovery_lever_count") or len(actions.get("recovery_levers") or [])),
        field_question_count=_safe_int((management or {}).get("field_questions") or current.get("field_question_count")),
        parser_warning_count=parser_warning_count,
        rows_dropped_or_skipped=_safe_int(summary_block.get("rows_dropped_or_skipped")),
        total_float_days=total_float_days,
        critical_path_activity_count=critical_path_activity_count,
        risk_flags=[str(flag) for flag in (dashboard.get("risk_flags") or [])],
        top_drivers=top_drivers,
        source_file=_optional_str(project.get("source_file") or summary_block.get("source_file")),
        trust=TrustIndicator(status=trust_status, rationale=trust_rationale, missing_data_flags=missing),
        provenance=[item for item in provenance if item is not None],
    )


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except Exception:
        return None


def _optional_str(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    return str(value)


def _resolve_finish_metadata(
    *,
    project: dict[str, Any],
    summary_block: dict[str, Any],
    current: dict[str, Any],
    outputs_dir: Path,
) -> dict[str, str | None]:
    finish_date = _optional_str(
        project.get("finish_date")
        or project.get("forecast_finish")
        or summary_block.get("finish_date")
        or summary_block.get("forecast_finish")
        or current.get("finish_date")
        or current.get("forecast_finish")
    )
    if finish_date:
        return {
            "finish_date": finish_date,
            "finish_source": "published_schedule_field",
            "finish_source_label": "Published schedule finish field",
            "finish_detail": "Derived from an explicit finish field in the published schedule artifact.",
            "finish_artifact_path": None,
            "finish_activity_id": None,
            "finish_activity_name": None,
        }
    milestone_drift_path = outputs_dir / "milestone_drift_log.csv"
    milestone_finish = _milestone_finish_metadata(milestone_drift_path)
    if milestone_finish is not None:
        return milestone_finish
    if not outputs_dir.exists():
        reason = "The published artifact is incomplete and does not expose a usable finish signal."
    else:
        reason = "No finish milestone/date was found in the published schedule artifact."
    return {
        "finish_date": None,
        "finish_source": "unavailable",
        "finish_source_label": "Projected finish unavailable",
        "finish_detail": reason,
        "finish_artifact_path": str(milestone_drift_path) if milestone_drift_path.exists() else None,
        "finish_activity_id": None,
        "finish_activity_name": None,
    }


def _milestone_finish_metadata(path: Path) -> dict[str, str | None] | None:
    if not path.exists():
        return None
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            finish_date = _optional_str(row.get("finish"))
            if not finish_date:
                continue
            rows.append({key: str(value or "") for key, value in row.items()})
    if not rows:
        return None
    finish_date = max(_optional_str(row.get("finish")) or "" for row in rows)
    latest_rows = [row for row in rows if _optional_str(row.get("finish")) == finish_date]
    latest_rows.sort(
        key=lambda row: (
            _completion_keyword_score(row.get("name") or ""),
            row.get("activity_id") or "",
        ),
        reverse=True,
    )
    selected = latest_rows[0]
    activity_id = _optional_str(selected.get("activity_id"))
    activity_name = _optional_str(selected.get("name"))
    detail = f"Derived from the published milestone drift log using the latest milestone finish {finish_date}"
    if activity_name:
        detail += f" ({activity_name}"
        if activity_id:
            detail += f", activity {activity_id}"
        detail += ")."
    else:
        detail += "."
    return {
        "finish_date": finish_date,
        "finish_source": "published_milestone_drift_log",
        "finish_source_label": "Published milestone drift log",
        "finish_detail": detail,
        "finish_artifact_path": str(path),
        "finish_activity_id": activity_id,
        "finish_activity_name": activity_name,
    }


def _completion_keyword_score(value: str) -> int:
    lowered = str(value or "").strip().lower()
    if "project substantial completion" in lowered:
        return 5
    if "project completion" in lowered or "final completion" in lowered:
        return 4
    if "substantial completion" in lowered or "substantially complete" in lowered:
        return 3
    if "occupancy" in lowered or "turnover" in lowered:
        return 2
    if "complete" in lowered or "completion" in lowered:
        return 1
    return 0


def _artifact(source_system: str, artifact_type: str, path: Path, relative_root: Path | None) -> SourceArtifactRef:
    if not path.exists():
        return SourceArtifactRef(
            source_system=source_system,
            artifact_type=artifact_type,
            path=str(path),
            status="missing",
        )
    relative_path = None
    if relative_root is not None:
        try:
            relative_path = str(path.relative_to(relative_root)).replace("\\", "/")
        except ValueError:
            relative_path = None
    return SourceArtifactRef(
        source_system=source_system,
        artifact_type=artifact_type,
        path=str(path),
        relative_path=relative_path,
        status="resolved",
    )

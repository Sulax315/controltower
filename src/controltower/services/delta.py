from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from controltower.adapters.schedulelab import load_schedule_from_outputs
from controltower.domain.models import (
    ComparisonTrust,
    ExportRecord,
    FinancialDelta,
    FinancialSummary,
    ProjectDelta,
    ProjectDeltaDetails,
    ProjectIdentity,
    ProjectSnapshot,
    RiskDelta,
    ScheduleDelta,
    ScheduleSummary,
)


def load_latest_run_record(state_root: Path) -> ExportRecord | None:
    latest_path = Path(state_root) / "latest_run.json"
    if not latest_path.exists():
        return None
    return _rehydrate_record_finish_signals(ExportRecord.model_validate(json.loads(latest_path.read_text(encoding="utf-8"))))


def load_run_record(state_root: Path, run_id: str) -> ExportRecord | None:
    history_path = Path(state_root) / "history" / f"{run_id}.json"
    if history_path.exists():
        return _rehydrate_record_finish_signals(ExportRecord.model_validate(json.loads(history_path.read_text(encoding="utf-8"))))
    manifest_path = Path(state_root) / "runs" / run_id / "manifest.json"
    if manifest_path.exists():
        return _rehydrate_record_finish_signals(ExportRecord.model_validate(json.loads(manifest_path.read_text(encoding="utf-8"))))
    latest = load_latest_run_record(state_root)
    if latest and latest.run_id == run_id:
        return latest
    return None


def load_run_history(state_root: Path) -> list[ExportRecord]:
    state_root = Path(state_root)
    records: dict[str, ExportRecord] = {}
    history_root = state_root / "history"
    if history_root.exists():
        for path in sorted(history_root.glob("*.json")):
            record = _rehydrate_record_finish_signals(ExportRecord.model_validate(json.loads(path.read_text(encoding="utf-8"))))
            records[record.run_id] = record
    runs_root = state_root / "runs"
    if runs_root.exists():
        for manifest_path in sorted(runs_root.glob("*/manifest.json")):
            record = _rehydrate_record_finish_signals(ExportRecord.model_validate(json.loads(manifest_path.read_text(encoding="utf-8"))))
            records.setdefault(record.run_id, record)
    latest = load_latest_run_record(state_root)
    if latest is not None:
        records[latest.run_id] = latest
    return sorted(records.values(), key=lambda item: item.generated_at, reverse=True)


def load_previous_run_record(state_root: Path, current_run_id: str | None = None) -> ExportRecord | None:
    for record in load_run_history(state_root):
        if current_run_id and record.run_id == current_run_id:
            continue
        return record
    return None


def select_comparison_run_record(
    state_root: Path,
    current_projects: list[tuple[ProjectIdentity, ScheduleSummary | None, FinancialSummary | None]],
) -> ExportRecord | None:
    history = load_run_history(state_root)
    if not history:
        return None
    latest = history[0]
    if record_matches_current(latest, current_projects):
        return history[1] if len(history) > 1 else None
    return latest


def describe_comparison_trust(
    state_root: Path,
    current_projects: list[tuple[ProjectIdentity, ScheduleSummary | None, FinancialSummary | None]],
) -> ComparisonTrust:
    history = load_run_history(state_root)
    if not current_projects:
        return ComparisonTrust(
            status="unavailable",
            label="No comparison baseline",
            detail="No current portfolio entities were resolved, so change-sensitive ranking is unavailable.",
            delta_ranking_enabled=False,
            reason_code="no_current_entities",
            ranking_authority="unavailable",
            ranking_label="Ranking unavailable",
            ranking_detail="No current portfolio entities were resolved, so no ranked comparison surface can be asserted.",
            baseline_label="No current comparison scope",
            baseline_detail="No current portfolio entities were resolved, so no comparison baseline can be selected.",
        )
    if not history:
        return ComparisonTrust(
            status="unavailable",
            label="No prior comparison baseline",
            detail=(
                "No prior export run exists yet, so delta-driven ranking is unavailable and the current queue stays trust-bounded "
                "to present-run health, risk, and trust signals."
            ),
            delta_ranking_enabled=False,
            reason_code="no_prior_run",
            ranking_authority="trust_bounded",
            ranking_label="Trust-bounded ranking",
            ranking_detail="The queue is limited to current-run health, risk, and trust signals because no trusted prior comparison run exists yet.",
            baseline_label="No prior comparison baseline",
            baseline_detail="No prior export run exists yet, so no trusted comparison baseline can be selected.",
        )

    latest = history[0]
    if record_matches_current(latest, current_projects):
        if len(history) > 1:
            return ComparisonTrust(
                status="trusted",
                label="Trusted comparison",
                detail=(
                    f"Latest run {latest.run_id} matches the current source signatures, so comparisons use the prior distinct "
                    f"run {history[1].run_id}."
                ),
                comparison_run_id=history[1].run_id,
                delta_ranking_enabled=True,
                reason_code="prior_distinct_run",
                ranking_authority="authoritative",
                ranking_label="Authoritative delta-driven ranking",
                ranking_detail=f"Delta-driven ranking is authoritative because the prior distinct trusted run is {history[1].run_id}.",
                baseline_label="Trusted prior distinct run selected",
                baseline_detail=(
                    f"Latest run {latest.run_id} matches the current signatures, so the selected baseline is the prior distinct run {history[1].run_id}."
                ),
            )
        return ComparisonTrust(
            status="contained",
            label="Contained comparison",
            detail=(
                f"Latest run {latest.run_id} matches the current source signatures and no older distinct run is available, "
                "so delta-driven ranking is contained and the surface remains trust-bounded until a trusted prior baseline exists."
            ),
            delta_ranking_enabled=False,
            reason_code="no_distinct_prior_run",
            ranking_authority="trust_bounded",
            ranking_label="Trust-bounded ranking",
            ranking_detail="Delta-driven ranking is suppressed because no distinct trusted prior baseline exists yet.",
            baseline_label="No distinct trusted prior baseline",
            baseline_detail=(
                f"Latest run {latest.run_id} matches the current signatures and there is no older distinct trusted run to use as baseline."
            ),
        )

    return ComparisonTrust(
        status="trusted",
        label="Trusted comparison",
        detail=f"Comparisons use the latest prior distinct run {latest.run_id}.",
        comparison_run_id=latest.run_id,
        delta_ranking_enabled=True,
        reason_code="latest_prior_distinct_run",
        ranking_authority="authoritative",
        ranking_label="Authoritative delta-driven ranking",
        ranking_detail=f"Delta-driven ranking is authoritative because the latest prior distinct run is {latest.run_id}.",
        baseline_label="Trusted prior distinct run selected",
        baseline_detail=f"The latest prior distinct run {latest.run_id} is selected as the comparison baseline.",
    )


def index_projects_by_id(record: ExportRecord | None) -> dict[str, ProjectSnapshot]:
    if record is None:
        return {}
    return {project.canonical_project_id: project for project in record.project_snapshots}


def compute_project_deltas(
    current_projects: list[tuple[ProjectIdentity, ScheduleSummary | None, FinancialSummary | None]],
    previous_projects: dict[str, ProjectSnapshot],
) -> list[ProjectDelta]:
    deltas: list[ProjectDelta] = []
    for identity, schedule, financial in current_projects:
        previous = previous_projects.get(identity.canonical_project_id)
        delta = build_project_delta(identity, schedule, financial, previous)
        deltas.append(ProjectDelta(project_id=identity.canonical_project_id, delta=delta))
    return deltas


def build_project_delta(
    identity: ProjectIdentity,
    schedule: ScheduleSummary | None,
    financial: FinancialSummary | None,
    previous: ProjectSnapshot | None,
) -> ProjectDeltaDetails:
    schedule_delta = _build_schedule_delta(schedule, previous.schedule if previous else None)
    financial_delta = _build_financial_delta(financial, previous.financial if previous else None)
    risk_delta = _build_risk_delta(schedule, financial, previous)
    summary_parts = [part for part in [schedule_delta.summary, financial_delta.summary, risk_delta.summary] if part]
    summary = " ".join(summary_parts) if summary_parts else f"{identity.project_name}: baseline established for future comparisons."
    return ProjectDeltaDetails(schedule=schedule_delta, financial=financial_delta, risk=risk_delta, summary=summary)


def record_matches_current(
    record: ExportRecord,
    current_projects: list[tuple[ProjectIdentity, ScheduleSummary | None, FinancialSummary | None]],
) -> bool:
    if len(record.project_snapshots) != len(current_projects):
        return False
    snapshot_signatures = {project.canonical_project_id: _snapshot_signature(project) for project in record.project_snapshots}
    current_signatures = {
        identity.canonical_project_id: _current_signature(identity, schedule, financial)
        for identity, schedule, financial in current_projects
    }
    return snapshot_signatures == current_signatures


def _build_schedule_delta(current: ScheduleSummary | None, previous: ScheduleSummary | None) -> ScheduleDelta:
    previous = _rehydrate_schedule_finish(previous)
    current_finish = current.finish_date if current else None
    previous_finish = previous.finish_date if previous else None
    finish_movement = _date_diff_days(current_finish, previous_finish)
    finish_movement_reason = None
    if finish_movement is None:
        if current_finish is None:
            finish_movement_reason = "Projected finish is unavailable for the current run, so movement versus the prior trusted run cannot be computed."
        elif previous is None:
            finish_movement_reason = "A finish date exists for the current run, but no trusted prior baseline exists for comparison."
        elif previous_finish is None:
            finish_movement_reason = "A trusted prior baseline exists, but it does not expose a usable finish signal."
    current_float = _float_signal(current)
    previous_float = _float_signal(previous)
    float_movement = None if current_float is None or previous_float is None else round(current_float - previous_float, 1)
    if float_movement is None:
        float_direction = "unknown"
    elif float_movement < 0:
        float_direction = "compression"
    elif float_movement > 0:
        float_direction = "expansion"
    else:
        float_direction = "flat"
    current_cp = current.critical_path_activity_count if current else None
    previous_cp = previous.critical_path_activity_count if previous else None
    critical_path_changed = False
    if current and previous:
        critical_path_changed = (
            current_cp != previous_cp
            or _first_driver_label(current) != _first_driver_label(previous)
            or (current.risk_path_count or 0) != (previous.risk_path_count or 0)
        )
    summary_parts: list[str] = []
    if finish_movement is not None:
        if finish_movement > 0:
            summary_parts.append(f"Finish date slipped by {finish_movement} day(s).")
        elif finish_movement < 0:
            summary_parts.append(f"Finish date improved by {abs(finish_movement)} day(s).")
    if float_movement is not None:
        if float_movement < 0:
            summary_parts.append(f"Float compressed by {abs(float_movement):.1f} day(s).")
        elif float_movement > 0:
            summary_parts.append(f"Float expanded by {float_movement:.1f} day(s).")
    if critical_path_changed:
        summary_parts.append("Critical-path signature changed from the prior run.")
    if not summary_parts:
        summary_parts.append("No prior schedule baseline was available for comparison." if previous is None else "Schedule held flat versus the prior run.")
    return ScheduleDelta(
        current_finish_date=current_finish,
        previous_finish_date=previous_finish,
        finish_date_movement_days=finish_movement,
        finish_date_movement_reason=finish_movement_reason,
        current_float_days=current_float,
        previous_float_days=previous_float,
        float_movement_days=float_movement,
        float_direction=float_direction,  # type: ignore[arg-type]
        critical_path_changed=critical_path_changed,
        current_critical_path_activity_count=current_cp,
        previous_critical_path_activity_count=previous_cp,
        summary=" ".join(summary_parts),
    )


def _build_financial_delta(current: FinancialSummary | None, previous: FinancialSummary | None) -> FinancialDelta:
    current_cost_variance = _cost_variance(current)
    previous_cost_variance = _cost_variance(previous)
    cost_variance_change = None
    if current_cost_variance is not None and previous_cost_variance is not None:
        cost_variance_change = round(current_cost_variance - previous_cost_variance, 1)
    current_margin = current.metrics.get("margin_percent") if current else None
    previous_margin = previous.metrics.get("margin_percent") if previous else None
    margin_movement = None
    if current_margin is not None and previous_margin is not None:
        margin_movement = round(current_margin - previous_margin, 2)
    summary_parts: list[str] = []
    if cost_variance_change is not None:
        if cost_variance_change > 0:
            summary_parts.append(f"Cost variance worsened by ${cost_variance_change:,.0f}.")
        elif cost_variance_change < 0:
            summary_parts.append(f"Cost variance improved by ${abs(cost_variance_change):,.0f}.")
    if margin_movement is not None:
        if margin_movement < 0:
            summary_parts.append(f"Margin moved down {abs(margin_movement):.2f} pts.")
        elif margin_movement > 0:
            summary_parts.append(f"Margin improved {margin_movement:.2f} pts.")
    if not summary_parts:
        summary_parts.append("No prior financial baseline was available for comparison." if previous is None else "Financial posture was effectively unchanged.")
    return FinancialDelta(
        current_cost_variance=current_cost_variance,
        previous_cost_variance=previous_cost_variance,
        cost_variance_change=cost_variance_change,
        current_margin_percent=current_margin,
        previous_margin_percent=previous_margin,
        margin_movement=margin_movement,
        summary=" ".join(summary_parts),
    )


def _build_risk_delta(
    current_schedule: ScheduleSummary | None,
    current_financial: FinancialSummary | None,
    previous: ProjectSnapshot | None,
) -> RiskDelta:
    current_risks = set(_risk_signals(current_schedule, current_financial))
    previous_risks = set(_risk_signals(previous.schedule if previous else None, previous.financial if previous else None))
    new_risks = sorted(current_risks - previous_risks)
    resolved_risks = sorted(previous_risks - current_risks)
    worsening: list[str] = []
    if current_schedule and previous and previous.schedule:
        open_end_delta = ((current_schedule.open_start_count or 0) + (current_schedule.open_finish_count or 0)) - (
            (previous.schedule.open_start_count or 0) + (previous.schedule.open_finish_count or 0)
        )
        if open_end_delta > 0:
            worsening.append(f"Open ends increased by {open_end_delta}.")
        cycle_delta = (current_schedule.cycle_count or 0) - (previous.schedule.cycle_count or 0)
        if cycle_delta > 0:
            worsening.append(f"Schedule cycles increased by {cycle_delta}.")
    if current_financial and previous and previous.financial:
        current_profit = current_financial.metrics.get("projected_profit")
        previous_profit = previous.financial.metrics.get("projected_profit")
        if current_profit is not None and previous_profit is not None and current_profit < previous_profit:
            worsening.append(f"Projected profit declined by ${abs(current_profit - previous_profit):,.0f}.")
    summary_parts: list[str] = []
    if new_risks:
        summary_parts.append("New risks: " + ", ".join(new_risks[:4]) + ".")
    if resolved_risks:
        summary_parts.append("Resolved risks: " + ", ".join(resolved_risks[:4]) + ".")
    if worsening:
        summary_parts.append("Worsening signals: " + " ".join(worsening[:3]))
    if not summary_parts:
        summary_parts.append("No material risk movement was detected against the prior run." if previous else "No prior risk baseline was available for comparison.")
    return RiskDelta(
        new_risks=new_risks,
        resolved_risks=resolved_risks,
        worsening_signals=worsening,
        summary=" ".join(summary_parts),
    )


def _date_diff_days(current_value: str | None, previous_value: str | None) -> int | None:
    current_date = _parse_date(current_value)
    previous_date = _parse_date(previous_value)
    if current_date is None or previous_date is None:
        return None
    return (current_date - previous_date).days


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _float_signal(schedule: ScheduleSummary | None) -> float | None:
    if schedule is None:
        return None
    if schedule.total_float_days is not None:
        return float(schedule.total_float_days)
    if schedule.negative_float_count is not None:
        return float(-1 * schedule.negative_float_count)
    return None


def _first_driver_label(schedule: ScheduleSummary | None) -> str | None:
    if schedule and schedule.top_drivers:
        return schedule.top_drivers[0].label
    return None


def _cost_variance(financial: FinancialSummary | None) -> float | None:
    if financial is None:
        return None
    forecast = financial.metrics.get("forecast_final_cost")
    baseline = (
        financial.metrics.get("revised_budget")
        or financial.metrics.get("original_budget")
        or financial.metrics.get("revised_contract")
        or financial.metrics.get("contract_value")
    )
    if forecast is None or baseline is None:
        return None
    return round(forecast - baseline, 1)


def _risk_signals(schedule: ScheduleSummary | None, financial: FinancialSummary | None) -> list[str]:
    signals: list[str] = []
    if schedule is None:
        signals.append("schedule_data_missing")
    else:
        signals.extend(schedule.risk_flags)
        if (schedule.cycle_count or 0) > 0:
            signals.append("schedule_cycles")
        if ((schedule.open_start_count or 0) + (schedule.open_finish_count or 0)) > 0:
            signals.append("schedule_open_ends")
        if (schedule.negative_float_count or 0) > 0:
            signals.append("negative_float")
    if financial is None:
        signals.append("financial_data_missing")
    else:
        signals.extend(financial.flags)
        margin = financial.metrics.get("margin_percent")
        if margin is not None and margin < 10:
            signals.append("margin_pressure")
        projected_profit = financial.metrics.get("projected_profit")
        if projected_profit is not None and projected_profit < 0:
            signals.append("negative_projected_profit")
        if financial.trust_tier != "high":
            signals.append("financial_trust_limited")
    return sorted({signal for signal in signals if signal})


def _snapshot_signature(project: ProjectSnapshot) -> tuple:
    return (
        project.canonical_project_id,
        project.schedule.run_timestamp if project.schedule else None,
        project.schedule.finish_date if project.schedule else None,
        _float_signal(project.schedule),
        project.schedule.cycle_count if project.schedule else None,
        tuple(project.schedule.risk_flags) if project.schedule else (),
        project.financial.snapshot_id if project.financial else None,
        project.financial.report_month if project.financial else None,
        project.financial.metrics.get("projected_profit") if project.financial else None,
        project.financial.metrics.get("margin_percent") if project.financial else None,
    )


def _current_signature(identity: ProjectIdentity, schedule: ScheduleSummary | None, financial: FinancialSummary | None) -> tuple:
    return (
        identity.canonical_project_id,
        schedule.run_timestamp if schedule else None,
        schedule.finish_date if schedule else None,
        _float_signal(schedule),
        schedule.cycle_count if schedule else None,
        tuple(schedule.risk_flags) if schedule else (),
        financial.snapshot_id if financial else None,
        financial.report_month if financial else None,
        financial.metrics.get("projected_profit") if financial else None,
        financial.metrics.get("margin_percent") if financial else None,
    )


def _rehydrate_record_finish_signals(record: ExportRecord) -> ExportRecord:
    changed = False
    project_snapshots: list[ProjectSnapshot] = []
    for project in record.project_snapshots:
        schedule = _rehydrate_schedule_finish(project.schedule)
        project_delta = project.delta
        if schedule is not project.schedule:
            changed = True
            if schedule and project_delta.schedule.current_finish_date is None and schedule.finish_date:
                project_delta = project_delta.model_copy(
                    update={
                        "schedule": project_delta.schedule.model_copy(
                            update={"current_finish_date": schedule.finish_date}
                        )
                    }
                )
        project_snapshots.append(
            project if schedule is project.schedule and project_delta is project.delta else project.model_copy(update={"schedule": schedule, "delta": project_delta})
        )
    if not changed:
        return record
    return record.model_copy(update={"project_snapshots": project_snapshots})


def _rehydrate_schedule_finish(schedule: ScheduleSummary | None) -> ScheduleSummary | None:
    if schedule is None or schedule.finish_date:
        return schedule
    outputs_dir = _outputs_dir_from_provenance(schedule)
    if outputs_dir is None:
        return schedule
    try:
        hydrated = load_schedule_from_outputs(outputs_dir, project_code_hint=schedule.project_code)
    except Exception:
        return schedule
    if not _schedule_signatures_match(schedule, hydrated):
        return schedule
    if (
        hydrated.finish_date == schedule.finish_date
        and hydrated.finish_source == schedule.finish_source
        and hydrated.finish_detail == schedule.finish_detail
    ):
        return schedule
    return schedule.model_copy(
        update={
            "finish_date": hydrated.finish_date,
            "finish_source": hydrated.finish_source,
            "finish_source_label": hydrated.finish_source_label,
            "finish_detail": hydrated.finish_detail,
            "finish_artifact_path": hydrated.finish_artifact_path,
            "finish_activity_id": hydrated.finish_activity_id,
            "finish_activity_name": hydrated.finish_activity_name,
            "provenance": hydrated.provenance or schedule.provenance,
        }
    )


def _outputs_dir_from_provenance(schedule: ScheduleSummary) -> Path | None:
    candidates = []
    for artifact in schedule.provenance:
        if artifact.source_system != "schedulelab":
            continue
        path = Path(artifact.path)
        if path.name in {"dashboard_feed.json", "summary.json", "run_manifest.json", "milestone_drift_log.csv"}:
            candidates.append(path.parent)
    return candidates[0] if candidates else None


def _schedule_signatures_match(expected: ScheduleSummary, hydrated: ScheduleSummary) -> bool:
    if expected.run_timestamp and hydrated.run_timestamp and expected.run_timestamp != hydrated.run_timestamp:
        return False
    if expected.source_file and hydrated.source_file and expected.source_file != hydrated.source_file:
        return False
    if expected.project_code and hydrated.project_code and expected.project_code != hydrated.project_code:
        return False
    return True

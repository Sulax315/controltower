from __future__ import annotations

from math import fabs

from controltower.domain.models import (
    ChangeNote,
    FinancialSummary,
    HealthAssessment,
    IssueDriver,
    ProjectDeltaDetails,
    ProjectSnapshot,
    RecommendedAction,
    ScheduleSummary,
    TrustIndicator,
)


def assess_project_health(
    *,
    project_name: str,
    schedule: ScheduleSummary | None,
    financial: FinancialSummary | None,
    delta: ProjectDeltaDetails | None = None,
) -> tuple[HealthAssessment, list[IssueDriver], list[RecommendedAction], list[ChangeNote], str, TrustIndicator, list[str]]:
    delta = delta or ProjectDeltaDetails()
    score = 100.0
    rationales: list[str] = []
    issues: list[IssueDriver] = []
    actions: list[RecommendedAction] = []
    changes: list[ChangeNote] = []
    missing_flags: list[str] = []
    trust_rationale: list[str] = []
    trust_status = "high"

    def add_issue(source: str, severity: str, label: str, detail: str) -> None:
        issues.append(IssueDriver(source=source, severity=severity, label=label, detail=detail))

    def add_action(priority: str, owner_hint: str, action: str) -> None:
        candidate = RecommendedAction(priority=priority, owner_hint=owner_hint, action=action)
        if candidate not in actions:
            actions.append(candidate)

    if schedule is None:
        score -= 18
        missing_flags.append("schedule_data_missing")
        trust_status = "partial"
        trust_rationale.append("ScheduleLab data is missing for this project.")
        rationales.append("Schedule visibility is missing.")
        add_issue("schedule", "high", "Missing schedule feed", "No ScheduleLab artifact resolved for the current project.")
        add_action("high", "Scheduler", "Recover the missing ScheduleLab publication before the next leadership review.")
    else:
        schedule_score = schedule.health_score if schedule.health_score is not None else 65.0
        score -= max(0.0, 100.0 - schedule_score) * 0.45
        if (schedule.cycle_count or 0) > 0:
            penalty = min(18.0, 6.0 + float(schedule.cycle_count or 0) * 2.0)
            score -= penalty
            rationales.append(f"Schedule logic still contains {schedule.cycle_count} cycle(s).")
            add_issue(
                "schedule",
                "high",
                "Circular schedule logic",
                f"{schedule.cycle_count} cycle(s) remain in the latest published schedule output.",
            )
            add_action(
                "high",
                "Scheduler",
                f"Validate and remove {schedule.cycle_count} schedule cycle(s) before the next publish.",
            )
        open_ends = (schedule.open_start_count or 0) + (schedule.open_finish_count or 0)
        if open_ends > 0:
            penalty = min(18.0, open_ends * 0.08)
            score -= penalty
            rationales.append(f"Schedule has {open_ends} open-end conditions across starts and finishes.")
            add_issue(
                "schedule",
                "medium" if open_ends < 25 else "high",
                "Open-end exposure",
                f"{schedule.open_start_count or 0} open starts and {schedule.open_finish_count or 0} open finishes remain.",
            )
            add_action(
                "medium" if open_ends < 25 else "high",
                "Scheduler",
                f"Validate missing successors and predecessors across {open_ends} open-end activities.",
            )
        if (schedule.negative_float_count or 0) > 0:
            penalty = min(12.0, float(schedule.negative_float_count or 0) * 1.2)
            score -= penalty
            rationales.append(f"Negative float remains on {schedule.negative_float_count} activity(ies).")
            add_issue(
                "schedule",
                "high" if (schedule.negative_float_count or 0) >= 3 else "medium",
                "Negative float pressure",
                f"{schedule.negative_float_count} activity(ies) are carrying negative float.",
            )
        if (schedule.parser_warning_count or 0) > 100:
            score -= 12
            rationales.append(f"Parser warnings are elevated at {schedule.parser_warning_count}.")
            missing_flags.append("schedule_parser_warning_elevated")
            trust_status = "partial"
            trust_rationale.append(
                f"ScheduleLab parser warnings are elevated ({schedule.parser_warning_count}), so schedule traceability needs review."
            )
            add_action("medium", "Scheduler", "Validate elevated parser warnings before acting on the current schedule logic.")
        if schedule.risk_flags:
            rationales.append("ScheduleLab flagged: " + ", ".join(schedule.risk_flags[:4]).replace("_", " ") + ".")
        if schedule.top_drivers:
            changes.append(ChangeNote(source="schedule", summary=f"Top schedule driver is {schedule.top_drivers[0].label}."))
            if delta.schedule.float_direction == "compression":
                add_action(
                    "high",
                    "Scheduler",
                    f"Investigate float compression on path {schedule.top_drivers[0].label}.",
                )
        if delta.schedule.finish_date_movement_days is not None:
            if delta.schedule.finish_date_movement_days > 0:
                score -= min(15.0, float(delta.schedule.finish_date_movement_days) * 1.5)
                add_issue(
                    "cross_source",
                    "high",
                    "Finish date slippage",
                    f"Finish date slipped by {delta.schedule.finish_date_movement_days} day(s) versus the prior run.",
                )
                add_action(
                    "high",
                    "PM / Scheduler",
                    f"Recover the {delta.schedule.finish_date_movement_days}-day finish slippage before the next update cycle.",
                )
            elif delta.schedule.finish_date_movement_days < 0:
                changes.append(
                    ChangeNote(
                        source="schedule",
                        summary=f"Finish date improved by {abs(delta.schedule.finish_date_movement_days)} day(s).",
                    )
                )
        if delta.schedule.float_movement_days is not None and delta.schedule.float_movement_days < 0:
            score -= min(10.0, abs(delta.schedule.float_movement_days) * 2.0)
            add_issue(
                "cross_source",
                "high" if abs(delta.schedule.float_movement_days) >= 2 else "medium",
                "Float compression",
                f"Total float compressed by {abs(delta.schedule.float_movement_days):.1f} day(s) versus the prior run.",
            )
        if delta.schedule.critical_path_changed:
            changes.append(ChangeNote(source="schedule", summary="Critical-path signature changed this week."))
            add_action("medium", "PM / Scheduler", "Review the critical-path shift and confirm the logic ties are intentional.")

    if financial is None:
        score -= 12
        missing_flags.append("financial_data_missing")
        trust_status = "partial" if trust_status == "high" else trust_status
        trust_rationale.append("ProfitIntel financial data is missing for this project.")
        rationales.append("Financial visibility is missing.")
        add_issue("financial", "medium", "Missing financial feed", "No ProfitIntel snapshot resolved for the current project.")
        add_action("medium", "PM / Finance", "Recover the missing ProfitIntel snapshot before the next forecast review.")
    else:
        if financial.trust_tier == "low":
            score -= 20
            trust_status = "low"
        elif financial.trust_tier == "partial":
            score -= 10
            trust_status = "partial" if trust_status == "high" else trust_status
        trust_rationale.extend(financial.trust_reasons[:4])
        margin = financial.metrics.get("margin_percent")
        if margin is not None:
            if margin < 5:
                score -= 20
                rationales.append(f"Margin is critically compressed at {margin:.1f}%.")
                add_issue(
                    "financial",
                    "high",
                    "Margin compression",
                    f"Current margin is {margin:.1f}%, which is below the critical threshold.",
                )
                add_action("high", "PM / Finance", "Review cost overrun drivers behind the sub-5% margin forecast.")
            elif margin < 10:
                score -= 12
                rationales.append(f"Margin is under pressure at {margin:.1f}%.")
                add_issue("financial", "medium", "Margin pressure", f"Current margin is {margin:.1f}%, below the watch threshold.")
                add_action("medium", "PM / Finance", "Validate margin erosion in the latest ProfitIntel snapshot.")
        projected_profit = financial.metrics.get("projected_profit")
        if projected_profit is not None and projected_profit < 0:
            score -= 18
            rationales.append("Projected profit is negative.")
            add_issue("financial", "high", "Negative projected profit", "Projected profit is below zero in the current forecast.")
            add_action("high", "PM / Finance", "Review cost overrun in the current forecast that is driving negative projected profit.")
        for variance in financial.variances:
            if variance.metric_name == "projected_profit" and variance.absolute_change is not None and variance.absolute_change < 0:
                delta_amount = fabs(variance.absolute_change)
                if delta_amount >= 50000:
                    score -= 12
                    rationales.append(f"Projected profit declined by ${delta_amount:,.0f} versus the comparison period.")
                    add_issue(
                        "financial",
                        "high",
                        "Profit fade",
                        f"Projected profit declined by ${delta_amount:,.0f} from {financial.comparison_month or 'the prior period'}.",
                    )
            if variance.metric_name == "forecast_final_cost" and variance.absolute_change is not None and variance.absolute_change > 0:
                delta_amount = fabs(variance.absolute_change)
                if delta_amount >= 25000:
                    score -= 8
                    rationales.append(f"Forecast final cost increased by ${delta_amount:,.0f}.")
            if variance.metric_name == "committed_cost" and variance.absolute_change is not None and variance.absolute_change > 0:
                delta_amount = fabs(variance.absolute_change)
                if delta_amount >= 25000:
                    changes.append(
                        ChangeNote(
                            source="financial",
                            summary=f"Committed cost increased by ${delta_amount:,.0f} in the latest ProfitIntel comparison.",
                        )
                    )
        if delta.financial.cost_variance_change is not None and delta.financial.cost_variance_change > 25000:
            score -= 10
            add_issue(
                "cross_source",
                "high",
                "Cost variance growth",
                f"Cost variance worsened by ${delta.financial.cost_variance_change:,.0f} versus the prior run.",
            )
            add_action(
                "high",
                "PM / Finance",
                f"Review cost overrun against the budget drift of ${delta.financial.cost_variance_change:,.0f}.",
            )
        if delta.financial.margin_movement is not None and delta.financial.margin_movement < 0:
            score -= min(10.0, abs(delta.financial.margin_movement) * 2.0)
            add_issue(
                "cross_source",
                "medium",
                "Margin moved down",
                f"Margin declined by {abs(delta.financial.margin_movement):.2f} pts versus the prior run.",
            )
            add_action("medium", "PM / Finance", "Validate margin movement and update the recovery plan for the next cost review.")
        if financial.executive_summary:
            changes.append(ChangeNote(source="financial", summary=financial.executive_summary))

    if delta.risk.new_risks:
        add_issue(
            "cross_source",
            "medium",
            "New risks surfaced",
            "New risk signals appeared this week: " + ", ".join(delta.risk.new_risks[:4]) + ".",
        )
        add_action("medium", "PM", "Mitigate the newly surfaced risk signals before the next weekly review.")
    if delta.risk.worsening_signals:
        add_issue(
            "cross_source",
            "high",
            "Worsening risk trend",
            " ".join(delta.risk.worsening_signals[:3]),
        )
    if delta.summary:
        changes.append(ChangeNote(source="cross_source", summary=delta.summary))

    score = max(0.0, min(100.0, round(score, 1)))
    if score >= 85:
        tier = "healthy"
        risk_level = "LOW"
    elif score >= 70:
        tier = "watch"
        risk_level = "MEDIUM"
    elif score >= 50:
        tier = "at_risk"
        risk_level = "HIGH"
    else:
        tier = "critical"
        risk_level = "HIGH"

    if not rationales:
        rationales.append("No material risk signals were triggered by the current schedule and financial adapters.")

    if tier != "healthy" and not actions:
        add_action("medium", "PM", "Validate the current signals and lock a corrective action before the next update cycle.")
    if tier == "healthy" and not actions:
        add_action(
            "low",
            "PM",
            "Maintain the current update cadence and verify the next source publication lands on schedule.",
        )

    executive_summary = f"{project_name} is {tier.replace('_', ' ')} at a score of {score:.1f}. {rationales[0]}"
    trust = TrustIndicator(
        status=trust_status,  # type: ignore[arg-type]
        rationale=_dedupe(trust_rationale) or ["Source artifacts were resolved without trust blockers."],
        missing_data_flags=_dedupe(missing_flags),
    )
    actions = _sort_actions(actions)[:8]
    return (
        HealthAssessment(
            health_score=score,
            risk_level=risk_level,  # type: ignore[arg-type]
            score=score,
            tier=tier,  # type: ignore[arg-type]
            rationale=_dedupe(rationales)[:8],
            required_actions=actions,
            recommended_actions=actions,
        ),
        _dedupe_issue_objects(issues)[:10],
        actions,
        _dedupe_change_objects(changes)[:8],
        executive_summary,
        trust,
        _dedupe(missing_flags),
    )


def posture_text(projects: list[ProjectSnapshot]) -> str:
    if not projects:
        return "No active projects were resolved from the configured sources."
    high_risk = sum(1 for project in projects if project.health.risk_level == "HIGH")
    medium_risk = sum(1 for project in projects if project.health.risk_level == "MEDIUM")
    avg = sum(project.health.health_score for project in projects) / len(projects)
    if high_risk:
        return f"Portfolio requires intervention: {high_risk} project(s) carry HIGH risk and average health is {avg:.1f}."
    if medium_risk:
        return f"Portfolio is under watch: {medium_risk} project(s) carry MEDIUM risk and average health is {avg:.1f}."
    return f"Portfolio posture is stable with average health at {avg:.1f}."


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _dedupe_issue_objects(values: list[IssueDriver]) -> list[IssueDriver]:
    result: list[IssueDriver] = []
    seen: set[tuple[str, str, str]] = set()
    for value in values:
        key = (value.source, value.label, value.detail)
        if key not in seen:
            result.append(value)
            seen.add(key)
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(result, key=lambda item: (priority_order[item.severity], item.label))


def _dedupe_change_objects(values: list[ChangeNote]) -> list[ChangeNote]:
    result: list[ChangeNote] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        key = (value.source, value.summary)
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result


def _sort_actions(values: list[RecommendedAction]) -> list[RecommendedAction]:
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(values, key=lambda item: (priority_order[item.priority], item.owner_hint, item.action))

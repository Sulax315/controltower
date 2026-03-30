from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from controltower.domain.models import FinancialSummary, MetricVariance, SourceArtifactRef, TrustIndicator


COMPARISON_FIELDS = [
    "contract_value",
    "revised_contract",
    "original_budget",
    "revised_budget",
    "cost_to_date",
    "committed_cost",
    "cost_to_complete",
    "forecast_final_cost",
    "projected_profit",
    "margin_percent",
    "fee_percent",
]

TRUST_RANK = {"low": 0, "partial": 1, "high": 2}
PARSE_RANK = {"failed": 0, "partial": 1, "success": 2}
LIFECYCLE_RANK = {"active": 2, "superseded": 1}


@dataclass(frozen=True)
class SnapshotRow:
    snapshot_id: int
    project_slug: str
    report_month: str | None
    snapshot_version: int
    snapshot_status: str
    parse_status: str
    completeness_score: float | None
    completeness_label: str | None
    warning_count: int
    error_count: int
    ingested_at: str | None
    source_file_name: str
    source_file_path: str
    trusted: bool
    comparison_eligible: bool
    trust_tier: str
    trust_reasons: list[str]
    reason_codes: list[str]
    checks_json: dict[str, Any]
    metrics: dict[str, float | None]


class ProfitIntelAdapter:
    def __init__(self, database_path: Path, validation_search_roots: list[Path] | None = None) -> None:
        self.database_path = Path(database_path)
        self.validation_search_roots = [Path(item) for item in (validation_search_roots or [])]

    def validate(self) -> list[str]:
        return [] if self.resolve_database() is not None else [
            "No usable ProfitIntel database was resolved from the configured database path or validation roots."
        ]

    def resolve_database(self) -> Path | None:
        candidates: list[Path] = []
        if self.database_path.exists():
            candidates.append(self.database_path)
        for root in self.validation_search_roots:
            if root.exists():
                candidates.extend(sorted(root.rglob("validation.db"), reverse=True))
        for candidate in candidates:
            if self._db_has_snapshots(candidate):
                return candidate
        return None

    def list_projects(self) -> list[FinancialSummary]:
        database = self.resolve_database()
        if database is None:
            return []
        with sqlite3.connect(database) as connection:
            rows = connection.execute("SELECT DISTINCT project_slug FROM report_snapshots ORDER BY project_slug").fetchall()
        return [self.load_project(str(row[0]), database_path=database) for row in rows]

    def load_project(self, project_slug: str, database_path: Path | None = None) -> FinancialSummary:
        database = database_path or self.resolve_database()
        if database is None:
            return FinancialSummary(
                project_slug=project_slug,
                trust=TrustIndicator(status="missing", rationale=["No ProfitIntel database was resolved."], missing_data_flags=["database_missing"]),
            )
        snapshots = self._fetch_snapshots(database, project_slug)
        if not snapshots:
            return FinancialSummary(
                project_slug=project_slug,
                trust=TrustIndicator(status="missing", rationale=["No ProfitIntel snapshots were found for this project."], missing_data_flags=["snapshot_missing"]),
            )

        current = self._select_current_snapshot(snapshots)
        comparison = self._select_comparison_snapshot(snapshots, current)
        variances = self._build_variances(current, comparison)
        executive_summary, key_findings, flags = self._summarize(current, comparison, variances)
        trust = TrustIndicator(
            status=current.trust_tier,
            rationale=current.trust_reasons or ["No explicit ProfitIntel trust reasons were recorded."],
            missing_data_flags=[str(item) for item in (current.checks_json.get("required_metrics_missing") or [])],
        )

        provenance = [
            SourceArtifactRef(
                source_system="profitintel",
                artifact_type="profitintel_validation_db",
                path=str(database),
                status="resolved",
            ),
            SourceArtifactRef(
                source_system="profitintel",
                artifact_type="profitintel_workbook",
                path=current.source_file_path,
                status="resolved" if Path(current.source_file_path).exists() else "derived",
                notes=current.source_file_name,
            ),
        ]

        return FinancialSummary(
            project_slug=project_slug,
            report_month=current.report_month,
            comparison_month=comparison.report_month if comparison else None,
            snapshot_timestamp=current.ingested_at,
            snapshot_id=current.snapshot_id,
            snapshot_version=current.snapshot_version,
            parse_status=current.parse_status,
            completeness_score=current.completeness_score,
            completeness_label=current.completeness_label,
            trusted=current.trusted,
            comparison_eligible=current.comparison_eligible and bool(comparison),
            trust_tier=current.trust_tier,  # type: ignore[arg-type]
            trust_reasons=current.trust_reasons,
            metrics=current.metrics,
            variances=variances,
            executive_summary=executive_summary,
            key_findings=key_findings,
            flags=flags,
            trust=trust,
            source_file_name=current.source_file_name,
            source_file_path=current.source_file_path,
            provenance=provenance,
        )

    def _db_has_snapshots(self, database_path: Path) -> bool:
        try:
            with sqlite3.connect(database_path) as connection:
                row = connection.execute("SELECT COUNT(*) FROM report_snapshots").fetchone()
                return bool(row and row[0])
        except Exception:
            return False

    def _fetch_snapshots(self, database_path: Path, project_slug: str) -> list[SnapshotRow]:
        with sqlite3.connect(database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT
                    rs.id AS snapshot_id,
                    rs.project_slug,
                    rs.report_month,
                    rs.snapshot_version,
                    rs.snapshot_status,
                    rs.parse_status,
                    rs.completeness_score,
                    rs.completeness_label,
                    rs.warning_count,
                    rs.error_count,
                    rs.ingested_at,
                    rs.source_file_name,
                    rs.source_file_path,
                    COALESCE(st.trusted, 0) AS trusted,
                    COALESCE(st.comparison_eligible, 0) AS comparison_eligible,
                    st.reason_codes,
                    st.checks_json,
                    pfs.contract_value,
                    pfs.revised_contract,
                    pfs.original_budget,
                    pfs.revised_budget,
                    pfs.cost_to_date,
                    pfs.committed_cost,
                    pfs.cost_to_complete,
                    pfs.forecast_final_cost,
                    pfs.projected_profit,
                    pfs.margin_percent,
                    pfs.fee_percent
                FROM report_snapshots rs
                LEFT JOIN snapshot_trust st ON st.report_snapshot_id = rs.id
                LEFT JOIN project_financial_snapshots pfs ON pfs.report_snapshot_id = rs.id
                WHERE rs.project_slug = ?
                ORDER BY rs.report_month, rs.snapshot_version, rs.id
                """,
                (project_slug,),
            ).fetchall()
        snapshots: list[SnapshotRow] = []
        for row in rows:
            checks_json = json.loads(row["checks_json"]) if row["checks_json"] else {}
            trust_tier = str(checks_json.get("trust_tier") or ("high" if row["trusted"] else "low"))
            reason_codes = json.loads(row["reason_codes"]) if row["reason_codes"] else []
            reason_details = checks_json.get("reason_details") or []
            reasons = [str(item.get("message")) for item in reason_details if isinstance(item, dict) and item.get("message")]
            if not reasons:
                reasons = [str(item) for item in (checks_json.get("reason_messages") or [])]
            metrics = {field: _float_or_none(row[field]) for field in COMPARISON_FIELDS}
            snapshots.append(
                SnapshotRow(
                    snapshot_id=int(row["snapshot_id"]),
                    project_slug=str(row["project_slug"]),
                    report_month=str(row["report_month"]) if row["report_month"] is not None else None,
                    snapshot_version=int(row["snapshot_version"] or 0),
                    snapshot_status=str(row["snapshot_status"] or ""),
                    parse_status=str(row["parse_status"] or ""),
                    completeness_score=_float_or_none(row["completeness_score"]),
                    completeness_label=str(row["completeness_label"]) if row["completeness_label"] is not None else None,
                    warning_count=int(row["warning_count"] or 0),
                    error_count=int(row["error_count"] or 0),
                    ingested_at=str(row["ingested_at"]) if row["ingested_at"] is not None else None,
                    source_file_name=str(row["source_file_name"]),
                    source_file_path=str(row["source_file_path"]),
                    trusted=bool(row["trusted"]),
                    comparison_eligible=bool(row["comparison_eligible"]),
                    trust_tier=trust_tier,
                    trust_reasons=reasons,
                    reason_codes=[str(item) for item in reason_codes],
                    checks_json=checks_json,
                    metrics=metrics,
                )
            )
        return snapshots

    def _select_current_snapshot(self, snapshots: list[SnapshotRow]) -> SnapshotRow:
        monthly_best: dict[str, SnapshotRow] = {}
        for snapshot in snapshots:
            if snapshot.report_month is None:
                continue
            prior = monthly_best.get(snapshot.report_month)
            if prior is None or self._sort_key(snapshot) > self._sort_key(prior):
                monthly_best[snapshot.report_month] = snapshot
        latest_month = sorted(monthly_best.keys())[-1]
        return monthly_best[latest_month]

    def _select_comparison_snapshot(self, snapshots: list[SnapshotRow], current: SnapshotRow) -> SnapshotRow | None:
        monthly_best: dict[str, SnapshotRow] = {}
        for snapshot in snapshots:
            if snapshot.report_month is None or snapshot.report_month == current.report_month:
                continue
            prior = monthly_best.get(snapshot.report_month)
            if prior is None or self._sort_key(snapshot) > self._sort_key(prior):
                monthly_best[snapshot.report_month] = snapshot
        if not monthly_best:
            return None
        month_keys = sorted(monthly_best.keys())
        comparison_month = month_keys[-1]
        if current.report_month in month_keys:
            current_index = month_keys.index(current.report_month)
            if current_index > 0:
                comparison_month = month_keys[current_index - 1]
        return monthly_best[comparison_month]

    def _sort_key(self, snapshot: SnapshotRow) -> tuple[int, int, int, int, int, str, int]:
        return (
            TRUST_RANK.get(snapshot.trust_tier, 0),
            LIFECYCLE_RANK.get(snapshot.snapshot_status, 0),
            1 if snapshot.report_month else 0,
            PARSE_RANK.get(snapshot.parse_status, 0),
            snapshot.snapshot_version,
            snapshot.ingested_at or "",
            snapshot.snapshot_id,
        )

    def _build_variances(self, current: SnapshotRow, comparison: SnapshotRow | None) -> list[MetricVariance]:
        variances: list[MetricVariance] = []
        for field in COMPARISON_FIELDS:
            current_value = current.metrics.get(field)
            comparison_value = comparison.metrics.get(field) if comparison else None
            absolute_change = None
            percent_change = None
            trend_direction = "flat"
            if current_value is not None and comparison_value is not None:
                absolute_change = current_value - comparison_value
                if absolute_change > 0:
                    trend_direction = "up"
                elif absolute_change < 0:
                    trend_direction = "down"
                if comparison_value != 0:
                    percent_change = (absolute_change / abs(comparison_value)) * 100
            elif current_value is not None and comparison_value is None:
                trend_direction = "up"
            elif current_value is None and comparison_value is not None:
                trend_direction = "down"
            variances.append(
                MetricVariance(
                    metric_name=field,
                    current_value=current_value,
                    comparison_value=comparison_value,
                    absolute_change=absolute_change,
                    percent_change=percent_change,
                    trend_direction=trend_direction,  # type: ignore[arg-type]
                )
            )
        return variances

    def _summarize(self, current: SnapshotRow, comparison: SnapshotRow | None, variances: list[MetricVariance]) -> tuple[str, list[str], list[str]]:
        comp_month = comparison.report_month if comparison else "n/a"
        lookup = {item.metric_name: item for item in variances}
        projected_profit = lookup["projected_profit"]
        margin = lookup["margin_percent"]
        forecast = lookup["forecast_final_cost"]
        findings = [reason for reason in current.trust_reasons[:4]]
        flags: list[str] = []
        if projected_profit.absolute_change is not None and projected_profit.absolute_change < 0:
            flags.append("profit_fade")
            findings.append(f"Projected profit declined by ${abs(projected_profit.absolute_change):,.0f}.")
        if margin.absolute_change is not None and margin.absolute_change < 0:
            flags.append("margin_compression")
            findings.append(f"Margin compressed by {abs(margin.absolute_change):.1f} percentage points.")
        if forecast.absolute_change is not None and forecast.absolute_change > 0:
            flags.append("forecast_growth_risk")
            findings.append(f"Forecast final cost increased by ${forecast.absolute_change:,.0f}.")
        committed = lookup["committed_cost"]
        if committed.absolute_change is not None and committed.absolute_change > 0:
            flags.append("commitment_spike")
            findings.append(f"Committed cost increased by ${committed.absolute_change:,.0f}.")
        if current.trust_tier != "high":
            flags.append("financial_trust_limited")
        summary = (
            f"ProfitIntel selected {current.report_month or 'unknown month'} as the authoritative financial snapshot "
            f"for {current.project_slug} compared against {comp_month}. "
            f"{_variance_sentence('Projected profit', projected_profit)} "
            f"{_variance_sentence('Margin', margin, percent=True)} "
            f"{_variance_sentence('Forecast final cost', forecast)} "
            f"Trust tier is {current.trust_tier}."
        )
        return summary, _dedupe(findings)[:8], _dedupe(flags)


def _variance_sentence(label: str, variance: MetricVariance, percent: bool = False) -> str:
    if variance.absolute_change is None:
        return f"{label} movement is unavailable."
    direction = "increased" if variance.absolute_change > 0 else "decreased" if variance.absolute_change < 0 else "was unchanged"
    current_value = _format_metric(variance.current_value, percent=percent)
    comparison_value = _format_metric(variance.comparison_value, percent=percent)
    return f"{label} {direction} to {current_value} from {comparison_value}."


def _format_metric(value: float | None, percent: bool = False) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}%" if percent else f"${value:,.0f}"


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except Exception:
        return None


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def deterministic_orchestration_notification_transport(monkeypatch):
    """Keep orchestration tests independent of local signal-cli installation."""

    def _fake_notify_controltower_event(event, **kwargs):
        status = str(kwargs.get("status") or "INFO").upper()
        project = str(kwargs.get("project") or "Control Tower")
        message = "\n".join(
            [
                "[CONTROL TOWER]",
                f"Event: {event}",
                f"Project: {project}",
                f"Status: {status}",
            ]
        )
        return {
            "event": str(event),
            "message": message,
            "artifact_path": "test://notification_artifact.json",
            "delivery": {
                "success": True,
                "selected_channel": "test_stub",
                "delivery_state": "send_succeeded",
            },
        }

    monkeypatch.setattr(
        "controltower.services.orchestration.notify_controltower_event",
        _fake_notify_controltower_event,
    )


@pytest.fixture
def sample_schedulelab_root(tmp_path: Path) -> Path:
    root = tmp_path / "schedulelab_published"
    (root / "portfolio_outputs").mkdir(parents=True, exist_ok=True)
    (root / "runs" / "AURORA_HILLS" / "outputs").mkdir(parents=True, exist_ok=True)
    portfolio_feed = {
        "generated_at": "2026-03-27T14:00:00+00:00",
        "projects": [
            {
                "project_name": "Aurora Hills",
                "project_code": "AURORA_HILLS",
            }
        ],
    }
    dashboard_feed = {
        "project": {
            "project_name": "Aurora Hills",
            "project_code": "AURORA_HILLS",
            "schedule_date": "2026-03-26",
            "finish_date": "2026-08-15",
            "source_file": "aurora_2026-03-26.csv",
        },
        "run": {"run_timestamp": "2026-03-27T13:45:00+00:00"},
        "summary": {
            "activity_count": 220,
            "relationship_count": 410,
            "negative_float_count": 2,
            "open_start_count": 5,
            "open_finish_count": 7,
            "cycle_count": 1,
            "overall_health_score": 73.0,
            "parser_warning_count": 14,
            "rows_dropped_or_skipped": 0,
            "total_float_days": 12.0,
            "critical_path_activity_count": 18,
            "source_file": "aurora_2026-03-26.csv",
        },
        "management": {"milestones": 18, "recovery_levers": 4, "field_questions": 2, "risk_paths": 2, "critical_path_activity_count": 18},
        "trend": {"current": {"issues_total": 44, "top_driver_count": 3, "risk_path_count": 2}},
        "health_score": 73.0,
        "issues_total": 44,
        "risk_flags": ["open_ends", "negative_float"],
        "top_drivers": [
            {"activity_id": "A-101", "activity_name": "Steel Release", "driver_score": 66.0, "driver_reasons": "long lead procurement"}
        ],
    }
    summary = {
        "project_name": "Aurora Hills",
        "project_code": "AURORA_HILLS",
        "schedule_date": "2026-03-26",
        "finish_date": "2026-08-15",
        "overall_health_score": 73.0,
        "parser_warning_count": 14,
        "open_start_count": 5,
        "open_finish_count": 7,
        "cycle_count": 1,
        "negative_float_count": 2,
        "activity_count": 220,
        "relationship_count": 410,
        "total_float_days": 12.0,
        "critical_path_activity_count": 18,
    }
    run_manifest = {
        "run_timestamp": "2026-03-27T13:45:00+00:00",
        "project": {"project_name": "Aurora Hills", "project_code": "AURORA_HILLS", "schedule_date": "2026-03-26", "finish_date": "2026-08-15"},
    }
    management_actions = {
        "top_10_driver_activities": [
            {"activity_id": "A-101", "activity_name": "Steel Release", "risk_score": 66.0, "why_it_matters": "long lead procurement"}
        ],
        "recovery_levers": ["Lock the steel release package this week."],
    }
    files = {
        root / "portfolio_outputs" / "portfolio_feed.json": portfolio_feed,
        root / "runs" / "AURORA_HILLS" / "outputs" / "dashboard_feed.json": dashboard_feed,
        root / "runs" / "AURORA_HILLS" / "outputs" / "summary.json": summary,
        root / "runs" / "AURORA_HILLS" / "outputs" / "run_manifest.json": run_manifest,
        root / "runs" / "AURORA_HILLS" / "outputs" / "management_actions.json": management_actions,
    }
    for path, payload in files.items():
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (root / "runs" / "AURORA_HILLS" / "outputs" / "management_brief.md").write_text("# Brief\n", encoding="utf-8")
    return root


@pytest.fixture
def sample_profitintel_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "profitintel.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE report_snapshots (
                id INTEGER PRIMARY KEY,
                project_slug TEXT NOT NULL,
                report_month TEXT,
                snapshot_version INTEGER NOT NULL DEFAULT 1,
                snapshot_status TEXT NOT NULL DEFAULT 'active',
                source_file_name TEXT NOT NULL,
                source_file_path TEXT NOT NULL,
                source_checksum TEXT NOT NULL,
                summary_sheet_name TEXT,
                parse_status TEXT NOT NULL DEFAULT 'success',
                completeness_score REAL,
                completeness_label TEXT,
                warning_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                diagnostic_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE project_financial_snapshots (
                id INTEGER PRIMARY KEY,
                report_snapshot_id INTEGER NOT NULL UNIQUE,
                contract_value REAL,
                revised_contract REAL,
                original_budget REAL,
                revised_budget REAL,
                cost_to_date REAL,
                committed_cost REAL,
                cost_to_complete REAL,
                forecast_final_cost REAL,
                projected_profit REAL,
                margin_percent REAL,
                fee_percent REAL
            );
            CREATE TABLE snapshot_trust (
                id INTEGER PRIMARY KEY,
                report_snapshot_id INTEGER NOT NULL UNIQUE,
                trusted INTEGER NOT NULL DEFAULT 0,
                comparison_eligible INTEGER NOT NULL DEFAULT 0,
                reason_codes TEXT NOT NULL DEFAULT '[]',
                checks_json TEXT
            );
            """
        )
        rows = [
            (
                1,
                "219128",
                "2026-02",
                1,
                "active",
                "2026-02.xlsx",
                str(tmp_path / "2026-02.xlsx"),
                "checksum-1",
                "Summary",
                "success",
                100.0,
                "complete",
                0,
                0,
                json.dumps({"trust_tier": "high", "reason_messages": [], "required_metrics_missing": []}),
            ),
            (
                2,
                "219128",
                "2026-03",
                1,
                "active",
                "2026-03.xlsx",
                str(tmp_path / "2026-03.xlsx"),
                "checksum-2",
                "Summary",
                "success",
                100.0,
                "complete",
                0,
                0,
                json.dumps({"trust_tier": "high", "reason_messages": [], "required_metrics_missing": []}),
            ),
        ]
        connection.executemany(
            """
            INSERT INTO report_snapshots (
                id, project_slug, report_month, snapshot_version, snapshot_status, source_file_name,
                source_file_path, source_checksum, summary_sheet_name, parse_status, completeness_score,
                completeness_label, warning_count, error_count, diagnostic_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        financial_rows = [
            (1, 1000000, 1000000, 850000, 880000, 350000, 120000, 460000, 810000, 190000, 19.0, 4.0),
            (2, 1000000, 1020000, 850000, 910000, 420000, 180000, 470000, 890000, 130000, 13.0, 4.0),
        ]
        connection.executemany(
            """
            INSERT INTO project_financial_snapshots (
                report_snapshot_id, contract_value, revised_contract, original_budget, revised_budget,
                cost_to_date, committed_cost, cost_to_complete, forecast_final_cost, projected_profit,
                margin_percent, fee_percent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            financial_rows,
        )
        trust_rows = [
            (1, 1, 1, 1, json.dumps([]), json.dumps({"trust_tier": "high", "reason_messages": [], "required_metrics_missing": []})),
            (2, 2, 1, 1, json.dumps([]), json.dumps({"trust_tier": "high", "reason_messages": [], "required_metrics_missing": []})),
        ]
        connection.executemany(
            "INSERT INTO snapshot_trust (id, report_snapshot_id, trusted, comparison_eligible, reason_codes, checks_json) VALUES (?, ?, ?, ?, ?, ?)",
            trust_rows,
        )
        connection.commit()
    return db_path


@pytest.fixture
def sample_config_path(tmp_path: Path, sample_schedulelab_root: Path, sample_profitintel_db: Path) -> Path:
    config_path = tmp_path / "controltower.yaml"
    registry_path = tmp_path / "project_registry.yaml"
    registry_payload = {
        "manual_overrides": {"profitintel": {"219128": "AURORA_HILLS"}},
        "projects": [
            {
                "canonical_project_id": "AURORA_HILLS",
                "canonical_project_code": "AURORA_HILLS",
                "project_name": "Aurora Hills",
                "project_code_aliases": ["AURORA_HILLS", "Aurora Hills", "219128"],
                "source_aliases": {
                    "schedulelab": ["AURORA_HILLS", "Aurora Hills"],
                    "profitintel": ["219128", "Aurora Hills"],
                },
            }
        ],
    }
    registry_path.write_text(yaml.safe_dump(registry_payload, sort_keys=False), encoding="utf-8")
    payload = {
        "sources": {
            "schedulelab": {"published_root": str(sample_schedulelab_root)},
            "profitintel": {"database_path": str(sample_profitintel_db), "validation_search_roots": []},
        },
        "identity": {"registry_path": str(registry_path)},
        "obsidian": {"vault_root": str(tmp_path / "vault")},
        "runtime": {"state_root": str(tmp_path / "state")},
    }
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return config_path

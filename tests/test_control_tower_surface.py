from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import yaml

from controltower.config import load_config
from controltower.services.controltower import ControlTowerService


def test_control_tower_ranks_attention_and_preserves_arena_order(sample_config_path: Path):
    config = load_config(sample_config_path)
    _add_second_project(config)
    service = ControlTowerService(config)

    tower = service.build_control_tower(["AURORA_HILLS", "BAYVIEW_POINT"])
    arena = service.build_arena(["AURORA_HILLS", "BAYVIEW_POINT"])

    assert tower.top_attention[0].canonical_project_code == "AURORA_HILLS"
    assert tower.top_attention[1].canonical_project_code == "BAYVIEW_POINT"
    assert tower.selected_arena_codes == ["AURORA_HILLS", "BAYVIEW_POINT"]
    assert arena.items[0].canonical_project_code == "AURORA_HILLS"
    assert arena.items[1].canonical_project_code == "BAYVIEW_POINT"
    assert arena.selection_summary == "Agenda order: AURORA_HILLS, BAYVIEW_POINT"
    assert arena.artifact_path.endswith("selected=AURORA_HILLS&selected=BAYVIEW_POINT")
    assert arena.items[0].comparison_label == "Trust-bounded ranking"
    assert [card.key for card in tower.executive_scan] == ["posture", "change", "action", "risk"]
    assert [card.key for card in arena.executive_scan] == ["headline", "change", "impact", "decision"]
    assert tower.required_actions_section.items
    assert arena.material_changes_section.items
    assert arena.items[0].why_it_matters_statement
    assert tower.material_changes_section.items[0].who == "AURORA_HILLS"
    assert tower.material_changes_section.items[0].cause
    assert "projected finish" in tower.material_changes_section.items[0].impact.lower()
    assert tower.meeting_packet.items[0].canonical_project_code == "AURORA_HILLS"
    assert arena.meeting_packet.items[1].canonical_project_code == "BAYVIEW_POINT"
    assert tower.action_queue.item_count >= 1
    assert arena.action_queue.item_count >= 1
    assert tower.continuity.comparison_label == "Current-run continuity only"
    assert arena.continuity.comparison_label == "Current-run continuity only"
    assert arena.items[0].schedule_signal
    assert arena.items[0].action_timing
    assert tower.primary_project_answer.finish_driver.controlling_driver
    assert tower.primary_project_answer.finish_driver_investigation.current_driver.activity_id.value == "A-101"
    assert tower.primary_project_answer.finish_driver_investigation.current_driver.activity_name.value == "Steel Release"
    assert tower.primary_project_answer.finish_driver_investigation.current_driver.float_signal.available is True
    assert tower.primary_project_answer.finish_driver_investigation.current_driver.constraint_signal.available is True
    assert tower.primary_project_answer.finish_driver_investigation.current_driver.sequence_context.available is True
    assert tower.primary_project_answer.driver_change_investigation.available is False
    assert tower.primary_project_answer.change_intelligence.finish.detail
    assert arena.items[0].finish_driver.comparison_state == "unavailable"


def test_arena_defaults_to_current_lead_when_no_selection(sample_config_path: Path):
    config = load_config(sample_config_path)
    service = ControlTowerService(config)

    arena = service.build_arena([])

    assert arena.selected_arena_codes == ["AURORA_HILLS"]
    assert arena.project_answers[0].canonical_project_code == "AURORA_HILLS"
    assert arena.scope_summary == "Fallback review slate: AURORA_HILLS"
    assert arena.selection_summary == "Showing current Control Tower lead: AURORA_HILLS"
    assert arena.promotion_summary.startswith("No explicit Arena selection was stored.")


def _add_second_project(config) -> None:
    published_root = config.sources.schedulelab.published_root
    portfolio_feed_path = published_root / "portfolio_outputs" / "portfolio_feed.json"
    portfolio_feed = json.loads(portfolio_feed_path.read_text(encoding="utf-8"))
    portfolio_feed["projects"].append({"project_name": "Bayview Point", "project_code": "BAYVIEW_POINT"})
    portfolio_feed_path.write_text(json.dumps(portfolio_feed, indent=2), encoding="utf-8")

    outputs_dir = published_root / "runs" / "BAYVIEW_POINT" / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    dashboard = {
        "project": {
            "project_name": "Bayview Point",
            "project_code": "BAYVIEW_POINT",
            "schedule_date": "2026-03-26",
            "finish_date": "2026-07-30",
            "source_file": "bayview_2026-03-26.csv",
        },
        "run": {"run_timestamp": "2026-03-27T13:45:00+00:00"},
        "summary": {
            "activity_count": 140,
            "relationship_count": 255,
            "negative_float_count": 0,
            "open_start_count": 0,
            "open_finish_count": 1,
            "cycle_count": 0,
            "overall_health_score": 92.0,
            "parser_warning_count": 1,
            "rows_dropped_or_skipped": 0,
            "total_float_days": 24.0,
            "critical_path_activity_count": 9,
            "source_file": "bayview_2026-03-26.csv",
        },
        "management": {"milestones": 8, "recovery_levers": 1, "field_questions": 0, "risk_paths": 0, "critical_path_activity_count": 9},
        "trend": {"current": {"issues_total": 4, "top_driver_count": 1, "risk_path_count": 0}},
        "health_score": 92.0,
        "issues_total": 4,
        "risk_flags": [],
        "top_drivers": [
            {"activity_id": "B-101", "activity_name": "Site Finish", "driver_score": 18.0, "driver_reasons": "normal progress"}
        ],
    }
    summary = {
        "project_name": "Bayview Point",
        "project_code": "BAYVIEW_POINT",
        "schedule_date": "2026-03-26",
        "finish_date": "2026-07-30",
        "overall_health_score": 92.0,
        "parser_warning_count": 1,
        "open_start_count": 0,
        "open_finish_count": 1,
        "cycle_count": 0,
        "negative_float_count": 0,
        "activity_count": 140,
        "relationship_count": 255,
        "total_float_days": 24.0,
        "critical_path_activity_count": 9,
    }
    run_manifest = {
        "run_timestamp": "2026-03-27T13:45:00+00:00",
        "project": {"project_name": "Bayview Point", "project_code": "BAYVIEW_POINT", "schedule_date": "2026-03-26", "finish_date": "2026-07-30"},
    }
    management_actions = {
        "top_10_driver_activities": [
            {"activity_id": "B-101", "activity_name": "Site Finish", "risk_score": 18.0, "why_it_matters": "normal progress"}
        ],
        "recovery_levers": ["Maintain the current closeout sequence."],
    }
    for filename, payload in {
        "dashboard_feed.json": dashboard,
        "summary.json": summary,
        "run_manifest.json": run_manifest,
        "management_actions.json": management_actions,
    }.items():
        (outputs_dir / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (outputs_dir / "management_brief.md").write_text("# Brief\n", encoding="utf-8")

    with sqlite3.connect(config.sources.profitintel.database_path) as connection:
        connection.execute(
            """
            INSERT INTO report_snapshots (
                id, project_slug, report_month, snapshot_version, snapshot_status, source_file_name,
                source_file_path, source_checksum, summary_sheet_name, parse_status, completeness_score,
                completeness_label, warning_count, error_count, diagnostic_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                3,
                "220001",
                "2026-03",
                1,
                "active",
                "2026-03-bayview.xlsx",
                str(config.sources.profitintel.database_path.parent / "2026-03-bayview.xlsx"),
                "checksum-3",
                "Summary",
                "success",
                100.0,
                "complete",
                0,
                0,
                json.dumps({"trust_tier": "high", "reason_messages": [], "required_metrics_missing": []}),
            ),
        )
        connection.execute(
            """
            INSERT INTO project_financial_snapshots (
                report_snapshot_id, contract_value, revised_contract, original_budget, revised_budget,
                cost_to_date, committed_cost, cost_to_complete, forecast_final_cost, projected_profit,
                margin_percent, fee_percent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (3, 900000, 900000, 760000, 770000, 320000, 90000, 260000, 760000, 140000, 15.6, 4.0),
        )
        connection.execute(
            "INSERT INTO snapshot_trust (id, report_snapshot_id, trusted, comparison_eligible, reason_codes, checks_json) VALUES (?, ?, ?, ?, ?, ?)",
            (3, 3, 1, 0, json.dumps([]), json.dumps({"trust_tier": "high", "reason_messages": [], "required_metrics_missing": []})),
        )
        connection.commit()

    registry_path = config.identity.registry_path
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["manual_overrides"]["profitintel"]["220001"] = "BAYVIEW_POINT"
    registry["projects"].append(
        {
            "canonical_project_id": "BAYVIEW_POINT",
            "canonical_project_code": "BAYVIEW_POINT",
            "project_name": "Bayview Point",
            "project_code_aliases": ["BAYVIEW_POINT", "Bayview Point", "220001"],
            "source_aliases": {
                "schedulelab": ["BAYVIEW_POINT", "Bayview Point"],
                "profitintel": ["220001", "Bayview Point"],
            },
        }
    )
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

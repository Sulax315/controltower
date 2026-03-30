from __future__ import annotations

import json
import sqlite3
import time

from controltower.config import load_config
from controltower.services.controltower import ControlTowerService
from controltower.services.delta import select_comparison_run_record


def test_delta_computation_tracks_run_to_run_changes(sample_config_path):
    config = load_config(sample_config_path)
    service = ControlTowerService(config)
    first_record = service.export_notes(preview_only=False)

    schedule_summary_path = config.sources.schedulelab.published_root / "runs" / "AURORA_HILLS" / "outputs" / "summary.json"
    dashboard_path = config.sources.schedulelab.published_root / "runs" / "AURORA_HILLS" / "outputs" / "dashboard_feed.json"
    run_manifest_path = config.sources.schedulelab.published_root / "runs" / "AURORA_HILLS" / "outputs" / "run_manifest.json"

    summary = json.loads(schedule_summary_path.read_text(encoding="utf-8"))
    summary["finish_date"] = "2026-08-22"
    summary["total_float_days"] = 8.0
    summary["cycle_count"] = 2
    summary["open_finish_count"] = 9
    summary["negative_float_count"] = 0
    schedule_summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    dashboard["project"]["finish_date"] = "2026-08-22"
    dashboard["summary"]["total_float_days"] = 8.0
    dashboard["summary"]["cycle_count"] = 2
    dashboard["summary"]["open_finish_count"] = 9
    dashboard["summary"]["negative_float_count"] = 0
    dashboard["risk_flags"] = ["open_ends", "critical_path_shift"]
    dashboard["top_drivers"] = [
        {"activity_id": "A-205", "activity_name": "Exterior Close-In", "driver_score": 71.0, "driver_reasons": "enclosure sequence"}
    ]
    dashboard_path.write_text(json.dumps(dashboard, indent=2), encoding="utf-8")

    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    run_manifest["project"]["finish_date"] = "2026-08-22"
    run_manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")

    with sqlite3.connect(config.sources.profitintel.database_path) as connection:
        connection.execute(
            """
            UPDATE project_financial_snapshots
            SET forecast_final_cost = 930000,
                projected_profit = 90000,
                margin_percent = 9.0
            WHERE report_snapshot_id = 2
            """
        )
        connection.commit()

    time.sleep(1.1)
    portfolio = service.build_portfolio()
    project = portfolio.project_rankings[0]
    second_record = service.export_notes(preview_only=False)

    assert first_record.run_id != second_record.run_id
    assert project.delta.schedule.finish_date_movement_days == 7
    assert project.delta.schedule.float_direction == "compression"
    assert project.delta.financial.margin_movement == -4.0
    assert "critical_path_shift" in project.delta.risk.new_risks
    assert project.health.required_actions
    assert project.finish_driver.controlling_driver == "A-205 - Exterior Close-In"
    assert project.finish_driver.comparison_state == "changed"
    assert project.finish_driver.previous_driver == "A-101 - Steel Release"
    assert project.finish_driver_investigation.current_driver.activity_id.value == "A-205"
    assert project.finish_driver_investigation.prior_driver_presence.available is True
    assert "A-101 - Steel Release" in project.finish_driver_investigation.replacement_detail.value
    assert project.driver_change_investigation.available is True
    assert project.driver_change_investigation.prior_driver.activity_id.value == "A-101"
    assert project.driver_change_investigation.current_driver.activity_name.value == "Exterior Close-In"
    assert "Prior trusted run driver: A-101 - Steel Release." in project.driver_change_investigation.difference_summary
    assert project.change_intelligence.driver.state == "changed"
    assert project.change_intelligence.risk.state == "changed"
    assert project.change_intelligence.action.state == "changed"
    assert project.challenge_next == "Challenge why the controlling driver shifted from A-101 - Steel Release to A-205 - Exterior Close-In."
    assert any(item.continuity_state == "new_this_run" for group in service.build_arena(["AURORA_HILLS"]).action_queue.groups for item in group.items)
    assert any(item.continuity_state == "carry_forward" for item in project.action_queue)
    assert project.continuity.new_action_count >= 1
    assert project.continuity.carry_forward_action_count >= 1
    assert project.continuity.resolved_item_count >= 1
    assert any("no longer present" in item.resolution_basis.lower() for item in project.continuity.resolved_items)


def test_comparison_baseline_is_contained_when_only_current_run_exists(sample_config_path):
    config = load_config(sample_config_path)
    service = ControlTowerService(config)
    service.export_notes(preview_only=False)

    portfolio = service.build_portfolio()
    comparison_record = select_comparison_run_record(
        config.runtime.state_root,
        [(project.identity, project.schedule, project.financial) for project in portfolio.project_rankings],
    )

    assert comparison_record is None
    assert portfolio.comparison_trust.status == "contained"
    assert portfolio.comparison_trust.delta_ranking_enabled is False

from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.services.controltower import ControlTowerService


def test_finish_driver_investigation_is_clickable_and_renders_deterministic_panel(sample_config_path):
    config = load_config(sample_config_path)
    service = ControlTowerService(config)
    service.export_notes(preview_only=False)
    app = create_app(str(sample_config_path))
    client = TestClient(app)

    home = client.get("/control")
    script = client.get("/static/investigation.js")

    assert home.status_code == 200
    assert script.status_code == 200
    assert 'data-investigation-open="root-primary-answer-driver-panel"' in home.text
    assert 'id="root-primary-answer-driver-panel"' in home.text
    assert 'data-investigation-panel' in home.text
    assert "Finish Driver Detail" in home.text
    assert "Activity ID" in home.text
    assert "Activity name" in home.text
    assert "Float signal" in home.text
    assert "Constraint signal" in home.text
    assert "Sequence context" in home.text
    assert "Present before?" in home.text
    assert "What replaced it?" in home.text
    assert "A-101" in home.text
    assert "Steel Release" in home.text
    assert 'panel.dataset.panelState = "open"' in script.text
    assert 'trigger.setAttribute("aria-expanded", "true")' in script.text


def test_driver_change_exploration_panel_renders_prior_and_current_driver_details(sample_config_path):
    config = load_config(sample_config_path)
    service = ControlTowerService(config)
    service.export_notes(preview_only=False)
    _publish_driver_change(config)
    app = create_app(str(sample_config_path))
    client = TestClient(app)

    home = client.get("/control")

    assert home.status_code == 200
    assert 'data-investigation-open="root-primary-answer-change-panel"' in home.text
    assert 'id="root-primary-answer-change-panel"' in home.text
    assert "Driver Change Exploration" in home.text
    assert "Difference Summary" in home.text
    assert "Prior Driver" in home.text
    assert "Current Driver" in home.text
    assert "A-101 - Steel Release" in home.text
    assert "A-205 - Exterior Close-In" in home.text
    assert "Prior trusted run driver: A-101 - Steel Release." in home.text
    assert _ordered(
        home.text,
        (
            'id="root-primary-answer"',
            'id="root-answer-finish-driver"',
            'id="root-answer-what-changed"',
            'id="root-secondary-workspace"',
        ),
    )


def _publish_driver_change(config) -> None:
    summary_path = config.sources.schedulelab.published_root / "runs" / "AURORA_HILLS" / "outputs" / "summary.json"
    dashboard_path = config.sources.schedulelab.published_root / "runs" / "AURORA_HILLS" / "outputs" / "dashboard_feed.json"
    run_manifest_path = config.sources.schedulelab.published_root / "runs" / "AURORA_HILLS" / "outputs" / "run_manifest.json"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["finish_date"] = "2026-08-22"
    summary["total_float_days"] = 8.0
    summary["cycle_count"] = 2
    summary["open_finish_count"] = 9
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    dashboard["project"]["finish_date"] = "2026-08-22"
    dashboard["summary"]["total_float_days"] = 8.0
    dashboard["summary"]["cycle_count"] = 2
    dashboard["summary"]["open_finish_count"] = 9
    dashboard["risk_flags"] = ["open_ends", "negative_float", "critical_path_shift"]
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


def _ordered(text: str, tokens: tuple[str, ...]) -> bool:
    cursor = -1
    for token in tokens:
        position = text.find(token)
        if position <= cursor:
            return False
        cursor = position
    return True

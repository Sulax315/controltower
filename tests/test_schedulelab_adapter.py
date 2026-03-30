from __future__ import annotations

import json

from controltower.adapters.schedulelab import ScheduleLabAdapter


def test_schedulelab_adapter_loads_project(sample_schedulelab_root):
    adapter = ScheduleLabAdapter(sample_schedulelab_root)
    projects = adapter.list_projects()

    assert len(projects) == 1
    project = projects[0]
    assert project.project_code == "AURORA_HILLS"
    assert project.health_score == 73.0
    assert project.open_finish_count == 7
    assert project.top_drivers[0].label.startswith("A-101")
    assert project.top_drivers[0].activity_id == "A-101"
    assert project.top_drivers[0].activity_name == "Steel Release"
    assert not adapter.validate()


def test_schedulelab_adapter_derives_finish_from_milestone_drift_log(sample_schedulelab_root):
    dashboard_path = sample_schedulelab_root / "runs" / "AURORA_HILLS" / "outputs" / "dashboard_feed.json"
    summary_path = sample_schedulelab_root / "runs" / "AURORA_HILLS" / "outputs" / "summary.json"
    run_manifest_path = sample_schedulelab_root / "runs" / "AURORA_HILLS" / "outputs" / "run_manifest.json"
    milestone_path = sample_schedulelab_root / "runs" / "AURORA_HILLS" / "outputs" / "milestone_drift_log.csv"

    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    dashboard["project"].pop("finish_date", None)
    dashboard_path.write_text(json.dumps(dashboard, indent=2), encoding="utf-8")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.pop("finish_date", None)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    run_manifest["project"].pop("finish_date", None)
    run_manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")

    milestone_path.write_text(
        "month,activity_id,name,start,finish,float,duration,upstream_count,downstream_count,risk_score,milestone_basis,is_terminal,has_predecessor,has_successor\n"
        "2026-08,101,Project Substantial Completion,2026-08-15,2026-08-15,0,0,12,1,24.0,multiple,False,True,True\n",
        encoding="utf-8",
    )

    adapter = ScheduleLabAdapter(sample_schedulelab_root)
    project = adapter.list_projects()[0]

    assert project.finish_date == "2026-08-15"
    assert project.finish_source == "published_milestone_drift_log"
    assert project.finish_source_label == "Published milestone drift log"
    assert "Project Substantial Completion" in project.finish_detail


def test_schedulelab_adapter_emits_deterministic_finish_unavailable_reason(sample_schedulelab_root):
    dashboard_path = sample_schedulelab_root / "runs" / "AURORA_HILLS" / "outputs" / "dashboard_feed.json"
    summary_path = sample_schedulelab_root / "runs" / "AURORA_HILLS" / "outputs" / "summary.json"
    run_manifest_path = sample_schedulelab_root / "runs" / "AURORA_HILLS" / "outputs" / "run_manifest.json"
    milestone_path = sample_schedulelab_root / "runs" / "AURORA_HILLS" / "outputs" / "milestone_drift_log.csv"

    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    dashboard["project"].pop("finish_date", None)
    dashboard_path.write_text(json.dumps(dashboard, indent=2), encoding="utf-8")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.pop("finish_date", None)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    run_manifest["project"].pop("finish_date", None)
    run_manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")

    milestone_path.write_text(
        "month,activity_id,name,start,finish,float,duration,upstream_count,downstream_count,risk_score,milestone_basis,is_terminal,has_predecessor,has_successor\n",
        encoding="utf-8",
    )

    adapter = ScheduleLabAdapter(sample_schedulelab_root)
    project = adapter.list_projects()[0]

    assert project.finish_date is None
    assert project.finish_source == "unavailable"
    assert project.finish_detail == "No finish milestone/date was found in the published schedule artifact."

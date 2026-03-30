from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.services.controltower import ControlTowerService


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Control Tower trust posture and Arena export runtime coherence.")
    parser.add_argument("--config", type=Path, default=Path("controltower.example.yaml"), help="Control Tower config file to clone.")
    args = parser.parse_args()

    config = load_config(args.config)
    with TemporaryDirectory(prefix="controltower-runtime-proof-") as tmp_dir:
        temp_root = Path(tmp_dir)
        temp_config_path = _clone_config(config, temp_root)
        result = _run_verification(temp_config_path)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "pass" else 1


def _clone_config(config, temp_root: Path) -> Path:
    schedulelab_root = temp_root / "schedulelab"
    profitintel_root = temp_root / "profitintel"
    profitintel_root.mkdir(parents=True, exist_ok=True)
    registry_path = temp_root / "project_registry.yaml"
    vault_root = temp_root / "vault"
    state_root = temp_root / "state"

    shutil.copytree(config.sources.schedulelab.published_root, schedulelab_root)
    profitintel_db = profitintel_root / config.sources.profitintel.database_path.name
    shutil.copy2(config.sources.profitintel.database_path, profitintel_db)
    shutil.copy2(config.identity.registry_path, registry_path)

    payload = config.model_dump(mode="json")
    payload["sources"]["schedulelab"]["published_root"] = str(schedulelab_root)
    payload["sources"]["profitintel"]["database_path"] = str(profitintel_db)
    payload["sources"]["profitintel"]["validation_search_roots"] = [str(profitintel_root)]
    payload["identity"]["registry_path"] = str(registry_path)
    payload["obsidian"]["vault_root"] = str(vault_root)
    payload["runtime"]["state_root"] = str(state_root)

    config_path = temp_root / "verification_config.yaml"
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return config_path


def _run_verification(config_path: Path) -> dict[str, object]:
    config = load_config(config_path)
    service = ControlTowerService(config)
    selected_code = service.build_portfolio().project_rankings[0].canonical_project_code

    service.export_notes(preview_only=False)
    contained = _verify_scenario(config_path, [selected_code], expected_reason_code="no_distinct_prior_run", expected_authority="trust_bounded")

    _mutate_sources_for_distinct_run(config)
    time.sleep(1.1)
    service = ControlTowerService(config)
    service.export_notes(preview_only=False)
    trusted = _verify_scenario(config_path, [selected_code], expected_reason_code=None, expected_authority="authoritative")

    status = "pass" if contained["status"] == "pass" and trusted["status"] == "pass" else "fail"
    return {
        "status": status,
        "config_path": str(config_path),
        "contained_scenario": contained,
        "trusted_scenario": trusted,
    }


def _verify_scenario(
    config_path: Path,
    selected_codes: list[str],
    *,
    expected_reason_code: str | None,
    expected_authority: str,
) -> dict[str, object]:
    config = load_config(config_path)
    service = ControlTowerService(config)
    app = create_app(str(config_path))
    client = TestClient(app)

    control_tower = service.build_control_tower(selected_codes)
    arena = service.build_arena(selected_codes)
    diagnostics = client.get("/api/diagnostics")
    diagnostics_payload = diagnostics.json() if diagnostics.status_code == 200 else {}
    root = client.get(_path("/", selected_codes))
    arena_response = client.get(_path("/arena", selected_codes))
    artifact = client.get(_path("/arena/export/artifact.md", selected_codes))
    runtime_coherence = service.build_runtime_coherence_snapshot(selected_codes)

    checks = {
        "root_renders_trust_posture": (
            root.status_code == 200
            and arena.comparison_trust.ranking_label in root.text
            and arena.comparison_trust.baseline_label in root.text
        ),
        "arena_renders_trust_posture": (
            arena_response.status_code == 200
            and arena.comparison_trust.ranking_label in arena_response.text
            and arena.comparison_trust.baseline_label in arena_response.text
        ),
        "export_route_returns_successfully": artifact.status_code == 200,
        "export_contains_selection_context": (
            arena.selection_summary in artifact.text
            and arena.scope_summary in artifact.text
            and arena.promotion_summary in artifact.text
        ),
        "export_contains_timestamp_context": "Generated at:" in artifact.text and arena.generated_at[:10] in artifact.text,
        "export_contains_authority_or_degraded_state": (
            arena.comparison_trust.ranking_label in artifact.text
            and arena.comparison_trust.baseline_label in artifact.text
        ),
        "export_matches_selected_model": (
            artifact.headers.get("X-ControlTower-Arena-Selection") == ",".join(selected_codes)
            and runtime_coherence["arena_item_codes"] == selected_codes
            and control_tower.arena_artifact_path == _path("/arena/export/artifact.md", selected_codes)
        ),
        "baseline_selection_matches_runtime": bool(runtime_coherence["comparison_run_matches_surface"]),
        "delta_ranking_matches_baseline": bool(runtime_coherence["delta_ranking_consistent_with_baseline"]),
        "surfaced_trust_matches_diagnostics": (
            (diagnostics_payload.get("comparison_runtime") or {}).get("ranking_authority")
            == runtime_coherence["ranking_authority"]
        )
        and (
            (diagnostics_payload.get("comparison_runtime") or {}).get("comparison_trust", {}).get("reason_code")
            == runtime_coherence["comparison_trust"]["reason_code"]
        ),
        "no_distinct_prior_run_is_contained": True,
        "expected_authority_is_present": arena.comparison_trust.ranking_authority == expected_authority,
    }

    if expected_reason_code is not None:
        checks["no_distinct_prior_run_is_contained"] = (
            arena.comparison_trust.reason_code == expected_reason_code
            and arena.comparison_trust.ranking_authority == "trust_bounded"
            and "No distinct trusted prior baseline" in artifact.text
            and runtime_coherence["contained_blocks_authoritative_delta"] is True
        )

    status = "pass" if all(checks.values()) else "fail"
    return {
        "status": status,
        "comparison_trust": arena.comparison_trust.model_dump(mode="json"),
        "runtime_coherence": runtime_coherence,
        "checks": checks,
        "root_status_code": root.status_code,
        "arena_status_code": arena_response.status_code,
        "artifact_status_code": artifact.status_code,
        "artifact_excerpt": artifact.text.splitlines()[:24],
    }


def _mutate_sources_for_distinct_run(config) -> None:
    service = ControlTowerService(config)
    project = service.build_portfolio().project_rankings[0]
    project_code = project.canonical_project_code
    outputs_dir = config.sources.schedulelab.published_root / "runs" / project_code / "outputs"
    summary_path = outputs_dir / "summary.json"
    dashboard_path = outputs_dir / "dashboard_feed.json"
    manifest_path = outputs_dir / "run_manifest.json"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    next_finish = _bump_date(str(summary.get("finish_date") or dashboard.get("project", {}).get("finish_date") or date.today().isoformat()))
    next_timestamp = _bump_timestamp(str((dashboard.get("run") or {}).get("run_timestamp") or manifest.get("run_timestamp") or "2026-03-28T12:00:00+00:00"))
    current_float = float(summary.get("total_float_days") or dashboard.get("summary", {}).get("total_float_days") or 0.0)
    current_cycle_count = int(summary.get("cycle_count") or dashboard.get("summary", {}).get("cycle_count") or 0)
    current_open_finish = int(summary.get("open_finish_count") or dashboard.get("summary", {}).get("open_finish_count") or 0)

    summary["finish_date"] = next_finish
    summary["total_float_days"] = max(0.0, current_float - 4.0)
    summary["cycle_count"] = current_cycle_count + 1
    summary["open_finish_count"] = current_open_finish + 1
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    dashboard.setdefault("project", {})["finish_date"] = next_finish
    dashboard.setdefault("run", {})["run_timestamp"] = next_timestamp
    dashboard.setdefault("summary", {})["total_float_days"] = summary["total_float_days"]
    dashboard["summary"]["cycle_count"] = summary["cycle_count"]
    dashboard["summary"]["open_finish_count"] = summary["open_finish_count"]
    dashboard["risk_flags"] = sorted({*dashboard.get("risk_flags", []), "critical_path_shift"})
    dashboard_path.write_text(json.dumps(dashboard, indent=2), encoding="utf-8")

    manifest["run_timestamp"] = next_timestamp
    manifest.setdefault("project", {})["finish_date"] = next_finish
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if project.financial and project.financial.snapshot_id is not None:
        with sqlite3.connect(config.sources.profitintel.database_path) as connection:
            connection.execute(
                """
                UPDATE project_financial_snapshots
                SET forecast_final_cost = COALESCE(forecast_final_cost, 0) + 40000,
                    projected_profit = COALESCE(projected_profit, 0) - 40000,
                    margin_percent = COALESCE(margin_percent, 0) - 1.5
                WHERE report_snapshot_id = ?
                """,
                (project.financial.snapshot_id,),
            )
            connection.commit()


def _path(base: str, selected_codes: list[str]) -> str:
    if not selected_codes:
        return base
    return base + "?" + "&".join(f"selected={code}" for code in selected_codes)


def _bump_date(value: str) -> str:
    return (date.fromisoformat(value[:10]) + timedelta(days=7)).isoformat()


def _bump_timestamp(value: str) -> str:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return "2026-03-29T13:00:00+00:00"
    return (parsed + timedelta(days=1, hours=1)).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())

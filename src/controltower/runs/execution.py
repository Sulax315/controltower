from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from controltower.schedule_intake import (
    FILENAME_BUNDLE,
    FILENAME_MANIFEST,
    build_driver_analysis,
    build_exploration_contract,
    build_logic_graph_payload,
    build_schedule_graph_summary,
    build_schedule_intelligence_bundle,
    build_schedule_logic_graph,
    collect_schedule_risk_findings,
    export_deterministic_artifact_set,
    parse_asta_export_csv,
    rank_driver_candidates,
)
from controltower.schedule_intake.command_brief import build_command_brief
from controltower.schedule_intake.export_artifacts import compute_sha256_bytes
from controltower.schedule_intake.normalized_intake import build_normalized_intake_payload
from controltower.schedule_intake.output_contracts import ScheduleIntelligenceBundle
from controltower.schedule_intake.logic_quality import analyze_logic_quality
from controltower.schedule_intake.verification import validate_export_artifact_set

from .registry import create_run, update_run_status


def execute_run(csv_path: Path, *, state_root: Path) -> str:
    source_path = Path(csv_path).expanduser().resolve()
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"Run input CSV is missing: {source_path}")
    run_id = _generate_run_id(source_path)
    run_root = Path(state_root) / "runs" / run_id
    input_dir = run_root / "input"
    artifacts_dir = run_root / "artifacts"
    input_file = input_dir / "schedule.csv"

    create_run(
        state_root,
        run_id=run_id,
        input_filename=source_path.name,
        input_path=input_file,
        artifact_dir=artifacts_dir,
        bundle_path=artifacts_dir / FILENAME_BUNDLE,
        manifest_path=artifacts_dir / FILENAME_MANIFEST,
        status="running",
    )

    try:
        input_dir.mkdir(parents=True, exist_ok=True)
        source_bytes = source_path.read_bytes()
        input_file.write_bytes(source_bytes)

        bundle, normalized_intake, logic_graph, driver_analysis = _build_bundle_from_csv(
            input_file,
            source_sha256_hex=compute_sha256_bytes(source_bytes),
        )

        export_deterministic_artifact_set(
            artifacts_dir,
            bundle=bundle,
            normalized_intake=normalized_intake,
            logic_graph=logic_graph,
            driver_analysis=driver_analysis,
        )
        validation = validate_export_artifact_set(artifacts_dir)
        if not validation.ok:
            raise ValueError("; ".join(validation.errors))

        update_run_status(state_root, run_id, status="completed", error_message=None)
    except Exception as exc:
        update_run_status(state_root, run_id, status="failed", error_message=str(exc))
    return run_id


def _generate_run_id(source_path: Path) -> str:
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d_%H%M%S")
    seed = f"{source_path}:{now.isoformat()}".encode("utf-8")
    suffix = hashlib.sha1(seed).hexdigest()[:8]
    return f"run_{ts}_{suffix}"


def _build_bundle_from_csv(
    csv_path: Path, *, source_sha256_hex: str
) -> tuple[ScheduleIntelligenceBundle, dict, dict, dict]:
    parse_result = parse_asta_export_csv(csv_path)
    normalized_intake = build_normalized_intake_payload(
        parse_result.activities,
        warnings=tuple(parse_result.warnings),
        source_display_name=csv_path.name,
        source_sha256_hex=source_sha256_hex,
    )
    graph = build_schedule_logic_graph(parse_result.activities)
    logic_graph = build_logic_graph_payload(graph)
    driver_analysis_obj = build_driver_analysis(graph)
    if driver_analysis_obj is None:
        raise ValueError("No structural finish candidate available for deterministic driver detection.")
    driver_analysis = driver_analysis_obj.model_dump(mode="json")
    graph_summary = build_schedule_graph_summary(graph)
    logic_quality = analyze_logic_quality(graph)
    top_candidates = rank_driver_candidates(graph, limit=1)
    top_driver = top_candidates[0] if top_candidates else None
    risks = collect_schedule_risk_findings(
        graph,
        logic_quality=logic_quality,
        graph_summary=graph_summary,
        driver_analysis=driver_analysis_obj,
    )
    command_brief = build_command_brief(
        graph_summary=graph_summary,
        driver_analysis=driver_analysis_obj,
        risks=risks,
    )
    bundle = build_schedule_intelligence_bundle(
        graph_summary=graph_summary,
        logic_quality=logic_quality,
        driver_analysis=driver_analysis_obj,
        top_driver=top_driver,
        risks=risks,
        delta=None,
        command_brief=command_brief,
        exploration=build_exploration_contract(),
    )
    return bundle, normalized_intake, logic_graph, driver_analysis

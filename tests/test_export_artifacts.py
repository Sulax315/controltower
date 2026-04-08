from __future__ import annotations

import json
from pathlib import Path

from controltower.schedule_intake import (
    Activity,
    FILENAME_BUNDLE,
    FILENAME_COMMAND_BRIEF,
    FILENAME_DRIVER_ANALYSIS,
    FILENAME_ENGINE_SNAPSHOT,
    FILENAME_EXPLORATION,
    FILENAME_LOGIC_GRAPH,
    FILENAME_MANIFEST,
    FILENAME_NORMALIZED_INTAKE,
    NORMALIZED_INTAKE_SCHEMA_VERSION,
    build_command_brief,
    build_exploration_contract,
    build_export_manifest,
    build_normalized_intake_payload,
    build_logic_graph_payload,
    build_driver_analysis,
    build_schedule_graph_summary,
    build_schedule_intelligence_bundle,
    build_schedule_logic_graph,
    collect_schedule_risk_findings,
    compute_sha256_bytes,
    export_deterministic_artifact_set,
    export_directory_file_map,
    rank_driver_candidates,
)
from controltower.schedule_intake.logic_quality import analyze_logic_quality
from controltower.schedule_intake.verification import validate_export_artifact_set

_BUNDLE_ACTIVITIES = [
    Activity(task_id="1", successors=["2"]),
    Activity(task_id="2", predecessors=["1"], successors=["3"]),
    Activity(task_id="3", predecessors=["2"]),
]


def _synthetic_normalized_intake() -> dict:
    return build_normalized_intake_payload(
        _BUNDLE_ACTIVITIES,
        warnings=(),
        source_display_name="synthetic.json",
        source_sha256_hex=None,
    )


def _build_bundle():
    graph = build_schedule_logic_graph(_BUNDLE_ACTIVITIES)
    gs = build_schedule_graph_summary(graph)
    lq = analyze_logic_quality(graph)
    risks = collect_schedule_risk_findings(graph, logic_quality=lq, graph_summary=gs)
    top = rank_driver_candidates(graph, limit=1)[0]
    brief = build_command_brief(graph_summary=gs, driver=top, risks=risks, delta=None)
    exploration = build_exploration_contract()
    return build_schedule_intelligence_bundle(
        graph_summary=gs,
        logic_quality=lq,
        top_driver=top,
        risks=risks,
        delta=None,
        command_brief=brief,
        exploration=exploration,
    )


def _synthetic_logic_graph() -> dict:
    return build_logic_graph_payload(build_schedule_logic_graph(_BUNDLE_ACTIVITIES))


def _synthetic_driver_analysis() -> dict:
    da = build_driver_analysis(build_schedule_logic_graph(_BUNDLE_ACTIVITIES))
    assert da is not None
    return da.model_dump(mode="json")


def test_deterministic_json_bytes_across_repeated_runs(tmp_path: Path) -> None:
    bundle = _build_bundle()
    norm = _synthetic_normalized_intake()
    dir1 = tmp_path / "run1"
    dir2 = tmp_path / "run2"
    graph = _synthetic_logic_graph()
    driver = _synthetic_driver_analysis()
    export_deterministic_artifact_set(
        dir1,
        bundle=bundle,
        normalized_intake=norm,
        logic_graph=graph,
        driver_analysis=driver,
    )
    export_deterministic_artifact_set(
        dir2,
        bundle=bundle,
        normalized_intake=norm,
        logic_graph=graph,
        driver_analysis=driver,
    )
    files = [
        FILENAME_BUNDLE,
        FILENAME_COMMAND_BRIEF,
        FILENAME_ENGINE_SNAPSHOT,
        FILENAME_EXPLORATION,
        FILENAME_NORMALIZED_INTAKE,
        FILENAME_LOGIC_GRAPH,
        FILENAME_MANIFEST,
    ]
    for name in files:
        assert (dir1 / name).read_bytes() == (dir2 / name).read_bytes()


def test_stable_manifest_contents_and_filenames(tmp_path: Path) -> None:
    bundle = _build_bundle()
    artifacts, manifest = export_deterministic_artifact_set(
        tmp_path,
        bundle=bundle,
        normalized_intake=_synthetic_normalized_intake(),
        logic_graph=_synthetic_logic_graph(),
        driver_analysis=_synthetic_driver_analysis(),
    )
    assert tuple(a.filename for a in artifacts) == (
        FILENAME_BUNDLE,
        FILENAME_COMMAND_BRIEF,
        FILENAME_ENGINE_SNAPSHOT,
        FILENAME_EXPLORATION,
        FILENAME_NORMALIZED_INTAKE,
        FILENAME_LOGIC_GRAPH,
        FILENAME_DRIVER_ANALYSIS,
        FILENAME_MANIFEST,
    )
    assert manifest.bundle_present is True
    assert manifest.command_brief_present is True
    assert manifest.engine_snapshot_present is True
    assert manifest.exploration_present is True
    assert manifest.normalized_intake_present is True
    assert manifest.logic_graph_present is True
    assert manifest.driver_analysis_present is True
    on_disk = json.loads((tmp_path / FILENAME_MANIFEST).read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == "1.0.0"
    assert on_disk["export_scope"] == "schedule_intelligence"


def test_manifest_sha256_matches_written_files(tmp_path: Path) -> None:
    bundle = _build_bundle()
    artifacts, _ = export_deterministic_artifact_set(
        tmp_path,
        bundle=bundle,
        normalized_intake=_synthetic_normalized_intake(),
        logic_graph=_synthetic_logic_graph(),
        driver_analysis=_synthetic_driver_analysis(),
    )
    by_name = {a.filename: a for a in artifacts}
    for name, artifact in by_name.items():
        b = (tmp_path / name).read_bytes()
        assert artifact.sha256 == compute_sha256_bytes(b)
        assert artifact.byte_count == len(b)


def test_command_brief_export_integrity(tmp_path: Path) -> None:
    bundle = _build_bundle()
    export_deterministic_artifact_set(
        tmp_path,
        bundle=bundle,
        normalized_intake=_synthetic_normalized_intake(),
        logic_graph=_synthetic_logic_graph(),
        driver_analysis=_synthetic_driver_analysis(),
    )
    payload = json.loads((tmp_path / FILENAME_COMMAND_BRIEF).read_text(encoding="utf-8"))
    assert tuple(payload.keys()) == ("action", "delta", "driver", "finish", "risks")
    assert payload["finish"].startswith("FINISH:")


def test_engine_snapshot_export_integrity(tmp_path: Path) -> None:
    bundle = _build_bundle()
    export_deterministic_artifact_set(
        tmp_path,
        bundle=bundle,
        normalized_intake=_synthetic_normalized_intake(),
        logic_graph=_synthetic_logic_graph(),
        driver_analysis=_synthetic_driver_analysis(),
    )
    payload = json.loads((tmp_path / FILENAME_ENGINE_SNAPSHOT).read_text(encoding="utf-8"))
    assert "graph_summary" in payload
    assert "logic_quality" in payload
    assert "command_brief_lines" in payload


def test_exploration_export_integrity_default_empty(tmp_path: Path) -> None:
    bundle = _build_bundle()
    export_deterministic_artifact_set(
        tmp_path,
        bundle=bundle,
        normalized_intake=_synthetic_normalized_intake(),
        logic_graph=_synthetic_logic_graph(),
        driver_analysis=_synthetic_driver_analysis(),
    )
    payload = json.loads((tmp_path / FILENAME_EXPLORATION).read_text(encoding="utf-8"))
    assert payload["immediate_predecessors"] == []
    assert payload["immediate_successors"] == []
    assert payload["driver_structure"] is None
    assert payload["impact_span"] is None


def test_normalized_intake_export_integrity(tmp_path: Path) -> None:
    bundle = _build_bundle()
    export_deterministic_artifact_set(
        tmp_path,
        bundle=bundle,
        normalized_intake=_synthetic_normalized_intake(),
        logic_graph=_synthetic_logic_graph(),
        driver_analysis=_synthetic_driver_analysis(),
    )
    payload = json.loads((tmp_path / FILENAME_NORMALIZED_INTAKE).read_text(encoding="utf-8"))
    assert payload["schema_version"] == NORMALIZED_INTAKE_SCHEMA_VERSION
    assert payload["activity_count"] == 3
    assert payload["source_csv"] == "synthetic.json"
    assert len(payload["activities"]) == 3
    assert {a["task_id"] for a in payload["activities"]} == {"1", "2", "3"}


def test_intelligence_bundle_export_integrity(tmp_path: Path) -> None:
    bundle = _build_bundle()
    export_deterministic_artifact_set(
        tmp_path,
        bundle=bundle,
        normalized_intake=_synthetic_normalized_intake(),
        logic_graph=_synthetic_logic_graph(),
        driver_analysis=_synthetic_driver_analysis(),
    )
    payload = json.loads((tmp_path / FILENAME_BUNDLE).read_text(encoding="utf-8"))
    assert tuple(payload.keys()) == ("command_brief", "engine_snapshot", "exploration")


def test_repeat_export_clean_temp_dir_identical_contents(tmp_path: Path) -> None:
    bundle = _build_bundle()
    norm = _synthetic_normalized_intake()
    a = tmp_path / "a"
    b = tmp_path / "b"
    graph = _synthetic_logic_graph()
    driver = _synthetic_driver_analysis()
    export_deterministic_artifact_set(
        a, bundle=bundle, normalized_intake=norm, logic_graph=graph, driver_analysis=driver
    )
    export_deterministic_artifact_set(
        b, bundle=bundle, normalized_intake=norm, logic_graph=graph, driver_analysis=driver
    )
    assert export_directory_file_map(a) == export_directory_file_map(b)


def test_build_export_manifest_from_subset_artifacts() -> None:
    from controltower.schedule_intake.export_artifacts import ExportedArtifact

    artifacts = (
        ExportedArtifact(filename=FILENAME_COMMAND_BRIEF, sha256="a", byte_count=1, artifact_type="command_brief"),
        ExportedArtifact(filename=FILENAME_ENGINE_SNAPSHOT, sha256="b", byte_count=2, artifact_type="engine_snapshot"),
    )
    m = build_export_manifest(artifacts)
    assert m.bundle_present is False
    assert m.command_brief_present is True
    assert m.engine_snapshot_present is True
    assert m.exploration_present is False
    assert m.normalized_intake_present is False
    assert m.logic_graph_present is False
    assert m.driver_analysis_present is False


def test_export_validation_passes_for_clean_artifact_set(tmp_path: Path) -> None:
    bundle = _build_bundle()
    export_deterministic_artifact_set(
        tmp_path,
        bundle=bundle,
        normalized_intake=_synthetic_normalized_intake(),
        logic_graph=_synthetic_logic_graph(),
        driver_analysis=_synthetic_driver_analysis(),
    )
    result = validate_export_artifact_set(tmp_path)
    assert result.ok is True
    assert result.errors == ()


def test_export_validation_detects_tampered_artifact(tmp_path: Path) -> None:
    bundle = _build_bundle()
    export_deterministic_artifact_set(
        tmp_path,
        bundle=bundle,
        normalized_intake=_synthetic_normalized_intake(),
        logic_graph=_synthetic_logic_graph(),
        driver_analysis=_synthetic_driver_analysis(),
    )
    target = tmp_path / FILENAME_BUNDLE
    target.write_text('{"tampered":true}\n', encoding="utf-8")
    result = validate_export_artifact_set(tmp_path)
    assert result.ok is False
    assert any("hash mismatch" in e for e in result.errors)


def test_export_validation_detects_missing_artifact(tmp_path: Path) -> None:
    bundle = _build_bundle()
    export_deterministic_artifact_set(
        tmp_path,
        bundle=bundle,
        normalized_intake=_synthetic_normalized_intake(),
        logic_graph=_synthetic_logic_graph(),
        driver_analysis=_synthetic_driver_analysis(),
    )
    (tmp_path / FILENAME_EXPLORATION).unlink()
    result = validate_export_artifact_set(tmp_path)
    assert result.ok is False
    assert any(FILENAME_EXPLORATION in e for e in result.errors)


def test_export_validation_detects_missing_normalized_intake(tmp_path: Path) -> None:
    bundle = _build_bundle()
    export_deterministic_artifact_set(
        tmp_path,
        bundle=bundle,
        normalized_intake=_synthetic_normalized_intake(),
        logic_graph=_synthetic_logic_graph(),
        driver_analysis=_synthetic_driver_analysis(),
    )
    (tmp_path / FILENAME_NORMALIZED_INTAKE).unlink()
    result = validate_export_artifact_set(tmp_path)
    assert result.ok is False
    assert any(FILENAME_NORMALIZED_INTAKE in e for e in result.errors)


def test_export_validation_detects_missing_driver_analysis(tmp_path: Path) -> None:
    bundle = _build_bundle()
    export_deterministic_artifact_set(
        tmp_path,
        bundle=bundle,
        normalized_intake=_synthetic_normalized_intake(),
        logic_graph=_synthetic_logic_graph(),
        driver_analysis=_synthetic_driver_analysis(),
    )
    (tmp_path / FILENAME_DRIVER_ANALYSIS).unlink()
    result = validate_export_artifact_set(tmp_path)
    assert result.ok is False
    assert any(FILENAME_DRIVER_ANALYSIS in e for e in result.errors)


def test_logic_graph_export_integrity(tmp_path: Path) -> None:
    bundle = _build_bundle()
    export_deterministic_artifact_set(
        tmp_path,
        bundle=bundle,
        normalized_intake=_synthetic_normalized_intake(),
        logic_graph=_synthetic_logic_graph(),
        driver_analysis=_synthetic_driver_analysis(),
    )
    payload = json.loads((tmp_path / FILENAME_LOGIC_GRAPH).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "schedule_logic_graph_v1"
    assert payload["nodes"] == ["1", "2", "3"]
    assert payload["edges"] == [
        {"from_task_id": "1", "to_task_id": "2"},
        {"from_task_id": "2", "to_task_id": "3"},
    ]
    assert payload["finish_candidates"] == [
        {"task_id": "3", "in_degree": 1, "out_degree": 0, "has_predecessor": True},
    ]


def test_driver_analysis_export_integrity(tmp_path: Path) -> None:
    bundle = _build_bundle()
    export_deterministic_artifact_set(
        tmp_path,
        bundle=bundle,
        normalized_intake=_synthetic_normalized_intake(),
        logic_graph=_synthetic_logic_graph(),
        driver_analysis=_synthetic_driver_analysis(),
    )
    payload = json.loads((tmp_path / FILENAME_DRIVER_ANALYSIS).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "driver_analysis_v1"
    assert payload["authoritative_finish_target"]["task_id"] == "3"
    assert payload["driver_path"] == ["1", "2", "3"]

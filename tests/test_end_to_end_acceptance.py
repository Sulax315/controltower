from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.schedule_intake import (
    Activity,
    FILENAME_BUNDLE,
    build_command_brief,
    build_exploration_contract,
    build_schedule_graph_summary,
    build_schedule_intelligence_bundle,
    build_schedule_logic_graph,
    collect_schedule_risk_findings,
    export_deterministic_artifact_set,
    export_directory_file_map,
    rank_driver_candidates,
)
from controltower.schedule_intake.logic_quality import analyze_logic_quality
from controltower.schedule_intake.publish_assembly import build_publish_packet
from controltower.schedule_intake.verification import load_publish_bundle, validate_export_artifact_set


def _build_bundle():
    graph = build_schedule_logic_graph(
        [
            Activity(task_id="1", successors=["2"]),
            Activity(task_id="2", predecessors=["1"], successors=["3"]),
            Activity(task_id="3", predecessors=["2"]),
        ]
    )
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


def test_end_to_end_acceptance_full_chain(sample_config_path, tmp_path: Path) -> None:
    bundle = _build_bundle()
    export_dir = tmp_path / "full_chain"
    export_deterministic_artifact_set(export_dir, bundle=bundle)

    validation = validate_export_artifact_set(export_dir)
    assert validation.ok is True
    assert validation.errors == ()

    loaded_bundle = load_publish_bundle(str(export_dir / FILENAME_BUNDLE))
    publish_packet = build_publish_packet(loaded_bundle)
    packet_json = publish_packet.to_jsonable_dict()
    assert packet_json["header"]["finish_line"].startswith("FINISH:")
    assert packet_json["verdict"]["action_token"].startswith("ACTION:")
    assert isinstance(packet_json["kpis"]["risk_count"], int)

    client = TestClient(create_app(str(sample_config_path)))
    response = client.get("/publish/operator", params={"bundle": str(export_dir / FILENAME_BUNDLE)})
    assert response.status_code == 200
    assert 'id="publish-operator-header-strip"' in response.text
    assert 'id="publish-operator-verdict"' in response.text
    assert 'id="publish-operator-kpis"' in response.text
    assert 'id="publish-operator-drivers-risks"' in response.text
    assert 'id="publish-operator-evidence"' in response.text
    assert 'id="publish-operator-error"' not in response.text
    assert bundle.command_brief.finish in response.text


def test_end_to_end_deterministic_stable_outputs(tmp_path: Path) -> None:
    bundle = _build_bundle()
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    export_deterministic_artifact_set(run_a, bundle=bundle)
    export_deterministic_artifact_set(run_b, bundle=bundle)

    assert export_directory_file_map(run_a) == export_directory_file_map(run_b)

    packet_a = build_publish_packet(load_publish_bundle(str(run_a / FILENAME_BUNDLE))).to_jsonable_dict()
    packet_b = build_publish_packet(load_publish_bundle(str(run_b / FILENAME_BUNDLE))).to_jsonable_dict()
    assert packet_a == packet_b

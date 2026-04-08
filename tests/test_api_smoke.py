from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.obsidian.exporter import write_export_bundle
from controltower.services.controltower import ControlTowerService
from controltower.services.meeting_readiness import verify_meeting_readiness
from controltower.services.orchestration import OrchestrationService


@pytest.mark.skip(reason="Superseded by Phase 12/13 single-surface tests (tests/test_publish_authority.py).")
def test_api_and_pages_render(sample_config_path):
    config = load_config(sample_config_path)
    service = ControlTowerService(config)
    record = service.export_notes(preview_only=False)
    tower = service.build_control_tower(["AURORA_HILLS"])
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    health = client.get("/healthz")

    assert health.status_code == 200
    health_payload = health.json()
    assert health_payload["status"] == "ok"
    assert health_payload == {"status": "ok"}
    assert "no-store" in health.headers["cache-control"]

    root_redirect = client.get("/", follow_redirects=False)
    assert root_redirect.status_code == 307
    assert root_redirect.headers["location"].endswith("/publish")

    home = client.get("/")
    assert home.status_code == 200
    assert 'id="publish-command-sheet"' in home.text
    assert 'id="publish-latest-brief"' in home.text
    assert 'id="publish-home-header"' in home.text
    assert "Meeting-ready command brief" in home.text
    assert '/static/site.css?v=' in home.text
    assert '/static/investigation.js?v=' in home.text
    assert 'class="ct-layout"' in home.text
    assert 'class="ct-header"' in home.text
    assert 'class="ct-command-strip command-strip"' in home.text
    assert 'class="ct-sidebar"' in home.text
    assert "Open Arena" in home.text
    assert "Export PDF" in home.text
    assert "Copy 5-Line Brief" in home.text
    assert "Present" in home.text
    assert 'href="/publish" class="nav-primary is-active"' in home.text
    assert 'aria-current="page">Publish</a>' in home.text
    assert "Executive operating view" not in home.text
    assert 'id="root-primary-workspace"' not in home.text
    assert publish_markers_present(home.text)

    legacy = client.get("/control")
    assert legacy.status_code == 200
    assert "Legacy Control" in legacy.text
    assert "Executive operating view" in legacy.text
    assert 'id="root-primary-workspace"' in legacy.text
    assert 'id="root-secondary-workspace"' in legacy.text
    assert 'id="root-support-workspace"' in legacy.text
    assert 'id="root-primary-answer"' in legacy.text
    assert 'id="root-primary-answer-finish"' in legacy.text
    assert 'id="root-primary-answer-driver"' in legacy.text
    assert 'id="root-primary-answer-risks"' in legacy.text
    assert 'id="root-primary-answer-need"' in legacy.text
    assert 'id="root-primary-answer-doing"' in legacy.text
    assert 'id="root-answer-finish-driver"' in legacy.text
    assert 'id="root-answer-what-changed"' in legacy.text
    assert 'data-investigation-open="root-primary-answer-driver-panel"' in legacy.text
    assert 'id="root-primary-answer-driver-panel"' in legacy.text
    assert 'id="root-section-meeting-packet"' in legacy.text
    assert 'id="root-section-action-queue"' in legacy.text
    assert 'id="root-section-continuity"' in legacy.text
    assert 'id="root-section-material-changes"' in legacy.text
    assert 'class="action-queue-meta-bar"' in legacy.text
    assert 'class="continuity-lanes"' in legacy.text
    assert "Open finish driver detail" in legacy.text
    assert "Compare runs" in legacy.text
    assert "Projects Ranked By Health / Risk" not in legacy.text
    expected_root_status = (
        "SLIPPING"
        if tower.primary_project_answer and tower.primary_project_answer.movement_days and tower.primary_project_answer.movement_days > 0
        else "RECOVERING"
        if tower.primary_project_answer and tower.primary_project_answer.movement_days and tower.primary_project_answer.movement_days < 0
        else "ON TRACK"
        if tower.primary_project_answer and tower.primary_project_answer.movement_days == 0
        else "DELTA UNAVAILABLE"
    )
    assert expected_root_status in legacy.text
    assert "1. Finish" in legacy.text
    assert "2. Driver" in legacy.text
    assert "3. Risks" in legacy.text
    assert "4. Need" in legacy.text
    assert "5. Doing" in legacy.text
    assert "Deterministic trace" in legacy.text
    assert client.get("/projects").status_code == 200
    arena = client.get("/arena?selected=AURORA_HILLS")
    arena_export = client.get("/arena/export?selected=AURORA_HILLS")
    arena_artifact = client.get("/arena/export/artifact.md?selected=AURORA_HILLS")
    default_arena = client.get("/arena")
    default_arena_artifact = client.get("/arena/export/artifact.md")
    assert default_arena.status_code == 200
    assert client.get("/arena/export").status_code == 200
    assert default_arena_artifact.status_code == 200
    assert 'id="arena-project-answers"' in default_arena.text
    assert "Showing current Control Tower lead: AURORA_HILLS" in default_arena.text
    assert "Showing current Control Tower lead: AURORA_HILLS" in default_arena_artifact.text
    assert arena.status_code == 200
    assert arena_export.status_code == 200
    assert arena_artifact.status_code == 200
    assert 'id="arena-primary-workspace"' in arena.text
    assert 'id="arena-secondary-workspace"' in arena.text
    assert 'id="arena-support-workspace"' in arena.text
    assert 'id="arena-project-answers"' in arena.text
    assert 'id="arena-supporting-preview"' in arena.text
    assert 'id="arena-section-meeting-packet"' in arena.text
    assert 'id="arena-section-action-queue"' in arena.text
    assert 'id="arena-section-continuity"' in arena.text
    assert 'class="action-queue-meta-bar"' in arena.text
    assert 'class="continuity-lanes"' in arena.text
    assert 'id="arena-primary-answer-AURORA_HILLS-finish"' in arena.text
    assert "1. Finish" in arena.text
    assert "2. Driver" in arena.text
    assert "5. Doing" in arena.text
    assert "Open finish driver detail" in arena.text
    assert "Deterministic trace" in arena.text
    assert 'data-investigation-open="arena-primary-answer-AURORA_HILLS-driver-panel"' in arena.text
    assert "Download Authoritative Markdown" in arena.text
    project_detail = client.get("/projects/AURORA_HILLS")
    assert project_detail.status_code == 200
    assert 'id="project-detail-primary-workspace"' in project_detail.text
    assert 'id="project-detail-secondary-workspace"' in project_detail.text
    assert 'id="project-detail-support-workspace"' in project_detail.text
    assert 'id="project-detail-primary-answer"' in project_detail.text
    assert 'id="project-detail-primary-answer-finish"' in project_detail.text
    assert 'id="project-detail-primary-answer-doing"' in project_detail.text
    assert 'id="project-detail-answer-finish-driver"' in project_detail.text
    assert 'id="project-detail-answer-what-changed"' in project_detail.text
    assert 'id="project-detail-section-meeting-packet"' in project_detail.text
    assert 'id="project-detail-section-action-queue"' in project_detail.text
    assert 'id="project-detail-section-continuity"' in project_detail.text
    assert 'class="action-queue-meta-bar"' in project_detail.text
    assert 'class="continuity-lanes"' in project_detail.text
    assert 'data-investigation-open="project-detail-primary-answer-driver-panel"' in project_detail.text
    assert "Project detail command surface" in project_detail.text
    assert "Print / PDF view is presentation-only" in arena_export.text
    assert "## Scope / Timestamp" in arena_artifact.text
    assert "## Meeting Packet" in arena_artifact.text
    assert "## Action Queue" in arena_artifact.text
    assert "## Continuity" in arena_artifact.text
    assert "- Project: AURORA_HILLS" in arena_artifact.text
    assert "- Finish:" in arena_artifact.text
    assert "- Delta:" in arena_artifact.text
    assert "- Status:" in arena_artifact.text
    assert "- Controlling driver:" in arena_artifact.text
    assert "- What changed since prior run:" in arena_artifact.text
    assert "- Required action(s):" in arena_artifact.text
    assert "- Supporting evidence / signals:" in arena_artifact.text
    assert "- Timing:" in arena_artifact.text
    assert "Agenda order: AURORA_HILLS" in arena_artifact.text
    assert "Trust-bounded ranking" in arena_artifact.text
    meeting = verify_meeting_readiness(config, ["AURORA_HILLS"])
    assert meeting["status"] == "pass"
    assert meeting["checks"]["root_execution_brief_first_screen"] is True
    assert meeting["checks"]["root_finish_is_first"] is True
    assert meeting["checks"]["root_execution_brief_sections_complete"] is True
    assert meeting["checks"]["root_execution_brief_is_speakable"] is True
    assert meeting["checks"]["arena_execution_brief_leads_visible_surface"] is True
    assert meeting["checks"]["arena_finish_is_first"] is True
    assert meeting["checks"]["arena_execution_brief_sections_complete"] is True
    assert meeting["checks"]["artifact_preserves_finish_contract"] is True
    assert meeting["checks"]["packet_action_continuity_sections_present"] is True
    assert meeting["checks"]["meeting_packet_order_preserved"] is True
    assert meeting["checks"]["action_queue_items_trackable"] is True
    assert meeting["checks"]["continuity_output_is_bounded"] is True
    assert client.get("/runs").status_code == 200
    assert client.get("/diagnostics").status_code == 200
    assert client.get(f"/runs/{record.run_id}").status_code == 200
    assert client.get("/projects/AURORA_HILLS/compare").status_code == 200
    assert client.get("/api/portfolio").status_code == 200
    assert client.get("/api/diagnostics").status_code == 200
    payload = client.get("/api/projects/AURORA_HILLS").json()
    assert payload["canonical_project_id"] == "AURORA_HILLS"
    assert payload["domain"] == "professional"
    portfolio_payload = client.get("/api/portfolio").json()
    assert portfolio_payload["comparison_trust"]["status"] == "contained"
    assert portfolio_payload["comparison_trust"]["ranking_authority"] == "trust_bounded"
    assert portfolio_payload["domain_coverage"][1]["available"] is False
    assert "projected finish not available" not in home.text.lower()
    assert "no finish-date delta was emitted" not in home.text.lower()
    _seed_prior_export_run(service, config)
    publish = client.get("/publish")
    present = client.get("/publish/present")
    assert publish.status_code == 200
    assert present.status_code == 200
    assert publish_markers_present(publish.text)
    assert 'id="publish-home-header"' in publish.text
    assert "Meeting-ready command brief" in publish.text
    assert "Operational support" in publish.text
    assert "Evidence Grid" in publish.text
    assert "Proof Pack" in publish.text
    assert "Supporting Surface Only" in publish.text
    assert 'class="ct-layout"' in publish.text
    assert 'class="ct-main"' in publish.text
    assert 'class="ct-sidebar"' in publish.text
    assert 'class="workspace-status"' not in publish.text
    assert publish.text.count('class="ct-row command-strip-row"') == 5
    brief_match = re.search(r'<article class="ct-command-strip command-strip" id="publish-latest-brief"[^>]*>(.*?)</article>', publish.text, re.S)
    assert brief_match is not None
    brief_html = brief_match.group(1)
    assert 'data-brief-section="finish"' in brief_html
    assert 'data-brief-section="doing"' in brief_html
    assert "FINISH" in brief_html
    assert "DOING" in brief_html
    support_match = re.search(r'<section class="ct-section ct-section-tight" id="publish-support-table"[^>]*>(.*?)</section>', publish.text, re.S)
    assert support_match is not None
    support_html = support_match.group(1)
    assert "Signal / Item" in support_html
    assert "Current State" in support_html
    assert "Impact / Significance" in support_html
    assert "Source / Artifact" in support_html
    assert "Action" in support_html
    assert "Finish Forecast" in support_html
    assert "Controlling Driver" in support_html
    assert "Required Action" in support_html
    assert "Continuity" in support_html
    assert "Issued Output" in support_html
    assert "Copy brief" in support_html
    assert 'id="publish-artifact-viewer"' in publish.text
    assert 'id="publish-artifact-metadata"' in publish.text
    assert "Authoritative issued document" in publish.text
    assert "Current authoritative output" in publish.text
    assert "No material change from prior issued brief." in publish.text
    assert "Source Run" in publish.text
    assert str(config.obsidian.vault_root) not in publish.text
    assert str(config.sources.schedulelab.published_root) not in publish.text
    assert "Source Markdown" in publish.text
    assert 'id="publish-history"' in publish.text
    assert "Open prior output" in publish.text
    assert "Weekly Brief" in publish.text
    assert "Project Dossier" in publish.text
    assert "Portfolio Summary" in publish.text
    assert "No prior run comparison." not in publish.text
    dossier_artifact = next(
        artifact
        for artifact in service.build_publish_view(project_code="AURORA_HILLS").artifacts
        if artifact.note_kind == "project_dossier" and artifact.project_code == "AURORA_HILLS"
    )
    dossier_publish = client.get(f"/publish?project=AURORA_HILLS&artifact={dossier_artifact.artifact_id}")
    assert dossier_publish.status_code == 200
    artifact_match = re.search(
        r'<section class="ct-section" id="publish-artifact-viewer"[^>]*>(.*?)<section class="ct-section" id="publish-proof-pack"',
        dossier_publish.text,
        re.S,
    )
    assert artifact_match is not None
    artifact_html = artifact_match.group(1)
    assert "Run Date" in artifact_html
    assert "Generated" in artifact_html
    assert "Health Tier" in artifact_html
    assert "Risk Level" in artifact_html
    assert "Health Score" in artifact_html
    assert "<h2>Executive Summary</h2>" in artifact_html
    assert "---" not in artifact_html
    assert "title:" not in artifact_html
    assert "type:" not in artifact_html
    assert "project_code:" not in artifact_html
    assert "health_score:" not in artifact_html
    assert "## Executive Summary" not in artifact_html
    assert present_markers_present(present.text)
    assert '/static/site.css?v=' in present.text
    assert '/static/investigation.js?v=' in present.text
    assert _ordered(
        present.text,
        (
            'id="publish-present-topbar"',
            'id="publish-present-brief"',
            'id="publish-present-lines"',
            'data-brief-section="finish"',
            'data-brief-section="doing"',
            'id="publish-present-footer"',
        ),
    )
    assert 'class="present-command-strip"' in present.text
    assert 'class="workspace-nav"' not in present.text
    assert 'class="app-shell-header"' not in present.text
    assert 'id="publish-proof-pack"' not in present.text
    assert 'id="publish-supporting-surfaces"' not in present.text
    assert client.get("/publish?print=1").status_code == 200
    assert client.get("/publish/present?print=1").status_code == 200
    assert client.get("/exports/latest").status_code == 200

    state_root = config.runtime.state_root
    release_root = state_root / "release"
    release_root.mkdir(parents=True, exist_ok=True)
    review_artifact_a = release_root / "release_readiness_2026-03-30T17-32-56Z.json"
    review_artifact_b = release_root / "release_readiness_2026-03-30T17-36-32Z.json"
    review_artifact_a.write_text('{"status":"not_ready"}', encoding="utf-8")
    review_artifact_b.write_text('{"status":"ready"}', encoding="utf-8")
    review = OrchestrationService(config).ingest_release_readiness_pass(
        title="Control Tower Release Readiness Passed",
        workspace="controltower",
        summary="Release readiness passed after correcting HTML entity comparison in finish-driver verifier. Prior failure was a false negative caused by '&' vs '&amp;' mismatch.",
        raw_output_excerpt=[
            "Prior failure: verifier compared raw HTML and produced a false negative on '&' vs '&amp;'.",
            "Fix: verifier now compares unescaped visible text instead of raw HTML.",
            "Confirmation: release_readiness_controltower completed with exit code 0.",
        ],
        proposed_next_prompt=(
            "Checkpoint fix, push to repo, and run full production validation:\n"
            "1. pytest -q\n"
            "2. acceptance harness\n"
            "3. verify publish surface rendering\n"
            "4. confirm execution brief output is stable\n"
            "5. generate final operator brief artifact"
        ),
        artifact_paths=[review_artifact_a, review_artifact_b],
        source_operation_id="release_readiness_2026-03-30T17-35-54Z",
        release_generated_at="2026-03-30T17:36:32Z",
    )
    review_runs = client.get("/runs")
    assert review_runs.status_code == 200
    assert 'id="review-queue"' in review_runs.text
    assert review.run_id in review_runs.text
    assert "Control Tower Release Readiness Passed" in review_runs.text
    assert "review-risk-medium" in review_runs.text
    assert "review-decision-manual_review" in review_runs.text
    assert "noop_pack" in review_runs.text or "release_readiness_pack" in review_runs.text
    review_detail = client.get(review.detail_path)
    assert review_detail.status_code == 200
    assert "Approval-gated orchestration review surface" in review_detail.text
    assert "Control Tower Release Readiness Passed" in review_detail.text
    assert "Policy Decision" in review_detail.text
    assert "Execution Pack" in review_detail.text
    assert "Execution Event" in review_detail.text
    assert "Execution Dispatch" in review_detail.text
    assert "Decision Reasons" in review_detail.text
    assert "release-readiness handling defaults to manual review" in review_detail.text.lower()
    assert "false negative caused" in review_detail.text
    assert "Checkpoint fix, push to repo, and run full production validation:" in review_detail.text
    assert "Open artifact" in review_detail.text
    assert ">Approve</button>" in review_detail.text
    assert ">Reject</button>" in review_detail.text
    assert client.get(f"/reviews/{review.run_id}/artifacts/{review.artifacts[0].file_name}").status_code == 200
    review_api = client.get(f"/api/reviews/{review.run_id}")
    assert review_api.status_code == 200
    review_payload = review_api.json()
    assert review_payload["state"] == "pending_review"
    assert review_payload["risk_level"] == "medium"
    assert review_payload["decision_mode"] == "manual_review"
    assert review_payload["decision_reasons"]
    assert review_payload["notification"]["status"] == "sent"
    assert "execution_pack" in review_payload
    assert "execution_result" in review_payload
    assert "execution_event" in review_payload

    low_review = OrchestrationService(config).simulate_completed_run(profile="low")
    low_detail = client.get(low_review.detail_path)
    assert low_detail.status_code == 200
    assert "Auto-approved: yes" in low_detail.text
    assert "review-risk-low" in low_detail.text
    assert "review-decision-auto_approve" in low_detail.text

    high_review = OrchestrationService(config).simulate_completed_run(profile="high")
    high_detail = client.get(high_review.detail_path)
    assert high_detail.status_code == 200
    assert "Escalated: yes" in high_detail.text
    assert "review-state-escalated" in high_detail.text
    assert "review-decision-escalate" in high_detail.text

    emitted_review = OrchestrationService(config).simulate_execution_event(profile="medium", provider_override="file")
    result_ingest = client.post(
        "/api/execution/results",
        json={
            "event_id": emitted_review.execution_event.event_id,
            "run_id": emitted_review.run_id,
            "pack_id": emitted_review.execution_pack.pack_id,
            "status": "failed",
            "summary": "Smoke checks found a regression in the publish surface.",
            "output_artifacts": [{"label": "log", "path": "C:/tmp/smoke.log"}],
            "started_at": "2026-03-30T17:40:00Z",
            "completed_at": "2026-03-30T17:41:00Z",
            "external_reference": "n8n-77",
            "logs_excerpt": "publish smoke failed",
        },
    )
    assert result_ingest.status_code == 200
    result_payload = result_ingest.json()
    assert result_payload["status"] == "accepted"
    updated_detail = client.get(emitted_review.detail_path)
    assert updated_detail.status_code == 200
    assert "Downstream Result" in updated_detail.text
    assert "Smoke checks found a regression" in updated_detail.text
    assert "Closeout status: failed" in updated_detail.text
    assert "Closeout recorded at:" in updated_detail.text
    assert "External reference: n8n-77" in updated_detail.text
    updated_runs = client.get("/runs")
    assert updated_runs.status_code == 200
    assert "closeout_status: failed" in updated_runs.text
    assert "closeout_recorded_at:" in updated_runs.text


def publish_markers_present(text: str) -> bool:
    return 'id="publish-command-sheet"' in text and 'id="publish-latest-brief"' in text


def present_markers_present(text: str) -> bool:
    return 'id="publish-present-shell"' in text and 'id="publish-present-brief"' in text


def _ordered(text: str, tokens: tuple[str, ...]) -> bool:
    cursor = -1
    for token in tokens:
        position = text.find(token)
        if position <= cursor:
            return False
        cursor = position
    return True


def _seed_prior_export_run(service: ControlTowerService, config) -> None:
    portfolio, notes = service.build_notes()
    write_export_bundle(
        run_id="2026-03-20T14-00-00Z",
        generated_at="2026-03-20T14:00:00Z",
        notes=notes,
        vault_root=config.obsidian.vault_root,
        state_root=config.runtime.state_root,
        preview_only=False,
        timestamped_weekly_notes=config.obsidian.timestamped_weekly_notes,
        exports_folder=config.obsidian.exports_folder,
        source_artifacts=portfolio.provenance,
        issues=[],
        previous_run_id=None,
        portfolio_snapshot=portfolio,
        project_snapshots=portfolio.project_rankings,
        project_deltas=[],
    )

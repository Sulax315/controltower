from __future__ import annotations

from types import SimpleNamespace

from controltower.config import load_config
from controltower.services.meeting_readiness import _challenge_statement_is_source_backed, verify_meeting_readiness


def test_meeting_readiness_contract_passes(sample_config_path):
    config = load_config(sample_config_path)

    result = verify_meeting_readiness(config, ["AURORA_HILLS"])

    assert result["status"] == "pass"
    assert result["checks"]["root_execution_brief_first_screen"] is True
    assert result["checks"]["root_finish_is_first"] is True
    assert result["checks"]["root_execution_brief_visible_without_expansion"] is True
    assert result["checks"]["root_execution_brief_sections_complete"] is True
    assert result["checks"]["root_execution_brief_is_speakable"] is True
    assert result["checks"]["root_investigation_layer_visible_without_expansion"] is True
    assert result["checks"]["root_top_surface_is_not_category_first"] is True
    assert result["checks"]["root_sections_obey_project_decision_contract"] is True
    assert result["checks"]["root_finish_reason_is_deterministic"] is True
    assert result["checks"]["arena_execution_brief_leads_visible_surface"] is True
    assert result["checks"]["arena_finish_is_first"] is True
    assert result["checks"]["arena_execution_brief_visible_without_expansion"] is True
    assert result["checks"]["arena_execution_brief_sections_complete"] is True
    assert result["checks"]["arena_execution_brief_is_speakable"] is True
    assert result["checks"]["arena_investigation_layer_visible_without_expansion"] is True
    assert result["checks"]["arena_top_surface_is_not_category_first"] is True
    assert result["checks"]["arena_sections_obey_project_decision_contract"] is True
    assert result["checks"]["arena_finish_reason_is_deterministic"] is True
    assert result["checks"]["artifact_starts_with_project_finish_answers"] is True
    assert result["checks"]["artifact_preserves_finish_contract"] is True
    assert result["checks"]["cross_surface_finish_semantics_align"] is True
    assert result["checks"]["cross_surface_finish_driver_semantics_align"] is True
    assert result["checks"]["packet_action_continuity_sections_present"] is True
    assert result["checks"]["meeting_packet_order_preserved"] is True
    assert result["checks"]["action_queue_items_trackable"] is True
    assert result["checks"]["continuity_output_is_bounded"] is True
    assert result["checks"]["challenge_statement_is_source_backed"] is True
    assert result["checks"]["stale_vague_finish_language_absent"] is True


def test_cycle_challenge_is_accepted_when_artifact_carries_cycle_evidence():
    answer = SimpleNamespace(
        challenge_next="Challenge why cycles remain unresolved despite no finish movement.",
        movement_days=0,
        risk_level="MEDIUM",
        finish_driver=SimpleNamespace(comparison_state="same", driver_type="activity"),
        change_intelligence=SimpleNamespace(risk=SimpleNamespace(state="unchanged")),
    )

    assert (
        _challenge_statement_is_source_backed(
            answer,
            [answer],
            "- Challenge next: Challenge why cycles remain unresolved despite no finish movement.\n"
            "- Supporting evidence / signals:\n"
            "  - Circular schedule logic: 2 cycle(s) remain in the latest published schedule output.\n",
        )
        is True
    )

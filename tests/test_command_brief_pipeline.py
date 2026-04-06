from __future__ import annotations

from controltower.intelligence.command_brief import build_command_brief
from controltower.services.intelligence_packets import IntelligencePacketRecord, IntelligencePacketSection


def _packet() -> IntelligencePacketRecord:
    return IntelligencePacketRecord(
        packet_id="pkt_" + "1" * 32,
        project_name="Aurora Hills",
        canonical_project_code="AURORA_HILLS",
        packet_type="weekly_schedule_intelligence",
        reporting_period="2026-W14",
        title="Weekly schedule intelligence",
        operator_notes="",
        status="generated",
        sections=[
            IntelligencePacketSection(
                key="finish_milestone_outlook",
                title="Finish / milestone outlook",
                body_markdown="Projected finish: 2026-05-20",
            ),
            IntelligencePacketSection(
                key="delta_vs_prior",
                title="Delta vs prior update",
                body_markdown="- Finish slipped due to procurement lead-time increase",
            ),
            IntelligencePacketSection(
                key="key_drivers",
                title="Key drivers",
                body_markdown="- Critical path remains on procurement package release\n- Float compression on facade sequence",
            ),
            IntelligencePacketSection(
                key="near_term_risks",
                title="Near-term risks",
                body_markdown="- Delay risk on electrical switchgear approval",
            ),
            IntelligencePacketSection(
                key="required_decisions",
                title="Required decisions / asks",
                body_markdown="- Approve alternate procurement route by Friday",
            ),
            IntelligencePacketSection(
                key="action_register",
                title="Action register",
                body_markdown="- Confirm expediting vendor coverage",
            ),
        ],
        source_artifacts=[],
        created_at="2026-04-06T00:00:00Z",
        updated_at="2026-04-06T00:00:00Z",
    )


def test_command_brief_pipeline_emits_structured_schema():
    brief = build_command_brief(
        _packet(),
        {
            "rail_changed": "Prior finish was 2026-05-12 and now moved later",
            "rail_do": "Escalate procurement sequencing workshop this week",
            "intelligence_summary": "Schedule absorbed late procurement updates.",
        },
    )
    assert brief["schema_version"] == "command_brief.v2"
    assert brief["project_code"] == "AURORA_HILLS"
    assert brief["schedule_variance"]["current_finish_date"] == "2026-05-20"
    assert brief["schedule_variance"]["baseline_finish_date"] == "2026-05-12"
    assert brief["schedule_variance"]["finish_variance_days"] == 8
    assert brief["schedule_variance"]["finish_movement"] == "slip"
    assert isinstance(brief["activity_changes"], list) and brief["activity_changes"]
    assert isinstance(brief["movement_clusters"], list) and brief["movement_clusters"]
    assert isinstance(brief["top_movements"], list) and brief["top_movements"]
    assert isinstance(brief["lookahead_window"], list) and brief["lookahead_window"]
    assert isinstance(brief["critical_path_analysis"], dict)
    assert isinstance(brief["narrative"], dict)


def test_command_brief_narrative_references_computed_outputs():
    brief = build_command_brief(
        _packet(),
        {"rail_changed": "Prior finish was 2026-05-12", "rail_do": "Authorize overtime mitigation plan"},
    )
    headline = brief["narrative"]["headline"]
    why = brief["narrative"]["why_it_matters"]
    action = brief["narrative"]["action_statement"]
    assert "2026-05-20" in headline
    assert "slip" in headline.lower() or "slipped" in headline.lower()
    assert brief["critical_path_analysis"]["primary_constraint"] in why
    assert brief["lookahead_window"][0] in action


def test_command_brief_keeps_legacy_fields_for_brief_template():
    brief = build_command_brief(_packet(), {"rail_changed": "Prior finish was 2026-05-12"})
    for key in ("finish", "driver", "risks", "need", "doing"):
        assert key in brief
        assert isinstance(brief[key], str)

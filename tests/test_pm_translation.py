from __future__ import annotations

from controltower.schedule_intake.publish_assembly import (
    build_pm_translation_v1_partial,
    compose_doing_summary,
    compose_driver_summary,
    compose_finish_summary,
    compose_meeting_summary,
    compose_need_summary,
    compose_risk_summary,
    extend_pm_translation_v1_phase32c,
    extend_pm_translation_v1_phase32b,
    translate_baseline_status,
    translate_finish_position,
    translate_long_range_concern,
    translate_movement,
    translate_near_term_driver,
    translate_operating_focus,
    translate_pressure_statement,
)


def test_finish_position_emits_dates_with_traceability() -> None:
    result = translate_finish_position(
        final_finish_current="2026-05-15",
        substantial_finish_current="2026-05-01",
        milestone_ids=("MS-FINAL", "MS-SUB"),
    )
    assert result["rule_id"] == "F1"
    assert result["text"] == "Final completion is 2026-05-15 and substantial completion is 2026-05-01."
    assert result["sources"]
    assert result["sources"][0]["artifact"] == "finish_trend"
    assert result["sources"][0]["milestone_ids"] == ["MS-FINAL", "MS-SUB"]


def test_movement_improved_slipped_held_cases() -> None:
    improved = translate_movement(final_finish_current="2026-05-10", final_finish_prior="2026-05-15")
    slipped = translate_movement(final_finish_current="2026-05-20", final_finish_prior="2026-05-15")
    held = translate_movement(final_finish_current="2026-05-15", final_finish_prior="2026-05-15")
    assert improved["text"] == "Final completion improved 5 days."
    assert slipped["text"] == "Final completion slipped 5 days."
    assert held["text"] == "Final completion held."
    assert improved["rule_id"] == slipped["rule_id"] == held["rule_id"] == "M1"


def test_baseline_aligned_ahead_behind_cases() -> None:
    aligned = translate_baseline_status(final_finish_current="2026-06-01", final_finish_baseline="2026-06-01")
    ahead = translate_baseline_status(final_finish_current="2026-05-28", final_finish_baseline="2026-06-01")
    behind = translate_baseline_status(final_finish_current="2026-06-04", final_finish_baseline="2026-06-01")
    assert aligned["text"] == "Final completion is aligned with baseline."
    assert ahead["text"] == "Final completion is ahead of baseline by 4 days."
    assert behind["text"] == "Final completion is behind baseline by 3 days."
    assert aligned["rule_id"] == ahead["rule_id"] == behind["rule_id"] == "B1"


def test_near_term_driver_positive_case_emits_zero_float_chain() -> None:
    activities = (
        {
            "task_id": "A",
            "task_name": "Install conduit",
            "phase_exec": "Electrical",
            "start": "2026-04-11",
            "finish": "2026-04-14",
            "critical": True,
            "total_float_days": 0.0,
        },
        {
            "task_id": "B",
            "task_name": "Install panel",
            "phase_exec": "Electrical",
            "start": "2026-04-14",
            "finish": "2026-04-17",
            "critical": True,
            "total_float_days": 0.0,
        },
        {
            "task_id": "C",
            "task_name": "Install feeder",
            "phase_exec": "Electrical",
            "start": "2026-04-17",
            "finish": "2026-04-20",
            "critical": True,
            "total_float_days": 0.0,
        },
    )
    links = (("A", "B"), ("B", "C"))
    result = translate_near_term_driver(data_date="2026-04-10", activities=activities, dependency_links=links)
    assert result["rule_id"] == "D1"
    assert result["text"] == "The near-term path is driven by Electrical through 2026-04-20 with zero float."
    assert result["sources"]
    assert result["sources"][0]["task_ids"] == ["A", "B", "C"]
    assert result["sources"][0]["dependency_links"] == [
        {"from_task_id": "A", "to_task_id": "B"},
        {"from_task_id": "B", "to_task_id": "C"},
    ]


def test_near_term_driver_negative_case_suppresses_when_no_valid_chain() -> None:
    activities = (
        {
            "task_id": "A",
            "task_name": "Install conduit",
            "phase_exec": "Electrical",
            "start": "2026-04-11",
            "finish": "2026-04-12",
            "critical": False,
            "total_float_days": 4.0,
        },
        {
            "task_id": "B",
            "task_name": "Install panel",
            "phase_exec": "Electrical",
            "start": "2026-04-12",
            "finish": "2026-04-13",
            "critical": False,
            "total_float_days": 3.0,
        },
    )
    result = translate_near_term_driver(data_date="2026-04-10", activities=activities, dependency_links=(("A", "B"),))
    assert result["rule_id"] == "D1"
    assert result["text"] is None
    assert result["sources"] == []


def test_traceability_enforcement_for_emitted_statements() -> None:
    payload = build_pm_translation_v1_partial(
        final_finish_current="2026-05-15",
        substantial_finish_current="2026-05-01",
        final_finish_prior="2026-05-17",
        final_finish_baseline="2026-05-20",
        data_date="2026-04-10",
        activities=(
            {
                "task_id": "A",
                "task_name": "Install conduit",
                "phase_exec": "Electrical",
                "start": "2026-04-11",
                "finish": "2026-04-14",
                "critical": True,
                "total_float_days": 0.0,
            },
            {
                "task_id": "B",
                "task_name": "Install panel",
                "phase_exec": "Electrical",
                "start": "2026-04-14",
                "finish": "2026-04-17",
                "critical": True,
                "total_float_days": 0.0,
            },
            {
                "task_id": "C",
                "task_name": "Install feeder",
                "phase_exec": "Electrical",
                "start": "2026-04-17",
                "finish": "2026-04-20",
                "critical": True,
                "total_float_days": 0.0,
            },
        ),
        dependency_links=(("A", "B"), ("B", "C")),
        finish_milestone_ids=("MS-FINAL", "MS-SUB"),
    )
    for key in ("finish_position", "movement", "baseline_status", "near_term_driver"):
        statement = payload[key]
        if statement["text"] is not None:
            assert statement["rule_id"]
            assert statement["sources"]


def test_suppression_for_missing_inputs_returns_none_text() -> None:
    payload = build_pm_translation_v1_partial(
        final_finish_current=None,
        substantial_finish_current="2026-05-01",
        final_finish_prior="2026-05-17",
        final_finish_baseline="2026-05-20",
        data_date="2026-04-10",
        activities=(),
        dependency_links=(),
    )
    assert payload["finish_position"]["text"] is None


def test_long_range_concern_positive_case_emits_traceable_statement() -> None:
    result = translate_long_range_concern(
        data_date="2026-04-10",
        activities=(
            {
                "task_id": "L1",
                "task_name": "Curtain wall procurement",
                "phase_exec": "Envelope",
                "start": "2026-10-01",
                "finish_current": "2027-02-01",
                "finish_prior": "2026-07-01",
                "critical_current": True,
                "critical_prior": False,
                "total_float_days": 0.0,
            },
        ),
    )
    assert result["rule_id"] == "L1"
    assert result["text"] is not None
    assert "requiring validation of the long-range path" in result["text"]
    assert result["sources"]
    assert result["sources"][0]["task_ids"] == ["L1"]


def test_long_range_concern_suppresses_when_not_supported() -> None:
    result = translate_long_range_concern(
        data_date="2026-04-10",
        activities=(
            {
                "task_id": "L1",
                "task_name": "Curtain wall procurement",
                "phase_exec": "Envelope",
                "start": "2026-04-15",
                "finish_current": "2026-05-01",
                "finish_prior": "2026-04-01",
                "critical_current": False,
                "critical_prior": False,
                "total_float_days": 10.0,
            },
        ),
    )
    assert result["text"] is None
    assert result["rule_id"] is None
    assert result["sources"] == []


def test_pressure_statement_positive_case_emits_supported_wording() -> None:
    movement = {"text": "Final completion held.", "sources": [{"artifact": "finish_trend"}], "rule_id": "M1"}
    pressure = translate_pressure_statement(
        movement=movement,
        pressure_metrics={
            "new_critical_count": 3,
            "max_slip_days": 95,
            "baseline_slip_count_gt30": 4,
            "low_float_density_increase": False,
            "task_ids": ["P1", "P2", "P3"],
            "dominant_phase": "Envelope",
        },
    )
    assert pressure["rule_id"] == "P1"
    assert pressure["text"] == "The finish is holding, but internal pressure is increasing."
    assert pressure["sources"]


def test_pressure_statement_suppresses_on_slipping_finish() -> None:
    movement = {"text": "Final completion slipped 12 days.", "sources": [{"artifact": "finish_trend"}], "rule_id": "M1"}
    pressure = translate_pressure_statement(
        movement=movement,
        pressure_metrics={"new_critical_count": 10, "max_slip_days": 120, "baseline_slip_count_gt30": 5},
    )
    assert pressure["text"] is None
    assert pressure["rule_id"] is None
    assert pressure["sources"] == []


def test_operating_focus_positive_case_with_long_range() -> None:
    focus = translate_operating_focus(
        near_term_driver={"text": "The near-term path is driven by Electrical through 2026-04-20 with zero float."},
        long_range_concern={"text": "Several Envelope activities experienced extreme finish shifts and are now critical or zero-float, requiring validation of the long-range path."},
        pressure_statement={"text": None},
    )
    assert focus["rule_id"] == "O2"
    assert focus["text"] == "Our focus is protecting the Electrical and validating newly critical long-range activities."


def test_operating_focus_positive_case_with_pressure_only() -> None:
    focus = translate_operating_focus(
        near_term_driver={"text": "The near-term path is driven by Electrical through 2026-04-20 with zero float."},
        long_range_concern={"text": None},
        pressure_statement={"text": "The finish is holding, but internal pressure is increasing."},
    )
    assert focus["rule_id"] == "O2"
    assert focus["text"] == "Our focus is protecting the Electrical while monitoring rising internal schedule pressure."


def test_operating_focus_suppression_when_prereqs_missing() -> None:
    focus = translate_operating_focus(
        near_term_driver={"text": None},
        long_range_concern={"text": None},
        pressure_statement={"text": None},
    )
    assert focus["text"] is None
    assert focus["rule_id"] is None
    assert focus["sources"] == []


def test_phase32b_extension_additive_contract_shape() -> None:
    base = build_pm_translation_v1_partial(
        final_finish_current="2026-05-15",
        substantial_finish_current="2026-05-01",
        final_finish_prior="2026-05-15",
        final_finish_baseline="2026-05-20",
        data_date="2026-04-10",
        activities=(
            {
                "task_id": "A",
                "task_name": "Install conduit",
                "phase_exec": "Electrical",
                "start": "2026-04-11",
                "finish": "2026-04-14",
                "critical": True,
                "total_float_days": 0.0,
            },
            {
                "task_id": "B",
                "task_name": "Install panel",
                "phase_exec": "Electrical",
                "start": "2026-04-14",
                "finish": "2026-04-17",
                "critical": True,
                "total_float_days": 0.0,
            },
            {
                "task_id": "C",
                "task_name": "Install feeder",
                "phase_exec": "Electrical",
                "start": "2026-04-17",
                "finish": "2026-04-20",
                "critical": True,
                "total_float_days": 0.0,
            },
        ),
        dependency_links=(("A", "B"), ("B", "C")),
    )
    extended = extend_pm_translation_v1_phase32b(
        pm_translation_v1=base,
        data_date="2026-04-10",
        long_range_activities=(
            {
                "task_id": "L1",
                "task_name": "Curtain wall procurement",
                "phase_exec": "Envelope",
                "start": "2026-10-01",
                "finish_current": "2027-02-01",
                "finish_prior": "2026-07-01",
                "critical_current": True,
                "critical_prior": False,
                "total_float_days": 0.0,
            },
        ),
        pressure_metrics={"new_critical_count": 3, "max_slip_days": 95, "baseline_slip_count_gt30": 4},
    )
    assert "finish_position" in extended
    assert "movement" in extended
    assert "baseline_status" in extended
    assert "near_term_driver" in extended
    assert "long_range_concern" in extended
    assert "pressure_statement" in extended
    assert "operating_focus" in extended


def _phase32b_payload(*, with_driver: bool = True, with_long_range: bool = True, with_pressure: bool = True) -> dict:
    base = build_pm_translation_v1_partial(
        final_finish_current="2026-05-15",
        substantial_finish_current="2026-05-01",
        final_finish_prior="2026-05-15",
        final_finish_baseline="2026-05-20",
        data_date="2026-04-10",
        activities=(
            {
                "task_id": "A",
                "task_name": "Install conduit",
                "phase_exec": "Electrical",
                "start": "2026-04-11",
                "finish": "2026-04-14",
                "critical": with_driver,
                "total_float_days": 0.0 if with_driver else 5.0,
            },
            {
                "task_id": "B",
                "task_name": "Install panel",
                "phase_exec": "Electrical",
                "start": "2026-04-14",
                "finish": "2026-04-17",
                "critical": with_driver,
                "total_float_days": 0.0 if with_driver else 5.0,
            },
            {
                "task_id": "C",
                "task_name": "Install feeder",
                "phase_exec": "Electrical",
                "start": "2026-04-17",
                "finish": "2026-04-20",
                "critical": with_driver,
                "total_float_days": 0.0 if with_driver else 5.0,
            },
        ),
        dependency_links=(("A", "B"), ("B", "C")),
    )
    return extend_pm_translation_v1_phase32b(
        pm_translation_v1=base,
        data_date="2026-04-10",
        long_range_activities=(
            {
                "task_id": "L1",
                "task_name": "Curtain wall procurement",
                "phase_exec": "Envelope",
                "start": "2026-10-01",
                "finish_current": "2027-02-01" if with_long_range else "2026-05-01",
                "finish_prior": "2026-07-01" if with_long_range else "2026-04-20",
                "critical_current": with_long_range,
                "critical_prior": False,
                "total_float_days": 0.0 if with_long_range else 5.0,
            },
        ),
        pressure_metrics={
            "new_critical_count": 3 if with_pressure else 0,
            "max_slip_days": 95 if with_pressure else 0,
            "baseline_slip_count_gt30": 4 if with_pressure else 0,
            "low_float_density_increase": False,
        },
    )


def test_finish_summary_composes_f1_m1_b1_and_omits_missing() -> None:
    payload = _phase32b_payload()
    finish = compose_finish_summary(payload)
    assert "Final completion is 2026-05-15 and substantial completion is 2026-05-01." in finish["text"]
    assert "Final completion held." in finish["text"]
    assert "Final completion is ahead of baseline by 5 days." in finish["text"]
    assert finish["rule_ids"] == ["F1", "M1", "B1"]
    payload["movement"] = {"text": None, "sources": [], "rule_id": None}
    finish_omit = compose_finish_summary(payload)
    assert "Final completion held." not in finish_omit["text"]


def test_driver_summary_present_when_d1_exists_and_suppressed_when_missing() -> None:
    payload = _phase32b_payload(with_driver=True)
    driver = compose_driver_summary(payload)
    assert driver["text"] == payload["near_term_driver"]["text"]
    payload_no_driver = _phase32b_payload(with_driver=False)
    driver_none = compose_driver_summary(payload_no_driver)
    assert driver_none["text"] is None


def test_risk_summary_l1_only_p1_only_both_and_neither() -> None:
    both = _phase32b_payload(with_long_range=True, with_pressure=True)
    both_summary = compose_risk_summary(both)
    assert "long-range path" in both_summary["text"]
    assert "internal pressure is increasing" in both_summary["text"]
    l1_only = _phase32b_payload(with_long_range=True, with_pressure=False)
    l1_summary = compose_risk_summary(l1_only)
    assert "long-range path" in l1_summary["text"]
    assert "internal pressure is increasing" not in l1_summary["text"]
    p1_only = _phase32b_payload(with_long_range=False, with_pressure=True)
    p1_summary = compose_risk_summary(p1_only)
    assert p1_summary["text"] == "The finish is holding, but internal pressure is increasing."
    neither = _phase32b_payload(with_long_range=False, with_pressure=False)
    neither_summary = compose_risk_summary(neither)
    assert neither_summary["text"] is None


def test_need_summary_emitted_only_when_l1_exists() -> None:
    with_l1 = compose_need_summary(_phase32b_payload(with_long_range=True))
    assert with_l1["text"] == "This requires validation of newly critical long-range activities."
    without_l1 = compose_need_summary(_phase32b_payload(with_long_range=False))
    assert without_l1["text"] is None


def test_doing_summary_only_from_o2() -> None:
    payload = _phase32b_payload(with_driver=True, with_long_range=True, with_pressure=True)
    doing = compose_doing_summary(payload)
    assert doing["text"] == payload["operating_focus"]["text"]
    payload["operating_focus"] = {"text": None, "sources": [], "rule_id": None}
    doing_none = compose_doing_summary(payload)
    assert doing_none["text"] is None


def test_meeting_summary_mapping_order_no_recompute_and_traceability() -> None:
    payload = _phase32b_payload(with_driver=True, with_long_range=True, with_pressure=True)
    finish = compose_finish_summary(payload)
    driver = compose_driver_summary(payload)
    risk = compose_risk_summary(payload)
    need = compose_need_summary(payload)
    doing = compose_doing_summary(payload)
    meeting = compose_meeting_summary(
        finish_summary=finish,
        driver_summary=driver,
        risk_summary=risk,
        need_summary=need,
        doing_summary=doing,
    )
    assert list(k for k in meeting.keys() if k in {"finish", "driver", "risk", "need", "doing"}) == [
        "finish",
        "driver",
        "risk",
        "need",
        "doing",
    ]
    assert meeting["finish"] == finish["text"]
    assert meeting["driver"] == driver["text"]
    assert meeting["risk"] == risk["text"]
    assert meeting["need"] == need["text"]
    assert meeting["doing"] == doing["text"]
    assert meeting["sources"]
    assert set(meeting["rule_ids"]).issuperset({"F1", "M1", "B1", "D1"})


def test_no_invented_language_when_primitives_missing() -> None:
    payload = {
        "finish_position": {"text": None, "sources": [], "rule_id": None},
        "movement": {"text": None, "sources": [], "rule_id": None},
        "baseline_status": {"text": None, "sources": [], "rule_id": None},
        "near_term_driver": {"text": None, "sources": [], "rule_id": None},
        "long_range_concern": {"text": None, "sources": [], "rule_id": None},
        "pressure_statement": {"text": None, "sources": [], "rule_id": None},
        "operating_focus": {"text": None, "sources": [], "rule_id": None},
    }
    extended = extend_pm_translation_v1_phase32c(pm_translation_v1=payload)
    assert extended["finish_summary"]["text"] is None
    assert extended["driver_summary"]["text"] is None
    assert extended["risk_summary"]["text"] is None
    assert extended["need_summary"]["text"] is None
    assert extended["doing_summary"]["text"] is None
    assert "finish" not in extended["meeting_summary"]
    assert "driver" not in extended["meeting_summary"]
    assert "risk" not in extended["meeting_summary"]
    assert "need" not in extended["meeting_summary"]
    assert "doing" not in extended["meeting_summary"]

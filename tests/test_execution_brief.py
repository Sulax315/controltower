from __future__ import annotations

from controltower.config import load_config
from controltower.services.controltower import ControlTowerService


def test_execution_brief_is_ordered_bounded_and_speakable(sample_config_path):
    config = load_config(sample_config_path)
    service = ControlTowerService(config)
    portfolio = service.build_portfolio()
    project = portfolio.project_rankings[0]

    brief = service.build_project_command_view(project, portfolio.comparison_trust).execution_brief

    assert [section.key for section in brief.sections] == [
        "finish",
        "driver",
        "risks",
        "need",
        "doing",
    ]
    assert [section.label for section in brief.sections] == [
        "Finish",
        "Driver",
        "Risks",
        "Need",
        "Doing",
    ]
    assert brief.finish_summary.lines == ["Finish Aug 15, 2026. No baseline. Confidence medium."]
    assert brief.driver_statement.lines == ["Driver: Steel Release - long lead procurement."]
    assert brief.risks_list.lines == ["Risks: negative float (2), open ends (12), cycle (1), profit fade."]
    assert brief.need_statement.lines == ["Need: remove cycle, close open ends, review profit exposure."]
    assert brief.doing_statement.lines == ["Doing: resolving cycle, closing open ends, reviewing profit exposure."]
    assert all(len(section.lines) == 1 for section in brief.sections)
    assert all(len(line.split()) <= 12 for section in brief.sections for line in section.lines)
    assert sum(len(line.split()) for section in brief.sections for line in section.lines) <= 65
    assert all(line.strip().endswith((".", "!", "?")) for section in brief.sections for line in section.lines)
    assert all(
        token not in "\n".join(section.lines).lower()
        for token in ("tracking", "status unavailable", "what changed", "why")
        for section in brief.sections
    )


def test_execution_brief_falls_back_to_risk_path_driver_when_driver_signal_is_missing(sample_config_path):
    config = load_config(sample_config_path)
    service = ControlTowerService(config)
    portfolio = service.build_portfolio()
    project = portfolio.project_rankings[0].model_copy(deep=True)

    project.delta = project.delta.model_copy(
        update={"risk": project.delta.risk.model_copy(update={"worsening_signals": []})}
    )
    if project.schedule is not None:
        project.schedule = project.schedule.model_copy(update={"top_drivers": []})
    if project.financial is not None:
        project.financial = project.financial.model_copy(update={"key_findings": []})
    project.finish_driver = project.finish_driver.model_copy(
        update={
            "controlling_driver": "Driver unavailable",
            "why_it_matters": "No published finish-driver signal is available for this project.",
        }
    )

    brief = service.execution_brief_service.build(project, portfolio.comparison_trust)

    assert brief.driver_statement.lines[0] == "Driver: risk path (2)."


def test_execution_brief_prioritizes_material_financial_risk(sample_config_path):
    config = load_config(sample_config_path)
    service = ControlTowerService(config)
    portfolio = service.build_portfolio()
    project = portfolio.project_rankings[0].model_copy(deep=True)

    project.delta = project.delta.model_copy(
        update={
            "financial": project.delta.financial.model_copy(
                update={
                    "cost_variance_change": 125000,
                    "margin_movement": -1.5,
                }
            )
        }
    )
    project.top_issues = [
        issue
        for issue in project.top_issues
        if issue.label != "Profit fade"
    ]
    project.top_issues.append(
        project.top_issues[0].model_copy(
            update={
                "source": "financial",
                "severity": "high",
                "label": "Cost variance growth",
                "detail": "Forecast final cost increased materially in the current forecast.",
            }
        )
    )

    brief = service.execution_brief_service.build(project, portfolio.comparison_trust)

    assert brief.risks_list.lines[0] == "Risks: negative float (2), open ends (12), cycle (1), cost drift."
    assert brief.need_statement.lines[0] == "Need: remove cycle, close open ends, address cost drift."
    assert brief.doing_statement.lines[0] == "Doing: resolving cycle, closing open ends, reviewing cost exposure."

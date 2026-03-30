from __future__ import annotations

from controltower.adapters.profitintel import ProfitIntelAdapter


def test_profitintel_adapter_selects_current_and_variances(sample_profitintel_db):
    adapter = ProfitIntelAdapter(sample_profitintel_db, validation_search_roots=[])
    projects = adapter.list_projects()

    assert len(projects) == 1
    project = projects[0]
    assert project.project_slug == "219128"
    assert project.report_month == "2026-03"
    profit_variance = next(item for item in project.variances if item.metric_name == "projected_profit")
    assert profit_variance.absolute_change == -60000
    assert "profit_fade" in project.flags

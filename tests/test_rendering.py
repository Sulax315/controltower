from __future__ import annotations

from controltower.config import load_config
from controltower.render.markdown import (
    parse_markdown_frontmatter,
    render_portfolio_summary,
    render_project_dossier,
    render_project_weekly_brief,
    render_publish_markdown_preview,
)
from controltower.services.controltower import ControlTowerService


def test_markdown_renderers_emit_frontmatter(sample_config_path):
    config = load_config(sample_config_path)
    service = ControlTowerService(config)
    portfolio = service.build_portfolio()
    project = portfolio.project_rankings[0]

    dossier = render_project_dossier(project, config.obsidian, portfolio.generated_at)
    weekly = render_project_weekly_brief(project, config.obsidian, portfolio.generated_at)
    summary = render_portfolio_summary(portfolio, config.obsidian)

    assert dossier.body.startswith("---\n")
    assert "## Executive Summary" in dossier.body
    assert "project_id: AURORA_HILLS" in weekly.body
    assert "## What Changed This Week" in weekly.body
    assert "## Required Actions" in weekly.body
    assert "## Overall Portfolio Posture" in summary.body
    assert "## Portfolio Risk Ranking" in summary.body
    assert "AURORA_HILLS" in summary.body
    assert "Project:" in weekly.body


def test_publish_preview_parses_frontmatter_and_hides_yaml():
    document = (
        "---\r\n"
        "title: Aurora Hills Dossier\r\n"
        "type: project_dossier\r\n"
        "project_code: AURORA_HILLS\r\n"
        "health_score: 72.5\r\n"
        "risk_level: HIGH\r\n"
        "---\r\n"
        "\r\n"
        "# Executive Summary\r\n"
        "\r\n"
        "- Status: **Watch**\r\n"
    )

    frontmatter, body = parse_markdown_frontmatter(document)
    preview_html = render_publish_markdown_preview(document)

    assert frontmatter["title"] == "Aurora Hills Dossier"
    assert frontmatter["project_code"] == "AURORA_HILLS"
    assert body.startswith("# Executive Summary")
    assert "---" not in preview_html
    assert "title:" not in preview_html
    assert "project_code:" not in preview_html
    assert "health_score:" not in preview_html
    assert "## Executive Summary" not in preview_html
    assert "<h1>Executive Summary</h1>" in preview_html
    assert "<strong>Watch</strong>" in preview_html

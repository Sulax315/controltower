from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.services.controltower import ControlTowerService


SITE_CSS = Path(__file__).resolve().parents[1] / "src" / "controltower" / "api" / "static" / "site.css"


@pytest.mark.skip(reason="Asserts retired multi-surface routes (/control, /arena, /projects); Phase 12+ is publish-only.")
def test_desktop_surface_tiers_render_in_finish_first_order(sample_config_path):
    config = load_config(sample_config_path)
    service = ControlTowerService(config)
    service.export_notes(preview_only=False)
    app = create_app(str(sample_config_path))
    client = TestClient(app)

    redirect = client.get("/", follow_redirects=False)
    home = client.get("/")
    control = client.get("/control")
    arena = client.get("/arena?selected=AURORA_HILLS")
    detail = client.get("/projects/AURORA_HILLS")

    assert redirect.status_code == 307
    assert redirect.headers["location"].endswith("/publish")
    assert home.status_code == 200
    assert control.status_code == 200
    assert arena.status_code == 200
    assert detail.status_code == 200

    assert _ordered(
        home.text,
        (
            'id="publish-command-sheet"',
            'id="publish-home-header"',
            'id="publish-latest-brief"',
            'data-brief-section="finish"',
            'data-brief-section="doing"',
            'id="publish-support-table"',
            'id="publish-proof-pack"',
            'id="publish-supporting-surfaces"',
        ),
    )
    assert 'href="/publish" class="nav-primary is-active"' in home.text
    assert 'id="root-primary-workspace"' not in home.text
    assert _ordered(
        control.text,
        (
            'id="root-primary-workspace"',
            'data-command-surface="execution-brief"',
            'id="root-primary-answer-finish"',
            'id="root-primary-answer-doing"',
            'id="root-secondary-workspace"',
            'id="root-support-workspace"',
        ),
    )
    assert _ordered(
        arena.text,
        (
            'id="arena-primary-workspace"',
            'id="arena-project-answers"',
            'id="arena-primary-answer-AURORA_HILLS-finish"',
            'id="arena-primary-answer-AURORA_HILLS-doing"',
            'id="arena-secondary-workspace"',
            'id="arena-support-workspace"',
        ),
    )
    assert _ordered(
        detail.text,
        (
            'id="project-detail-primary-workspace"',
            'id="project-detail-primary-answer"',
            'id="project-detail-primary-answer-finish"',
            'id="project-detail-primary-answer-doing"',
            'id="project-detail-secondary-workspace"',
            'id="project-detail-support-workspace"',
        ),
    )


def test_desktop_visual_contracts_keep_command_surface_dominant():
    css = SITE_CSS.read_text(encoding="utf-8")

    assert ".app-shell-header" in css
    assert ".workspace-nav a.is-active" in css
    assert ".workspace-nav a.nav-primary" in css
    assert ".ct-layout" in css
    assert ".ct-main" in css
    assert ".ct-header" in css
    assert ".ct-command-strip" in css
    assert ".ct-row" in css
    assert ".ct-label" in css
    assert ".ct-value" in css
    assert ".ct-table" in css
    assert ".ct-table-row" in css
    assert ".ct-sidebar" in css
    assert ".ct-panel" in css
    assert ".ct-btn-primary" in css
    assert ".command-strip-row" in css
    assert ".ct-document-body" in css
    assert ".present-sheet" in css
    assert ".present-command-strip" in css
    assert ".present-meta-ribbon" in css
    assert "#404E3B" in css
    assert "#7B9669" in css
    assert "#6C8480" in css
    assert "#BAC8B1" in css
    assert "#E6E6E6" in css
    assert re.search(r"\.workspace-band\.band-secondary\s*\{[^}]*grid-template-columns:\s*minmax\(250px, 0\.58fr\) minmax\(0, 1\.42fr\)", css, re.S)
    assert re.search(r"\.execution-brief\s*\{[^}]*gap:\s*10px", css, re.S)
    assert re.search(r"\.brief-section-head\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) auto", css, re.S)
    assert re.search(r"\.brief-line\s*\{[^}]*padding:\s*7px 10px", css, re.S)
    assert re.search(r"\.brief-line\s*\{[^}]*line-height:\s*1\.35", css, re.S)
    assert re.search(r"\.command-brief-support\s*\{[^}]*grid-template-columns:\s*repeat\(auto-fit, minmax\(240px, 1fr\)\)", css, re.S)
    assert re.search(r"body\.publish\s*\{[^}]*background:\s*#d7dfd0", css, re.S)
    assert re.search(r"body\.publish \.app-shell-header\s*\{[^}]*background:\s*#c5d0bc[^}]*backdrop-filter:\s*none", css, re.S)
    assert re.search(r"body\.publish \.app-topbar\s*\{[^}]*min-height:\s*40px[^}]*gap:\s*8px", css, re.S)
    assert re.search(r"body\.publish \.app-topbar\.is-publish\s*\{[^}]*grid-template-columns:\s*minmax\(140px, auto\) minmax\(0, 1fr\)", css, re.S)
    assert re.search(r"body\.publish \.workspace-nav a\s*\{[^}]*padding:\s*5px 8px[^}]*border-radius:\s*2px[^}]*background:\s*transparent", css, re.S)
    assert re.search(r"body\.publish \.workspace-status\s*\{[^}]*display:\s*none", css, re.S)
    assert re.search(r"\.ct-layout\s*\{[^}]*display:\s*grid[^}]*grid-template-columns:\s*minmax\(0, 1\.82fr\) minmax\(260px, 0\.78fr\)[^}]*gap:\s*12px", css, re.S)
    assert re.search(r"\.ct-header\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1\.35fr\) repeat\(2, minmax\(170px, 0\.72fr\)\)[^}]*padding:\s*8px 10px", css, re.S)
    assert re.search(r"\.ct-command-strip\s*\{[^}]*border:\s*1px solid rgba\(0, 0, 0, 0\.1\)", css, re.S)
    assert re.search(r"\.ct-row\s*\{[^}]*grid-template-columns:\s*96px 1fr[^}]*padding:\s*6px 10px[^}]*border-bottom:\s*1px solid rgba\(0, 0, 0, 0\.1\)", css, re.S)
    assert re.search(r"\.ct-label\s*\{[^}]*font-weight:\s*700[^}]*text-transform:\s*uppercase[^}]*font-size:\s*11px[^}]*color:\s*#6C8480", css, re.S)
    assert re.search(r"\.ct-value\s*\{[^}]*font-size:\s*13px[^}]*color:\s*#404E3B", css, re.S)
    assert re.search(r"\.ct-table\s*\{[^}]*margin-top:\s*0[^}]*border:\s*1px solid rgba\(0, 0, 0, 0\.1\)", css, re.S)
    assert re.search(r"\.ct-table-header,\s*\.ct-table-row\s*\{[^}]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)[^}]*padding:\s*6px 10px", css, re.S)
    assert re.search(r"\.ct-table-5 \.ct-table-header,\s*\.ct-table-5 \.ct-table-row\s*\{[^}]*minmax\(110px, 1\.05fr\)[^}]*minmax\(120px, 0\.82fr\)", css, re.S)
    assert re.search(r"\.ct-table-row\s*\{[^}]*border-top:\s*1px solid rgba\(0, 0, 0, 0\.1\)", css, re.S)
    assert re.search(r"\.ct-sidebar\s*\{[^}]*gap:\s*8px[^}]*background:\s*transparent[^}]*border:\s*0", css, re.S)
    assert re.search(r"\.ct-panel\s*\{[^}]*padding:\s*8px 10px[^}]*background:\s*#eef1eb", css, re.S)
    assert re.search(r"\.ct-btn-primary\s*\{[^}]*background:\s*#7B9669[^}]*color:\s*white[^}]*border:\s*1px solid #70865f", css, re.S)
    assert re.search(r"\.ct-btn-secondary,\s*\.ct-inline-action\s*\{[^}]*background:\s*#e4eadf[^}]*border:\s*1px solid rgba\(64, 78, 59, 0\.16\)", css, re.S)
    assert not re.search(r"\.ct-(?:layout|header|command-strip|section|panel|btn-primary|btn-secondary|inline-action)\s*\{[^}]*gradient", css, re.S)
    assert re.search(r"\.present-command-strip-row\s*\{[^}]*grid-template-columns:\s*16px minmax\(104px, 128px\) minmax\(0, 1fr\)", css, re.S)
    assert re.search(r"\.present-footer\s*\{[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)", css, re.S)
    assert re.search(r"\.present-meta-ribbon\s*\{[^}]*display:\s*flex", css, re.S)
    assert re.search(r"\.action-queue-meta-bar\s*\{[^}]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)", css, re.S)
    assert re.search(r"\.action-queue-footer\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) auto", css, re.S)
    assert re.search(r"\.continuity-lanes\s*\{[^}]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)", css, re.S)
    assert re.search(r"\.continuity-lane-head\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) auto", css, re.S)
    assert re.search(r"\.investigation-panel\s*\{[^}]*position:\s*fixed", css, re.S)
    assert re.search(r"\.investigation-panel\s*\{[^}]*right:\s*20px", css, re.S)
    assert re.search(r"\.investigation-compare-grid\s*\{[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)", css, re.S)
    assert re.search(r"\.supporting-preview\s*\{[^}]*border-left:\s*3px solid", css, re.S)


def _ordered(text: str, tokens: tuple[str, ...]) -> bool:
    cursor = -1
    for token in tokens:
        position = text.find(token)
        if position <= cursor:
            return False
        cursor = position
    return True

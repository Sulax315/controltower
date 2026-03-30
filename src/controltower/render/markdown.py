from __future__ import annotations

import html
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from controltower.config import ObsidianConfig
from controltower.domain.models import ArenaView, GeneratedNote, PortfolioSummary, ProjectSnapshot


REQUIRED_MARKDOWN_TEMPLATES = (
    "arena_export_artifact.md.j2",
    "portfolio_weekly_summary.md.j2",
    "project_dossier.md.j2",
    "project_weekly_brief.md.j2",
)
_FRONTMATTER_RE = re.compile(r"\A(?:\ufeff)?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.DOTALL)


def validate_markdown_templates() -> None:
    template_root = Path(__file__).resolve().parent / "templates"
    missing = [template_root / template_name for template_name in REQUIRED_MARKDOWN_TEMPLATES if not (template_root / template_name).exists()]
    if missing:
        missing_list = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Control Tower markdown templates are missing: {missing_list}")


def _template_env() -> Environment:
    template_root = Path(__file__).resolve().parent / "templates"
    validate_markdown_templates()
    return Environment(
        loader=FileSystemLoader(str(template_root)),
        autoescape=select_autoescape(enabled_extensions=("html",)),
        trim_blocks=False,
        lstrip_blocks=False,
    )


def render_project_dossier(project: ProjectSnapshot, obsidian: ObsidianConfig, generated_at: str) -> GeneratedNote:
    title = f"{project.project_name} - {obsidian.canonical_dossier_suffix}"
    run_date = generated_at[:10]
    frontmatter = {
        "title": title,
        "type": "project_dossier",
        "project_code": project.canonical_project_code,
        "project_id": project.canonical_project_id,
        "project_name": project.project_name,
        "health_tier": project.health.tier,
        "health_score": project.health.score,
        "risk_level": project.health.risk_level,
        "generated_at": generated_at,
        "run_date": run_date,
        "tags": ["controltower", "project-dossier", project.canonical_project_code.lower()],
    }
    body = _document(
        template_name="project_dossier.md.j2",
        frontmatter=frontmatter,
        context={
            "project": project,
            "portfolio_note": obsidian.rolling_portfolio_note_name,
            "project_brief_name": obsidian.rolling_project_brief_name,
            "prior_week_link": _prior_week_link(
                generated_at=generated_at,
                project_code=project.canonical_project_code,
                title=title,
            ),
        },
    )
    return GeneratedNote(
        note_kind="project_dossier",
        canonical_project_code=project.canonical_project_code,
        title=title,
        frontmatter=frontmatter,
        body=body,
        output_path=Path(obsidian.projects_folder) / project.project_name / f"{title}.md",
        wikilinks=[obsidian.rolling_portfolio_note_name, obsidian.rolling_project_brief_name],
    )


def render_project_weekly_brief(project: ProjectSnapshot, obsidian: ObsidianConfig, generated_at: str) -> GeneratedNote:
    title = f"{project.project_name} - {obsidian.rolling_project_brief_name}"
    run_date = generated_at[:10]
    frontmatter = {
        "title": title,
        "type": "project_weekly_brief",
        "project_code": project.canonical_project_code,
        "project_id": project.canonical_project_id,
        "project_name": project.project_name,
        "generated_at": generated_at,
        "run_date": run_date,
        "health_score": project.health.health_score,
        "risk_level": project.health.risk_level,
        "tags": ["controltower", "weekly-brief", project.canonical_project_code.lower()],
    }
    body = _document(
        template_name="project_weekly_brief.md.j2",
        frontmatter=frontmatter,
        context={
            "project": project,
            "portfolio_note": obsidian.rolling_portfolio_note_name,
            "prior_week_link": _prior_week_link(
                generated_at=generated_at,
                project_code=project.canonical_project_code,
                title=title,
            ),
        },
    )
    return GeneratedNote(
        note_kind="project_weekly_brief",
        canonical_project_code=project.canonical_project_code,
        title=title,
        frontmatter=frontmatter,
        body=body,
        output_path=Path(obsidian.projects_folder) / project.project_name / f"{obsidian.rolling_project_brief_name}.md",
        wikilinks=[obsidian.rolling_portfolio_note_name],
    )


def render_portfolio_summary(summary: PortfolioSummary, obsidian: ObsidianConfig) -> GeneratedNote:
    title = obsidian.rolling_portfolio_note_name
    run_date = summary.generated_at[:10]
    frontmatter = {
        "title": title,
        "type": "portfolio_weekly_summary",
        "generated_at": summary.generated_at,
        "run_date": run_date,
        "project_count": summary.project_count,
        "active_project_count": summary.active_project_count,
        "tags": ["controltower", "portfolio-summary"],
    }
    body = _document(
        template_name="portfolio_weekly_summary.md.j2",
        frontmatter=frontmatter,
        context={"summary": summary},
    )
    return GeneratedNote(
        note_kind="portfolio_weekly_summary",
        title=title,
        frontmatter=frontmatter,
        body=body,
        output_path=Path(obsidian.exports_folder) / f"{title}.md",
        wikilinks=[project.project_name for project in summary.project_rankings[:10]],
    )


def render_arena_export_artifact(arena: ArenaView) -> str:
    frontmatter = {
        "title": arena.artifact_title,
        "type": "arena_export_artifact",
        "generated_at": arena.generated_at,
        "selection_count": len(arena.selected_arena_codes),
        "selected_codes": list(arena.selected_arena_codes),
        "comparison_status": arena.comparison_trust.status,
        "comparison_run_id": arena.comparison_trust.comparison_run_id,
        "ranking_authority": arena.comparison_trust.ranking_authority,
        "ranking_label": arena.comparison_trust.ranking_label,
        "baseline_label": arena.comparison_trust.baseline_label,
    }
    return _document(
        template_name="arena_export_artifact.md.j2",
        frontmatter=frontmatter,
        context={"arena": arena},
    )


def publishable_markdown(document: str) -> str:
    _frontmatter, body = parse_markdown_frontmatter(document)
    body = _strip_section(body, "Source Provenance")
    return body.strip()


def render_publish_markdown_preview(document: str) -> str:
    content = publishable_markdown(document)
    if not content:
        return "<p>No preview is available for this artifact.</p>"

    blocks: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    in_code_block = False
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if not paragraph_lines:
            return
        text = " ".join(line.strip() for line in paragraph_lines if line.strip())
        if text:
            blocks.append(f"<p>{_render_inline_markdown(text)}</p>")
        paragraph_lines = []

    def flush_list() -> None:
        nonlocal list_items
        if not list_items:
            return
        blocks.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_items) + "</ul>")
        list_items = []

    def flush_code() -> None:
        nonlocal code_lines
        blocks.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
        code_lines = []

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            flush_paragraph()
            flush_list()
            if in_code_block:
                flush_code()
                in_code_block = False
            else:
                in_code_block = True
            continue
        if in_code_block:
            code_lines.append(raw_line)
            continue
        if not line.strip():
            flush_paragraph()
            flush_list()
            continue
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading_match:
            flush_paragraph()
            flush_list()
            level = min(len(heading_match.group(1)), 4)
            blocks.append(f"<h{level}>{_render_inline_markdown(heading_match.group(2).strip())}</h{level}>")
            continue
        list_match = re.match(r"^[-*]\s+(.*)$", line)
        if list_match:
            flush_paragraph()
            list_items.append(_render_inline_markdown(list_match.group(1).strip()))
            continue
        paragraph_lines.append(line)

    flush_paragraph()
    flush_list()
    if in_code_block:
        flush_code()
    return "".join(blocks)


def parse_markdown_frontmatter(document: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(document)
    if not match:
        return ({}, document.lstrip("\ufeff"))
    raw_frontmatter = match.group(1)
    body = document[match.end() :]
    try:
        parsed = yaml.safe_load(raw_frontmatter) or {}
    except yaml.YAMLError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return (parsed, body.lstrip("\r\n"))


def _document(template_name: str, frontmatter: dict[str, Any], context: dict[str, Any]) -> str:
    template = _template_env().get_template(template_name)
    body = template.render(**context).strip() + "\n"
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False).strip()
    return f"---\n{yaml_block}\n---\n\n{body}"


def _prior_week_link(*, generated_at: str, project_code: str, title: str) -> str:
    current_date = date.fromisoformat(generated_at[:10])
    prior_date = (current_date - timedelta(days=7)).isoformat()
    return f"Weekly/{prior_date}/Projects/{project_code}/{title}"


def _strip_section(document: str, heading: str) -> str:
    lines = document.splitlines()
    result: list[str] = []
    skip_level: int | None = None
    target = heading.strip().lower()
    for line in lines:
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip().lower()
            if skip_level is not None and level <= skip_level:
                skip_level = None
            if title == target:
                skip_level = level
                continue
        if skip_level is None:
            result.append(line)
    return "\n".join(result).strip()


def _render_inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", lambda match: f"<code>{match.group(1)}</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", lambda match: f"<strong>{match.group(1)}</strong>", escaped)
    escaped = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", lambda match: html.escape(match.group(2)), escaped)
    escaped = re.sub(r"\[\[([^\]]+)\]\]", lambda match: html.escape(match.group(1)), escaped)
    return escaped

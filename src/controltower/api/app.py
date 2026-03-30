from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from controltower.config import load_config
from controltower.obsidian.exporter import load_latest_export
from controltower.services.controltower import ControlTowerService
from controltower.services.release import collect_operator_diagnostics


TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"
STATIC_ROOT = Path(__file__).resolve().parent / "static"
REQUIRED_UI_TEMPLATES = (
    "arena.html",
    "exports.html",
    "index.html",
    "layout.html",
    "publish.html",
    "publish_present.html",
    "projects.html",
    "project_compare.html",
    "project_detail.html",
    "runs.html",
    "run_detail.html",
    "diagnostics.html",
)


def create_app(config_path: str | None = None) -> FastAPI:
    resolved_path = config_path or os.getenv("CONTROLTOWER_CONFIG")
    config = load_config(Path(resolved_path)) if resolved_path else load_config()
    return create_app_from_config(config)


def create_app_from_config(config) -> FastAPI:
    validate_ui_assets()
    service = ControlTowerService(config)
    app = FastAPI(title=config.app.product_name)
    templates = Jinja2Templates(directory=str(TEMPLATE_ROOT))
    app.mount("/static", StaticFiles(directory=str(STATIC_ROOT)), name="static")

    def _render_control_surface(request: Request):
        tower = service.build_control_tower(_selected_codes(request))
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "config": config,
                "tower": tower,
                "page_title": "Legacy Control",
                "page_kicker": "Legacy executive operating view for investigation and queue management",
                "page_mode": "control-tower legacy-control",
            },
        )

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return RedirectResponse(url=str(request.url.replace(path="/publish")), status_code=307)

    @app.get("/control", response_class=HTMLResponse)
    def portfolio_overview(request: Request):
        return _render_control_surface(request)

    @app.get("/arena", response_class=HTMLResponse)
    def arena_view(request: Request):
        arena = service.build_arena(_selected_codes(request))
        return templates.TemplateResponse(
            request,
            "arena.html",
            {
                "config": config,
                "arena": arena,
                "export_mode": False,
                "page_title": "Arena",
                "page_kicker": "Presentation mode",
                "page_mode": "arena",
            },
        )

    @app.get("/arena/export", response_class=HTMLResponse)
    def arena_export_view(request: Request):
        arena = service.build_arena(_selected_codes(request))
        return templates.TemplateResponse(
            request,
            "arena.html",
            {
                "config": config,
                "arena": arena,
                "export_mode": True,
                "page_title": "Arena Export",
                "page_kicker": "Print / PDF layout",
                "page_mode": "arena arena-export",
            },
        )

    @app.get("/arena/export/artifact.md")
    def arena_export_artifact(request: Request):
        arena, filename, body = service.build_arena_export_artifact(_selected_codes(request))
        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-ControlTower-Arena-Selection": ",".join(arena.selected_arena_codes),
            },
        )

    @app.get("/projects", response_class=HTMLResponse)
    def projects_list(request: Request):
        portfolio = service.build_portfolio()
        return templates.TemplateResponse(
            request,
            "projects.html",
            {
                "config": config,
                "portfolio": portfolio,
                "projects": portfolio.project_rankings,
                "page_title": "Projects",
                "page_kicker": "Project ledger and ranked support surfaces",
                "page_mode": "projects",
            },
        )

    @app.get("/projects/{project_code}", response_class=HTMLResponse)
    def project_detail(request: Request, project_code: str):
        portfolio, notes = service.build_notes(project_code=project_code)
        project = next((item for item in portfolio.project_rankings if item.canonical_project_code == project_code), None)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        meeting_packet, action_queue, continuity = service.build_project_operational_views(project)
        dossier_note = next(
            (item for item in notes if item.note_kind == "project_dossier" and item.canonical_project_code == project_code),
            None,
        )
        return templates.TemplateResponse(
            request,
            "project_detail.html",
            {
                "config": config,
                "project": project,
                "project_answer": service.build_project_command_view(project, portfolio.comparison_trust),
                "meeting_packet": meeting_packet,
                "action_queue": action_queue,
                "continuity": continuity,
                "dossier_note": dossier_note,
                "page_title": project.project_name,
                "page_kicker": "Project detail command surface",
                "page_mode": "project-detail",
            },
        )

    @app.get("/projects/{project_code}/compare", response_class=HTMLResponse)
    def project_compare(request: Request, project_code: str):
        comparison = service.get_project_compare(project_code)
        if comparison is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return templates.TemplateResponse(
            request,
            "project_compare.html",
            {
                "config": config,
                "comparison": comparison,
                "page_title": f"{comparison['current'].project_name} Comparison",
                "page_kicker": "Deterministic cross-run comparison",
                "page_mode": "project-compare",
            },
        )

    @app.get("/runs", response_class=HTMLResponse)
    def runs_list(request: Request):
        return templates.TemplateResponse(
            request,
            "runs.html",
            {
                "config": config,
                "runs": service.list_runs(),
                "page_title": "Runs",
                "page_kicker": "Execution history and published artifacts",
                "page_mode": "runs",
            },
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_detail(request: Request, run_id: str):
        record = service.get_run(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Run not found")
        comparison_trust = record.portfolio_snapshot.comparison_trust if record.portfolio_snapshot else service.build_portfolio().comparison_trust
        return templates.TemplateResponse(
            request,
            "run_detail.html",
            {
                "config": config,
                "record": record,
                "run_answers": [service.build_project_command_view(project, comparison_trust) for project in record.project_snapshots],
                "page_title": f"Run {record.run_id}",
                "page_kicker": "Run detail and emitted project answers",
                "page_mode": "run-detail",
            },
        )

    @app.get("/exports/latest", response_class=HTMLResponse)
    def latest_export(request: Request):
        latest = load_latest_export(config.runtime.state_root)
        return templates.TemplateResponse(
            request,
            "exports.html",
            {
                "config": config,
                "latest": latest,
                "page_title": "Latest Export",
                "page_kicker": "Published dossier and portfolio export state",
                "page_mode": "exports",
            },
        )

    @app.get("/publish", response_class=HTMLResponse)
    def publish_view(
        request: Request,
        run: str | None = None,
        artifact: str | None = None,
        project: str | None = None,
        print: int = 0,
    ):
        try:
            publish = service.build_publish_view(run_id=run, artifact_id=artifact, project_code=project)
        except KeyError:
            raise HTTPException(status_code=404, detail="Run not found")
        return templates.TemplateResponse(
            request,
            "publish.html",
            {
                "config": config,
                "publish": publish,
                "auto_print": bool(print),
                "page_title": "Publish",
                "page_kicker": "Meeting-ready command brief and deliverable workspace",
                "page_mode": "publish",
            },
        )

    @app.get("/publish/present", response_class=HTMLResponse)
    def publish_present_view(
        request: Request,
        run: str | None = None,
        project: str | None = None,
        print: int = 0,
    ):
        try:
            publish = service.build_publish_view(run_id=run, project_code=project)
        except KeyError:
            raise HTTPException(status_code=404, detail="Run not found")
        return templates.TemplateResponse(
            request,
            "publish_present.html",
            {
                "config": config,
                "publish": publish,
                "auto_print": bool(print),
                "page_title": "Publish Presentation",
                "page_kicker": "Meeting-ready command brief presentation mode",
                "page_mode": "publish-present",
            },
        )

    @app.get("/exports/source/{run_id}/{artifact_id}")
    def export_source_markdown(run_id: str, artifact_id: str):
        artifact = service.get_publish_artifact_markdown(run_id, artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
        filename, body = artifact
        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    @app.get("/diagnostics", response_class=HTMLResponse)
    def diagnostics_page(request: Request):
        diagnostics = collect_operator_diagnostics(config)
        return templates.TemplateResponse(
            request,
            "diagnostics.html",
            {
                "config": config,
                "diagnostics": diagnostics,
                "page_title": "Diagnostics",
                "page_kicker": "Operator diagnostics and release posture",
                "page_mode": "diagnostics",
            },
        )

    @app.get("/api/portfolio")
    def portfolio_api():
        return service.build_portfolio().model_dump(mode="json")

    @app.get("/api/projects")
    def projects_api():
        return [project.model_dump(mode="json") for project in service.build_projects()]

    @app.get("/api/projects/{project_code}")
    def project_api(project_code: str):
        portfolio = service.build_portfolio()
        project = next((item for item in portfolio.project_rankings if item.canonical_project_code == project_code), None)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project.model_dump(mode="json")

    @app.get("/api/diagnostics")
    def diagnostics_api():
        return collect_operator_diagnostics(config)

    return app


def validate_ui_assets() -> None:
    missing = [TEMPLATE_ROOT / template_name for template_name in REQUIRED_UI_TEMPLATES if not (TEMPLATE_ROOT / template_name).exists()]
    if not STATIC_ROOT.exists():
        missing.append(STATIC_ROOT)
    if missing:
        missing_list = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Control Tower UI assets are missing: {missing_list}")


def _selected_codes(request: Request) -> list[str]:
    return [value for value in request.query_params.getlist("selected") if value]


app = create_app()

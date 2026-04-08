from __future__ import annotations

import hmac
import json
import os
import secrets
from typing import Any
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from pydantic import ValidationError

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from controltower.config import default_orchestrator_mcp_service_root, load_config
from controltower.obsidian.exporter import load_latest_export
from controltower.obsidian.intelligence_vault import try_sync_intelligence_packet_to_obsidian
from controltower.services.intelligence_vault_bridge import (
    build_packet_bridge_context,
    build_project_bridge_context,
    read_vault_markdown_html,
    resolve_packet_vault_doc_path,
    resolve_portfolio_index_path,
    resolve_project_index_path,
)
from controltower.services.build_info import current_build_info
from controltower.integrations import orchestrator_substrate as orch_substrate
from controltower.schedule_intake.publish_assembly import build_publish_packet
from controltower.schedule_intake.publish_assembly import build_publish_visualization
from controltower.schedule_intake.verification import BundleValidationError, load_publish_bundle
from controltower.runs.execution import execute_run
from controltower.runs.publish_authority import (
    assess_run_publishability,
    get_latest_publishable_run,
)
from controltower.runs.registry import get_run, list_runs
from controltower.runs.validation import (
    VALIDATION_CATEGORIES,
    VALIDATION_MD_FILENAME,
    load_validation_note,
    save_validation_note,
    validation_artifact_paths,
)
from controltower.services.controltower import ControlTowerService
from controltower.services.intelligence_packets import (
    GeneratePacketRequest,
    export_markdown_bytes,
    generate_weekly_schedule_intelligence_packet,
    load_packet,
    publish_packet,
    write_packet_artifacts,
)
from controltower.services.orchestration import OrchestrationService, ReviewActorContext
from controltower.services.orchestrator_panel import build_orchestrator_publish_panel, mutation_query_notices
from controltower.services.release import collect_operator_diagnostics


TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"
STATIC_ROOT = Path(__file__).resolve().parent / "static"
REQUIRED_UI_TEMPLATES = (
    "arena.html",
    "exports.html",
    "index.html",
    "login.html",
    "layout.html",
    "publish.html",
    "publish_present.html",
    "publish_operator.html",
    "runs_home.html",
    "projects.html",
    "project_compare.html",
    "project_detail.html",
    "runs.html",
    "run_detail.html",
    "review_detail.html",
    "diagnostics.html",
    "packet_new.html",
    "packet_detail.html",
    "vault_intelligence_view.html",
    "_orchestrator_execution_section.html",
)

AUTH_SESSION_KEY = "controltower_auth"
AUTH_CSRF_SESSION_KEY = "controltower_csrf_token"
DEFAULT_DEV_SESSION_SECRET = "controltower-dev-session"
PUBLIC_PATH_PREFIXES = ("/login", "/logout", "/reviews/login", "/reviews/logout", "/static")
PUBLIC_EXACT_PATHS = {"/favicon.ico", "/healthz", "/api/orchestrator/status"}
VALIDATION_CATEGORY_LABELS: dict[str, str] = {
    "entry_upload_flow": "Entry / Upload",
    "command_brief_clarity": "Command Brief Clarity",
    "evidence_precision": "Evidence Trust",
    "graph_comprehension": "Graph Usability",
    "interaction_flow": "Interaction Flow",
    "export_usefulness": "Export Usefulness",
    "stakeholder_readability": "Stakeholder Clarity",
}


class AppAuthGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, config, orchestration: OrchestrationService) -> None:
        super().__init__(app)
        self.config = config
        self.orchestration = orchestration

    async def dispatch(self, request: Request, call_next):
        if not _app_auth_requires_login(self.config) or _is_public_path(request.url.path):
            return await call_next(request)
        if _authenticated_session(request):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication is required for this Control Tower route."},
            )
        return RedirectResponse(url=_login_redirect_path(request), status_code=303)


def create_app(config_path: str | None = None) -> FastAPI:
    resolved_path = config_path or os.getenv("CONTROLTOWER_CONFIG")
    config = load_config(Path(resolved_path)) if resolved_path else load_config()
    return create_app_from_config(config)


def create_app_from_config(config) -> FastAPI:
    validate_ui_assets()
    service = ControlTowerService(config)
    orchestration = OrchestrationService(config)
    build_info = current_build_info()
    app = FastAPI(title=config.app.product_name)
    app.add_middleware(AppAuthGuardMiddleware, config=config, orchestration=orchestration)
    app.add_middleware(
        SessionMiddleware,
        secret_key=_session_secret(config, orchestration),
        same_site="lax",
        https_only=_session_requires_https(config, orchestration),
        session_cookie=_session_cookie_name(config, orchestration),
        max_age=60 * 60 * 12,
    )
    templates = Jinja2Templates(directory=str(TEMPLATE_ROOT))
    templates.env.filters["urlquote"] = lambda value: quote(str(value or ""), safe="")
    app.mount("/static", StaticFiles(directory=str(STATIC_ROOT)), name="static")

    @app.middleware("http")
    async def primary_surface_only(request: Request, call_next):
        path = request.url.path or "/"
        if _is_allowed_primary_surface_path(path):
            return await call_next(request)
        if _is_allowed_infra_path(path):
            return await call_next(request)
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    def _template_payload(request: Request, **context: object) -> dict[str, object]:
        payload = {
            "config": config,
            "build_info": build_info,
            "asset_version": build_info["asset_version"],
            "auth_context": _app_auth_context(config, orchestration, request),
            "auth_csrf_token": _ensure_auth_csrf_token(request),
        }
        payload.update(context)
        return payload

    def _render_control_surface(request: Request):
        tower = service.build_control_tower(_selected_codes(request))
        return templates.TemplateResponse(
            request,
            "index.html",
            _template_payload(
                request,
                tower=tower,
                page_title="Legacy Control",
                page_kicker="Legacy executive operating view for investigation and queue management",
                page_mode="control-tower legacy-control",
            ),
        )

    @app.get("/healthz")
    def healthz():
        return JSONResponse(
            content={"status": "ok"},
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next_path: str | None = None):
        if _authenticated_session(request):
            return RedirectResponse(url=_safe_next_path(next_path), status_code=303)
        auth_error = _interactive_auth_configuration_error(config, orchestration)
        return templates.TemplateResponse(
            request,
            "login.html",
            _template_payload(
                request,
                page_title="Sign In",
                page_kicker="Operator authentication gate for browser entry and publish surfaces.",
                page_mode="auth",
                next_path=_safe_next_path(next_path),
                auth_error=auth_error,
                auth_action=request.query_params.get("auth"),
            ),
        )

    @app.post("/login")
    async def login(
        request: Request,
        username: str = Form(""),
        password: str = Form(""),
        operator_username: str = Form(""),
        operator_password: str = Form(""),
        next_path: str = Form("/publish"),
        csrf_token: str = Form(""),
    ):
        _verify_auth_csrf(request, csrf_token)
        destination = _safe_next_path(next_path)
        auth_error = _interactive_auth_configuration_error(config, orchestration)
        if auth_error:
            raise HTTPException(status_code=503, detail=auth_error)
        expected_username, expected_password = _interactive_auth_credentials(config, orchestration)
        provided_username = (username or operator_username).strip()
        provided_password = password or operator_password
        if not (
            hmac.compare_digest(provided_username, expected_username)
            and hmac.compare_digest(provided_password, expected_password)
        ):
            return RedirectResponse(url=_with_auth_action(destination, "login_failed"), status_code=303)
        request.session[AUTH_SESSION_KEY] = {
            "identity": provided_username,
            "auth_mode": _interactive_auth_mode(config, orchestration),
        }
        _ensure_auth_csrf_token(request, rotate=True)
        return RedirectResponse(url=_with_auth_action(destination, "login_success"), status_code=303)

    @app.post("/logout")
    async def logout(
        request: Request,
        next_path: str = Form("/login"),
        csrf_token: str = Form(""),
    ):
        _verify_auth_csrf(request, csrf_token)
        request.session.pop(AUTH_SESSION_KEY, None)
        _ensure_auth_csrf_token(request, rotate=True)
        return RedirectResponse(url=_with_auth_action(_safe_next_path(next_path, default="/login"), "logged_out"), status_code=303)

    def _publishable_recent_runs(limit: int = 10) -> list[dict[str, object]]:
        publishable: list[dict[str, object]] = []
        for run in list_runs(config.runtime.state_root):
            ok, _ = assess_run_publishability(config.runtime.state_root, run)
            if ok:
                publishable.append(run)
            if len(publishable) >= limit:
                break
        return publishable

    def _render_runs_home(request: Request, *, status_code: int = 200, upload_error: str | None = None):
        recent_runs = _publishable_recent_runs(limit=10)
        latest_run = recent_runs[0] if recent_runs else None
        response = templates.TemplateResponse(
            request,
            "runs_home.html",
            _template_payload(
                request,
                latest_run=latest_run,
                recent_runs=recent_runs,
                upload_error=upload_error,
                page_title="Control Tower Browser Entry",
                page_kicker="Deterministic run launch and operator surface access",
                page_mode="runs-home",
            ),
        )
        response.status_code = status_code
        return response

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return _render_runs_home(request)

    @app.post("/entry/upload")
    async def entry_upload(request: Request, csv_file: UploadFile | None = File(None), csrf_token: str = Form("")):
        _verify_auth_csrf(request, csrf_token)
        wants_json = _wants_json_response(request)
        if csv_file is None:
            if wants_json:
                return JSONResponse(status_code=400, content={"detail": "csv_file upload is required."})
            return _render_runs_home(request, status_code=400, upload_error="A CSV upload is required.")
        raw_name = (csv_file.filename or "").strip()
        filename = Path(raw_name).name.strip()
        if not filename:
            if wants_json:
                return JSONResponse(status_code=400, content={"detail": "csv_file filename is required."})
            return _render_runs_home(request, status_code=400, upload_error="CSV filename is required.")
        if not filename.lower().endswith(".csv"):
            if wants_json:
                return JSONResponse(status_code=400, content={"detail": "csv_file must be a .csv upload."})
            return _render_runs_home(request, status_code=400, upload_error="Only .csv uploads are supported.")
        payload = await csv_file.read()
        if len(payload) == 0:
            if wants_json:
                return JSONResponse(status_code=400, content={"detail": "csv_file upload cannot be empty."})
            return _render_runs_home(request, status_code=400, upload_error="CSV upload cannot be empty.")
        uploads_root = config.runtime.state_root / "runs" / "_uploads"
        uploads_root.mkdir(parents=True, exist_ok=True)
        upload_path = uploads_root / f"{secrets.token_hex(8)}_{filename}"
        upload_path.write_bytes(payload)
        try:
            run_id = execute_run(upload_path, state_root=config.runtime.state_root)
        except Exception as exc:
            if wants_json:
                return JSONResponse(status_code=500, content={"detail": f"Deterministic execution failed: {exc}"})
            return _render_runs_home(
                request,
                status_code=500,
                upload_error=f"Deterministic execution failed: {exc}",
            )
        run = get_run(config.runtime.state_root, run_id)
        if run is None:
            raise HTTPException(status_code=500, detail="Run metadata not found after execution.")
        if wants_json:
            return {"run_id": run_id, "status": run["status"]}
        return RedirectResponse(url=f"/publish/operator/{run_id}", status_code=303)

    @app.get("/control", response_class=HTMLResponse)
    def portfolio_overview(request: Request):
        return _render_control_surface(request)

    @app.get("/arena", response_class=HTMLResponse)
    def arena_view(request: Request):
        arena = service.build_arena(_selected_codes(request))
        return templates.TemplateResponse(
            request,
            "arena.html",
            _template_payload(
                request,
                arena=arena,
                export_mode=False,
                page_title="Arena",
                page_kicker="Presentation mode",
                page_mode="arena",
            ),
        )

    @app.get("/arena/export", response_class=HTMLResponse)
    def arena_export_view(request: Request):
        arena = service.build_arena(_selected_codes(request))
        return templates.TemplateResponse(
            request,
            "arena.html",
            _template_payload(
                request,
                arena=arena,
                export_mode=True,
                page_title="Arena Export",
                page_kicker="Print / PDF layout",
                page_mode="arena arena-export",
            ),
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
            _template_payload(
                request,
                portfolio=portfolio,
                projects=portfolio.project_rankings,
                page_title="Projects",
                page_kicker="Project ledger and ranked support surfaces",
                page_mode="projects",
            ),
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
        vault_bridge = build_project_bridge_context(
            canonical_project_code=project.canonical_project_code,
            project_name=project.project_name,
            config=config,
        )
        return templates.TemplateResponse(
            request,
            "project_detail.html",
            _template_payload(
                request,
                project=project,
                project_answer=service.build_project_command_view(project, portfolio.comparison_trust),
                meeting_packet=meeting_packet,
                action_queue=action_queue,
                continuity=continuity,
                dossier_note=dossier_note,
                vault_bridge=vault_bridge,
                page_title=project.project_name,
                page_kicker="Project detail command surface",
                page_mode="project-detail",
            ),
        )

    @app.get("/packets/new", response_class=HTMLResponse)
    def packet_intake_page(request: Request):
        portfolio = service.build_portfolio()
        return templates.TemplateResponse(
            request,
            "packet_new.html",
            _template_payload(
                request,
                projects=portfolio.project_rankings,
                page_title="New intelligence packet",
                page_kicker="Weekly schedule intelligence — deterministic assembly from live Control Tower signals",
                page_mode="packets-intake",
            ),
        )

    @app.post("/packets/new")
    async def packet_intake_submit(
        request: Request,
        project_code: str = Form(""),
        packet_type: str = Form("weekly_schedule_intelligence"),
        reporting_period: str = Form(""),
        title: str = Form(""),
        operator_notes: str = Form(""),
        csrf_token: str = Form(""),
    ):
        _verify_auth_csrf(request, csrf_token)
        try:
            req = GeneratePacketRequest(
                project_code=project_code,
                packet_type=packet_type,
                reporting_period=reporting_period,
                title=title,
                operator_notes=operator_notes,
            )
            record = generate_weekly_schedule_intelligence_packet(service, req)
            write_packet_artifacts(config.runtime.state_root, record)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url=f"/packets/{record.packet_id}", status_code=303)

    @app.get("/packets/{packet_id}", response_class=HTMLResponse)
    def packet_detail_page(request: Request, packet_id: str):
        try:
            record = load_packet(config.runtime.state_root, packet_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if record is None:
            raise HTTPException(status_code=404, detail="Packet not found")
        vault_bridge = build_packet_bridge_context(record, config)
        return templates.TemplateResponse(
            request,
            "packet_detail.html",
            _template_payload(
                request,
                packet=record,
                vault_bridge=vault_bridge,
                page_title=record.title,
                page_kicker=f"{record.project_name} · {record.reporting_period}",
                page_mode="packet-detail",
            ),
        )

    @app.post("/packets/{packet_id}/publish")
    async def packet_publish_form(
        request: Request,
        packet_id: str,
        csrf_token: str = Form(""),
    ):
        _verify_auth_csrf(request, csrf_token)
        try:
            updated = publish_packet(config.runtime.state_root, packet_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Packet not found")
        try_sync_intelligence_packet_to_obsidian(
            config.obsidian,
            updated,
            state_root=config.runtime.state_root,
        )
        return RedirectResponse(url=f"/packets/{packet_id}?published=1", status_code=303)

    @app.get("/vault/intelligence/packets/{packet_id}/note", response_class=HTMLResponse)
    def vault_intelligence_packet_note(request: Request, packet_id: str):
        target = resolve_packet_vault_doc_path(config, packet_id, "packet")
        if target is None:
            raise HTTPException(status_code=404, detail="Packet not found")
        ok, html_body = read_vault_markdown_html(config, target)
        title = "Intelligence packet note (vault)"
        if not ok:
            return templates.TemplateResponse(
                request,
                "vault_intelligence_view.html",
                _template_payload(
                    request,
                    page_title=title,
                    page_kicker="Obsidian intelligence vault",
                    page_mode="vault-intelligence",
                    vault_doc_title=title,
                    vault_doc_missing=True,
                    vault_doc_path=str(target),
                    vault_doc_body="",
                ),
            )
        return templates.TemplateResponse(
            request,
            "vault_intelligence_view.html",
            _template_payload(
                request,
                page_title=title,
                page_kicker="Obsidian intelligence vault",
                page_mode="vault-intelligence",
                vault_doc_title=title,
                vault_doc_missing=False,
                vault_doc_path=str(target),
                vault_doc_body=html_body,
            ),
        )

    @app.get("/vault/intelligence/packets/{packet_id}/project-index", response_class=HTMLResponse)
    def vault_intelligence_packet_project_index(request: Request, packet_id: str):
        target = resolve_packet_vault_doc_path(config, packet_id, "project_index")
        if target is None:
            raise HTTPException(status_code=404, detail="Packet not found")
        title = "Project index (vault)"
        ok, html_body = read_vault_markdown_html(config, target)
        if not ok:
            return templates.TemplateResponse(
                request,
                "vault_intelligence_view.html",
                _template_payload(
                    request,
                    page_title=title,
                    page_kicker="Obsidian intelligence vault",
                    page_mode="vault-intelligence",
                    vault_doc_title=title,
                    vault_doc_missing=True,
                    vault_doc_path=str(target),
                    vault_doc_body="",
                ),
            )
        return templates.TemplateResponse(
            request,
            "vault_intelligence_view.html",
            _template_payload(
                request,
                page_title=title,
                page_kicker="Obsidian intelligence vault",
                page_mode="vault-intelligence",
                vault_doc_title=title,
                vault_doc_missing=False,
                vault_doc_path=str(target),
                vault_doc_body=html_body,
            ),
        )

    @app.get("/vault/intelligence/projects/{project_code}/project-index", response_class=HTMLResponse)
    def vault_intelligence_project_index(request: Request, project_code: str):
        target = resolve_project_index_path(config, project_code)
        if target is None:
            raise HTTPException(status_code=404, detail="Project not found")
        title = "Project index (vault)"
        ok, html_body = read_vault_markdown_html(config, target)
        if not ok:
            return templates.TemplateResponse(
                request,
                "vault_intelligence_view.html",
                _template_payload(
                    request,
                    page_title=title,
                    page_kicker="Obsidian intelligence vault",
                    page_mode="vault-intelligence",
                    vault_doc_title=title,
                    vault_doc_missing=True,
                    vault_doc_path=str(target),
                    vault_doc_body="",
                ),
            )
        return templates.TemplateResponse(
            request,
            "vault_intelligence_view.html",
            _template_payload(
                request,
                page_title=title,
                page_kicker="Obsidian intelligence vault",
                page_mode="vault-intelligence",
                vault_doc_title=title,
                vault_doc_missing=False,
                vault_doc_path=str(target),
                vault_doc_body=html_body,
            ),
        )

    @app.get("/vault/intelligence/portfolio-index", response_class=HTMLResponse)
    def vault_intelligence_portfolio_index(request: Request):
        target = resolve_portfolio_index_path(config)
        title = "Portfolio index (vault)"
        ok, html_body = read_vault_markdown_html(config, target)
        if not ok:
            return templates.TemplateResponse(
                request,
                "vault_intelligence_view.html",
                _template_payload(
                    request,
                    page_title=title,
                    page_kicker="Obsidian intelligence vault",
                    page_mode="vault-intelligence",
                    vault_doc_title=title,
                    vault_doc_missing=True,
                    vault_doc_path=str(target),
                    vault_doc_body="",
                ),
            )
        return templates.TemplateResponse(
            request,
            "vault_intelligence_view.html",
            _template_payload(
                request,
                page_title=title,
                page_kicker="Obsidian intelligence vault",
                page_mode="vault-intelligence",
                vault_doc_title=title,
                vault_doc_missing=False,
                vault_doc_path=str(target),
                vault_doc_body=html_body,
            ),
        )

    @app.get("/projects/{project_code}/compare", response_class=HTMLResponse)
    def project_compare(request: Request, project_code: str):
        comparison = service.get_project_compare(project_code)
        if comparison is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return templates.TemplateResponse(
            request,
            "project_compare.html",
            _template_payload(
                request,
                comparison=comparison,
                page_title=f"{comparison['current'].project_name} Comparison",
                page_kicker="Deterministic cross-run comparison",
                page_mode="project-compare",
            ),
        )

    @app.get("/runs", response_class=HTMLResponse)
    def runs_list(request: Request):
        return templates.TemplateResponse(
            request,
            "runs.html",
            _template_payload(
                request,
                runs=service.list_runs(),
                review_runs=orchestration.list_review_runs(),
                page_title="Runs",
                page_kicker="Execution history and published artifacts",
                page_mode="runs",
            ),
        )

    @app.post("/runs")
    async def runs_execute(request: Request, csv_file: UploadFile | None = File(None)):
        wants_json = _wants_json_response(request)
        if csv_file is None:
            if wants_json:
                return JSONResponse(status_code=400, content={"detail": "csv_file upload is required."})
            return _render_runs_home(request, status_code=400, upload_error="A CSV upload is required.")
        raw_name = (csv_file.filename or "").strip()
        filename = Path(raw_name).name.strip()
        if not filename:
            if wants_json:
                return JSONResponse(status_code=400, content={"detail": "csv_file filename is required."})
            return _render_runs_home(request, status_code=400, upload_error="CSV filename is required.")
        if not filename.lower().endswith(".csv"):
            if wants_json:
                return JSONResponse(status_code=400, content={"detail": "csv_file must be a .csv upload."})
            return _render_runs_home(request, status_code=400, upload_error="Only .csv uploads are supported.")
        payload = await csv_file.read()
        if len(payload) == 0:
            if wants_json:
                return JSONResponse(status_code=400, content={"detail": "csv_file upload cannot be empty."})
            return _render_runs_home(request, status_code=400, upload_error="CSV upload cannot be empty.")
        uploads_root = config.runtime.state_root / "runs" / "_uploads"
        uploads_root.mkdir(parents=True, exist_ok=True)
        upload_path = uploads_root / f"{secrets.token_hex(8)}_{filename}"
        upload_path.write_bytes(payload)
        run_id = execute_run(upload_path, state_root=config.runtime.state_root)
        run = get_run(config.runtime.state_root, run_id)
        if run is None:
            raise HTTPException(status_code=500, detail="Run metadata not found after execution.")
        if wants_json:
            return {"run_id": run_id, "status": run["status"]}
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_detail(request: Request, run_id: str):
        run_record = get_run(config.runtime.state_root, run_id)
        if run_record is not None:
            return templates.TemplateResponse(
                request,
                "run_detail.html",
                _template_payload(
                    request,
                    run_record=run_record,
                    page_title=f"Run {run_record['run_id']}",
                    page_kicker="Run registry detail and deterministic artifact pointers",
                    page_mode="run-detail",
                ),
            )
        record = service.get_run(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Run not found")
        comparison_trust = record.portfolio_snapshot.comparison_trust if record.portfolio_snapshot else service.build_portfolio().comparison_trust
        return templates.TemplateResponse(
            request,
            "run_detail.html",
            _template_payload(
                request,
                record=record,
                run_answers=[service.build_project_command_view(project, comparison_trust) for project in record.project_snapshots],
                page_title=f"Run {record.run_id}",
                page_kicker="Run detail and emitted project answers",
                page_mode="run-detail",
            ),
        )

    @app.get("/reviews/{run_id}", response_class=HTMLResponse)
    def review_detail(request: Request, run_id: str):
        review = orchestration.get_review_run(run_id)
        if review is None:
            raise HTTPException(status_code=404, detail="Review run not found")
        review_auth = _review_auth_context(orchestration, request)
        return templates.TemplateResponse(
            request,
            "review_detail.html",
            _template_payload(
                request,
                review=review,
                action_status=request.query_params.get("action"),
                csrf_token=_ensure_auth_csrf_token(request),
                review_auth=review_auth,
                review_mode=orchestration.review_mode(),
                page_title=review.title,
                page_kicker="Approval-gated orchestration review surface",
                page_mode="review-detail",
            ),
        )

    @app.post("/reviews/login")
    async def review_login(
        request: Request,
        operator_username: str = Form(""),
        operator_password: str = Form(""),
        next_path: str = Form("/runs#review-queue"),
        csrf_token: str = Form(""),
    ):
        return await login(
            request,
            username=operator_username,
            password=operator_password,
            next_path=_safe_review_path(next_path),
            csrf_token=csrf_token,
        )

    @app.post("/reviews/logout")
    async def review_logout(
        request: Request,
        next_path: str = Form("/runs#review-queue"),
        csrf_token: str = Form(""),
    ):
        return await logout(
            request,
            next_path=_safe_review_path(next_path),
            csrf_token=csrf_token,
        )

    @app.get("/reviews/{run_id}/artifacts/{artifact_name}")
    def review_artifact_download(run_id: str, artifact_name: str):
        review = orchestration.get_review_run(run_id)
        if review is None:
            raise HTTPException(status_code=404, detail="Review run not found")
        artifact = next((item for item in [*review.artifacts, *review.decision_artifacts] if item.file_name == artifact_name), None)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
        path = Path(artifact.path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Artifact file missing")
        return FileResponse(path, media_type=artifact.content_type, filename=artifact.file_name)

    @app.post("/reviews/{run_id}/approve")
    async def approve_review(
        request: Request,
        run_id: str,
        approved_next_prompt: str = Form(""),
        csrf_token: str = Form(""),
    ):
        actor = _require_review_actor(orchestration, request, csrf_token)
        result = orchestration.approve_review(
            run_id,
            approved_next_prompt=approved_next_prompt or None,
            reviewer_identity=actor.identity,
            auth_mode=actor.auth_mode,
            source_ip=actor.source_ip,
            forwarded_for=actor.forwarded_for,
            user_agent=actor.user_agent,
            request_id=_request_id(request),
            correlation_id=_correlation_id(request),
        )
        if result.review is None:
            raise HTTPException(status_code=404, detail=result.message)
        return RedirectResponse(url=f"{result.review.detail_path}?action={result.status}", status_code=303)

    @app.post("/reviews/{run_id}/reject")
    async def reject_review(
        request: Request,
        run_id: str,
        rejection_note: str = Form(""),
        csrf_token: str = Form(""),
    ):
        actor = _require_review_actor(orchestration, request, csrf_token)
        result = orchestration.reject_review(
            run_id,
            rejection_note=rejection_note or None,
            reviewer_identity=actor.identity,
            auth_mode=actor.auth_mode,
            source_ip=actor.source_ip,
            forwarded_for=actor.forwarded_for,
            user_agent=actor.user_agent,
            request_id=_request_id(request),
            correlation_id=_correlation_id(request),
        )
        if result.review is None:
            raise HTTPException(status_code=404, detail=result.message)
        return RedirectResponse(url=f"{result.review.detail_path}?action={result.status}", status_code=303)

    @app.get("/exports/latest", response_class=HTMLResponse)
    def latest_export(request: Request):
        latest = load_latest_export(config.runtime.state_root)
        return templates.TemplateResponse(
            request,
            "exports.html",
            _template_payload(
                request,
                latest=latest,
                page_title="Latest Export",
                page_kicker="Published dossier and portfolio export state",
                page_mode="exports",
            ),
        )

    def _orch_publish_redirect_url(*, orch_wf: str, notice: str, err: str | None) -> str:
        params: list[tuple[str, str]] = []
        if orch_wf.strip():
            params.append(("orch_wf", orch_wf.strip()))
        if notice.strip():
            params.append(("orch_notice", notice.strip()))
        if err and err.strip():
            params.append(("orch_err", err.strip()[:600]))
        tail = urlencode(params) if params else ""
        return f"/publish?{tail}" if tail else "/publish"

    @app.get("/publish", response_class=HTMLResponse)
    def publish_view(
        request: Request,
        run: str | None = None,
        artifact: str | None = None,
        project: str | None = None,
        print: int = 0,
        orch_wf: str | None = None,
        orch_notice: str | None = None,
        orch_err: str | None = None,
    ):
        latest_run = get_latest_publishable_run(config.runtime.state_root)
        if latest_run is None:
            return _render_publish_operator(request, bundle=None, auto_print=bool(print))
        run_id = str(latest_run.get("run_id") or "").strip()
        if not run_id:
            return _render_publish_operator(request, bundle=None, auto_print=bool(print))
        return RedirectResponse(url=f"/publish/operator/{run_id}", status_code=303)

    def _require_orchestrator_substrate_enabled() -> None:
        if not config.orchestrator_substrate.enabled:
            raise HTTPException(
                status_code=404,
                detail="Orchestrator substrate is not enabled for this Control Tower deployment.",
            )

    @app.get("/api/orchestrator/status")
    def api_orchestrator_status():
        """
        Runtime snapshot for orchestrator substrate binding. Always JSON; does not 404 when disabled.
        Uses the same config flags and path resolution as other orchestrator routes.
        """
        enabled = bool(config.orchestrator_substrate.enabled)
        body: dict[str, Any] = {"enabled": enabled}
        try:
            root = (config.orchestrator_substrate.mcp_service_root or default_orchestrator_mcp_service_root()).resolve()
            runtime_dir = (config.orchestrator_substrate.runtime_dir or (root / "runtime")).resolve()
            body["service_root"] = str(root)
            body["runtime_dir"] = str(runtime_dir)
        except Exception as exc:  # noqa: BLE001 — status must never fail closed
            body["service_root"] = None
            body["runtime_dir"] = None
            body["status"] = "error"
            body["error"] = str(exc)
            return JSONResponse(content=body)

        if not enabled:
            body["status"] = "ok"
            return JSONResponse(content=body)

        try:
            bind_err = orch_substrate.ensure_substrate_bound(config)
        except Exception as exc:  # noqa: BLE001
            body["status"] = "degraded"
            body["bind_error"] = str(exc)
            return JSONResponse(content=body)

        if bind_err:
            body["status"] = "degraded"
            body["bind_error"] = bind_err
        else:
            body["status"] = "ok"
        return JSONResponse(content=body)

    @app.post("/publish/orchestrator/approve-approval")
    async def publish_orch_approve_approval(
        request: Request,
        approval_request_id: str = Form(""),
        reason: str = Form(""),
        orch_wf: str = Form(""),
        csrf_token: str = Form(""),
    ):
        _require_orchestrator_substrate_enabled()
        actor = _require_review_actor(orchestration, request, csrf_token)
        aid = approval_request_id.strip()
        if not aid:
            raise HTTPException(status_code=400, detail="approval_request_id is required.")
        result = orch_substrate.approve_approval_request(
            config,
            approval_request_id=aid,
            actor=str(actor.identity),
            reason=reason or None,
        )
        notice, err = mutation_query_notices(result)
        return RedirectResponse(
            url=_orch_publish_redirect_url(orch_wf=orch_wf, notice=notice, err=err),
            status_code=303,
        )

    @app.post("/publish/orchestrator/deny-approval")
    async def publish_orch_deny_approval(
        request: Request,
        approval_request_id: str = Form(""),
        reason: str = Form(""),
        orch_wf: str = Form(""),
        csrf_token: str = Form(""),
    ):
        _require_orchestrator_substrate_enabled()
        actor = _require_review_actor(orchestration, request, csrf_token)
        aid = approval_request_id.strip()
        if not aid:
            raise HTTPException(status_code=400, detail="approval_request_id is required.")
        result = orch_substrate.deny_approval_request(
            config,
            approval_request_id=aid,
            actor=str(actor.identity),
            reason=reason or None,
        )
        notice, err = mutation_query_notices(result)
        return RedirectResponse(
            url=_orch_publish_redirect_url(orch_wf=orch_wf, notice=notice, err=err),
            status_code=303,
        )

    @app.post("/publish/orchestrator/promote-publish")
    async def publish_orch_promote_publish(
        request: Request,
        publish_request_id: str = Form(""),
        reason: str = Form(""),
        orch_wf: str = Form(""),
        csrf_token: str = Form(""),
    ):
        _require_orchestrator_substrate_enabled()
        actor = _require_review_actor(orchestration, request, csrf_token)
        pid = publish_request_id.strip()
        if not pid:
            raise HTTPException(status_code=400, detail="publish_request_id is required.")
        result = orch_substrate.promote_publish_packet(
            config,
            publish_request_id=pid,
            actor=str(actor.identity),
            reason=reason or None,
        )
        notice, err = mutation_query_notices(result)
        return RedirectResponse(
            url=_orch_publish_redirect_url(orch_wf=orch_wf, notice=notice, err=err),
            status_code=303,
        )

    @app.post("/publish/orchestrator/execute-release")
    async def publish_orch_execute_release(
        request: Request,
        release_request_id: str = Form(""),
        reason: str = Form(""),
        orch_wf: str = Form(""),
        csrf_token: str = Form(""),
    ):
        _require_orchestrator_substrate_enabled()
        actor = _require_review_actor(orchestration, request, csrf_token)
        rid = release_request_id.strip()
        if not rid:
            raise HTTPException(status_code=400, detail="release_request_id is required.")
        result = orch_substrate.execute_release_request(
            config,
            release_request_id=rid,
            actor=str(actor.identity),
            reason=reason or None,
        )
        notice, err = mutation_query_notices(result)
        return RedirectResponse(
            url=_orch_publish_redirect_url(orch_wf=orch_wf, notice=notice, err=err),
            status_code=303,
        )

    @app.get("/api/orchestrator/workflow/{workflow_id}")
    def api_orchestrator_workflow(workflow_id: str):
        _require_orchestrator_substrate_enabled()
        return orch_substrate.get_schedule_publish_workflow(config, workflow_id)

    @app.get("/api/orchestrator/approval-requests")
    def api_orchestrator_approval_requests(
        limit: int = 50,
        state: str | None = None,
        approval_type: str | None = None,
        target_id: str | None = None,
    ):
        _require_orchestrator_substrate_enabled()
        lim = max(1, min(limit, 500))
        return orch_substrate.list_approval_requests(
            config,
            limit=lim,
            state=state,
            approval_type=approval_type,
            target_id=target_id,
        )

    @app.get("/api/orchestrator/publish-packets")
    def api_orchestrator_publish_packets(
        limit: int = 50,
        state: str | None = None,
        publish_target: str | None = None,
    ):
        _require_orchestrator_substrate_enabled()
        lim = max(1, min(limit, 500))
        return orch_substrate.list_publish_packets(
            config,
            limit=lim,
            state=state,
            publish_target=publish_target,
        )

    @app.get("/api/orchestrator/release-requests")
    def api_orchestrator_release_requests(
        limit: int = 50,
        state: str | None = None,
        target_env: str | None = None,
        release_type: str | None = None,
    ):
        _require_orchestrator_substrate_enabled()
        lim = max(1, min(limit, 500))
        return orch_substrate.list_release_requests(
            config,
            limit=lim,
            state=state,
            target_env=target_env,
            release_type=release_type,
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
            _template_payload(
                request,
                publish=publish,
                auto_print=bool(print),
                page_title="Publish Presentation",
                page_kicker="Meeting-ready command brief presentation mode",
                page_mode="publish-present",
            ),
        )

    @app.get("/publish/operator", response_class=HTMLResponse)
    def publish_operator_view(request: Request, bundle: str | None = None, print: int = 0):
        return _render_publish_operator(request, bundle=bundle, auto_print=bool(print), run_id=None)

    @app.get("/publish/operator/{run_id}", response_class=HTMLResponse)
    def publish_operator_run_view(request: Request, run_id: str, print: int = 0):
        run = get_run(config.runtime.state_root, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        ok, reason = assess_run_publishability(config.runtime.state_root, run)
        if not ok:
            raise HTTPException(status_code=409, detail=reason or "Run is not publishable.")
        bundle_path = str(run.get("bundle_path") or "").strip()
        # Phase 21 decision: keep PDF export transport-thin by reusing the existing
        # deterministic operator surface and browser print-to-PDF flow. We intentionally
        # avoid server-side HTML->PDF infrastructure or duplicate template stacks here.
        return _render_publish_operator(request, bundle=bundle_path, auto_print=bool(print), run_id=run_id)

    @app.post("/publish/operator/{run_id}/validation")
    async def publish_operator_validation_submit(
        request: Request,
        run_id: str,
        reviewer: str = Form(""),
        schedule_source: str = Form(""),
        meeting_context: str = Form(""),
        open_friction: str = Form(""),
        high_value_hardening: str = Form(""),
        csrf_token: str = Form(""),
    ):
        _verify_auth_csrf(request, csrf_token)
        run = get_run(config.runtime.state_root, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        ok, reason = assess_run_publishability(config.runtime.state_root, run)
        if not ok:
            raise HTTPException(status_code=409, detail=reason or "Run is not publishable.")
        form = await request.form()
        category_scores: dict[str, int] = {}
        category_notes: dict[str, str] = {}
        for category in VALIDATION_CATEGORIES:
            raw_score = str(form.get(f"score_{category}") or "3").strip()
            try:
                score = int(raw_score)
            except Exception:
                score = 3
            category_scores[category] = max(1, min(5, score))
            category_notes[category] = str(form.get(f"note_{category}") or "")
        save_validation_note(
            config.runtime.state_root,
            run_id=run_id,
            reviewer=reviewer,
            schedule_source=schedule_source,
            meeting_context=meeting_context,
            category_scores=category_scores,
            category_notes=category_notes,
            open_friction=open_friction,
            high_value_hardening=high_value_hardening,
        )
        return RedirectResponse(url=f"/publish/operator/{run_id}?validation_saved=1", status_code=303)

    @app.get("/publish/operator/{run_id}/validation.md")
    def publish_operator_validation_download(run_id: str):
        run = get_run(config.runtime.state_root, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        ok, reason = assess_run_publishability(config.runtime.state_root, run)
        if not ok:
            raise HTTPException(status_code=409, detail=reason or "Run is not publishable.")
        _, md_path = validation_artifact_paths(config.runtime.state_root, run_id)
        if not md_path.exists() or not md_path.is_file():
            raise HTTPException(status_code=404, detail="Validation note not found for this run.")
        return FileResponse(md_path, media_type="text/markdown; charset=utf-8", filename=VALIDATION_MD_FILENAME)

    def _render_publish_operator(
        request: Request,
        *,
        bundle: str | None,
        auto_print: bool = False,
        run_id: str | None = None,
    ):
        packet = None
        command_brief = None
        load_error = None
        validation_note = load_validation_note(config.runtime.state_root, run_id) if run_id else None
        if bundle:
            try:
                validated_bundle = load_publish_bundle(bundle)
                bundle_path = Path(bundle).expanduser().resolve()
                logic_graph = _load_optional_json_dict(bundle_path.parent / "logic_graph.json")
                driver_analysis = _load_optional_json_dict(bundle_path.parent / "driver_analysis.json")
                visualization = build_publish_visualization(
                    validated_bundle,
                    logic_graph=logic_graph,
                    driver_analysis=driver_analysis,
                )
                packet = build_publish_packet(validated_bundle, visualization=visualization)
                command_brief = {
                    "finish": validated_bundle.command_brief.finish,
                    "driver": validated_bundle.command_brief.driver,
                    "risks": validated_bundle.command_brief.risks,
                    "need": validated_bundle.command_brief.need,
                    "doing": validated_bundle.command_brief.doing,
                }
            except BundleValidationError as exc:
                load_error = str(exc)
            except Exception:
                load_error = "bundle could not be processed."
        return templates.TemplateResponse(
            request,
            "publish_operator.html",
            _template_payload(
                request,
                publish_packet=packet.to_jsonable_dict() if packet is not None else None,
                publish_command_brief=command_brief,
                publish_bundle_path=bundle,
                publish_load_error=load_error,
                auto_print=auto_print,
                publish_run_id=run_id,
                publish_validation_note=validation_note,
                publish_validation_categories=VALIDATION_CATEGORIES,
                publish_validation_category_labels=VALIDATION_CATEGORY_LABELS,
                validation_saved=request.query_params.get("validation_saved"),
                page_title="Publish Operator",
                page_kicker="Deterministic PublishPacket operator surface",
                page_mode="publish publish-operator",
            ),
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
            _template_payload(
                request,
                diagnostics=diagnostics,
                page_title="Diagnostics",
                page_kicker="Operator diagnostics and release posture",
                page_mode="diagnostics",
            ),
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

    @app.get("/api/reviews")
    def review_runs_api():
        return [review.model_dump(mode="json") for review in orchestration.list_review_runs()]

    @app.get("/api/reviews/{run_id}")
    def review_run_api(run_id: str):
        review = orchestration.get_review_run(run_id)
        if review is None:
            raise HTTPException(status_code=404, detail="Review run not found")
        return review.model_dump(mode="json")

    @app.post("/api/packets/generate")
    def api_packets_generate(payload: dict = Body(...)):
        try:
            req = GeneratePacketRequest.model_validate(payload)
            record = generate_weekly_schedule_intelligence_packet(service, req)
            write_packet_artifacts(config.runtime.state_root, record)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "packet_id": record.packet_id,
            "status": record.status,
            "detail_path": f"/packets/{record.packet_id}",
        }

    @app.get("/api/packets/{packet_id}")
    def api_packets_get(packet_id: str):
        try:
            record = load_packet(config.runtime.state_root, packet_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if record is None:
            raise HTTPException(status_code=404, detail="Packet not found")
        return record.model_dump(mode="json")

    @app.post("/api/packets/{packet_id}/publish")
    def api_packets_publish(packet_id: str):
        try:
            updated = publish_packet(config.runtime.state_root, packet_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Packet not found")
        try_sync_intelligence_packet_to_obsidian(
            config.obsidian,
            updated,
            state_root=config.runtime.state_root,
        )
        return updated.model_dump(mode="json")

    @app.get("/api/packets/{packet_id}/export/markdown")
    def api_packets_export_markdown(packet_id: str):
        try:
            exported = export_markdown_bytes(config.runtime.state_root, packet_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if exported is None:
            raise HTTPException(status_code=404, detail="Packet not found")
        filename, body = exported
        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/execution/results")
    def execution_result_ingest(payload: dict = Body(...)):
        try:
            review = orchestration.ingest_execution_result(payload)
        except ValueError as exc:
            message = str(exc)
            if "disabled" in message.lower():
                raise HTTPException(status_code=403, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc
        return {
            "status": "accepted",
            "run_id": review.run_id,
            "event_id": review.execution_event.event_id,
            "execution_status": review.execution_result.status,
        }

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


def _request_id(request: Request) -> str | None:
    return request.headers.get("X-Request-ID") or request.headers.get("X-Amzn-Trace-Id")


def _correlation_id(request: Request) -> str | None:
    return request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")


def _app_auth_requires_login(config) -> bool:
    return (config.auth.mode or "dev").strip().lower() == "prod"


def _session_requires_https(config, orchestration: OrchestrationService) -> bool:
    return _app_auth_requires_login(config) or orchestration.review_mutation_requires_auth()


def _session_cookie_name(config, orchestration: OrchestrationService) -> str:
    if _app_auth_requires_login(config):
        return config.auth.session_cookie_name
    if orchestration.review_mutation_requires_auth():
        return config.review.session_cookie_name
    return config.auth.session_cookie_name or config.review.session_cookie_name


def _session_secret(config, orchestration: OrchestrationService) -> str:
    for candidate in (config.auth.session_secret, config.review.session_secret):
        value = (candidate or "").strip()
        if value:
            return value
    if _session_requires_https(config, orchestration):
        return secrets.token_urlsafe(32)
    return DEFAULT_DEV_SESSION_SECRET


def _interactive_auth_credentials(config, orchestration: OrchestrationService) -> tuple[str, str]:
    if _app_auth_requires_login(config):
        return (config.auth.username or "").strip(), (config.auth.password or "").strip()
    return (config.review.operator_username or "").strip(), (config.review.operator_password or "").strip()


def _interactive_auth_mode(config, orchestration: OrchestrationService) -> str:
    if _app_auth_requires_login(config):
        return "session"
    return orchestration.review_auth_mode()


def _interactive_auth_configuration_error(config, orchestration: OrchestrationService) -> str | None:
    if _app_auth_requires_login(config):
        missing: list[str] = []
        if not (config.auth.session_secret or "").strip():
            missing.append("CODEX_AUTH_SESSION_SECRET")
        if not (config.auth.username or "").strip():
            missing.append("CODEX_AUTH_USERNAME")
        if not (config.auth.password or "").strip():
            missing.append("CODEX_AUTH_PASSWORD")
        if missing:
            return f"Application auth is not configured. Missing: {', '.join(missing)}"
    elif orchestration.review_mutation_requires_auth():
        return orchestration.review_auth_configuration_error()
    return None


def _ensure_auth_csrf_token(request: Request, *, rotate: bool = False) -> str:
    token = request.session.get(AUTH_CSRF_SESSION_KEY)
    if rotate or not token:
        token = secrets.token_urlsafe(24)
        request.session[AUTH_CSRF_SESSION_KEY] = token
    return token


def _verify_auth_csrf(request: Request, csrf_token: str | None) -> None:
    expected = request.session.get(AUTH_CSRF_SESSION_KEY)
    provided = (csrf_token or "").strip()
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Control Tower form submission is missing a valid CSRF token.")


def _authenticated_session(request: Request) -> dict[str, object]:
    return request.session.get(AUTH_SESSION_KEY) or {}


def _is_public_path(path: str) -> bool:
    return path in PUBLIC_EXACT_PATHS or any(path == prefix or path.startswith(f"{prefix}/") for prefix in PUBLIC_PATH_PREFIXES)


def _login_redirect_path(request: Request) -> str:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return f"/login?next_path={quote(next_path, safe='/%#?=&')}"


def _app_auth_context(config, orchestration: OrchestrationService, request: Request) -> dict[str, object]:
    config_error = _interactive_auth_configuration_error(config, orchestration) if _app_auth_requires_login(config) else None
    authenticated_session = _authenticated_session(request)
    auth_required = _app_auth_requires_login(config)
    authenticated = (not auth_required) or bool(authenticated_session.get("identity"))
    if authenticated_session.get("identity"):
        identity = str(authenticated_session.get("identity"))
    elif auth_required:
        identity = None
    else:
        identity = _reviewer_identity(request) or "dev-local"
    auth_mode = str(authenticated_session.get("auth_mode") or ("session" if auth_required else "dev_open"))
    return {
        "required": auth_required,
        "configured": config_error is None,
        "configuration_error": config_error,
        "authenticated": authenticated,
        "identity": identity,
        "auth_mode": auth_mode,
        "login_path": "/login",
        "logout_path": "/logout",
    }


def _review_auth_context(orchestration: OrchestrationService, request: Request) -> dict[str, object]:
    config = orchestration.config
    config_error = _interactive_auth_configuration_error(config, orchestration)
    authenticated_session = _authenticated_session(request)
    auth_required = _app_auth_requires_login(config) or orchestration.review_mutation_requires_auth()
    authenticated = (not auth_required) or bool(authenticated_session.get("identity"))
    if authenticated_session.get("identity"):
        identity = str(authenticated_session.get("identity"))
    elif auth_required:
        identity = None
    else:
        identity = _reviewer_identity(request) or "dev-local"
    auth_mode = (
        str(authenticated_session.get("auth_mode"))
        if authenticated_session.get("auth_mode")
        else ("session" if auth_required else orchestration.review_auth_mode())
    )
    return {
        "required": auth_required,
        "configured": config_error is None,
        "configuration_error": config_error,
        "authenticated": authenticated,
        "can_mutate": (not auth_required) or (config_error is None and authenticated),
        "identity": identity,
        "auth_mode": auth_mode,
        "login_path": "/login" if _app_auth_requires_login(config) else "/reviews/login",
        "logout_path": "/logout" if _app_auth_requires_login(config) else "/reviews/logout",
    }


def _require_review_actor(
    orchestration: OrchestrationService,
    request: Request,
    csrf_token: str | None,
) -> ReviewActorContext:
    if not (_app_auth_requires_login(orchestration.config) or orchestration.review_mutation_requires_auth()):
        return ReviewActorContext(
            identity=_reviewer_identity(request) or "dev-local",
            auth_mode=orchestration.review_auth_mode(),
            source_ip=_source_ip(request),
            forwarded_for=_forwarded_for(request),
            user_agent=_user_agent(request),
        )
    auth_error = _interactive_auth_configuration_error(orchestration.config, orchestration)
    if auth_error:
        raise HTTPException(status_code=503, detail=auth_error)
    auth_context = _review_auth_context(orchestration, request)
    if not auth_context["authenticated"]:
        raise HTTPException(status_code=401, detail="Production review mutations require an authenticated operator session.")
    _verify_auth_csrf(request, csrf_token)
    return ReviewActorContext(
        identity=str(auth_context["identity"]),
        auth_mode=str(auth_context["auth_mode"]),
        source_ip=_source_ip(request),
        forwarded_for=_forwarded_for(request),
        user_agent=_user_agent(request),
    )


def _reviewer_identity(request: Request) -> str | None:
    return request.headers.get("X-Forwarded-User") or (request.client.host if request.client else None)


def _source_ip(request: Request) -> str | None:
    forwarded = _forwarded_for(request)
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _forwarded_for(request: Request) -> str | None:
    return request.headers.get("X-Forwarded-For")


def _user_agent(request: Request) -> str | None:
    return request.headers.get("User-Agent")


def _safe_next_path(candidate: str | None, *, default: str = "/publish") -> str:
    value = (candidate or "").strip()
    if value.startswith("/") and not value.startswith("//"):
        return value
    return default


def _safe_review_path(candidate: str | None) -> str:
    return _safe_next_path(candidate, default="/runs#review-queue")


def _with_auth_action(path: str, action: str) -> str:
    parts = urlsplit(path)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["action" if parts.path.startswith("/reviews") or parts.path.startswith("/runs") else "auth"] = action
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _with_review_action(path: str, action: str) -> str:
    parts = urlsplit(path)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["action"] = action
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _wants_json_response(request: Request) -> bool:
    accepts = (request.headers.get("accept") or "").lower()
    return "application/json" in accepts and "text/html" not in accepts


def _load_optional_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
        return None
    except Exception:
        return None


def _is_allowed_primary_surface_path(path: str) -> bool:
    if path in {"/", "/publish", "/entry/upload"}:
        return True
    if path.startswith("/publish/operator/"):
        suffix = path.removeprefix("/publish/operator/").strip("/")
        return bool(suffix)
    return False


def _is_allowed_infra_path(path: str) -> bool:
    if path in {"/healthz", "/favicon.ico", "/login", "/logout"}:
        return True
    return path.startswith("/static/")


app = create_app()

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from fastapi import Body, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from controltower.config import load_config
from controltower.obsidian.exporter import load_latest_export
from controltower.services.controltower import ControlTowerService
from controltower.services.orchestration import OrchestrationService, ReviewActorContext
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
    "projects.html",
    "project_compare.html",
    "project_detail.html",
    "runs.html",
    "run_detail.html",
    "review_detail.html",
    "diagnostics.html",
)

AUTH_SESSION_KEY = "controltower_auth"
AUTH_CSRF_SESSION_KEY = "controltower_csrf_token"
DEFAULT_DEV_SESSION_SECRET = "controltower-dev-session"
PUBLIC_PATH_PREFIXES = ("/login", "/logout", "/reviews/login", "/reviews/logout", "/static")
PUBLIC_EXACT_PATHS = {"/favicon.ico", "/healthz"}


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
    app.mount("/static", StaticFiles(directory=str(STATIC_ROOT)), name="static")

    def _template_payload(request: Request, **context: object) -> dict[str, object]:
        payload = {
            "config": config,
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
        return {"status": "ok"}

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
                page_kicker="Public Control Tower access now requires application-layer authentication.",
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
                page_title=project.project_name,
                page_kicker="Project detail command surface",
                page_mode="project-detail",
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

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_detail(request: Request, run_id: str):
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
            _template_payload(
                request,
                publish=publish,
                auto_print=bool(print),
                page_title="Publish",
                page_kicker="Meeting-ready command brief and deliverable workspace",
                page_mode="publish",
            ),
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


app = create_app()

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _dev_root() -> Path:
    return _repo_root().parent


def default_orchestrator_mcp_service_root() -> Path:
    """Sibling checkout: ``Dev/mcp_gateway/services/controltower_orchestrator_mcp``."""
    return _dev_root() / "mcp_gateway" / "services" / "controltower_orchestrator_mcp"


def _default_registry_path() -> Path:
    return _repo_root() / "config" / "project_registry.yaml"


class ScheduleLabSourceConfig(BaseModel):
    published_root: Path = Field(default_factory=lambda: _dev_root() / "ScheduleLab" / "schedule_validator" / "published")


class ProfitIntelSourceConfig(BaseModel):
    database_path: Path = Field(default_factory=lambda: _dev_root() / "ProfitIntel" / "data" / "runtime" / "profitintel.db")
    validation_search_roots: list[Path] = Field(
        default_factory=lambda: [
            _dev_root() / "ProfitIntel" / "data" / "runtime",
            _dev_root() / "ProfitIntel" / "artifacts" / "validation",
        ]
    )


class SourcesConfig(BaseModel):
    schedulelab: ScheduleLabSourceConfig = Field(default_factory=ScheduleLabSourceConfig)
    profitintel: ProfitIntelSourceConfig = Field(default_factory=ProfitIntelSourceConfig)


class IdentityConfig(BaseModel):
    registry_path: Path | None = Field(default_factory=_default_registry_path)


class ObsidianConfig(BaseModel):
    vault_root: Path = Field(default_factory=lambda: _repo_root() / ".tmp" / "demo_vault")
    intelligence_vault_enabled: bool = True
    intelligence_vault_projects_folder: str = "Projects"
    projects_folder: str = "02 Projects"
    exports_folder: str = "10 Exports"
    timestamped_weekly_notes: bool = True
    rolling_portfolio_note_name: str = "Portfolio Weekly Summary"
    rolling_project_brief_name: str = "Weekly Brief"
    canonical_dossier_suffix: str = "Dossier"
    continuity_root: Path | None = None
    checkout_notes: list[str] = Field(default_factory=lambda: ["active_control.md"])
    active_control_note: str = "active_control.md"
    session_log_dir: str = "session_logs"
    active_control_section_heading: str = "## Active Lane Check-In"

    @model_validator(mode="after")
    def normalize_continuity(self) -> "ObsidianConfig":
        if self.continuity_root is None:
            self.continuity_root = self.vault_root / "20 Control Tower"
        normalized_notes = [str(item).strip().replace("\\", "/") for item in self.checkout_notes if str(item).strip()]
        if not normalized_notes:
            normalized_notes = [self.active_control_note]
        active_control_note = str(self.active_control_note).strip().replace("\\", "/") or "active_control.md"
        if active_control_note not in normalized_notes:
            normalized_notes.insert(0, active_control_note)
        self.checkout_notes = normalized_notes[:5]
        self.active_control_note = active_control_note
        self.session_log_dir = str(self.session_log_dir).strip().replace("\\", "/") or "session_logs"
        self.active_control_section_heading = str(self.active_control_section_heading).strip() or "## Active Lane Check-In"
        return self


class RetentionConfig(BaseModel):
    run_history_limit: int = 30
    release_history_limit: int = 12
    operations_history_limit: int = 60
    diagnostics_history_limit: int = 30
    log_file_limit: int = 60

    @model_validator(mode="after")
    def validate_limits(self) -> "RetentionConfig":
        for field_name in (
            "run_history_limit",
            "release_history_limit",
            "operations_history_limit",
            "diagnostics_history_limit",
            "log_file_limit",
        ):
            if getattr(self, field_name) < 1:
                raise ValueError(f"Control Tower runtime retention '{field_name}' must be >= 1.")
        return self


class RuntimeConfig(BaseModel):
    state_root: Path = Field(default_factory=lambda: _repo_root() / ".controltower_runtime")
    retention: RetentionConfig = Field(default_factory=RetentionConfig)


class UiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787


class NotificationsConfig(BaseModel):
    provider: str = "runtime_log"


class ExecutionConfig(BaseModel):
    provider: str = "file"
    webhook_url: str | None = None
    file_dir: Path | None = None
    webhook_timeout_ms: int = 5000
    dead_letter_dir: Path | None = None
    result_ingest_enabled: bool = True
    event_version: str = "v1"
    max_attempts: int = 3
    retry_backoff_ms: int = 1000
    retry_backoff_multiplier: float = 2.0
    guarded_packs: list[str] = Field(default_factory=lambda: ["deploy_pack", "release_readiness_pack"])
    allow_guarded_in_prod: bool = False
    codex_executor_command: str | None = None
    codex_executor_workdir: Path | None = Field(default_factory=_repo_root)
    codex_executor_timeout_seconds: int = 3600
    codex_executor_poll_interval_seconds: int = 30

    @model_validator(mode="after")
    def validate_execution(self) -> "ExecutionConfig":
        self.max_attempts = max(int(self.max_attempts), 1)
        self.retry_backoff_ms = max(int(self.retry_backoff_ms), 0)
        self.retry_backoff_multiplier = max(float(self.retry_backoff_multiplier), 1.0)
        self.guarded_packs = [item.strip() for item in self.guarded_packs if str(item).strip()]
        self.codex_executor_command = (self.codex_executor_command or "").strip() or None
        self.codex_executor_timeout_seconds = max(int(self.codex_executor_timeout_seconds), 1)
        self.codex_executor_poll_interval_seconds = max(int(self.codex_executor_poll_interval_seconds), 1)
        return self

    @property
    def max_retries(self) -> int:
        return max(int(self.max_attempts) - 1, 0)

    @property
    def webhook_timeout_seconds(self) -> float:
        return max(float(self.webhook_timeout_ms) / 1000.0, 0.1)

    @webhook_timeout_seconds.setter
    def webhook_timeout_seconds(self, value: float) -> None:
        self.webhook_timeout_ms = max(int(float(value) * 1000), 100)


class ReviewConfig(BaseModel):
    mode: str | None = None
    shared_token: str | None = None
    token_header: str = "X-ControlTower-Review-Token"
    session_secret: str | None = None
    operator_username: str | None = None
    operator_password: str | None = None
    session_cookie_name: str = "controltower_review_session"


class AuthConfig(BaseModel):
    mode: str | None = None
    session_secret: str | None = None
    username: str | None = None
    password: str | None = None
    session_cookie_name: str = "controltower_app_session"


class AutonomyConfig(BaseModel):
    enabled: bool = True
    auto_approve_low_risk: bool = True
    escalate_high_risk: bool = True
    policy_version: str = "v1"
    notify_on_auto_approve: bool = False


class PromptOrchestrationConfig(BaseModel):
    enabled: bool = False
    obsidian_gating_enabled: bool = True
    model: str = "gpt-5"
    openai_api_key: str | None = None


class OrchestratorSubstrateConfig(BaseModel):
    """
    Read and mutate controltower_orchestrator_mcp durable stores in-process.

    Control Tower does not own workflow state; it binds the orchestrator package to configured
    JSON paths and forwards operator reads/actions through those seams.
    """

    enabled: bool = False
    mcp_service_root: Path | None = None
    runtime_dir: Path | None = None


class AppConfig(BaseModel):
    product_name: str = "Control Tower"
    environment: str = "local"
    public_base_url: str | None = None


class ControlTowerConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    obsidian: ObsidianConfig = Field(default_factory=ObsidianConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    autonomy: AutonomyConfig = Field(default_factory=AutonomyConfig)
    prompt_orchestration: PromptOrchestrationConfig = Field(default_factory=PromptOrchestrationConfig)
    orchestrator_substrate: OrchestratorSubstrateConfig = Field(default_factory=OrchestratorSubstrateConfig)

    @model_validator(mode="after")
    def normalize_paths(self) -> "ControlTowerConfig":
        local_environments = {"local", "local-livecheck", "dev", "development", "test"}
        if self.identity.registry_path is None:
            self.identity.registry_path = _default_registry_path()
        if not self.identity.registry_path.exists():
            raise FileNotFoundError(f"Control Tower identity registry is missing: {self.identity.registry_path}")
        for path_value in [
            self.sources.schedulelab.published_root,
            self.sources.profitintel.database_path,
            self.obsidian.vault_root,
            self.obsidian.continuity_root,
            self.runtime.state_root,
        ]:
            path_value.parent.mkdir(parents=True, exist_ok=True)
        if self.execution.file_dir is None:
            self.execution.file_dir = self.runtime.state_root / "orchestration" / "execution_queue"
        if self.execution.dead_letter_dir is None:
            self.execution.dead_letter_dir = self.runtime.state_root / "orchestration" / "dead_letter"
        self.execution.file_dir.parent.mkdir(parents=True, exist_ok=True)
        self.execution.dead_letter_dir.parent.mkdir(parents=True, exist_ok=True)
        if self.review.mode is None:
            normalized_environment = self.app.environment.lower()
            self.review.mode = "dev" if normalized_environment in local_environments else "prod"
        if self.auth.mode is None:
            normalized_environment = self.app.environment.lower()
            self.auth.mode = "dev" if normalized_environment in local_environments else "prod"
        if self.orchestrator_substrate.enabled:
            root = self.orchestrator_substrate.mcp_service_root or default_orchestrator_mcp_service_root()
            if not root.is_dir():
                raise FileNotFoundError(
                    f"Orchestrator substrate is enabled but mcp_service_root is missing: {root}"
                )
            rdir = self.orchestrator_substrate.runtime_dir or (root / "runtime")
            rdir.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def trigger(self) -> ExecutionConfig:
        return self.execution


def _resolve_path(candidate: str | Path | None, base_dir: Path) -> Path | None:
    if candidate in {None, ""}:
        return None
    path = Path(candidate)
    return path if path.is_absolute() else (base_dir / path).resolve()


def _resolve_payload_paths(payload: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    copied = dict(payload)
    sources = dict(copied.get("sources") or {})
    schedulelab = dict(sources.get("schedulelab") or {})
    profitintel = dict(sources.get("profitintel") or {})
    identity = dict(copied.get("identity") or {})
    obsidian = dict(copied.get("obsidian") or {})
    runtime = dict(copied.get("runtime") or {})
    execution = dict(copied.get("execution") or copied.get("trigger") or {})
    review = dict(copied.get("review") or {})

    if "published_root" in schedulelab:
        schedulelab["published_root"] = _resolve_path(schedulelab.get("published_root"), base_dir)
    if "database_path" in profitintel:
        profitintel["database_path"] = _resolve_path(profitintel.get("database_path"), base_dir)
    if "validation_search_roots" in profitintel:
        profitintel["validation_search_roots"] = [
            _resolve_path(item, base_dir) for item in (profitintel.get("validation_search_roots") or [])
        ]
    if "registry_path" in identity:
        identity["registry_path"] = _resolve_path(identity.get("registry_path"), base_dir)
    if "vault_root" in obsidian:
        obsidian["vault_root"] = _resolve_path(obsidian.get("vault_root"), base_dir)
    if "continuity_root" in obsidian:
        vault_root = _resolve_path(obsidian.get("vault_root"), base_dir)
        obsidian["continuity_root"] = _resolve_path(obsidian.get("continuity_root"), vault_root or base_dir)
    if "state_root" in runtime:
        runtime["state_root"] = _resolve_path(runtime.get("state_root"), base_dir)
    if "file_dir" in execution:
        execution["file_dir"] = _resolve_path(execution.get("file_dir"), base_dir)
    if "dead_letter_dir" in execution:
        execution["dead_letter_dir"] = _resolve_path(execution.get("dead_letter_dir"), base_dir)
    if "codex_executor_workdir" in execution:
        execution["codex_executor_workdir"] = _resolve_path(execution.get("codex_executor_workdir"), base_dir)

    copied["sources"] = {**sources, "schedulelab": schedulelab, "profitintel": profitintel}
    copied["identity"] = identity
    copied["obsidian"] = obsidian
    copied["runtime"] = runtime
    copied["execution"] = execution
    copied["review"] = review

    orchestrator_substrate = dict(copied.get("orchestrator_substrate") or {})
    if "mcp_service_root" in orchestrator_substrate:
        orchestrator_substrate["mcp_service_root"] = _resolve_path(
            orchestrator_substrate.get("mcp_service_root"), base_dir
        )
    if "runtime_dir" in orchestrator_substrate:
        orchestrator_substrate["runtime_dir"] = _resolve_path(orchestrator_substrate.get("runtime_dir"), base_dir)

    copied["orchestrator_substrate"] = orchestrator_substrate
    return copied


def _env_bool(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Environment variable {name} must be a boolean value.")


def _apply_env_overrides(payload: dict[str, Any]) -> dict[str, Any]:
    copied = dict(payload)
    app = dict(copied.get("app") or {})
    execution = dict(copied.get("execution") or copied.get("trigger") or {})
    review = dict(copied.get("review") or {})
    auth = dict(copied.get("auth") or {})
    autonomy = dict(copied.get("autonomy") or {})
    prompt_orchestration = dict(copied.get("prompt_orchestration") or {})

    if value := os.getenv("CONTROLTOWER_PUBLIC_BASE_URL") or os.getenv("CODEX_PUBLIC_BASE_URL"):
        app["public_base_url"] = value

    if value := os.getenv("CODEX_EXECUTION_PROVIDER") or os.getenv("CODEX_TRIGGER_PROVIDER"):
        execution["provider"] = value
    if value := os.getenv("CODEX_EXECUTION_WEBHOOK_URL") or os.getenv("CODEX_TRIGGER_WEBHOOK_URL"):
        execution["webhook_url"] = value
    if value := os.getenv("CODEX_EXECUTION_FILE_DIR") or os.getenv("CODEX_TRIGGER_FILE_DIR"):
        execution["file_dir"] = value
    if value := os.getenv("CODEX_EXECUTION_WEBHOOK_TIMEOUT_MS") or os.getenv("CODEX_TRIGGER_WEBHOOK_TIMEOUT_MS"):
        execution["webhook_timeout_ms"] = max(int(float(value)), 100)
    if value := os.getenv("CODEX_EXECUTION_DEAD_LETTER_DIR"):
        execution["dead_letter_dir"] = value
    if value := os.getenv("CODEX_EXECUTION_MAX_ATTEMPTS"):
        execution["max_attempts"] = max(int(float(value)), 1)
    if value := os.getenv("CODEX_EXECUTION_RETRY_BACKOFF_MS"):
        execution["retry_backoff_ms"] = max(int(float(value)), 0)
    if value := os.getenv("CODEX_EXECUTION_RETRY_BACKOFF_MULTIPLIER"):
        execution["retry_backoff_multiplier"] = max(float(value), 1.0)
    if value := os.getenv("CODEX_EXECUTION_GUARDED_PACKS"):
        execution["guarded_packs"] = [item.strip() for item in value.split(",") if item.strip()]
    if (value := _env_bool("CODEX_EXECUTION_ALLOW_GUARDED_IN_PROD")) is not None:
        execution["allow_guarded_in_prod"] = value
    if value := os.getenv("CODEX_EXECUTOR_COMMAND"):
        execution["codex_executor_command"] = value
    if value := os.getenv("CODEX_EXECUTOR_WORKDIR"):
        execution["codex_executor_workdir"] = value
    if value := os.getenv("CODEX_EXECUTOR_TIMEOUT_SECONDS"):
        execution["codex_executor_timeout_seconds"] = max(int(float(value)), 1)
    if value := os.getenv("CODEX_EXECUTOR_POLL_INTERVAL_SECONDS"):
        execution["codex_executor_poll_interval_seconds"] = max(int(float(value)), 1)
    if (value := _env_bool("CODEX_RESULT_INGEST_ENABLED")) is not None:
        execution["result_ingest_enabled"] = value
    if value := os.getenv("CODEX_EVENT_VERSION"):
        execution["event_version"] = value.strip() or "v1"

    if value := os.getenv("CODEX_REVIEW_MODE"):
        review["mode"] = value
    if value := os.getenv("CODEX_REVIEW_SHARED_TOKEN"):
        review["shared_token"] = value
    if value := os.getenv("CODEX_REVIEW_SESSION_SECRET"):
        review["session_secret"] = value
    if value := os.getenv("CODEX_REVIEW_OPERATOR_USERNAME"):
        review["operator_username"] = value
    if value := os.getenv("CODEX_REVIEW_OPERATOR_PASSWORD"):
        review["operator_password"] = value
    if value := os.getenv("CODEX_REVIEW_SESSION_COOKIE_NAME"):
        review["session_cookie_name"] = value

    if value := os.getenv("CODEX_AUTH_MODE"):
        auth["mode"] = value
    if value := os.getenv("CODEX_AUTH_SESSION_SECRET"):
        auth["session_secret"] = value
    if value := os.getenv("CODEX_AUTH_USERNAME"):
        auth["username"] = value
    if value := os.getenv("CODEX_AUTH_PASSWORD"):
        auth["password"] = value
    if value := os.getenv("CODEX_AUTH_SESSION_COOKIE_NAME"):
        auth["session_cookie_name"] = value

    if (value := _env_bool("CODEX_AUTONOMY_ENABLED")) is not None:
        autonomy["enabled"] = value
    if (value := _env_bool("CODEX_AUTO_APPROVE_LOW_RISK")) is not None:
        autonomy["auto_approve_low_risk"] = value
    if (value := _env_bool("CODEX_ESCALATE_HIGH_RISK")) is not None:
        autonomy["escalate_high_risk"] = value
    if value := os.getenv("CODEX_POLICY_VERSION"):
        autonomy["policy_version"] = value.strip() or "v1"
    if (value := _env_bool("CODEX_NOTIFY_ON_AUTO_APPROVE")) is not None:
        autonomy["notify_on_auto_approve"] = value

    if value := os.getenv("OPENAI_API_KEY") or os.getenv("CONTROLTOWER_OPENAI_API_KEY"):
        prompt_orchestration["openai_api_key"] = value
    if value := os.getenv("CONTROLTOWER_ORCHESTRATION_MODEL") or os.getenv("CODEX_ORCHESTRATION_MODEL"):
        prompt_orchestration["model"] = value.strip() or "gpt-5"
    if (value := _env_bool("CONTROLTOWER_PROMPT_ORCHESTRATION_ENABLED")) is not None:
        prompt_orchestration["enabled"] = value
    elif (value := _env_bool("CODEX_PROMPT_ORCHESTRATION_ENABLED")) is not None:
        prompt_orchestration["enabled"] = value
    if (value := _env_bool("CONTROLTOWER_OBSIDIAN_GATING_ENABLED")) is not None:
        prompt_orchestration["obsidian_gating_enabled"] = value
    elif (value := _env_bool("CODEX_OBSIDIAN_GATING_ENABLED")) is not None:
        prompt_orchestration["obsidian_gating_enabled"] = value

    copied["app"] = app
    copied["execution"] = execution
    copied["review"] = review
    copied["auth"] = auth
    copied["autonomy"] = autonomy
    copied["prompt_orchestration"] = prompt_orchestration

    orchestrator_substrate = dict(copied.get("orchestrator_substrate") or {})
    if (value := _env_bool("CONTROLTOWER_ORCHESTRATOR_SUBSTRATE_ENABLED")) is not None:
        orchestrator_substrate["enabled"] = value
    if value := os.getenv("CONTROLTOWER_ORCHESTRATOR_MCP_SERVICE_ROOT"):
        orchestrator_substrate["mcp_service_root"] = value
    if value := os.getenv("CONTROLTOWER_ORCHESTRATOR_RUNTIME_DIR"):
        orchestrator_substrate["runtime_dir"] = value
    copied["orchestrator_substrate"] = orchestrator_substrate

    return copied


def load_config(config_path: Path | None = None) -> ControlTowerConfig:
    if config_path is None:
        return ControlTowerConfig.model_validate(_apply_env_overrides({}))
    config_path = Path(config_path).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Control Tower config file is missing: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Control Tower config file is malformed YAML: {config_path}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Control Tower config root must be a mapping: {config_path}")
    overridden = _apply_env_overrides(raw)
    resolved = _resolve_payload_paths(overridden, config_path.parent)
    return ControlTowerConfig.model_validate(resolved)

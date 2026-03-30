from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _dev_root() -> Path:
    return _repo_root().parent


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
    vault_root: Path = Field(default_factory=lambda: _repo_root() / "tmp" / "demo_vault")
    projects_folder: str = "02 Projects"
    exports_folder: str = "10 Exports"
    timestamped_weekly_notes: bool = True
    rolling_portfolio_note_name: str = "Portfolio Weekly Summary"
    rolling_project_brief_name: str = "Weekly Brief"
    canonical_dossier_suffix: str = "Dossier"


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


class AppConfig(BaseModel):
    product_name: str = "Control Tower"
    environment: str = "local"


class ControlTowerConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    obsidian: ObsidianConfig = Field(default_factory=ObsidianConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    ui: UiConfig = Field(default_factory=UiConfig)

    @model_validator(mode="after")
    def normalize_paths(self) -> "ControlTowerConfig":
        if self.identity.registry_path is None:
            self.identity.registry_path = _default_registry_path()
        if not self.identity.registry_path.exists():
            raise FileNotFoundError(f"Control Tower identity registry is missing: {self.identity.registry_path}")
        for path_value in [
            self.sources.schedulelab.published_root,
            self.sources.profitintel.database_path,
            self.obsidian.vault_root,
            self.runtime.state_root,
        ]:
            path_value.parent.mkdir(parents=True, exist_ok=True)
        return self


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
    if "state_root" in runtime:
        runtime["state_root"] = _resolve_path(runtime.get("state_root"), base_dir)

    copied["sources"] = {**sources, "schedulelab": schedulelab, "profitintel": profitintel}
    copied["identity"] = identity
    copied["obsidian"] = obsidian
    copied["runtime"] = runtime
    return copied


def load_config(config_path: Path | None = None) -> ControlTowerConfig:
    if config_path is None:
        return ControlTowerConfig()
    config_path = Path(config_path).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Control Tower config file is missing: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Control Tower config file is malformed YAML: {config_path}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Control Tower config root must be a mapping: {config_path}")
    resolved = _resolve_payload_paths(raw, config_path.parent)
    return ControlTowerConfig.model_validate(resolved)

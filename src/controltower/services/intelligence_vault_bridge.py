from __future__ import annotations

from pathlib import Path
from typing import Any

from controltower.config import ControlTowerConfig
from controltower.obsidian.intelligence_vault import (
    intelligence_packet_note_stem,
    intelligence_vault_project_slug,
    intelligence_vault_settings_from_obsidian,
    _planned_export_paths,
)
from controltower.render.markdown import parse_markdown_frontmatter, render_publish_markdown_preview
from controltower.services.intelligence_packets import IntelligencePacketRecord, load_packet
from controltower.services.runtime_state import read_json


def resolve_paths_for_packet(record: IntelligencePacketRecord, config: ControlTowerConfig) -> dict[str, str]:
    obsidian = config.obsidian
    slug = intelligence_vault_project_slug(
        canonical_project_code=record.canonical_project_code or "",
        project_name=record.project_name or "",
    )
    _enabled, projects_folder = intelligence_vault_settings_from_obsidian(obsidian)
    stem = intelligence_packet_note_stem(record)
    return _planned_export_paths(
        vault=Path(obsidian.vault_root),
        projects_folder=projects_folder,
        project_slug=slug,
        packet_stem=stem,
    )


def relative_vault_path(vault_root: Path, absolute: Path) -> str:
    try:
        rel = Path(absolute).resolve().relative_to(Path(vault_root).resolve())
        return rel.as_posix()
    except ValueError:
        return Path(absolute).name


def load_export_evidence(state_root: Path, packet_id: str) -> dict[str, Any] | None:
    path = Path(state_root) / "obsidian_exports" / f"{packet_id}.json"
    return read_json(path)


def vault_sync_status(record: IntelligencePacketRecord, config: ControlTowerConfig) -> tuple[str, dict[str, Any] | None]:
    enabled, _folder = intelligence_vault_settings_from_obsidian(config.obsidian)
    if not enabled:
        return ("unknown", None)
    ev = load_export_evidence(config.runtime.state_root, record.packet_id)
    if ev is None:
        if record.status != "published":
            return ("unknown", None)
        return ("not_synced", None)
    if not ev.get("success"):
        return ("not_synced", ev)
    paths = ev.get("paths_written") or {}
    pkt = paths.get("packet")
    if not pkt or not Path(pkt).is_file():
        return ("not_synced", ev)
    return ("synced", ev)


def build_packet_bridge_context(record: IntelligencePacketRecord, config: ControlTowerConfig) -> dict[str, Any]:
    status, _ev = vault_sync_status(record, config)
    obsidian = config.obsidian
    planned = resolve_paths_for_packet(record, config)
    slug = intelligence_vault_project_slug(
        canonical_project_code=record.canonical_project_code or "",
        project_name=record.project_name or "",
    )
    _enabled, projects_folder = intelligence_vault_settings_from_obsidian(obsidian)
    vault_root = Path(obsidian.vault_root)
    code = (record.canonical_project_code or "").strip()
    pid = record.packet_id
    return {
        "status": status,
        "vault_root_display": str(vault_root),
        "projects_folder": projects_folder,
        "project_slug": slug,
        "canonical_project_code": code,
        "paths": {
            "packet_relative": relative_vault_path(vault_root, Path(planned["packet"])),
            "project_index_relative": relative_vault_path(vault_root, Path(planned["project_index"])),
            "portfolio_index_relative": relative_vault_path(vault_root, Path(planned["global_index"])),
        },
        "urls": {
            "packet_note": f"/vault/intelligence/packets/{pid}/note",
            "project_index": f"/vault/intelligence/projects/{code}/project-index" if code else "",
            "portfolio_index": "/vault/intelligence/portfolio-index",
        },
    }


def build_project_bridge_context(
    *,
    canonical_project_code: str,
    project_name: str,
    config: ControlTowerConfig,
) -> dict[str, Any]:
    obsidian = config.obsidian
    slug = intelligence_vault_project_slug(
        canonical_project_code=canonical_project_code,
        project_name=project_name,
    )
    enabled, projects_folder = intelligence_vault_settings_from_obsidian(obsidian)
    vault_root = Path(obsidian.vault_root)
    project_index = vault_root / projects_folder.strip().strip("/\\") / slug / "00 Project Index.md"
    portfolio_index = vault_root / projects_folder.strip().strip("/\\") / "_Index.md"
    code = (canonical_project_code or "").strip()
    return {
        "enabled": enabled,
        "vault_root_display": str(vault_root),
        "projects_folder": projects_folder,
        "project_slug": slug,
        "paths": {
            "project_root_relative": f"{projects_folder}/{slug}",
            "project_index_relative": relative_vault_path(vault_root, project_index),
            "portfolio_index_relative": relative_vault_path(vault_root, portfolio_index),
        },
        "urls": {
            "project_index": f"/vault/intelligence/projects/{code}/project-index" if code else "",
            "portfolio_index": "/vault/intelligence/portfolio-index",
        },
    }


def _is_under_vault(vault_root: Path, target: Path) -> bool:
    try:
        vault_root = vault_root.resolve()
        target = target.resolve()
    except OSError:
        return False
    try:
        target.relative_to(vault_root)
    except ValueError:
        return False
    return True


def read_vault_markdown_html(config: ControlTowerConfig, absolute_path: Path) -> tuple[bool, str]:
    vault_root = Path(config.obsidian.vault_root)
    if not _is_under_vault(vault_root, absolute_path):
        return (False, "")
    if not absolute_path.is_file():
        return (False, "")
    raw = absolute_path.read_text(encoding="utf-8")
    _fm, body = parse_markdown_frontmatter(raw)
    return (True, render_publish_markdown_preview(body))


def resolve_packet_vault_doc_path(config: ControlTowerConfig, packet_id: str, key: str) -> Path | None:
    record = load_packet(config.runtime.state_root, packet_id)
    if record is None:
        return None
    planned = resolve_paths_for_packet(record, config)
    path_key = key if key in planned else None
    if path_key is None:
        return None
    return Path(planned[path_key])


def resolve_project_index_path(config: ControlTowerConfig, project_code: str) -> Path | None:
    code = (project_code or "").strip()
    if not code:
        return None
    obsidian = config.obsidian
    slug = intelligence_vault_project_slug(canonical_project_code=code, project_name="")
    _enabled, projects_folder = intelligence_vault_settings_from_obsidian(obsidian)
    return Path(obsidian.vault_root) / projects_folder.strip().strip("/\\") / slug / "00 Project Index.md"


def resolve_portfolio_index_path(config: ControlTowerConfig) -> Path:
    obsidian = config.obsidian
    _enabled, projects_folder = intelligence_vault_settings_from_obsidian(obsidian)
    return Path(obsidian.vault_root) / projects_folder.strip().strip("/\\") / "_Index.md"

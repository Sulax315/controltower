from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from controltower.config import ControlTowerConfig
from controltower.render.markdown import parse_markdown_frontmatter
from controltower.services.build_info import current_build_info
from controltower.services.intelligence_packets import load_packet
from controltower.services.intelligence_vault_bridge import resolve_paths_for_packet
from controltower.services.runtime_state import ensure_runtime_layout, write_json

VERIFICATION_SCHEMA_VERSION = "2026-04-05"
LATEST_VERIFICATION_JSON = "intelligence_vault_verification_latest.json"


def _utc_now_iso_override(now_utc_iso: Callable[[], str] | None) -> str:
    if now_utc_iso:
        return now_utc_iso()
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _check_packet_markdown(text: str) -> bool:
    fm, body = parse_markdown_frontmatter(text)
    return fm.get("type") == "controltower_packet" and "## Executive Summary" in body and "## Finish Outlook" in body


def _check_project_index(text: str) -> bool:
    return "## Packet History" in text or "## Latest Packet" in text


def _check_portfolio_index(text: str) -> bool:
    return "Control Tower Portfolio" in text and "| Project |" in text


def verify_intelligence_vault_packets(
    config: ControlTowerConfig,
    packet_ids: list[str],
    *,
    now_utc_iso: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """
    Fail-closed verification of Obsidian intelligence vault artifacts for published packets.
    Returns a result dict including result PASS|FAIL; does not write files.
    """
    verified_at = _utc_now_iso_override(now_utc_iso)
    build_info = current_build_info()
    obsidian = config.obsidian
    projects_folder = getattr(obsidian, "intelligence_vault_projects_folder", "Projects")
    vault_root = str(Path(obsidian.vault_root))
    state_root = str(Path(config.runtime.state_root))

    def _fail(reason: str) -> dict[str, Any]:
        return {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "verified_at_utc": verified_at,
            "result": "FAIL",
            "failure_reason": reason,
            "git_commit": build_info.get("git_commit"),
            "git_commit_short": build_info.get("git_commit_short"),
            "environment": {
                "product_name": config.app.product_name,
                "environment": config.app.environment,
                "python_version": build_info.get("python_version"),
                "public_base_url": config.app.public_base_url,
            },
            "vault_root": vault_root,
            "projects_folder": projects_folder,
            "state_root": state_root,
            "intelligence_vault_enabled": getattr(obsidian, "intelligence_vault_enabled", True),
            "packet_ids_verified": list(packet_ids),
            "files_verified_present": [],
            "content_checks": {
                "packet_markdown": False,
                "project_index": False,
                "portfolio_index": False,
            },
        }

    if not packet_ids:
        return _fail("no_packet_ids")

    if not getattr(obsidian, "intelligence_vault_enabled", True):
        return _fail("intelligence_vault_disabled")

    all_files: list[str] = []

    for raw_pid in packet_ids:
        pid = raw_pid.strip()
        if not pid:
            return _fail("empty_packet_id")

        record = load_packet(config.runtime.state_root, pid)
        if record is None:
            return _fail(f"packet_not_found:{pid}")
        if record.status != "published":
            return _fail(f"packet_not_published:{pid}")

        evidence_path = Path(config.runtime.state_root) / "obsidian_exports" / f"{pid}.json"
        if not evidence_path.is_file():
            return _fail(f"missing_export_evidence:{evidence_path}")
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return _fail(f"evidence_json_invalid:{pid}:{exc}")

        if not evidence.get("success"):
            return _fail(f"export_evidence_not_success:{pid}:{evidence.get('error')}")

        paths_written: dict[str, str] = dict(evidence.get("paths_written") or {})
        planned = resolve_paths_for_packet(record, config)
        for logical in ("packet", "project_index", "risks", "actions", "timeline", "global_index"):
            p = paths_written.get(logical) or planned.get(logical)
            if not p:
                return _fail(f"missing_path_key:{logical}:{pid}")
            path = Path(p)
            if not path.is_file():
                return _fail(f"missing_file:{path}")
            all_files.append(str(path))

        pkt_path = Path(paths_written.get("packet") or planned["packet"])
        pkt_text = pkt_path.read_text(encoding="utf-8")
        if not _check_packet_markdown(pkt_text):
            out = _fail(f"packet_markdown_content_check_failed:{pid}")
            out["files_verified_present"] = sorted(set(all_files))
            return out

        idx_path = Path(paths_written.get("project_index") or planned["project_index"])
        idx_text = idx_path.read_text(encoding="utf-8")
        if not _check_project_index(idx_text):
            out = _fail(f"project_index_content_check_failed:{pid}")
            out["files_verified_present"] = sorted(set(all_files))
            return out

        gpath = Path(paths_written.get("global_index") or planned["global_index"])
        gtext = gpath.read_text(encoding="utf-8")
        if not _check_portfolio_index(gtext):
            out = _fail(f"portfolio_index_content_check_failed:{pid}")
            out["files_verified_present"] = sorted(set(all_files))
            return out

    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "verified_at_utc": verified_at,
        "result": "PASS",
        "failure_reason": None,
        "git_commit": build_info.get("git_commit"),
        "git_commit_short": build_info.get("git_commit_short"),
        "environment": {
            "product_name": config.app.product_name,
            "environment": config.app.environment,
            "python_version": build_info.get("python_version"),
            "public_base_url": config.app.public_base_url,
        },
        "vault_root": vault_root,
        "projects_folder": projects_folder,
        "state_root": state_root,
        "intelligence_vault_enabled": getattr(obsidian, "intelligence_vault_enabled", True),
        "packet_ids_verified": [p.strip() for p in packet_ids if p.strip()],
        "files_verified_present": sorted(set(all_files)),
        "content_checks": {
            "packet_markdown": True,
            "project_index": True,
            "portfolio_index": True,
        },
    }


def write_intelligence_vault_verification_artifact(
    state_root: Path,
    payload: dict[str, Any],
    *,
    write_history: bool = True,
) -> tuple[Path, Path | None]:
    """
    Persist verification JSON under state_root/release/ only when result is PASS.
    """
    if payload.get("result") != "PASS":
        raise ValueError("verification artifact is only written for PASS results")
    layout = ensure_runtime_layout(Path(state_root))
    release_root = layout["release_root"]
    latest_path = release_root / LATEST_VERIFICATION_JSON
    write_json(latest_path, payload)
    hist_path: Path | None = None
    if write_history:
        stamp = str(payload.get("verified_at_utc") or "unknown").replace(":", "-")
        hist_path = release_root / f"intelligence_vault_verification_{stamp}.json"
        write_json(hist_path, payload)
    return latest_path, hist_path


def format_verification_markdown_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Intelligence vault verification",
        "",
        f"- **Result:** {payload.get('result')}",
        f"- **Verified at (UTC):** {payload.get('verified_at_utc')}",
        f"- **Git commit:** {payload.get('git_commit')}",
        f"- **Vault root:** `{payload.get('vault_root')}`",
        f"- **Projects folder:** `{payload.get('projects_folder')}`",
        "",
        "## Content checks",
        "",
    ]
    checks = payload.get("content_checks") or {}
    for k, v in checks.items():
        lines.append(f"- `{k}`: {v}")
    lines.extend(["", "## Files verified", ""])
    for fpath in payload.get("files_verified_present") or []:
        lines.append(f"- `{fpath}`")
    if payload.get("failure_reason"):
        lines.extend(["", "## Failure", "", str(payload["failure_reason"])])
    return "\n".join(lines) + "\n"

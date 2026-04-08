from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .export_artifacts import (
    FILENAME_BUNDLE,
    FILENAME_COMMAND_BRIEF,
    FILENAME_DRIVER_ANALYSIS,
    FILENAME_ENGINE_SNAPSHOT,
    FILENAME_EXPLORATION,
    FILENAME_LOGIC_GRAPH,
    FILENAME_MANIFEST,
    FILENAME_NORMALIZED_INTAKE,
    compute_sha256_bytes,
)
from .drivers import DRIVER_ANALYSIS_SCHEMA_VERSION
from .graph import LOGIC_GRAPH_SCHEMA_VERSION
from .normalized_intake import NORMALIZED_INTAKE_SCHEMA_VERSION
from .output_contracts import CommandBriefContract, EngineSnapshot, ExplorationContract, ScheduleIntelligenceBundle

REQUIRED_BUNDLE_TOP_LEVEL_KEYS = ("engine_snapshot", "command_brief", "exploration")
REQUIRED_COMMAND_BRIEF_KEYS = ("finish", "driver", "risks", "delta", "action")
REQUIRED_ENGINE_SNAPSHOT_KEYS = ("graph_summary", "logic_quality", "command_brief_lines")
REQUIRED_EXPLORATION_KEYS = (
    "immediate_predecessors",
    "immediate_successors",
    "upstream_closure",
    "downstream_closure",
    "shortest_path",
    "all_simple_paths",
    "shared_ancestors",
    "shared_descendants",
    "driver_structure",
    "impact_span",
)
REQUIRED_EXPORT_FILES = (
    FILENAME_BUNDLE,
    FILENAME_COMMAND_BRIEF,
    FILENAME_ENGINE_SNAPSHOT,
    FILENAME_EXPLORATION,
    FILENAME_NORMALIZED_INTAKE,
    FILENAME_LOGIC_GRAPH,
    FILENAME_DRIVER_ANALYSIS,
    FILENAME_MANIFEST,
)


class BundleValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ExportValidationResult:
    ok: bool
    errors: tuple[str, ...]


def load_publish_bundle(bundle_path: str | None) -> ScheduleIntelligenceBundle:
    path = _resolve_bundle_path(bundle_path)
    raw = _load_json_dict(path)
    _validate_bundle_json(raw)
    return _bundle_from_jsonable(raw)


def validate_export_artifact_set(export_dir: Path) -> ExportValidationResult:
    errors: list[str] = []
    target_dir = export_dir.expanduser().resolve()
    existing = {p.name: p for p in target_dir.glob("*") if p.is_file()}

    for required in REQUIRED_EXPORT_FILES:
        if required not in existing:
            errors.append(f"missing artifact file: {required}")

    manifest_path = existing.get(FILENAME_MANIFEST)
    if manifest_path is None:
        return ExportValidationResult(ok=False, errors=tuple(errors))

    try:
        manifest = _load_json_dict(manifest_path)
    except BundleValidationError as exc:
        errors.append(f"invalid manifest: {exc}")
        return ExportValidationResult(ok=False, errors=tuple(errors))

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("invalid manifest: artifacts must be a list")
        return ExportValidationResult(ok=False, errors=tuple(errors))

    manifest_names: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            errors.append("invalid manifest: artifact entry must be an object")
            continue
        name = item.get("filename")
        digest = item.get("sha256")
        byte_count = item.get("byte_count")
        if not isinstance(name, str) or not name:
            errors.append("invalid manifest: artifact filename missing")
            continue
        manifest_names.add(name)
        path = existing.get(name)
        if path is None:
            errors.append(f"manifest references missing file: {name}")
            continue
        file_bytes = path.read_bytes()
        actual_digest = compute_sha256_bytes(file_bytes)
        if digest != actual_digest:
            errors.append(f"hash mismatch for {name}")
        if byte_count != len(file_bytes):
            errors.append(f"byte_count mismatch for {name}")

    expected_manifest_names = {
        FILENAME_BUNDLE,
        FILENAME_COMMAND_BRIEF,
        FILENAME_ENGINE_SNAPSHOT,
        FILENAME_EXPLORATION,
        FILENAME_NORMALIZED_INTAKE,
        FILENAME_LOGIC_GRAPH,
        FILENAME_DRIVER_ANALYSIS,
    }
    if manifest_names != expected_manifest_names:
        errors.append("manifest artifacts do not match required export files")

    norm_path = existing.get(FILENAME_NORMALIZED_INTAKE)
    if norm_path is not None and not errors:
        try:
            norm_raw = _load_json_dict(norm_path)
        except BundleValidationError as exc:
            errors.append(f"invalid normalized_intake.json: {exc}")
        else:
            if norm_raw.get("schema_version") != NORMALIZED_INTAKE_SCHEMA_VERSION:
                errors.append("normalized_intake.json: unexpected schema_version")
            acts = norm_raw.get("activities")
            if not isinstance(acts, list):
                errors.append("normalized_intake.json: activities must be a list")

    graph_path = existing.get(FILENAME_LOGIC_GRAPH)
    if graph_path is not None and not errors:
        try:
            graph_raw = _load_json_dict(graph_path)
        except BundleValidationError as exc:
            errors.append(f"invalid logic_graph.json: {exc}")
        else:
            if graph_raw.get("schema_version") != LOGIC_GRAPH_SCHEMA_VERSION:
                errors.append("logic_graph.json: unexpected schema_version")
            if not isinstance(graph_raw.get("nodes"), list):
                errors.append("logic_graph.json: nodes must be a list")
            if not isinstance(graph_raw.get("edges"), list):
                errors.append("logic_graph.json: edges must be a list")
            if not isinstance(graph_raw.get("finish_candidates"), list):
                errors.append("logic_graph.json: finish_candidates must be a list")
            if not isinstance(graph_raw.get("orphan_chains"), list):
                errors.append("logic_graph.json: orphan_chains must be a list")

    driver_path = existing.get(FILENAME_DRIVER_ANALYSIS)
    if driver_path is not None and not errors:
        try:
            driver_raw = _load_json_dict(driver_path)
        except BundleValidationError as exc:
            errors.append(f"invalid driver_analysis.json: {exc}")
        else:
            if driver_raw.get("schema_version") != DRIVER_ANALYSIS_SCHEMA_VERSION:
                errors.append("driver_analysis.json: unexpected schema_version")
            finish = driver_raw.get("authoritative_finish_target")
            if not isinstance(finish, dict):
                errors.append("driver_analysis.json: authoritative_finish_target must be an object")
            driver_ids = driver_raw.get("driver_path")
            if not isinstance(driver_ids, list):
                errors.append("driver_analysis.json: driver_path must be a list")
            acts = driver_raw.get("driver_activities")
            if not isinstance(acts, list):
                errors.append("driver_analysis.json: driver_activities must be a list")

    return ExportValidationResult(ok=(len(errors) == 0), errors=tuple(errors))


def _resolve_bundle_path(bundle_path: str | None) -> Path:
    value = (bundle_path or "").strip()
    if not value:
        raise BundleValidationError("bundle query parameter is required.")
    try:
        path = Path(value).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise BundleValidationError("bundle path is invalid.") from exc
    if not path.exists() or not path.is_file():
        raise BundleValidationError("bundle path does not exist.")
    return path


def _load_json_dict(path: Path) -> dict[str, Any]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise BundleValidationError("bundle file must be valid UTF-8 JSON.") from exc
    except OSError as exc:
        raise BundleValidationError("bundle file could not be read.") from exc
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise BundleValidationError("bundle file contains invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise BundleValidationError("bundle payload must be a JSON object.")
    return payload


def _validate_bundle_json(raw: dict[str, Any]) -> None:
    for key in REQUIRED_BUNDLE_TOP_LEVEL_KEYS:
        if key not in raw:
            raise BundleValidationError(f"incomplete bundle: missing {key}.")
        if not isinstance(raw[key], dict):
            raise BundleValidationError(f"incomplete bundle: {key} must be an object.")

    command_brief = raw["command_brief"]
    for key in REQUIRED_COMMAND_BRIEF_KEYS:
        value = command_brief.get(key)
        if not isinstance(value, str) or not value.strip():
            raise BundleValidationError(f"incomplete bundle: command_brief.{key} is required.")

    engine_snapshot = raw["engine_snapshot"]
    for key in REQUIRED_ENGINE_SNAPSHOT_KEYS:
        if key not in engine_snapshot:
            raise BundleValidationError(f"incomplete bundle: missing engine_snapshot.{key}.")
    if not isinstance(engine_snapshot["graph_summary"], dict):
        raise BundleValidationError("incomplete bundle: engine_snapshot.graph_summary must be an object.")
    if not isinstance(engine_snapshot["logic_quality"], dict):
        raise BundleValidationError("incomplete bundle: engine_snapshot.logic_quality must be an object.")
    lines = engine_snapshot["command_brief_lines"]
    if not isinstance(lines, list | tuple) or len(lines) != 5 or any(not isinstance(x, str) for x in lines):
        raise BundleValidationError("incomplete bundle: engine_snapshot.command_brief_lines must contain 5 strings.")

    exploration = raw["exploration"]
    for key in REQUIRED_EXPLORATION_KEYS:
        if key not in exploration:
            raise BundleValidationError(f"incomplete bundle: missing exploration.{key}.")


def _bundle_from_jsonable(raw: dict[str, Any]) -> ScheduleIntelligenceBundle:
    es = raw.get("engine_snapshot", {})
    cb = raw.get("command_brief", {})
    ex = raw.get("exploration", {})
    return ScheduleIntelligenceBundle(
        engine_snapshot=EngineSnapshot(
            graph_summary=dict(es.get("graph_summary") or {}),
            logic_quality=dict(es.get("logic_quality") or {}),
            top_driver=dict(es["top_driver"]) if es.get("top_driver") is not None else None,
            risks=tuple(dict(x) for x in (es.get("risks") or [])),
            delta_summary=dict(es["delta_summary"]) if es.get("delta_summary") is not None else None,
            command_brief_lines=tuple(es.get("command_brief_lines") or ("", "", "", "", "")),
        ),
        command_brief=CommandBriefContract(
            finish=str(cb.get("finish", "")),
            driver=str(cb.get("driver", "")),
            risks=str(cb.get("risks", "")),
            delta=str(cb.get("delta", "")),
            action=str(cb.get("action", "")),
        ),
        exploration=ExplorationContract(
            immediate_predecessors=tuple(ex.get("immediate_predecessors") or ()),
            immediate_successors=tuple(ex.get("immediate_successors") or ()),
            upstream_closure=tuple(ex.get("upstream_closure") or ()),
            downstream_closure=tuple(ex.get("downstream_closure") or ()),
            shortest_path=tuple(ex.get("shortest_path") or ()),
            all_simple_paths=tuple(tuple(p) for p in (ex.get("all_simple_paths") or ())),
            shared_ancestors=tuple(ex.get("shared_ancestors") or ()),
            shared_descendants=tuple(ex.get("shared_descendants") or ()),
            driver_structure=ex.get("driver_structure"),
            impact_span=ex.get("impact_span"),
        ),
    )

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .output_contracts import CommandBriefContract, EngineSnapshot, ExplorationContract, ScheduleIntelligenceBundle

JSON_INDENT = 2
JSON_SORT_KEYS = True
MANIFEST_SCHEMA_VERSION = "1.0.0"
DETERMINISTIC_MODE_LABEL = "deterministic_contract_export_v1"
EXPORT_SCOPE = "schedule_intelligence"
SOURCE_COMPONENTS = (
    "output_contracts.CommandBriefContract",
    "output_contracts.EngineSnapshot",
    "output_contracts.ExplorationContract",
    "output_contracts.ScheduleIntelligenceBundle",
    "normalized_intake.build_normalized_intake_payload",
)

FILENAME_BUNDLE = "intelligence_bundle.json"
FILENAME_COMMAND_BRIEF = "command_brief.json"
FILENAME_ENGINE_SNAPSHOT = "engine_snapshot.json"
FILENAME_EXPLORATION = "exploration.json"
FILENAME_NORMALIZED_INTAKE = "normalized_intake.json"
FILENAME_MANIFEST = "manifest.json"


@dataclass(frozen=True)
class ExportedArtifact:
    filename: str
    sha256: str
    byte_count: int
    artifact_type: str


@dataclass(frozen=True)
class ExportManifest:
    schema_version: str
    export_scope: str
    deterministic_mode: str
    source_components: tuple[str, ...]
    artifacts: tuple[ExportedArtifact, ...]
    bundle_present: bool
    command_brief_present: bool
    engine_snapshot_present: bool
    exploration_present: bool
    normalized_intake_present: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonable_dict(self) -> dict[str, Any]:
        return to_jsonable_dict(self.to_dict())


def to_jsonable_dict(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {k: to_jsonable_dict(payload[k]) for k in sorted(payload)}
    if isinstance(payload, tuple):
        return [to_jsonable_dict(x) for x in payload]
    if isinstance(payload, list):
        return [to_jsonable_dict(x) for x in payload]
    return payload


def compute_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_json_bytes(payload: dict[str, Any]) -> bytes:
    text = json.dumps(payload, indent=JSON_INDENT, sort_keys=JSON_SORT_KEYS, ensure_ascii=True) + "\n"
    return text.encode("utf-8")


def write_json_artifact(path: Path, payload: dict[str, Any]) -> ExportedArtifact:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _stable_json_bytes(payload)
    path.write_bytes(data)
    return ExportedArtifact(
        filename=path.name,
        sha256=compute_sha256_bytes(data),
        byte_count=len(data),
        artifact_type=path.stem,
    )


def export_directory_file_map(export_dir: Path) -> tuple[tuple[str, str, int], ...]:
    out: list[tuple[str, str, int]] = []
    for p in sorted(export_dir.glob("*")):
        if not p.is_file():
            continue
        b = p.read_bytes()
        out.append((p.name, compute_sha256_bytes(b), len(b)))
    return tuple(out)


def export_command_brief_contract(export_dir: Path, contract: CommandBriefContract) -> ExportedArtifact:
    return write_json_artifact(export_dir / FILENAME_COMMAND_BRIEF, contract.to_jsonable_dict())


def export_engine_snapshot(export_dir: Path, snapshot: EngineSnapshot) -> ExportedArtifact:
    return write_json_artifact(export_dir / FILENAME_ENGINE_SNAPSHOT, snapshot.to_jsonable_dict())


def export_exploration_contract(export_dir: Path, exploration: ExplorationContract) -> ExportedArtifact:
    return write_json_artifact(export_dir / FILENAME_EXPLORATION, exploration.to_jsonable_dict())


def export_schedule_intelligence_bundle(export_dir: Path, bundle: ScheduleIntelligenceBundle) -> ExportedArtifact:
    return write_json_artifact(export_dir / FILENAME_BUNDLE, bundle.to_jsonable_dict())


def build_export_manifest(artifacts: tuple[ExportedArtifact, ...]) -> ExportManifest:
    names = frozenset(a.filename for a in artifacts)
    return ExportManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        export_scope=EXPORT_SCOPE,
        deterministic_mode=DETERMINISTIC_MODE_LABEL,
        source_components=SOURCE_COMPONENTS,
        artifacts=tuple(sorted(artifacts, key=lambda a: a.filename)),
        bundle_present=FILENAME_BUNDLE in names,
        command_brief_present=FILENAME_COMMAND_BRIEF in names,
        engine_snapshot_present=FILENAME_ENGINE_SNAPSHOT in names,
        exploration_present=FILENAME_EXPLORATION in names,
        normalized_intake_present=FILENAME_NORMALIZED_INTAKE in names,
    )


def export_normalized_intake_document(export_dir: Path, payload: dict[str, Any]) -> ExportedArtifact:
    return write_json_artifact(export_dir / FILENAME_NORMALIZED_INTAKE, payload)


def export_deterministic_artifact_set(
    export_dir: Path,
    *,
    bundle: ScheduleIntelligenceBundle,
    normalized_intake: dict[str, Any],
) -> tuple[tuple[ExportedArtifact, ...], ExportManifest]:
    export_dir.mkdir(parents=True, exist_ok=True)
    artifacts = (
        export_schedule_intelligence_bundle(export_dir, bundle),
        export_command_brief_contract(export_dir, bundle.command_brief),
        export_engine_snapshot(export_dir, bundle.engine_snapshot),
        export_exploration_contract(export_dir, bundle.exploration),
        export_normalized_intake_document(export_dir, normalized_intake),
    )
    manifest = build_export_manifest(artifacts)
    manifest_artifact = write_json_artifact(export_dir / FILENAME_MANIFEST, manifest.to_jsonable_dict())
    ordered = (
        next(a for a in artifacts if a.filename == FILENAME_BUNDLE),
        next(a for a in artifacts if a.filename == FILENAME_COMMAND_BRIEF),
        next(a for a in artifacts if a.filename == FILENAME_ENGINE_SNAPSHOT),
        next(a for a in artifacts if a.filename == FILENAME_EXPLORATION),
        next(a for a in artifacts if a.filename == FILENAME_NORMALIZED_INTAKE),
        manifest_artifact,
    )
    return ordered, manifest

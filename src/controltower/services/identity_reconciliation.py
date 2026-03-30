from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from controltower.domain.models import ProjectIdentity


def slugify_code(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_").upper()
    return slug or "UNKNOWN_PROJECT"


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", value).strip().upper()
    return re.sub(r"\s+", " ", cleaned)


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


class RegistryProject(BaseModel):
    canonical_project_id: str
    canonical_project_code: str | None = None
    project_name: str
    project_code_aliases: list[str] = Field(default_factory=list)
    source_aliases: dict[str, list[str]] = Field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict) -> "RegistryProject":
        raw_canonical_project_id = str(payload.get("canonical_project_id") or payload.get("canonical_project_code") or "").strip()
        if not raw_canonical_project_id:
            raise ValueError("Registry project entry is missing canonical_project_id or canonical_project_code.")
        project_name = str(payload.get("project_name") or "").strip()
        if not project_name:
            raise ValueError(f"Registry project '{raw_canonical_project_id}' is missing project_name.")
        canonical_project_id = raw_canonical_project_id
        canonical_project_code = str(payload.get("canonical_project_code") or canonical_project_id)
        source_aliases = {
            str(source): _as_list(values)
            for source, values in dict(payload.get("source_aliases") or {}).items()
        }
        project_code_aliases = _as_list(payload.get("project_code_aliases"))

        legacy_aliases = payload.get("aliases")
        if isinstance(legacy_aliases, dict):
            for source, alias in legacy_aliases.items():
                source_aliases.setdefault(str(source), []).extend(_as_list(alias))
                project_code_aliases.extend(_as_list(alias))
        elif legacy_aliases is not None:
            project_code_aliases.extend(_as_list(legacy_aliases))

        return cls(
            canonical_project_id=slugify_code(canonical_project_id),
            canonical_project_code=slugify_code(canonical_project_code),
            project_name=project_name,
            project_code_aliases=_dedupe(
                [canonical_project_id, canonical_project_code, project_name, *project_code_aliases]
            ),
            source_aliases={source: _dedupe(values) for source, values in source_aliases.items()},
        )

    def alias_values(self, source_system: str | None = None) -> list[str]:
        aliases = list(self.project_code_aliases)
        if source_system is not None:
            aliases.extend(self.source_aliases.get(source_system, []))
        else:
            for values in self.source_aliases.values():
                aliases.extend(values)
        return _dedupe(aliases)


class RegistryDocument(BaseModel):
    manual_overrides: dict[str, dict[str, str]] = Field(default_factory=dict)
    projects: list[RegistryProject] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None) -> "RegistryDocument":
        if path is None:
            return cls()
        if not path.exists():
            raise FileNotFoundError(f"Control Tower identity registry is missing: {path}")
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Control Tower identity registry is malformed YAML: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Control Tower identity registry root must be a mapping: {path}")
        raw_projects = payload.get("projects") or []
        if not isinstance(raw_projects, list):
            raise ValueError(f"Control Tower identity registry 'projects' must be a list: {path}")
        projects: list[RegistryProject] = []
        for index, item in enumerate(raw_projects):
            if not isinstance(item, dict):
                raise ValueError(f"Control Tower identity registry project entry #{index + 1} must be a mapping: {path}")
            try:
                projects.append(RegistryProject.from_payload(item))
            except ValueError as exc:
                raise ValueError(f"{exc} Registry path: {path}") from exc
        raw_overrides = payload.get("manual_overrides") or {}
        if not isinstance(raw_overrides, dict):
            raise ValueError(f"Control Tower identity registry 'manual_overrides' must be a mapping: {path}")
        overrides: dict[str, dict[str, str]] = {}
        for source, values in raw_overrides.items():
            if not isinstance(values, dict):
                raise ValueError(f"Control Tower identity registry manual overrides for '{source}' must be a mapping: {path}")
            overrides[str(source)] = {
                _normalize(raw_key): slugify_code(str(canonical_id))
                for raw_key, canonical_id in dict(values or {}).items()
                if _normalize(str(raw_key))
            }
        _validate_registry(projects, overrides, path)
        return cls(manual_overrides=overrides, projects=projects)


@dataclass(frozen=True)
class MatchResult:
    project: RegistryProject
    method: str
    matched_on: str


class IdentityReconciliationService:
    def __init__(self, registry: RegistryDocument | None = None) -> None:
        self.registry = registry or RegistryDocument()
        self._project_index = {project.canonical_project_id: project for project in self.registry.projects}

    @classmethod
    def load(cls, path: Path | None) -> "IdentityReconciliationService":
        return cls(RegistryDocument.load(path))

    def resolve(self, source_system: str, source_key: str, fallback_name: str | None = None) -> ProjectIdentity:
        normalized_candidates = _dedupe([_normalize(source_key), _normalize(fallback_name)])
        match = (
            self._manual_override(source_system, normalized_candidates)
            or self._raw_match(source_system, normalized_candidates)
            or self._fuzzy_match(source_system, normalized_candidates)
        )
        if match is not None:
            aliases = match.project.alias_values(source_system)
            return ProjectIdentity(
                canonical_project_id=match.project.canonical_project_id,
                canonical_project_code=match.project.canonical_project_code or match.project.canonical_project_id,
                project_name=match.project.project_name,
                source_keys=[f"{source_system}:{source_key.strip()}"],
                aliases=aliases,
                match_method=match.method,  # type: ignore[arg-type]
                matched_on=match.matched_on,
            )
        canonical = slugify_code(source_key or fallback_name or "UNKNOWN_PROJECT")
        project_name = (fallback_name or source_key or canonical).strip()
        return ProjectIdentity(
            canonical_project_id=canonical,
            canonical_project_code=canonical,
            project_name=project_name,
            source_keys=[f"{source_system}:{source_key.strip()}"],
            aliases=_dedupe([source_key, fallback_name, canonical]),
            match_method="raw_match",
            matched_on=source_key.strip(),
        )

    def _manual_override(self, source_system: str, candidates: list[str]) -> MatchResult | None:
        overrides = self.registry.manual_overrides.get(source_system, {})
        for candidate in candidates:
            canonical_id = overrides.get(candidate)
            if canonical_id and canonical_id in self._project_index:
                project = self._project_index[canonical_id]
                return MatchResult(project=project, method="manual_override", matched_on=candidate)
        return None

    def _raw_match(self, source_system: str, candidates: list[str]) -> MatchResult | None:
        for candidate in candidates:
            if not candidate:
                continue
            for project in sorted(self.registry.projects, key=lambda item: item.canonical_project_id):
                alias_pool = [_normalize(item) for item in project.alias_values(source_system)]
                if candidate in alias_pool:
                    return MatchResult(project=project, method="raw_match", matched_on=candidate)
        return None

    def _fuzzy_match(self, source_system: str, candidates: list[str]) -> MatchResult | None:
        best: tuple[float, RegistryProject, str] | None = None
        for candidate in candidates:
            if not candidate or len(candidate) < 4:
                continue
            for project in sorted(self.registry.projects, key=lambda item: item.canonical_project_id):
                for alias in project.alias_values():
                    normalized_alias = _normalize(alias)
                    if not normalized_alias:
                        continue
                    score = SequenceMatcher(None, candidate, normalized_alias).ratio()
                    if alias in project.source_aliases.get(source_system, []):
                        score += 0.02
                    if best is None or score > best[0] or (score == best[0] and project.canonical_project_id < best[1].canonical_project_id):
                        best = (score, project, alias)
        if best and best[0] >= 0.84:
            return MatchResult(project=best[1], method="fuzzy_match", matched_on=best[2])
        return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def _validate_registry(projects: list[RegistryProject], overrides: dict[str, dict[str, str]], path: Path) -> None:
    seen_projects: dict[str, str] = {}
    seen_aliases: dict[tuple[str, str], str] = {}

    for project in projects:
        if project.canonical_project_id in seen_projects:
            raise ValueError(
                f"Control Tower identity registry duplicates canonical_project_id '{project.canonical_project_id}' in {path}"
            )
        seen_projects[project.canonical_project_id] = project.project_name

        for alias in project.project_code_aliases:
            _claim_alias(seen_aliases, ("project_code_aliases", _normalize(alias)), project, path)
        for source_system, aliases in project.source_aliases.items():
            source_name = str(source_system).strip()
            if not source_name:
                raise ValueError(f"Control Tower identity registry has a blank source_aliases key in {path}")
            for alias in aliases:
                _claim_alias(seen_aliases, (f"source_aliases:{source_name}", _normalize(alias)), project, path)

    for source_system, source_overrides in overrides.items():
        for canonical_id in source_overrides.values():
            if canonical_id not in seen_projects:
                raise ValueError(
                    f"Control Tower identity registry override for '{source_system}' points to unknown canonical id '{canonical_id}' in {path}"
                )


def _claim_alias(
    seen_aliases: dict[tuple[str, str], str],
    key: tuple[str, str],
    project: RegistryProject,
    path: Path,
) -> None:
    scope, normalized_alias = key
    if not normalized_alias:
        return
    existing = seen_aliases.get(key)
    if existing is not None and existing != project.canonical_project_id:
        raise ValueError(
            "Control Tower identity registry contains an ambiguous alias "
            f"'{normalized_alias}' in scope '{scope}' for both '{existing}' and '{project.canonical_project_id}' in {path}"
        )
    seen_aliases[key] = project.canonical_project_id

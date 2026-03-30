from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from controltower.config import ControlTowerConfig
from controltower.domain.models import ReviewDecisionMode, ReviewPolicyRiskLevel, utc_now_iso


LOW_RISK_DOC_EXTENSIONS = {".md", ".txt", ".rst", ".adoc"}
LOW_RISK_UI_COPY_EXTENSIONS = {".html", ".htm", ".css", ".md", ".txt"}
SAFE_FRONTEND_TEXT_PATHS = (
    "src/controltower/api/templates/",
    "src/controltower/api/static/",
    "src/controltower/render/templates/",
)
RISKY_FILE_MARKERS = (
    "auth",
    "security",
    "session",
    "token",
    "csrf",
    "orchestration",
    "review",
    "approval",
    "controltower/api/app.py",
    "nginx",
    "tls",
    "domain",
    "router",
    "routing",
    "gateway",
    "infra/",
    "config/",
    ".env",
    "docker",
    "k8s",
    "kubernetes",
    "migrations",
    "migration",
    "schema",
    "model",
    "api/",
    "service",
)


@dataclass(slots=True)
class PolicyEvaluationInput:
    workspace: str
    title: str
    summary: str
    proposed_next_prompt: str
    raw_output_excerpt: list[str] = field(default_factory=list)
    artifact_paths: list[Path | str] = field(default_factory=list)
    changed_files: list[str] | None = None
    tests_passed: bool | None = None
    acceptance_passed: bool | None = None


@dataclass(slots=True)
class PolicyEvaluation:
    risk_level: ReviewPolicyRiskLevel
    decision_mode: ReviewDecisionMode
    decision_reasons: list[str]
    policy_version: str
    policy_evaluated_at: str
    auto_approved_at: str | None = None
    escalated_at: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


def evaluate_review_policy(config: ControlTowerConfig, policy_input: PolicyEvaluationInput) -> PolicyEvaluation:
    extracted = _extract_artifact_evidence(policy_input.artifact_paths)
    changed_files = [str(item) for item in (policy_input.changed_files or extracted.get("changed_files") or []) if str(item).strip()]
    artifact_names = [Path(item).name for item in policy_input.artifact_paths]
    tests_passed = _coalesce_bool(policy_input.tests_passed, extracted.get("tests_passed"))
    acceptance_passed = _coalesce_bool(policy_input.acceptance_passed, extracted.get("acceptance_passed"))

    combined_text = "\n".join(
        [
            policy_input.workspace,
            policy_input.title,
            policy_input.summary,
            policy_input.proposed_next_prompt,
            *policy_input.raw_output_excerpt,
            *artifact_names,
        ]
    ).lower()
    changed_files_lower = [item.replace("\\", "/").lower() for item in changed_files]
    artifact_names_lower = [item.lower() for item in artifact_names]
    reasons: list[str] = []

    scope = _evaluate_scope(
        combined_text=combined_text,
        changed_files=changed_files_lower,
        artifact_names=artifact_names_lower,
        tests_passed=tests_passed,
        acceptance_passed=acceptance_passed,
    )
    reasons.extend(scope["reasons"])

    risk_level: ReviewPolicyRiskLevel
    decision_mode: ReviewDecisionMode

    if scope["critical"]:
        risk_level = "critical"
        decision_mode = "escalate"
    elif scope["high"]:
        risk_level = "high"
        decision_mode = "escalate"
    elif scope["low"]:
        risk_level = "low"
        decision_mode = "auto_approve"
    else:
        risk_level = "medium"
        decision_mode = "manual_review"

    if not scope["evidence_sufficient"] and decision_mode == "auto_approve":
        decision_mode = "manual_review"
        risk_level = "medium"
        reasons.append("Low-risk autonomy was denied because the available evidence was insufficient.")

    if not config.autonomy.enabled:
        if decision_mode != "manual_review":
            reasons.append("Selective autonomy is disabled by configuration, so the run remains in manual review.")
        decision_mode = "manual_review"
    elif decision_mode == "auto_approve" and not config.autonomy.auto_approve_low_risk:
        decision_mode = "manual_review"
        reasons.append("Low-risk auto-approval is disabled by configuration.")
    elif decision_mode == "escalate" and not config.autonomy.escalate_high_risk:
        decision_mode = "manual_review"
        reasons.append("High-risk escalation is disabled by configuration, so the run remains in manual review.")

    evaluated_at = utc_now_iso()
    auto_approved_at = evaluated_at if decision_mode == "auto_approve" else None
    escalated_at = evaluated_at if decision_mode == "escalate" else None
    return PolicyEvaluation(
        risk_level=risk_level,
        decision_mode=decision_mode,
        decision_reasons=_dedupe_reasons(reasons),
        policy_version=config.autonomy.policy_version,
        policy_evaluated_at=evaluated_at,
        auto_approved_at=auto_approved_at,
        escalated_at=escalated_at,
        evidence={
            "changed_files": changed_files,
            "artifact_names": artifact_names,
            "tests_passed": tests_passed,
            "acceptance_passed": acceptance_passed,
            "artifact_evidence": extracted,
        },
    )


def _evaluate_scope(
    *,
    combined_text: str,
    changed_files: list[str],
    artifact_names: list[str],
    tests_passed: bool | None,
    acceptance_passed: bool | None,
) -> dict[str, Any]:
    reasons: list[str] = []
    changed_file_set = set(changed_files)
    risky_keywords = {
        "auth_security": _contains_any(combined_text, ("auth", "authentication", "authorize", "security", "session", "csrf", "token", "permission")),
        "infra_routing": _contains_any(combined_text, ("nginx", "tls", "ssl", "domain", "routing", "router", "reverse proxy", "ingress")),
        "deploy_restart": _contains_any(combined_text, ("deploy", "deployment", "restart", "release to prod", "production deploy", "production restart")),
        "destructive": _contains_any(combined_text, ("delete", "drop", "destroy", "truncate", "wipe", "remove production data", "destructive")),
        "migration": _contains_any(combined_text, ("migration", "migrate", "alembic", "backfill", "schema change")),
        "config_env": _contains_any(combined_text, ("config", "configuration", ".env", "environment variable", "secret", "prod config")),
        "api_schema_model": _contains_any(combined_text, ("api", "service", "schema", "model", "contract", "endpoint")),
        "control_plane": _contains_any(combined_text, ("approval", "review control plane", "orchestration", "control-plane", "trigger emission", "review queue")),
        "release_readiness": _contains_any(combined_text, ("release readiness", "release gate", "ready for live operations")),
        "product_behavior": _contains_any(combined_text, ("behavior", "user flow", "operator meaning", "template meaning", "rendering change", "rendering", "template")),
        "read_only": _contains_any(combined_text, ("read-only", "analysis only", "report generation", "investigation", "inspection", "diagnostics snapshot", "no mutation")),
        "docs": _contains_any(combined_text, ("documentation", "docs", "readme", "operator guide", "runbook")),
        "continuity_obsidian": _contains_any(combined_text, ("continuity", "obsidian", "export history", "history artifact")),
        "local_only": _contains_any(combined_text, ("local-only", "non-prod", "cursor demo", "demo only", "workflow task", "dry run")),
        "ui_copy": _contains_any(combined_text, ("copy change", "text-only", "label update", "wording", "copy tweak", "headline copy")),
    }

    risky_changed_files = [path for path in changed_files if any(marker in path for marker in RISKY_FILE_MARKERS)]
    docs_only_files = bool(changed_files) and all(_is_doc_file(path) for path in changed_files)
    continuity_only_files = bool(changed_files) and all(_is_continuity_file(path) for path in changed_files)
    safe_ui_copy_files = bool(changed_files) and all(_is_safe_ui_copy_file(path) for path in changed_files)
    risky_scope = any(
        (
            risky_keywords["auth_security"],
            risky_keywords["infra_routing"],
            risky_keywords["deploy_restart"],
            risky_keywords["destructive"],
            risky_keywords["migration"],
            risky_keywords["config_env"],
            risky_keywords["api_schema_model"],
            risky_keywords["control_plane"],
            bool(risky_changed_files),
        )
    )

    critical = False
    high = False
    low = False
    evidence_sufficient = False

    if risky_keywords["destructive"]:
        critical = True
        reasons.append("Destructive operation language was detected.")
    if risky_keywords["auth_security"]:
        critical = True
        reasons.append("Auth, security, or session scope was detected.")
    if risky_keywords["infra_routing"]:
        critical = True
        reasons.append("Routing, domain, TLS, or ingress scope was detected.")
    if risky_keywords["deploy_restart"]:
        critical = True
        reasons.append("Production deploy or restart language was detected.")
    if risky_keywords["control_plane"]:
        critical = True
        reasons.append("Approval or control-plane mutation scope was detected.")
    if risky_keywords["migration"]:
        high = True
        reasons.append("Migration or backfill scope was detected.")
    if risky_keywords["config_env"]:
        high = True
        reasons.append("Config or environment-variable scope was detected.")
    if risky_keywords["api_schema_model"]:
        high = True
        reasons.append("API, service, schema, or model scope was detected.")
    if risky_keywords["release_readiness"]:
        reasons.append("Release-readiness handling defaults to manual review.")
    if risky_keywords["product_behavior"]:
        reasons.append("Behavioral or operator-meaning changes default to manual review.")
    if risky_changed_files:
        reasons.append("Risk-sensitive files were involved in the run scope.")

    if risky_scope and tests_passed is not True:
        high = True
        reasons.append("Risky scope is missing passing test evidence.")
    if risky_scope and acceptance_passed not in {True, None}:
        high = True
        reasons.append("Risky scope does not have passing acceptance evidence.")

    if docs_only_files:
        low = True
        evidence_sufficient = True
        reasons.append("Documentation-only changed files were detected.")
    if continuity_only_files or risky_keywords["continuity_obsidian"]:
        low = True
        evidence_sufficient = True
        reasons.append("Continuity or Obsidian history-only scope was detected.")
    if risky_keywords["read_only"] and not risky_scope:
        low = True
        evidence_sufficient = True
        reasons.append("Explicit read-only or reporting language was detected.")
    if risky_keywords["local_only"] and not risky_scope:
        low = True
        evidence_sufficient = True
        reasons.append("The run is explicitly local-only or non-production.")
    if risky_keywords["docs"] and not risky_scope and not changed_files:
        low = True
        evidence_sufficient = True
        reasons.append("Documentation-focused scope was detected.")
    if safe_ui_copy_files and risky_keywords["ui_copy"] and tests_passed is True and not risky_scope:
        low = True
        evidence_sufficient = True
        reasons.append("Low-risk UI copy-only changes were detected with passing tests.")

    artifact_is_text_only = bool(artifact_names) and all(Path(name).suffix.lower() in (LOW_RISK_DOC_EXTENSIONS | {".json"}) for name in artifact_names)
    if low and artifact_is_text_only:
        reasons.append("Attached artifacts are text/report oriented.")

    if tests_passed is True:
        reasons.append("Passing test evidence was found.")
    if acceptance_passed is True:
        reasons.append("Passing acceptance evidence was found.")
    if tests_passed is None and acceptance_passed is None and not low:
        reasons.append("Sufficient positive evidence was not available, so the run defaults to manual review.")

    if critical or high:
        low = False
        evidence_sufficient = True

    if not reasons:
        reasons.append("Ordinary code changes default to manual review.")

    return {
        "critical": critical,
        "high": high,
        "low": low,
        "evidence_sufficient": evidence_sufficient,
        "reasons": reasons,
    }


def _extract_artifact_evidence(artifact_paths: list[Path | str]) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "tests_passed": None,
        "acceptance_passed": None,
        "changed_files": [],
        "artifacts_scanned": [],
    }
    for raw_path in artifact_paths:
        path = Path(raw_path)
        evidence["artifacts_scanned"].append(path.name)
        if not path.exists() or path.suffix.lower() != ".json" or path.stat().st_size > 512_000:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        extracted = _extract_json_evidence(payload)
        evidence["tests_passed"] = _coalesce_bool(evidence["tests_passed"], extracted.get("tests_passed"))
        evidence["acceptance_passed"] = _coalesce_bool(evidence["acceptance_passed"], extracted.get("acceptance_passed"))
        evidence["changed_files"] = [*evidence["changed_files"], *(extracted.get("changed_files") or [])]
    if evidence["changed_files"]:
        evidence["changed_files"] = sorted({str(item) for item in evidence["changed_files"]})
    return evidence


def _extract_json_evidence(payload: Any) -> dict[str, Any]:
    changed_files: list[str] = []
    tests_passed: bool | None = None
    acceptance_passed: bool | None = None

    if isinstance(payload, dict):
        if isinstance(payload.get("changed_files"), list):
            changed_files.extend(str(item) for item in payload["changed_files"])
        tests_passed = _status_to_bool(payload.get("tests_passed"))
        acceptance_passed = _status_to_bool(payload.get("acceptance_passed"))

        pytest_status = _nested_status(payload, "gate_results", "pytest", "status")
        acceptance_status = _nested_status(payload, "gate_results", "acceptance", "status")
        tests_passed = _coalesce_bool(tests_passed, _status_to_bool(pytest_status))
        acceptance_passed = _coalesce_bool(acceptance_passed, _status_to_bool(acceptance_status))

        direct_acceptance = _nested_status(payload, "acceptance", "status")
        acceptance_passed = _coalesce_bool(acceptance_passed, _status_to_bool(direct_acceptance))
        direct_pytest = _nested_status(payload, "pytest", "status")
        tests_passed = _coalesce_bool(tests_passed, _status_to_bool(direct_pytest))

    return {
        "changed_files": changed_files,
        "tests_passed": tests_passed,
        "acceptance_passed": acceptance_passed,
    }


def _nested_status(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _status_to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"pass", "passed", "success", "ready", "true"}:
        return True
    if normalized in {"fail", "failed", "error", "not_ready", "false"}:
        return False
    return None


def _coalesce_bool(primary: bool | None, secondary: bool | None) -> bool | None:
    return primary if primary is not None else secondary


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_doc_file(path: str) -> bool:
    pure = path.replace("\\", "/")
    suffix = Path(pure).suffix.lower()
    return suffix in LOW_RISK_DOC_EXTENSIONS or pure.startswith("docs/") or pure.endswith("/readme")


def _is_continuity_file(path: str) -> bool:
    pure = path.replace("\\", "/")
    return any(marker in pure for marker in ("obsidian", "continuity", "review history", "exports/"))


def _is_safe_ui_copy_file(path: str) -> bool:
    pure = path.replace("\\", "/")
    suffix = Path(pure).suffix.lower()
    if suffix not in LOW_RISK_UI_COPY_EXTENSIONS:
        return False
    return pure.startswith(SAFE_FRONTEND_TEXT_PATHS)


def _dedupe_reasons(reasons: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        normalized = reason.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered

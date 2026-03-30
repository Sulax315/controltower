from __future__ import annotations

import argparse
import html
import hashlib
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from controltower.config import load_config
from controltower.services.controltower import ControlTowerService
from controltower.services.runtime_state import ARTIFACT_INDEX_NAME, LATEST_DIAGNOSTICS_NAME, LATEST_RELEASE_JSON


EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 10
EXIT_BACKEND_ERROR = 11
EXIT_PROXY_ERROR = 12
EXIT_DIAGNOSTICS_ERROR = 13
EXIT_SMOKE_ERROR = 14
EXIT_RELEASE_ERROR = 15


def _default_config_path() -> Path | None:
    config_path = os.getenv("CONTROLTOWER_CONFIG")
    return Path(config_path) if config_path else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_production_deployment",
        description="Verify Control Tower production deployment through the backend listener and nginx route.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_config_path(),
        help="Path to the production Control Tower YAML config. Defaults to CONTROLTOWER_CONFIG when set.",
    )
    parser.add_argument(
        "--public-base-url",
        default=os.getenv("CONTROLTOWER_PUBLIC_BASE_URL", "https://controltower.bratek.io"),
        help="Public nginx URL for the deployed site.",
    )
    parser.add_argument(
        "--public-http-base-url",
        default=os.getenv("CONTROLTOWER_PUBLIC_HTTP_BASE_URL"),
        help="Optional HTTP base URL for redirect verification. Defaults to the public base URL with the http scheme.",
    )
    parser.add_argument(
        "--backend-base-url",
        default=None,
        help="Optional direct backend URL. Defaults to http://<config.ui.host>:<config.ui.port>.",
    )
    parser.add_argument(
        "--python-bin",
        default=os.getenv("PYTHON_BIN", sys.executable),
        help="Python interpreter used for smoke and release-readiness subprocesses.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=10,
        help="HTTP timeout for backend and nginx route checks.",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="Skip the production smoke subprocess.",
    )
    parser.add_argument(
        "--skip-release-readiness",
        action="store_true",
        help="Skip the persisted-evidence release-readiness subprocess.",
    )
    parser.add_argument(
        "--rerun-pytest",
        action="store_true",
        help="Rerun pytest during release-readiness instead of reusing existing evidence.",
    )
    parser.add_argument(
        "--rerun-acceptance",
        action="store_true",
        help="Rerun acceptance during release-readiness instead of reusing existing evidence.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summary: dict[str, Any] = {
        "status": "failed",
        "config_path": str(args.config.resolve()) if args.config else None,
        "public_base_url": args.public_base_url.rstrip("/"),
        "public_http_base_url": None,
        "backend_base_url": None,
        "checks": [],
        "artifacts": {},
    }

    if args.config is None:
        summary["error"] = "No config path was provided and CONTROLTOWER_CONFIG is not set."
        print(json.dumps(summary, indent=2))
        return EXIT_CONFIG_ERROR

    try:
        config = load_config(args.config)
    except Exception as exc:
        summary["error"] = str(exc)
        print(json.dumps(summary, indent=2))
        return EXIT_CONFIG_ERROR

    config_path = Path(args.config).resolve()
    runtime_root = Path(config.runtime.state_root)
    service = ControlTowerService(config)
    backend_base_url = (args.backend_base_url or f"http://{config.ui.host}:{config.ui.port}").rstrip("/")
    public_base_url = args.public_base_url.rstrip("/")
    public_http_base_url = (args.public_http_base_url or _to_http_url(public_base_url)).rstrip("/")
    selected_codes = _selected_codes(service)
    base_arena = service.build_arena([])
    arena = service.build_arena(selected_codes)
    tower = service.build_control_tower(selected_codes)
    runtime_coherence = service.build_runtime_coherence_snapshot()

    summary["backend_base_url"] = backend_base_url
    summary["public_http_base_url"] = public_http_base_url
    summary["artifacts"] = {
        "runtime_root": str(runtime_root),
        "artifact_index": str(runtime_root / ARTIFACT_INDEX_NAME),
        "latest_diagnostics": str(runtime_root / "diagnostics" / LATEST_DIAGNOSTICS_NAME),
        "latest_release_json": str(runtime_root / "release" / LATEST_RELEASE_JSON),
        "selected_codes": selected_codes,
    }
    summary["checks"].append(
        {
            "name": "config_presence",
            "status": "pass",
            "config_path": str(config_path),
            "runtime_root": str(runtime_root),
            "selected_codes": selected_codes,
        }
    )

    public_http_root = _http_check(
        f"{public_http_base_url}/",
        timeout_seconds=args.timeout_seconds,
        follow_redirects=False,
        expected_statuses={301, 302, 307, 308},
    )
    public_http_root["expected_location"] = f"{public_base_url}/"
    public_http_root["location_matches_https"] = public_http_root.get("headers", {}).get("location") == f"{public_base_url}/"
    public_http_root["status"] = (
        "pass"
        if public_http_root["status"] == "pass" and public_http_root["location_matches_https"]
        else "fail"
    )
    summary["checks"].append({"name": "public_http_root_redirect", **public_http_root})
    if public_http_root["status"] != "pass":
        summary["error"] = "The public HTTP route did not redirect cleanly to HTTPS."
        print(json.dumps(summary, indent=2))
        return EXIT_PROXY_ERROR

    tls_certificate = _tls_certificate_check(public_base_url, timeout_seconds=args.timeout_seconds)
    summary["checks"].append({"name": "public_tls_certificate", **tls_certificate})
    if tls_certificate["status"] != "pass":
        summary["error"] = "The public TLS certificate was invalid for the configured Control Tower hostname."
        print(json.dumps(summary, indent=2))
        return EXIT_PROXY_ERROR

    route_expectations = {
        "/": {
            "name": "root",
            "expected_content_type_prefix": "text/html",
            "markers": [
                "Executive operating view",
                'id="root-primary-answer"',
                tower.comparison_trust.ranking_label,
                tower.comparison_trust.baseline_label,
            ],
            "visible_prefix_anchor": 'id="root-executive-prelude"',
            "expected_visible_markers": _root_visible_markers(tower),
            "forbidden_markers": [
                "Leading change items on this run.",
                "Immediate owner-led actions in view.",
                "Rising risks still above the fold.",
                "projected finish not available",
                "no finish-date delta was emitted",
            ],
            "forbidden_visible_markers": [
                "Material Change",
                "High Risk",
                "Overall Posture",
            ],
        },
        "/arena": {
            "name": "arena",
            "expected_content_type_prefix": "text/html",
            "markers": [
                'id="arena-project-answers"',
                "Download Authoritative Markdown",
                base_arena.comparison_trust.ranking_label,
                base_arena.comparison_trust.baseline_label,
            ],
            "visible_prefix_anchor": 'id="arena-executive-prelude"',
            "expected_visible_markers": _arena_visible_markers(base_arena),
            "forbidden_markers": [
                "projected finish not available",
                "no finish-date delta was emitted",
            ],
            "forbidden_visible_markers": [
                "Material Change",
                "High Risk",
                "Overall Posture",
            ],
        },
        "/arena/export/artifact.md": {
            "name": "artifact",
            "expected_content_type_prefix": "text/markdown",
            "markers": [
                "## Scope / Timestamp",
                "## Project Finish Answers",
                "## Trust Posture / Baseline",
                base_arena.selection_summary,
                base_arena.comparison_trust.ranking_label,
            ],
            "expected_headers": {
                "x-controltower-arena-selection": ",".join(base_arena.selected_arena_codes),
            },
        },
    }
    if selected_codes:
        selected_query = "&".join(f"selected={code}" for code in selected_codes)
        route_expectations[f"/arena?{selected_query}"] = {
            "name": "arena_selected",
            "expected_content_type_prefix": "text/html",
            "markers": [
                'id="arena-project-answers"',
                "Download Authoritative Markdown",
                arena.comparison_trust.ranking_label,
                arena.comparison_trust.baseline_label,
            ],
            "visible_prefix_anchor": 'id="arena-executive-prelude"',
            "expected_visible_markers": _arena_visible_markers(arena),
            "forbidden_markers": [
                "projected finish not available",
                "no finish-date delta was emitted",
            ],
            "forbidden_visible_markers": [
                "Material Change",
                "High Risk",
                "Overall Posture",
            ],
        }
        route_expectations[f"/arena/export/artifact.md?{selected_query}"] = {
            "name": "artifact_selected",
            "expected_content_type_prefix": "text/markdown",
            "markers": [
                "## Scope / Timestamp",
                "## Project Finish Answers",
                "## Trust Posture / Baseline",
                arena.selection_summary,
                arena.comparison_trust.ranking_label,
            ],
            "expected_headers": {
                "x-controltower-arena-selection": ",".join(arena.selected_arena_codes),
            },
        }
    route_results = _verify_route_set(
        route_expectations=route_expectations,
        backend_base_url=backend_base_url,
        public_base_url=public_base_url,
        timeout_seconds=args.timeout_seconds,
    )
    summary["checks"].extend(route_results)
    if any(check["status"] != "pass" for check in route_results):
        summary["error"] = "One or more required backend/public routes failed or did not match across nginx."
        print(json.dumps(summary, indent=2))
        return EXIT_PROXY_ERROR

    diagnostics_page = _http_check(f"{public_base_url}/diagnostics", timeout_seconds=args.timeout_seconds)
    summary["checks"].append({"name": "public_diagnostics", **diagnostics_page})
    if diagnostics_page["status"] != "pass":
        summary["error"] = "The public /diagnostics route did not answer successfully."
        print(json.dumps(summary, indent=2))
        return EXIT_DIAGNOSTICS_ERROR

    diagnostics_api = _json_check(f"{public_base_url}/api/diagnostics", timeout_seconds=args.timeout_seconds)
    diagnostics_check = {"name": "public_api_diagnostics", **diagnostics_api}
    if diagnostics_api["status"] == "pass":
        payload = diagnostics_api["payload"]
        diagnostics_check["config_status"] = payload.get("config", {}).get("status")
        diagnostics_check["release_status"] = payload.get("release", {}).get("status")
        diagnostics_check["latest_run_status"] = payload.get("latest_run", {}).get("status")
        diagnostics_check["artifact_index_present"] = payload.get("artifacts", {}).get("artifact_index_present")
        diagnostics_check["latest_diagnostics_present"] = payload.get("artifacts", {}).get("latest_diagnostics_present")
        diagnostics_check["comparison_runtime_present"] = "comparison_runtime" in payload
        comparison_runtime = payload.get("comparison_runtime") or {}
        diagnostics_check["comparison_runtime_has_arena_artifact_path"] = (
            str(comparison_runtime.get("arena_artifact_path") or "").startswith("/arena/export/artifact.md")
        )
        diagnostics_check["comparison_runtime_selected_codes_match"] = (
            comparison_runtime.get("selected_arena_codes") == runtime_coherence.get("selected_arena_codes")
        )
        diagnostics_check.pop("payload", None)
    summary["checks"].append(diagnostics_check)
    if (
        diagnostics_api["status"] != "pass"
        or diagnostics_check.get("comparison_runtime_present") is not True
        or diagnostics_check.get("comparison_runtime_has_arena_artifact_path") is not True
        or diagnostics_check.get("comparison_runtime_selected_codes_match") is not True
    ):
        summary["error"] = "The public /api/diagnostics route did not return the accepted Control Tower runtime contract."
        print(json.dumps(summary, indent=2))
        return EXIT_DIAGNOSTICS_ERROR

    if not args.skip_smoke:
        smoke_result = _run_subprocess(
            [
                args.python_bin,
                str(REPO_ROOT / "scripts" / "smoke_controltower.py"),
                "--config",
                str(config_path),
            ],
            cwd=REPO_ROOT,
        )
        summary["checks"].append({"name": "smoke", **smoke_result})
        if smoke_result["status"] != "pass":
            summary["error"] = "Smoke verification failed."
            print(json.dumps(summary, indent=2))
            return EXIT_SMOKE_ERROR

    if not args.skip_release_readiness:
        command = [
            args.python_bin,
            str(REPO_ROOT / "scripts" / "release_readiness_controltower.py"),
            "--config",
            str(config_path),
        ]
        if not args.rerun_pytest:
            command.append("--skip-pytest")
        if not args.rerun_acceptance:
            command.append("--skip-acceptance")
        release_result = _run_subprocess(command, cwd=REPO_ROOT)
        summary["checks"].append({"name": "release_readiness", **release_result})
        if release_result["status"] != "pass":
            summary["error"] = "Release readiness failed."
            print(json.dumps(summary, indent=2))
            return EXIT_RELEASE_ERROR

    summary["status"] = "pass"
    print(json.dumps(summary, indent=2))
    return EXIT_SUCCESS


def _verify_route_set(
    *,
    route_expectations: dict[str, dict[str, Any]],
    backend_base_url: str,
    public_base_url: str,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path, expectation in route_expectations.items():
        backend_result = _http_check(
            f"{backend_base_url}{path}",
            timeout_seconds=timeout_seconds,
            expected_content_type_prefix=expectation["expected_content_type_prefix"],
            expected_markers=expectation["markers"],
            expected_headers=expectation.get("expected_headers"),
            visible_prefix_anchor=expectation.get("visible_prefix_anchor"),
            expected_visible_markers=expectation.get("expected_visible_markers"),
            forbidden_markers=expectation.get("forbidden_markers"),
        )
        backend_result["name"] = f"backend_{expectation['name']}"
        results.append(backend_result)

        public_result = _http_check(
            f"{public_base_url}{path}",
            timeout_seconds=timeout_seconds,
            expected_content_type_prefix=expectation["expected_content_type_prefix"],
            expected_markers=expectation["markers"],
            expected_headers=expectation.get("expected_headers"),
            visible_prefix_anchor=expectation.get("visible_prefix_anchor"),
            expected_visible_markers=expectation.get("expected_visible_markers"),
            forbidden_markers=expectation.get("forbidden_markers"),
        )
        public_result["name"] = f"public_{expectation['name']}"
        results.append(public_result)

        matched = {
            "name": f"public_matches_backend_{expectation['name']}",
            "status": "fail",
            "path": path,
            "backend_body_sha256": backend_result.get("body_sha256"),
            "public_body_sha256": public_result.get("body_sha256"),
            "backend_semantic_body_sha256": backend_result.get("semantic_body_sha256"),
            "public_semantic_body_sha256": public_result.get("semantic_body_sha256"),
        }
        if backend_result["status"] == "pass" and public_result["status"] == "pass":
            matched["status"] = (
                "pass"
                if backend_result.get("semantic_body_sha256") == public_result.get("semantic_body_sha256")
                else "fail"
            )
        results.append(matched)
    return results


def _http_check(
    url: str,
    *,
    timeout_seconds: int,
    follow_redirects: bool = True,
    expected_statuses: set[int] | None = None,
    expected_content_type_prefix: str | None = None,
    expected_markers: list[str] | None = None,
    expected_headers: dict[str, str] | None = None,
    visible_prefix_anchor: str | None = None,
    expected_visible_markers: list[str] | None = None,
    forbidden_markers: list[str] | None = None,
    forbidden_visible_markers: list[str] | None = None,
) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "controltower-production-verifier/1.0"})
    opener = build_opener() if follow_redirects else build_opener(_NoRedirectHandler())
    allowed_statuses = expected_statuses or {200}
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            status_code = response.status
            headers = {key.lower(): value for key, value in response.headers.items()}
            body_bytes = response.read()
    except HTTPError as exc:
        status_code = exc.code
        headers = {key.lower(): value for key, value in exc.headers.items()}
        body_bytes = exc.read()
    except URLError as exc:
        return {"status": "fail", "url": url, "error": str(exc.reason)}

    body_text = body_bytes.decode("utf-8", errors="replace")
    search_text = html.unescape(body_text)
    semantic_text = _normalize_semantic_text(search_text)
    visible_prefix_text = _surface_visible_prefix(search_text, visible_prefix_anchor) if visible_prefix_anchor else search_text
    missing_markers = [marker for marker in (expected_markers or []) if marker not in search_text]
    missing_visible_markers = [marker for marker in (expected_visible_markers or []) if marker not in visible_prefix_text]
    forbidden_markers_present = [marker for marker in (forbidden_markers or []) if marker in search_text]
    forbidden_visible_markers_present = [marker for marker in (forbidden_visible_markers or []) if marker in visible_prefix_text]
    header_mismatches: dict[str, dict[str, str | None]] = {}
    for header_name, expected_value in (expected_headers or {}).items():
        actual_value = headers.get(header_name.lower())
        if actual_value != expected_value:
            header_mismatches[header_name.lower()] = {"expected": expected_value, "actual": actual_value}

    content_type = headers.get("content-type")
    checks_pass = (
        status_code in allowed_statuses
        and (expected_content_type_prefix is None or (content_type or "").startswith(expected_content_type_prefix))
        and not missing_markers
        and not missing_visible_markers
        and not forbidden_markers_present
        and not forbidden_visible_markers_present
        and not header_mismatches
    )
    return {
        "status": "pass" if checks_pass else "fail",
        "url": url,
        "http_status": status_code,
        "headers": headers,
        "content_type": content_type,
        "body_sha256": hashlib.sha256(body_bytes).hexdigest(),
        "semantic_body_sha256": hashlib.sha256(semantic_text.encode("utf-8")).hexdigest(),
        "body_snippet": search_text[:512],
        "visible_prefix_snippet": visible_prefix_text[:512],
        "missing_markers": missing_markers,
        "missing_visible_markers": missing_visible_markers,
        "forbidden_markers_present": forbidden_markers_present,
        "forbidden_visible_markers_present": forbidden_visible_markers_present,
        "header_mismatches": header_mismatches,
    }


def _json_check(url: str, *, timeout_seconds: int) -> dict[str, Any]:
    result = _http_check(url, timeout_seconds=timeout_seconds)
    if result["status"] != "pass":
        return result
    try:
        request = Request(url, headers={"User-Agent": "controltower-production-verifier/1.0"})
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, HTTPError, json.JSONDecodeError) as exc:
        return {"status": "fail", "url": url, "error": str(exc)}
    if payload.get("config", {}).get("status") != "loaded":
        return {"status": "fail", "url": url, "payload": payload, "error": "Diagnostics config status was not loaded."}
    return {"status": "pass", "url": url, "payload": payload}


def _run_subprocess(command: list[str], *, cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, check=False)
    return {
        "status": "pass" if completed.returncode == 0 else "fail",
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "stdout_tail": _tail_lines(completed.stdout),
        "stderr_tail": _tail_lines(completed.stderr),
    }


def _tail_lines(text: str, count: int = 20) -> list[str]:
    return [line for line in text.splitlines()[-count:] if line.strip()]


def _root_visible_markers(tower: Any) -> list[str]:
    markers: list[str] = ["Projected finish", "Movement Vs Prior Trusted Run", "Required Action", "Finish Authority"]
    answer = tower.primary_project_answer
    if answer is not None:
        markers.extend(
            [
                answer.project_name,
                answer.canonical_project_code,
                answer.projected_finish_label,
                answer.movement_label,
                answer.primary_issue,
                answer.required_action,
                answer.finish_authority_state,
            ]
        )
        if answer.projected_finish_reason:
            markers.append(answer.projected_finish_reason)
        if answer.movement_reason:
            markers.append(answer.movement_reason)
    return [marker for marker in markers if marker]


def _arena_visible_markers(arena: Any) -> list[str]:
    markers: list[str] = ["Projected finish", "Movement Vs Prior Trusted Run", "Required Action", "Finish Authority"]
    if arena.project_answers:
        answer = arena.project_answers[0]
        markers.extend(
            [
                answer.project_name,
                answer.canonical_project_code,
                answer.projected_finish_label,
                answer.movement_label,
                answer.primary_issue,
                answer.required_action,
                answer.finish_authority_state,
            ]
        )
        if answer.projected_finish_reason:
            markers.append(answer.projected_finish_reason)
        if answer.movement_reason:
            markers.append(answer.movement_reason)
    return [marker for marker in markers if marker]


def _selected_codes(service: ControlTowerService) -> list[str]:
    portfolio = service.build_portfolio()
    selected = [project.canonical_project_code for project in portfolio.project_rankings[:1]]
    return selected


def _to_http_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme:
        return f"http://{url.lstrip('/')}"
    return parsed._replace(scheme="http").geturl()


def _tls_certificate_check(base_url: str, *, timeout_seconds: int) -> dict[str, Any]:
    parsed = urlparse(base_url)
    hostname = parsed.hostname
    if hostname is None:
        return {"status": "fail", "url": base_url, "error": "The public base URL did not contain a hostname."}
    port = parsed.port or 443

    try:
        pem = ssl.get_server_certificate((hostname, port))
    except OSError as exc:
        return {"status": "fail", "url": base_url, "error": str(exc)}

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".pem") as handle:
        handle.write(pem)
        cert_path = Path(handle.name)
    try:
        decoded = ssl._ssl._test_decode_cert(str(cert_path))
    finally:
        cert_path.unlink(missing_ok=True)

    san_entries = [value for kind, value in decoded.get("subjectAltName", []) if kind == "DNS"]
    not_before = decoded.get("notBefore")
    not_after = decoded.get("notAfter")
    handshake_ok = True
    handshake_error = None
    tls_version = None
    cipher = None
    context = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, port), timeout=timeout_seconds) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as tls_socket:
                tls_version = tls_socket.version()
                cipher = tls_socket.cipher()[0] if tls_socket.cipher() else None
    except (OSError, ssl.SSLError) as exc:
        handshake_ok = False
        handshake_error = str(exc)

    now = datetime.now(timezone.utc)
    not_before_iso = _parse_cert_time(not_before)
    not_after_iso = _parse_cert_time(not_after)
    currently_valid = bool(not_before_iso and not_after_iso and not_before_iso <= now <= not_after_iso)
    hostname_match = handshake_ok or _hostname_in_sans(hostname, san_entries)

    return {
        "status": "pass" if hostname_match and handshake_ok and currently_valid else "fail",
        "url": base_url,
        "subject": decoded.get("subject"),
        "issuer": decoded.get("issuer"),
        "subject_alt_names": san_entries,
        "not_before": not_before,
        "not_after": not_after,
        "hostname_match": hostname_match,
        "handshake_ok": handshake_ok,
        "tls_version": tls_version,
        "cipher": cipher,
        "currently_valid": currently_valid,
        "verification_error": None if hostname_match else f"{hostname} was not listed in the certificate SANs.",
        "handshake_error": handshake_error,
    }


def _parse_cert_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)


def _hostname_in_sans(hostname: str, san_entries: list[str]) -> bool:
    for entry in san_entries:
        if entry == hostname:
            return True
        if entry.startswith("*.") and hostname.endswith(entry[1:]) and hostname.count(".") == entry.count("."):
            return True
    return False


def _surface_visible_prefix(text: str, anchor: str | None) -> str:
    start = text.find(anchor) if anchor else -1
    scoped = text[start:] if start >= 0 else text
    details_index = scoped.find("<details")
    return scoped if details_index < 0 else scoped[:details_index]


def _normalize_semantic_text(text: str) -> str:
    normalized = re.sub(r"generated_at:\s*'[^']+'", "generated_at: '<normalized>'", text)
    normalized = re.sub(r"- Generated at:\s*[0-9T:\-]+Z", "- Generated at: <normalized>", normalized)
    return normalized


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


if __name__ == "__main__":
    raise SystemExit(main())

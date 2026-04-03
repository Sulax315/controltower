from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from controltower.api.app import create_app
from controltower.config import load_config
from controltower.integrations import orchestrator_substrate as orch


def _orch_mcp_root() -> Path:
    return Path(__file__).resolve().parents[2] / "mcp_gateway" / "services" / "controltower_orchestrator_mcp"


@pytest.fixture
def orch_mcp_root():
    root = _orch_mcp_root()
    if not root.is_dir():
        pytest.skip("controltower_orchestrator_mcp not present beside ControlTower checkout")
    return root


@pytest.fixture
def orch_enabled_config_path(sample_config_path: Path, tmp_path: Path, orch_mcp_root: Path) -> Path:
    raw = yaml.safe_load(sample_config_path.read_text(encoding="utf-8")) or {}
    runtime = tmp_path / "orch_runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    raw["orchestrator_substrate"] = {
        "enabled": True,
        "mcp_service_root": str(orch_mcp_root),
        "runtime_dir": str(runtime),
    }
    path = tmp_path / "controltower_orch.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def orch_enabled_prod_review_config_path(orch_enabled_config_path: Path, tmp_path: Path) -> Path:
    raw = yaml.safe_load(orch_enabled_config_path.read_text(encoding="utf-8")) or {}
    raw["review"] = {
        "mode": "prod",
        "session_secret": "test_review_session_secret_value_min_len_ok________",
        "operator_username": "orch_op",
        "operator_password": "orch_pw_test",
        "session_cookie_name": "controltower_review_session",
    }
    path = tmp_path / "controltower_orch_prod_review.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_strip_secrets_for_browser_redacts_common_keys() -> None:
    payload = {"workflow_id": "w1", "nested": {"api_key": "secret", "ok": 1}}
    out = orch._strip_secrets_for_browser(payload)
    assert out["workflow_id"] == "w1"
    assert out["nested"]["api_key"] == "[redacted]"
    assert out["nested"]["ok"] == 1


def test_substrate_disabled_returns_envelope_without_binding(sample_config_path: Path) -> None:
    config = load_config(sample_config_path)
    out = orch.list_approval_requests(config, limit=10)
    assert out["status"] == "error"
    assert out["error"]["code"] == "orchestrator_substrate_disabled"


def test_substrate_lists_and_workflow_not_found(orch_enabled_config_path: Path) -> None:
    config = load_config(orch_enabled_config_path)
    approvals = orch.list_approval_requests(config, limit=10)
    assert approvals["status"] == "ok"
    assert approvals["count"] == 0

    packets = orch.list_publish_packets(config, limit=10)
    assert packets["status"] == "ok"

    releases = orch.list_release_requests(config, limit=10)
    assert releases["status"] == "ok"

    wf = orch.get_schedule_publish_workflow(config, "missing_workflow_id")
    assert wf["status"] == "not_found"
    assert wf["error"]["message"] == "schedule_publish_workflow_not_found"


def test_api_orchestrator_routes_404_when_disabled(sample_config_path: Path) -> None:
    app = create_app(str(sample_config_path))
    client = TestClient(app)
    r = client.get("/api/orchestrator/approval-requests")
    assert r.status_code == 404


def test_api_orchestrator_reads_when_enabled(orch_enabled_config_path: Path) -> None:
    app = create_app(str(orch_enabled_config_path))
    client = TestClient(app)
    r = client.get("/api/orchestrator/approval-requests")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "bearer" not in r.text.lower()
    assert "authorization:" not in r.text.lower()

    wf = client.get("/api/orchestrator/workflow/missing_wf")
    assert wf.status_code == 200
    assert wf.json()["status"] == "not_found"


def test_publish_page_renders_orchestrator_band(orch_enabled_config_path: Path) -> None:
    app = create_app(str(orch_enabled_config_path))
    client = TestClient(app)
    r = client.get("/publish")
    assert r.status_code == 200
    assert 'id="ct-orch-execution-band"' in r.text
    assert "controltower_orchestrator_mcp" in r.text
    assert "blocking_condition" in r.text or "Schedule publish workflow" in r.text


def _login_session(client: TestClient, *, username: str, password: str) -> None:
    login_page = client.get("/login")
    assert login_page.status_code == 200
    m = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text)
    assert m
    logged = client.post(
        "/login",
        data={
            "operator_username": username,
            "operator_password": password,
            "next_path": "/publish",
            "csrf_token": m.group(1),
        },
        follow_redirects=False,
    )
    assert logged.status_code == 303


def test_publish_orchestrator_mutation_requires_csrf_when_review_prod(
    orch_enabled_prod_review_config_path: Path,
) -> None:
    app = create_app(str(orch_enabled_prod_review_config_path))
    # Secure session cookies require HTTPS when review mutations are production-gated.
    client = TestClient(app, base_url="https://testserver")
    _login_session(client, username="orch_op", password="orch_pw_test")
    r = client.post(
        "/publish/orchestrator/approve-approval",
        data={"approval_request_id": "nope", "orch_wf": "", "csrf_token": "bad"},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_publish_orchestrator_mutation_unknown_id_redirects_with_error(orch_enabled_config_path: Path) -> None:
    app = create_app(str(orch_enabled_config_path))
    client = TestClient(app)
    page = client.get("/publish")
    assert page.status_code == 200
    m = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert m, "csrf token must be present for mutation forms"
    token = m.group(1)
    r = client.post(
        "/publish/orchestrator/approve-approval",
        data={
            "approval_request_id": "missing_approval_id",
            "reason": "test",
            "orch_wf": "",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    loc = r.headers.get("location") or ""
    assert "orch_notice=error" in loc or "orch_err=" in loc

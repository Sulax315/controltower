from __future__ import annotations

import re

from fastapi.testclient import TestClient

from controltower.config import ControlTowerConfig


_CSRF_TOKEN_PATTERN = re.compile(r'name="csrf_token" value="([^"]+)"')


def app_auth_required(config: ControlTowerConfig) -> bool:
    return (config.auth.mode or "dev").strip().lower() == "prod"


def build_authenticated_test_client(
    app,
    config: ControlTowerConfig,
    *,
    next_path: str = "/publish",
) -> TestClient:
    base_url = str(config.app.public_base_url or "https://controltower.example.com")
    client = TestClient(app, base_url=base_url if app_auth_required(config) else "http://testserver")
    if not app_auth_required(config):
        return client

    username = (config.auth.username or "").strip()
    password = (config.auth.password or "").strip()
    if not username or not password:
        raise ValueError("Application auth is enabled, but auth.username/auth.password are not configured.")

    login_page = client.get(f"/login?next_path={next_path}")
    if login_page.status_code != 200:
        raise ValueError(f"Application login page did not return HTTP 200. Got {login_page.status_code}.")

    match = _CSRF_TOKEN_PATTERN.search(login_page.text)
    if match is None:
        raise ValueError("Application login page did not render a CSRF token.")

    login_response = client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "next_path": next_path,
            "csrf_token": match.group(1),
        },
        follow_redirects=False,
    )
    location = login_response.headers.get("location", "")
    if login_response.status_code != 303 or not location.startswith(next_path):
        raise ValueError(
            f"Application login did not redirect to the protected route. Got {login_response.status_code} -> {location!r}."
        )
    return client

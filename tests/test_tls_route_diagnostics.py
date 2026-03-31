from __future__ import annotations

from controltower.services.tls_route_diagnostics import classify_tls_routes


def test_tls_route_classifies_non_production_endpoint_hit():
    summary = {
        "expected_address": "161.35.177.158",
        "system_route": {
            "peer_ip": "208.91.112.55",
            "verified": False,
            "certificate": {
                "hostname_match": False,
                "currently_valid": True,
                "sha256_fingerprint": "stale-cert",
            },
        },
        "expected_route": {
            "verified": True,
            "certificate": {
                "hostname_match": True,
                "currently_valid": True,
                "sha256_fingerprint": "live-cert",
            },
        },
    }

    classification = classify_tls_routes(summary)

    assert classification["category"] == "non_production_endpoint_hit"


def test_tls_route_classifies_production_misconfiguration():
    summary = {
        "expected_address": "161.35.177.158",
        "system_route": {
            "peer_ip": "161.35.177.158",
            "verified": False,
            "certificate": {
                "hostname_match": False,
                "currently_valid": False,
                "sha256_fingerprint": "bad-live-cert",
            },
        },
        "expected_route": {
            "verified": False,
            "certificate": {
                "hostname_match": False,
                "currently_valid": False,
                "sha256_fingerprint": "bad-live-cert",
            },
        },
    }

    classification = classify_tls_routes(summary)

    assert classification["category"] == "production_cert_misconfiguration"


def test_tls_route_classifies_local_interception_or_alternate_resolution_path():
    summary = {
        "expected_address": "161.35.177.158",
        "system_route": {
            "peer_ip": "161.35.177.158",
            "verified": False,
            "certificate": {
                "hostname_match": True,
                "currently_valid": True,
                "sha256_fingerprint": "intercepted-cert",
            },
        },
        "expected_route": {
            "verified": True,
            "certificate": {
                "hostname_match": True,
                "currently_valid": True,
                "sha256_fingerprint": "live-cert",
            },
        },
    }

    classification = classify_tls_routes(summary)

    assert classification["category"] == "local_interception_or_alternate_resolution_path"


def test_tls_route_classifies_trust_store_issue():
    summary = {
        "expected_address": "161.35.177.158",
        "system_route": {
            "peer_ip": "161.35.177.158",
            "verified": False,
            "certificate": {
                "hostname_match": True,
                "currently_valid": True,
                "sha256_fingerprint": "same-cert",
            },
        },
        "expected_route": {
            "verified": True,
            "certificate": {
                "hostname_match": True,
                "currently_valid": True,
                "sha256_fingerprint": "same-cert",
            },
        },
    }

    classification = classify_tls_routes(summary)

    assert classification["category"] == "trust_store_issue"

from __future__ import annotations

import hashlib
import ipaddress
import socket
import ssl
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def inspect_tls_routes(
    hostname: str,
    *,
    expected_address: str | None = None,
    port: int = 443,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    system_addresses = resolve_system_addresses(hostname, port=port)
    system_route = probe_tls_route(hostname, connect_host=hostname, port=port, timeout_seconds=timeout_seconds)
    expected_route = None
    if expected_address:
        expected_route = probe_tls_route(
            hostname,
            connect_host=expected_address,
            port=port,
            timeout_seconds=timeout_seconds,
        )

    summary = {
        "generated_at": _utc_now_iso(),
        "hostname": hostname,
        "port": port,
        "expected_address": expected_address,
        "system_addresses": system_addresses,
        "system_route": system_route,
        "expected_route": expected_route,
    }
    summary["classification"] = classify_tls_routes(summary)
    return summary


def resolve_system_addresses(hostname: str, *, port: int) -> list[str]:
    addresses: list[str] = []
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError:
        return addresses

    for info in infos:
        candidate = info[4][0]
        if candidate not in addresses:
            addresses.append(candidate)
    return addresses


def probe_tls_route(
    hostname: str,
    *,
    connect_host: str,
    port: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    verified = _verified_handshake(hostname, connect_host=connect_host, port=port, timeout_seconds=timeout_seconds)
    certificate = _fetch_certificate(hostname, connect_host=connect_host, port=port, timeout_seconds=timeout_seconds)

    return {
        "hostname": hostname,
        "connect_host": connect_host,
        "connect_host_type": "ip" if _looks_like_ip_address(connect_host) else "hostname",
        "peer_ip": verified.get("peer_ip") or certificate.get("peer_ip"),
        "verified": verified["verified"],
        "verification_error": verified["verification_error"],
        "tls_version": verified["tls_version"],
        "cipher": verified["cipher"],
        "certificate": certificate,
    }


def classify_tls_routes(summary: dict[str, Any]) -> dict[str, Any]:
    expected_address = summary.get("expected_address")
    system_route = summary["system_route"]
    expected_route = summary.get("expected_route")

    if expected_route is not None:
        expected_cert = expected_route["certificate"]
        expected_route_valid = (
            expected_route["verified"]
            and expected_cert.get("hostname_match") is True
            and expected_cert.get("currently_valid") is True
        )
        if not expected_route_valid:
            return {
                "status": "problem",
                "category": "production_cert_misconfiguration",
                "reason": "The explicit expected edge did not present a valid certificate for the requested hostname.",
            }

    system_cert = system_route["certificate"]
    if (
        system_route["verified"]
        and system_cert.get("hostname_match") is True
        and system_cert.get("currently_valid") is True
    ):
        return {
            "status": "pass",
            "category": "healthy",
            "reason": "The system route presented a valid certificate for the requested hostname.",
        }

    if expected_route is None:
        return {
            "status": "problem",
            "category": "indeterminate",
            "reason": "The system route failed TLS verification and no explicit expected edge was provided for comparison.",
        }

    if system_route.get("peer_ip") and expected_address and system_route["peer_ip"] != expected_address:
        return {
            "status": "problem",
            "category": "non_production_endpoint_hit",
            "reason": "The system route connected to a different IP than the expected live edge while the explicit edge route verified cleanly.",
        }

    system_fingerprint = system_cert.get("sha256_fingerprint")
    expected_fingerprint = expected_route["certificate"].get("sha256_fingerprint")
    if system_fingerprint and expected_fingerprint and system_fingerprint != expected_fingerprint:
        return {
            "status": "problem",
            "category": "local_interception_or_alternate_resolution_path",
            "reason": "The system route returned a different certificate than the verified explicit edge route.",
        }

    return {
        "status": "problem",
        "category": "trust_store_issue",
        "reason": "The same endpoint appears to be in use, but local TLS verification still failed.",
    }


def _verified_handshake(
    hostname: str,
    *,
    connect_host: str,
    port: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    context = ssl.create_default_context()
    peer_ip = None
    tls_version = None
    cipher = None
    try:
        with socket.create_connection((connect_host, port), timeout=timeout_seconds) as sock:
            peer = sock.getpeername()
            if isinstance(peer, tuple) and peer:
                peer_ip = str(peer[0])
            with context.wrap_socket(sock, server_hostname=hostname) as tls_socket:
                tls_version = tls_socket.version()
                cipher = tls_socket.cipher()[0] if tls_socket.cipher() else None
        return {
            "verified": True,
            "peer_ip": peer_ip,
            "tls_version": tls_version,
            "cipher": cipher,
            "verification_error": None,
        }
    except (OSError, ssl.SSLError) as exc:
        return {
            "verified": False,
            "peer_ip": peer_ip,
            "tls_version": tls_version,
            "cipher": cipher,
            "verification_error": str(exc),
        }


def _fetch_certificate(
    hostname: str,
    *,
    connect_host: str,
    port: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    context = ssl._create_unverified_context()
    try:
        with socket.create_connection((connect_host, port), timeout=timeout_seconds) as sock:
            peer = sock.getpeername()
            peer_ip = str(peer[0]) if isinstance(peer, tuple) and peer else None
            with context.wrap_socket(sock, server_hostname=hostname) as tls_socket:
                der = tls_socket.getpeercert(binary_form=True)
                pem = ssl.DER_cert_to_PEM_cert(der)
    except (OSError, ssl.SSLError) as exc:
        return {
            "peer_ip": None,
            "subject": None,
            "issuer": None,
            "subject_alt_names": [],
            "not_before": None,
            "not_after": None,
            "currently_valid": False,
            "hostname_match": False,
            "sha256_fingerprint": None,
            "error": str(exc),
        }

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".pem") as handle:
        handle.write(pem)
        cert_path = Path(handle.name)
    try:
        decoded = ssl._ssl._test_decode_cert(str(cert_path))
    finally:
        cert_path.unlink(missing_ok=True)

    subject_alt_names = [value for kind, value in decoded.get("subjectAltName", []) if kind == "DNS"]
    not_before_iso = _parse_cert_time(decoded.get("notBefore"))
    not_after_iso = _parse_cert_time(decoded.get("notAfter"))
    now = datetime.now(timezone.utc)
    return {
        "peer_ip": peer_ip,
        "subject": decoded.get("subject"),
        "issuer": decoded.get("issuer"),
        "subject_alt_names": subject_alt_names,
        "not_before": decoded.get("notBefore"),
        "not_after": decoded.get("notAfter"),
        "currently_valid": bool(not_before_iso and not_after_iso and not_before_iso <= now <= not_after_iso),
        "hostname_match": _hostname_in_sans(hostname, subject_alt_names),
        "sha256_fingerprint": hashlib.sha256(der).hexdigest(),
        "error": None,
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


def _looks_like_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

"""Foreground, loopback-only, read-only review server."""

from __future__ import annotations

import html
import ipaddress
import json
import secrets
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .contracts import ContractError, is_link_like, parse_canonical_object, sha256_bytes


SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def _loopback(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _authority_host(value: str) -> str | None:
    try:
        parsed = urlsplit("//" + value)
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return None
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            return None
        return parsed.hostname
    except ValueError:
        return None


def validate_request_policy(
    *,
    method: str,
    host_header: str,
    origin: str | None,
    fetch_site: str | None,
    client_host: str,
    csrf_token: str | None,
    expected_csrf_token: str,
) -> None:
    host = _authority_host(host_header)
    if host is None or not _loopback(host) or not _loopback(client_host):
        raise ContractError("non-loopback request refused")
    expected_origin = f"http://{host_header}"
    if origin not in (None, "", expected_origin):
        raise ContractError("cross-origin request refused")
    if fetch_site not in (None, "", "none", "same-origin"):
        raise ContractError("cross-site request refused")
    if method.upper() == "POST" and (
        not csrf_token or not secrets.compare_digest(csrf_token, expected_csrf_token)
    ):
        raise ContractError("CSRF validation failed")


def load_review(run_root: Path) -> dict[str, Any]:
    if not run_root.is_absolute() or not run_root.is_dir() or is_link_like(run_root):
        raise ContractError("run root must be an absolute ordinary directory")
    manifest_raw = (run_root / "run_manifest.json").read_bytes()
    manifest = parse_canonical_object(manifest_raw, "run_manifest.json")
    rows = manifest.get("artifacts")
    if (
        manifest.get("schema_id") != "uvlm.triadicbrain.offline_demo_manifest.v1"
        or not isinstance(rows, list)
        or manifest.get("artifact_count") != len(rows)
    ):
        raise ContractError("run manifest contract invalid")
    values: dict[str, Any] = {}
    expected = {"run_manifest.json", "SHA256SUMS.txt"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"bytes", "path", "sha256"}:
            raise ContractError("run manifest row invalid")
        name = row["path"]
        if not isinstance(name, str) or Path(name).name != name or name in expected:
            raise ContractError("run manifest path invalid")
        path = run_root / name
        if is_link_like(path) or not path.is_file():
            raise ContractError("run artifact missing or link-like")
        payload = path.read_bytes()
        if len(payload) != row["bytes"] or sha256_bytes(payload) != row["sha256"]:
            raise ContractError("run artifact identity mismatch")
        expected.add(name)
        if name.endswith(".json"):
            values[name] = parse_canonical_object(payload, name)
    actual = {path.name for path in run_root.iterdir()}
    if actual != expected:
        raise ContractError("run root topology mismatch")
    return values


def render_review(values: dict[str, Any], csrf_token: str) -> bytes:
    candidate = values["candidate_packet.json"]
    sophia = values["sophia_audit.json"]
    atlas = values["atlas_posture.json"]
    human = values["human_review.json"]
    claims = "".join(
        f"<li>{html.escape(str(row.get('text', '')))}</li>" for row in candidate.get("claims", [])
    )
    body = (
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<title>Triadic Brain private-alpha review</title>"
        "<h1>Bounded local review</h1>"
        "<p>Candidate, audit, and posture are evidence for human review; none is truth or final authority.</p>"
        f"<h2>Candidate</h2><p>{html.escape(str(candidate.get('answer', '')))}</p><ul>{claims}</ul>"
        f"<h2>Sophia</h2><p>{html.escape(str(sophia.get('disposition', '')))}</p>"
        f"<h2>Atlas</h2><p>{html.escape(str(atlas.get('orientation', '')))}</p>"
        f"<h2>Human decision</h2><p>{html.escape(str(human.get('decision', 'PENDING')))}</p>"
        f"<meta name=\"csrf-token\" content=\"{html.escape(csrf_token)}\">"
        "</html>"
    )
    return body.encode("utf-8")


class _ReviewServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class _ReviewServerV6(_ReviewServer):
    address_family = socket.AF_INET6


def serve_review(run_root: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in {"127.0.0.1", "::1"} or not (0 <= port <= 65535):
        raise ContractError("serve host/port must be explicit loopback and valid")
    values = load_review(run_root.resolve(strict=True))
    csrf = secrets.token_urlsafe(32)
    page = render_review(values, csrf)

    class Handler(BaseHTTPRequestHandler):
        server_version = "TriadicBrainPrivateAlpha"
        sys_version = ""

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in SECURITY_HEADERS.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _policy(self) -> None:
            length = self.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > 4096):
                raise ContractError("request body too large")
            supplied = self.headers.get("X-CSRF-Token")
            validate_request_policy(
                method=self.command,
                host_header=self.headers.get("Host", ""),
                origin=self.headers.get("Origin"),
                fetch_site=self.headers.get("Sec-Fetch-Site"),
                client_host=self.client_address[0],
                csrf_token=supplied,
                expected_csrf_token=csrf,
            )

        def do_GET(self) -> None:  # noqa: N802
            try:
                self._policy()
                if self.path == "/health":
                    self._send(200, "application/json; charset=utf-8", b'{"authority_effect":"NONE","status":"ok"}\n')
                elif self.path in {"/", "/review"}:
                    self._send(200, "text/html; charset=utf-8", page)
                else:
                    self._send(404, "text/plain; charset=utf-8", b"not found\n")
            except ContractError:
                self._send(403, "text/plain; charset=utf-8", b"request refused\n")

        do_HEAD = do_GET

        def do_POST(self) -> None:  # noqa: N802
            try:
                self._policy()
                self._send(405, "text/plain; charset=utf-8", b"read-only review surface\n")
            except ContractError:
                self._send(403, "text/plain; charset=utf-8", b"request refused\n")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server_type = _ReviewServerV6 if host == "::1" else _ReviewServer
    server = server_type((host, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


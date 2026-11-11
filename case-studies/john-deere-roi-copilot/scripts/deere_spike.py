#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.32"]
# ///
"""Inventory what John Deere Operations Center credentials can actually see.

Answers one question: is `DeereProvider` a working client or a schema-faithful stub?

Writes `data/raw/deere-spike/inventory.json` (raw payloads) and `inventory.md`
(human-readable summary) so the result is reviewable without re-running OAuth.

Usage:
    cp .env.example .env      # fill in DEERE_CLIENT_ID / DEERE_CLIENT_SECRET
    ./scripts/deere_spike.py

Requires `http://localhost:9090/callback` registered as a Redirect URI on the
application profile at developer.deere.com.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import sys
import threading
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlencode, urlparse

import requests

WELL_KNOWN = (
    "https://signin.johndeere.com/oauth2/aus78tnlaysMraFhC1t7"
    "/.well-known/oauth-authorization-server"
)
SCOPES = "ag1 ag2 ag3 eq1 eq2 org1 org2 files offline_access"
ACCEPT = "application/vnd.deere.axiom.v3+json"
CALLBACK_PORT = 9090
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"
TIMEOUT = 30

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "deere-spike"

# Link rels worth probing, in the order they appear in the report. Probing the
# org's *advertised* rels rather than guessing paths matters: `machines` lives at
# `/isg/equipment?organizationIds=…`, not `/platform/organizations/{id}/machines`,
# so a hardcoded path reports a 403 that is really a wrong URL.
ORG_COLLECTION_RELS = [
    "clients",
    "farms",
    "fields",
    "boundaries",
    "machines",
    "assets",
    "fieldOperation",
    "operators",
    "files",
    "chemicals",
    "tankMixes",
    "varieties",
    "fertilizers",
]


@dataclass
class Probe:
    """Result of a single endpoint call."""

    path: str
    status: int
    count: int | None = None
    sample: Any = None
    error: str | None = None
    fields_seen: list[str] = field(default_factory=list)


def load_env() -> tuple[str, str, str]:
    """Read credentials from .env or the environment.

    Returns:
        (client_id, client_secret, base_url)

    Raises:
        SystemExit: if credentials are missing.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

    client_id = os.environ.get("DEERE_CLIENT_ID", "")
    client_secret = os.environ.get("DEERE_CLIENT_SECRET", "")
    base_url = os.environ.get("DEERE_BASE_URL", "https://sandboxapi.deere.com/platform")

    if not client_id or not client_secret:
        sys.exit(
            "Missing DEERE_CLIENT_ID / DEERE_CLIENT_SECRET.\n"
            f"Create {env_path} from .env.example and fill them in."
        )
    return client_id, client_secret, base_url


class _CallbackHandler(BaseHTTPRequestHandler):
    """Single-shot handler capturing the OAuth authorization code."""

    # Class-level: the server instantiates a fresh handler per request, so the
    # captured params have to outlive the instance.
    result: ClassVar[dict[str, str]] = {}

    def do_GET(self) -> None:
        params = parse_qs(urlparse(self.path).query)
        _CallbackHandler.result = {k: v[0] for k, v in params.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2>Authorized. You can close this tab.</h2>")

    def log_message(self, *_args: Any) -> None:
        """Silence the default stderr access log."""


def _await_callback() -> dict[str, str]:
    """Serve exactly one request on the callback port and return its query params."""
    server = HTTPServer(("localhost", CALLBACK_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout=300)
    server.server_close()
    if not _CallbackHandler.result:
        sys.exit("Timed out waiting for the OAuth callback (5 min).")
    return _CallbackHandler.result


def authorize(client_id: str, client_secret: str) -> str:
    """Run the authorization-code flow in the browser and return an access token."""
    meta = requests.get(WELL_KNOWN, timeout=TIMEOUT).json()
    state = secrets.token_urlsafe(16)

    auth_url = meta["authorization_endpoint"] + "?" + urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": SCOPES,
            "redirect_uri": REDIRECT_URI,
            "state": state,
        }
    )
    print(f"Opening browser for authorization...\n  {auth_url}\n")
    webbrowser.open(auth_url)

    params = _await_callback()
    if params.get("state") != state:
        sys.exit("State mismatch — aborting (possible CSRF).")
    if "code" not in params:
        sys.exit(f"No authorization code returned: {params}")

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        meta["token_endpoint"],
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": params["code"],
            "redirect_uri": REDIRECT_URI,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        sys.exit(f"Token exchange failed [{resp.status_code}]: {resp.text[:500]}")
    return resp.json()["access_token"]


def probe(session: requests.Session, base_url: str, path: str) -> Probe:
    """Call one endpoint and summarize what came back.

    Records status, item count, the field names present, and one sample record —
    enough to judge whether the data supports the ROI model.
    """
    url = path if path.startswith("http") else f"{base_url}/{path.lstrip('/')}"
    try:
        resp = session.get(url, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return Probe(path=path, status=0, error=str(exc))

    if resp.status_code != 200:
        return Probe(path=path, status=resp.status_code, error=resp.text[:300])

    try:
        body = resp.json()
    except ValueError:
        return Probe(path=path, status=resp.status_code, error="non-JSON response")

    values = body.get("values", []) if isinstance(body, dict) else []
    sample = values[0] if values else None
    return Probe(
        path=path,
        status=resp.status_code,
        count=len(values),
        sample=sample,
        fields_seen=sorted(sample.keys()) if isinstance(sample, dict) else [],
    )


def connection_state(org: dict[str, Any]) -> str:
    """Classify an organization's connection status from its HAL links.

    A `connections` link means authorization is incomplete and downstream
    collections will be empty. `manage_connections` means it is established.
    """
    rels = {link.get("rel") for link in org.get("links", [])}
    if "connections" in rels:
        return "INCOMPLETE — user must finish org authorization"
    # Deere documents the plural; the live sandbox sends the singular. Accept
    # both — matching only the documented spelling reports an established
    # connection as "unknown", which is the same failure as not checking at all.
    if rels & {"manage_connections", "manage_connection"}:
        return "established"
    return "unknown"


def rebase(uri: str, base_url: str) -> str:
    """Re-point a HAL link at the configured host.

    Deere's sandbox returns **production** URIs (`api.deere.com`) inside the
    links of organizations fetched from `sandboxapi.deere.com`. Following them
    verbatim — which is exactly what HAL invites a client to do — walks from
    sandbox into production against a real organization. Link URIs are therefore
    treated as identifiers, and every request is re-based onto the host we
    actually configured.

    Hosts that are not the Deere API (the connections dialog, for instance) are
    left alone: those are genuine production URLs a human is meant to visit.
    """
    parsed = urlparse(uri)
    if not parsed.netloc.endswith("api.deere.com"):
        return uri
    base = urlparse(base_url)
    return parsed._replace(scheme=base.scheme, netloc=base.netloc).geturl()


def connections_uri(org: dict[str, Any]) -> str | None:
    """Return the URI a user must visit to grant this org's access, if pending."""
    for link in org.get("links", []):
        if link.get("rel") == "connections":
            return f"{link['uri']}?redirect_uri={REDIRECT_URI}"
    return None


def render_markdown(base_url: str, orgs: list[dict], probes: dict[str, list[Probe]]) -> str:
    """Render the inventory as a reviewable report."""
    lines = [
        "# John Deere API — Access Inventory",
        "",
        f"Base URL: `{base_url}`",
        f"Scopes requested: `{SCOPES}`",
        "",
        "## Organizations",
        "",
        "| Name | ID | Type | Connection state |",
        "|---|---|---|---|",
    ]
    for org in orgs:
        lines.append(
            f"| {org.get('name', '?')} | {org.get('id', '?')} | "
            f"{org.get('type', '?')} | {connection_state(org)} |"
        )

    for org_id, results in probes.items():
        lines += ["", f"## Collections — org `{org_id}`", "",
                  "| Endpoint | Status | Count | Fields on first record |",
                  "|---|---|---|---|"]
        for p in results:
            detail = ", ".join(p.fields_seen[:12]) or (p.error or "—")
            count = "—" if p.count is None else str(p.count)
            lines.append(
                f"| `{p.path.split('/')[-1]}` | {p.status} | {count} | {detail} |"
            )

    lines += [
        "",
        "## Verdict",
        "",
        "_Fill in after review: is `DeereProvider` a live client or a stub?_",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    """Authenticate, probe every org collection, and write the inventory report."""
    client_id, client_secret, base_url = load_env()
    token = authorize(client_id, client_secret)

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "Accept": ACCEPT})

    org_probe = probe(session, base_url, "organizations")
    if org_probe.status != 200:
        sys.exit(f"Could not list organizations [{org_probe.status}]: {org_probe.error}")

    orgs_body = session.get(f"{base_url}/organizations", timeout=TIMEOUT).json()
    orgs = orgs_body.get("values", [])
    print(f"\nFound {len(orgs)} organization(s).\n")

    pending = [o for o in orgs if connection_state(o).startswith("INCOMPLETE")]
    for org in pending:
        uri = connections_uri(org)
        print(
            f"  ! '{org.get('name')}' needs org authorization before it returns data.\n"
            f"    Visit: {uri}\n"
        )

    probes: dict[str, list[Probe]] = {}
    for org in orgs:
        org_id = str(org.get("id"))
        print(f"  probing org {org_id} ({org.get('name')})...")
        by_rel = {link.get("rel"): link.get("uri") for link in org.get("links", [])}
        probes[org_id] = [
            probe(session, base_url, rebase(by_rel[rel], base_url))
            for rel in ORG_COLLECTION_RELS
            if rel in by_rel
        ]
        missing = [rel for rel in ORG_COLLECTION_RELS if rel not in by_rel]
        if missing:
            print(f"    (org advertises no link for: {', '.join(missing)})")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "inventory.json").write_text(
        json.dumps(
            {
                "base_url": base_url,
                "scopes": SCOPES,
                "organizations": orgs,
                "probes": {
                    k: [vars(p) for p in v] for k, v in probes.items()
                },
            },
            indent=2,
        )
    )
    (OUT_DIR / "inventory.md").write_text(render_markdown(base_url, orgs, probes))

    print(f"\nWrote {OUT_DIR / 'inventory.json'}")
    print(f"Wrote {OUT_DIR / 'inventory.md'}")
    if pending:
        print("\nComplete the org authorization links above, then re-run.")


if __name__ == "__main__":
    main()

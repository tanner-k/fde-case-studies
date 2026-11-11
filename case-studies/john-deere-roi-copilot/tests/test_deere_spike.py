"""Tests for the Deere API discovery spike's HAL-link interpretation.

The connection state is the single most confusing part of the Operations Center
API: an organization carrying a `connections` link returns HTTP 200 and an empty
`values` array for every downstream collection. Reading that as "no data" rather
than "not authorized yet" is the mistake this logic exists to prevent, so the
distinction is pinned here.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SPIKE = Path(__file__).resolve().parent.parent / "scripts" / "deere_spike.py"


def _load_spike() -> ModuleType:
    """Import the spike script by path — it is a PEP 723 script, not a package."""
    spec = importlib.util.spec_from_file_location("deere_spike", SPIKE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Must land in sys.modules before exec: @dataclass resolves annotations via
    # sys.modules[cls.__module__], which is None for an unregistered module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


spike = _load_spike()


def test_connections_link_means_authorization_is_incomplete():
    org = {"id": "1", "links": [{"rel": "connections", "uri": "https://c.deere.com/1"}]}
    assert spike.connection_state(org).startswith("INCOMPLETE")


def test_manage_connections_link_means_authorization_is_established():
    org = {"id": "1", "links": [{"rel": "manage_connections", "uri": "https://c/1"}]}
    assert spike.connection_state(org) == "established"


def test_singular_manage_connection_also_means_established():
    """Deere's docs say `manage_connections`; the live sandbox sends the singular.

    Observed 2026-08-12 against org 1234567 with a fully established connection.
    Matching only the documented plural reported a live connection as 'unknown'.
    """
    org = {"id": "1", "links": [{"rel": "manage_connection", "uri": "https://c/1"}]}
    assert spike.connection_state(org) == "established"


def test_absent_link_is_reported_as_unknown_not_established():
    """An org with no connection link must never read as authorized."""
    assert spike.connection_state({"id": "1", "links": []}) == "unknown"
    assert spike.connection_state({"id": "1"}) == "unknown"


def test_connections_uri_appends_the_registered_redirect():
    org = {"links": [{"rel": "connections", "uri": "https://connections.deere.com/1"}]}
    uri = spike.connections_uri(org)
    assert uri == f"https://connections.deere.com/1?redirect_uri={spike.REDIRECT_URI}"


def test_connections_uri_is_none_once_authorization_is_established():
    org = {"links": [{"rel": "manage_connections", "uri": "https://c/1"}]}
    assert spike.connections_uri(org) is None


# --- Sandbox links point at production (observed 2026-08-12) ----------------


def test_sandbox_links_are_rebased_onto_the_configured_host():
    """Deere's sandbox returns production URIs inside its HAL links.

    Following them verbatim walks from sandbox into production against a real
    organization. Every link must be re-based onto the configured base URL.
    """
    rebased = spike.rebase(
        "https://api.deere.com/platform/organizations/1234567/fields",
        "https://sandboxapi.deere.com/platform",
    )
    assert rebased == "https://sandboxapi.deere.com/platform/organizations/1234567/fields"


def test_rebase_preserves_query_strings():
    rebased = spike.rebase(
        "https://api.deere.com/isg/equipment?organizationIds=1234567",
        "https://sandboxapi.deere.com/platform",
    )
    assert rebased == "https://sandboxapi.deere.com/isg/equipment?organizationIds=1234567"


def test_rebase_leaves_a_foreign_host_alone():
    """The connections dialog is a real production URL the user must visit."""
    uri = "https://connections.deere.com/connections/abc/connections-dialog?orgId=1"
    assert spike.rebase(uri, "https://sandboxapi.deere.com/platform") == uri

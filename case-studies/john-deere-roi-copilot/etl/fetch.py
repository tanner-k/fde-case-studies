"""Cached, rate-limited HTTP fetching shared by the extractors.

These are batch jobs against free public services. Two rules follow from that:
never re-download something already on disk, and never hand a non-200 body to a
parser as if it were data. Both are enforced here so the extractors do not each
reinvent them.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol

import requests

USER_AGENT = "fde-portfolio-etl/0.1 (portfolio case study; contact via GitHub tanner-k)"
DEFAULT_TIMEOUT_S = 60
#: Minimum gap between outbound calls. Open-Meteo publishes no hard limit and
#: asks only that clients be reasonable; one call per second is well inside that.
DEFAULT_MIN_INTERVAL_S = 1.0

_last_request_at = 0.0


class FetchError(RuntimeError):
    """A request failed, or returned a status that is not 200."""


class HttpSession(Protocol):
    """The slice of `requests.Session` the extractors actually use."""

    def get(self, url: str, **kwargs: Any) -> Any:
        """Issue a GET request."""
        ...


def new_session() -> requests.Session:
    """Build a session with the project user agent set."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _throttle(min_interval_s: float) -> None:
    """Sleep until `min_interval_s` has elapsed since the last outbound call."""
    global _last_request_at
    if min_interval_s > 0:
        wait = min_interval_s - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
    _last_request_at = time.monotonic()


def fetch_bytes(
    url: str,
    dest: Path,
    *,
    session: HttpSession | None = None,
    params: dict[str, str] | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
) -> bytes:
    """Return the body at `url`, downloading it only if `dest` is not already populated.

    Args:
        url: Absolute URL to fetch.
        dest: Cache location. A non-empty file here short-circuits the request.
        session: HTTP session; a throwaway one is created if omitted.
        params: Query parameters.
        timeout_s: Per-request timeout.
        min_interval_s: Minimum gap since the previous call made through this module.

    Returns:
        The response body, or the cached file's contents.

    Raises:
        FetchError: On a transport failure or any status other than 200.
    """
    if dest.exists() and dest.stat().st_size > 0:
        return dest.read_bytes()

    client = session if session is not None else new_session()
    _throttle(min_interval_s)
    try:
        response = client.get(url, params=params, timeout=timeout_s)
    except requests.RequestException as exc:
        raise FetchError(f"GET {url} failed: {exc}") from exc

    if response.status_code != 200:
        raise FetchError(
            f"GET {url} returned HTTP {response.status_code}. "
            f"First 300 bytes of the body: {response.text[:300]!r}"
        )

    body: bytes = response.content
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Write via a temp file so an interrupted run cannot leave a truncated cache
    # entry that a later run would happily treat as complete.
    tmp = dest.with_suffix(dest.suffix + ".partial")
    tmp.write_bytes(body)
    tmp.replace(dest)
    return body

"""Tests for the shared cached-fetch helper.

The extractors are offline batch jobs run against free public services, so the
two behaviours that matter are: never re-download something already on disk,
and never let a non-200 response reach a parser as if it were data.
"""

import pytest
import requests
from etl import fetch


class _ExplodingSession:
    """Stand-in that fails the test if any network call is attempted."""

    def get(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("network call attempted when the cache should have been used")


class _StubResponse:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content
        self.text = content.decode("utf-8", "replace")


class _StubSession:
    def __init__(self, response: _StubResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url: str, params: dict | None = None, **_kwargs: object) -> _StubResponse:
        self.calls.append((url, params))
        return self.response


def test_cached_file_is_returned_without_touching_the_network(tmp_path):
    dest = tmp_path / "corn.csv"
    dest.write_bytes(b"already here")
    got = fetch.fetch_bytes(
        "https://example.test/corn.csv", dest, session=_ExplodingSession(), min_interval_s=0.0
    )
    assert got == b"already here"


def test_missing_file_is_downloaded_and_written_to_the_cache(tmp_path):
    dest = tmp_path / "nested" / "corn.csv"
    session = _StubSession(_StubResponse(200, b"col\n1\n"))
    got = fetch.fetch_bytes(
        "https://example.test/corn.csv", dest, session=session, min_interval_s=0.0
    )
    assert got == b"col\n1\n"
    assert dest.read_bytes() == b"col\n1\n"
    assert session.calls == [("https://example.test/corn.csv", None)]


def test_non_200_raises_with_the_url_and_status_in_the_message(tmp_path):
    dest = tmp_path / "corn.csv"
    session = _StubSession(_StubResponse(404, b"nope"))
    with pytest.raises(fetch.FetchError) as exc:
        fetch.fetch_bytes(
            "https://example.test/corn.csv", dest, session=session, min_interval_s=0.0
        )
    assert "404" in str(exc.value)
    assert "https://example.test/corn.csv" in str(exc.value)
    assert not dest.exists(), "a failed fetch must not poison the cache"


def test_transport_failure_is_wrapped_in_fetch_error(tmp_path):
    class _Failing:
        def get(self, *_args: object, **_kwargs: object) -> object:
            raise requests.RequestException("connection reset")

    with pytest.raises(fetch.FetchError, match="connection reset"):
        fetch.fetch_bytes(
            "https://example.test/x", tmp_path / "x", session=_Failing(), min_interval_s=0.0
        )


def test_empty_cached_file_is_re_downloaded(tmp_path):
    """A zero-byte file is a truncated write, not a cache hit."""
    dest = tmp_path / "corn.csv"
    dest.touch()
    session = _StubSession(_StubResponse(200, b"real"))
    assert fetch.fetch_bytes(
        "https://example.test/corn.csv", dest, session=session, min_interval_s=0.0
    ) == b"real"

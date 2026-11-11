"""USDA NASS Quick Stats — county yield and state price history.

**Status: not verified end to end.** This module was written without an API key.
The request construction and response parsing are pinned by unit test against a
synthetic fixture; the only live behaviour confirmed is that a missing or bad key
returns HTTP 401 with body `{"error":["unauthorized"]}`. Treat a first real run
as an experiment, not a regression.

**Geography.** Yield is published at county level. `PRICE RECEIVED` is not — NASS
publishes it at state and national level only — so the price pull is a separate,
explicitly state-level query rather than a county query that would silently come
back empty.

Query parameters accept the operator suffixes `__LE __LT __GT __GE __LIKE
__NOT_LIKE __NE`; the year range below uses `__GE` / `__LE`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import polars as pl

from etl.fetch import HttpSession, fetch_bytes

API_URL = "https://quickstats.nass.usda.gov/api/api_GET/"
API_KEY_ENV = "NASS_API_KEY"
SIGNUP_URL = "https://quickstats.nass.usda.gov/api"
#: Hard cap the API enforces per request. A response of exactly this size is a
#: truncated result, not a complete one.
RECORD_LIMIT = 50_000

STATE_ALPHA = "IA"
COMMODITIES: tuple[str, ...] = ("CORN", "SOYBEANS")
DEFAULT_START_YEAR = 2006
DEFAULT_END_YEAR = 2025

#: Documented NASS non-numeric markers. `(D)` is disclosure suppression. Anything
#: outside this set is schema drift and is raised rather than nulled.
SUPPRESSION_CODES = frozenset({"", "(D)", "(H)", "(L)", "(NA)", "(S)", "(X)", "(Z)"})

#: County code NASS uses for its pooled "OTHER COUNTIES" disclosure bucket.
COUNTY_AGGREGATE_SUFFIX = "998"

REQUIRED_FIELDS = (
    "commodity_desc",
    "statisticcat_desc",
    "agg_level_desc",
    "state_alpha",
    "county_name",
    "unit_desc",
    "short_desc",
    "year",
    "Value",
)

NORMALIZED_SCHEMA: dict[str, pl.DataType] = {
    "commodity": pl.String(),
    "statistic": pl.String(),
    "agg_level": pl.String(),
    "state_alpha": pl.String(),
    "county_name": pl.String(),
    "county_fips": pl.String(),
    "year": pl.Int32(),
    "unit": pl.String(),
    "short_desc": pl.String(),
    "value": pl.Float64(),
}
NORMALIZED_COLUMNS = tuple(NORMALIZED_SCHEMA)


class MissingApiKeyError(RuntimeError):
    """`NASS_API_KEY` is absent or blank."""


class QuickStatsError(RuntimeError):
    """The API returned an error, or a body this module cannot trust."""


@dataclass(frozen=True)
class QuerySpec:
    """One Quick Stats query, minus the key and the year range."""

    name: str
    params: Mapping[str, str]


_COMMON = {
    "source_desc": "SURVEY",
    "sector_desc": "CROPS",
    "state_alpha": STATE_ALPHA,
    "freq_desc": "ANNUAL",
}

#: NASS files corn silage under the same `statisticcat_desc=YIELD` as grain, but
#: reports it in TONS / ACRE. Fitting a distribution over the mixed result would
#: average tons with bushels. Only corn has this utilization split.
UTIL_PRACTICE_BY_COMMODITY: Mapping[str, str] = MappingProxyType({"CORN": "GRAIN"})

COUNTY_YIELD = QuerySpec(
    "county_yield",
    MappingProxyType({**_COMMON, "statisticcat_desc": "YIELD", "agg_level_desc": "COUNTY"}),
)
# State level deliberately: NASS does not publish PRICE RECEIVED by county.
STATE_PRICE = QuerySpec(
    "state_price",
    MappingProxyType(
        {**_COMMON, "statisticcat_desc": "PRICE RECEIVED", "agg_level_desc": "STATE"}
    ),
)
SPECS: tuple[QuerySpec, ...] = (COUNTY_YIELD, STATE_PRICE)


def api_key(env: Mapping[str, str] | None = None) -> str:
    """Read the Quick Stats API key from the environment.

    Args:
        env: Environment mapping; defaults to `os.environ`.

    Returns:
        The key, stripped.

    Raises:
        MissingApiKeyError: If the variable is unset or blank.
    """
    source = os.environ if env is None else env
    key = source.get(API_KEY_ENV, "").strip()
    if not key:
        raise MissingApiKeyError(
            f"{API_KEY_ENV} is not set. Request a free key at {SIGNUP_URL}, then either "
            f"export {API_KEY_ENV}=... or add it to the case study's .env file. "
            "Without it the API returns HTTP 401 for every request."
        )
    return key


def build_params(
    spec: QuerySpec,
    *,
    key: str,
    start_year: int = DEFAULT_START_YEAR,
    end_year: int = DEFAULT_END_YEAR,
    commodity: str | None = None,
) -> dict[str, str]:
    """Build the full query string for one Quick Stats request.

    Args:
        spec: Which statistic and aggregation level to pull.
        key: API key.
        start_year: First year, inclusive.
        end_year: Last year, inclusive.
        commodity: `CORN` or `SOYBEANS`; omitted means every commodity.

    Returns:
        A new parameter mapping.

    Raises:
        ValueError: If the year range is reversed or the commodity is unknown.
    """
    if start_year > end_year:
        raise ValueError(f"start_year {start_year} is after end_year {end_year}")
    if commodity is not None and commodity not in COMMODITIES:
        raise ValueError(f"commodity {commodity!r} is not one of {COMMODITIES}")

    # Utilization only disambiguates yield; PRICE RECEIVED has no silage variant.
    utilization = (
        {"util_practice_desc": UTIL_PRACTICE_BY_COMMODITY[commodity]}
        if commodity in UTIL_PRACTICE_BY_COMMODITY and spec is COUNTY_YIELD
        else {}
    )
    return {
        **dict(spec.params),
        "key": key,
        "format": "JSON",
        "year__GE": str(start_year),
        "year__LE": str(end_year),
        **({"commodity_desc": commodity} if commodity else {}),
        **utilization,
    }


def _parse_value(raw: object) -> float | None:
    """Convert a Quick Stats `Value` cell to a float, or null for a known marker.

    Raises:
        QuickStatsError: If the cell is neither numeric nor a documented marker.
    """
    text = str(raw).strip()
    if text in SUPPRESSION_CODES:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError as exc:
        raise QuickStatsError(
            f"Quick Stats returned Value={text!r}, which is neither numeric nor one of the "
            f"documented markers {sorted(SUPPRESSION_CODES)}. Refusing to guess."
        ) from exc


def _county_fips(record: Mapping[str, Any]) -> str | None:
    """Build a 5-digit county FIPS, or None for a non-county record."""
    state = str(record.get("state_fips_code", "")).strip()
    county = str(record.get("county_code", "")).strip()
    if len(state) == 2 and len(county) == 3:
        return state + county
    return None


def parse_response(payload: object, *, record_limit: int = RECORD_LIMIT) -> pl.DataFrame:
    """Validate a Quick Stats response body and normalize it.

    Args:
        payload: Decoded JSON body.
        record_limit: Row count that indicates the API clipped the result.

    Returns:
        A frame with exactly `NORMALIZED_COLUMNS`.

    Raises:
        QuickStatsError: On an error body, an unexpected shape, a missing field,
            an unrecognised value marker, or a result at the record cap.
    """
    if not isinstance(payload, dict):
        raise QuickStatsError(f"expected a JSON object with a 'data' array, got {type(payload)}")
    if "error" in payload:
        raise QuickStatsError(
            f"Quick Stats returned an error: {payload['error']}. "
            f"'unauthorized' means {API_KEY_ENV} is missing or invalid — see {SIGNUP_URL}."
        )
    records = payload.get("data")
    if not isinstance(records, list):
        raise QuickStatsError(f"response has no 'data' array; keys present: {sorted(payload)}")
    if len(records) >= record_limit:
        raise QuickStatsError(
            f"got {len(records)} records against a cap of {record_limit} — the result is "
            "truncated. Narrow the query (fewer years or one commodity at a time)."
        )

    rows = [_normalize_record(record, index) for index, record in enumerate(records)]
    rows = [row for row in rows if not _is_county_aggregate(row)]
    return pl.DataFrame(rows, schema=NORMALIZED_SCHEMA)


def _is_county_aggregate(row: Mapping[str, Any]) -> bool:
    """True for NASS's phantom "OTHER COUNTIES" buckets.

    NASS pools counties whose values are withheld for disclosure into a
    pseudo-county with county code 998, still tagged `agg_level_desc=COUNTY`.
    Iowa yields therefore arrive as 101 "counties" for 99 real ones. Left in, it
    becomes a phantom row in any per-county panel and a spurious observation in a
    fitted yield distribution, so it is dropped at the boundary rather than left
    for every downstream consumer to remember.
    """
    fips = row.get("county_fips")
    return bool(fips) and str(fips).endswith(COUNTY_AGGREGATE_SUFFIX)


def _normalize_record(record: object, index: int) -> dict[str, Any]:
    """Map one Quick Stats record onto the normalized schema.

    Raises:
        QuickStatsError: If the record is not an object or is missing a field.
    """
    if not isinstance(record, dict):
        raise QuickStatsError(f"record {index} is {type(record)}, expected an object")
    missing = [f for f in REQUIRED_FIELDS if f not in record]
    if missing:
        raise QuickStatsError(f"record {index} is missing required fields: {missing}")

    return {
        "commodity": str(record["commodity_desc"]),
        "statistic": str(record["statisticcat_desc"]),
        "agg_level": str(record["agg_level_desc"]),
        "state_alpha": str(record["state_alpha"]),
        "county_name": str(record["county_name"]),
        "county_fips": _county_fips(record),
        "year": int(record["year"]),
        "unit": str(record["unit_desc"]),
        "short_desc": str(record["short_desc"]),
        "value": _parse_value(record["Value"]),
    }


def extract(
    cache_dir: Path,
    out_path: Path,
    *,
    session: HttpSession | None = None,
    key: str | None = None,
    start_year: int = DEFAULT_START_YEAR,
    end_year: int = DEFAULT_END_YEAR,
) -> pl.DataFrame:
    """Pull every spec/commodity combination and write one parquet panel.

    Args:
        cache_dir: Where raw JSON responses are cached; existing files are reused.
        out_path: Destination parquet file.
        session: HTTP session to reuse.
        key: API key; read from the environment when omitted.
        start_year: First year, inclusive.
        end_year: Last year, inclusive.

    Returns:
        The normalized frame that was written.

    Raises:
        MissingApiKeyError: If no key is available.
    """
    resolved = key if key is not None else api_key()
    frames: list[pl.DataFrame] = []
    for spec in SPECS:
        for commodity in COMMODITIES:
            params = build_params(
                spec,
                key=resolved,
                start_year=start_year,
                end_year=end_year,
                commodity=commodity,
            )
            body = fetch_bytes(
                API_URL,
                cache_dir / f"{spec.name}_{commodity.lower()}_{start_year}_{end_year}.json",
                session=session,
                params=params,
            )
            frames.append(parse_response(json.loads(body)))

    panel = pl.concat(frames, how="vertical").sort(
        "commodity", "statistic", "county_name", "year"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(out_path)
    return panel

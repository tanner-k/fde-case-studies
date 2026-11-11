"""USDA NASS Crop Progress — Iowa planting, harvest, and days suitable for fieldwork.

**Why this module exists.** Phase 1's landscape exhibit put agronomic window
length on an axis and filled it with author estimates, which left the gate
unable to distinguish a wrong thesis from wrong inputs
(`deliverables/appendix/assumptions.md` §11.3). NASS publishes the measurement:
weekly percent-complete for planting and harvest, and — separately — the number
of days in each week that were suitable for fieldwork at all.

**Two series types, one panel.** Progress is a percentage of acres complete,
filed per commodity under `statisticcat_desc=PROGRESS`. Days suitable is a
count of days per week, filed under the pseudo-commodity `FIELDWORK` with
`statisticcat_desc=DAYS SUITABLE`. They share a weekly, state-level shape, so
they land in one panel distinguished by `series_key`.

**Corn grain harvest is filed under a different commodity string than corn
planting** — `CORN, GRAIN - PROGRESS, MEASURED IN PCT HARVESTED` against
`CORN - PROGRESS, MEASURED IN PCT PLANTED`. Querying the obvious-looking string
returns an empty result rather than an error, so each series names its
`short_desc` explicitly and the extractor refuses an empty series.

**State level only.** NASS does not publish crop progress by county; the
weekly survey is a statewide panel of reporters. Every window this feeds is
therefore a statewide quantity and an upper bound on any single farm's window.

Verified against the live API on 2026-08-16: 21 years of progress (2006-2026)
and 400 weekly days-suitable observations (from 2015-04-05).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from etl.fetch import HttpSession, fetch_bytes
from etl.nass import API_URL, RECORD_LIMIT, QuickStatsError, api_key

STATE_ALPHA = "IA"
DEFAULT_START_YEAR = 2006
DEFAULT_END_YEAR = 2026

#: Documented NASS non-numeric markers. A `(D)` parsed as 0.0 would read as an
#: operation that never started, which silently widens every measured window.
SUPPRESSION_CODES = frozenset({"", "(D)", "(H)", "(L)", "(NA)", "(S)", "(X)", "(Z)"})

REQUIRED_FIELDS = ("short_desc", "unit_desc", "week_ending", "year", "Value")

PROGRESS_SCHEMA: dict[str, pl.DataType] = {
    "series_key": pl.String(),
    "commodity": pl.String(),
    "year": pl.Int32(),
    "week_ending": pl.Date(),
    "unit": pl.String(),
    "value": pl.Float64(),
}
PROGRESS_COLUMNS = tuple(PROGRESS_SCHEMA)


@dataclass(frozen=True)
class SeriesSpec:
    """One NASS series, named exactly enough that a typo returns an error not silence."""

    key: str
    commodity_desc: str
    statisticcat_desc: str
    short_desc: str


SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        "corn_planted", "CORN", "PROGRESS", "CORN - PROGRESS, MEASURED IN PCT PLANTED"
    ),
    SeriesSpec(
        "soybean_planted",
        "SOYBEANS",
        "PROGRESS",
        "SOYBEANS - PROGRESS, MEASURED IN PCT PLANTED",
    ),
    SeriesSpec(
        "corn_harvested",
        "CORN",
        "PROGRESS",
        "CORN, GRAIN - PROGRESS, MEASURED IN PCT HARVESTED",
    ),
    SeriesSpec(
        "soybean_harvested",
        "SOYBEANS",
        "PROGRESS",
        "SOYBEANS - PROGRESS, MEASURED IN PCT HARVESTED",
    ),
    SeriesSpec(
        "days_suitable",
        "FIELDWORK",
        "DAYS SUITABLE",
        "FIELDWORK - DAYS SUITABLE, MEASURED IN DAYS / WEEK",
    ),
)


def build_params(
    spec: SeriesSpec,
    *,
    key: str,
    start_year: int = DEFAULT_START_YEAR,
    end_year: int = DEFAULT_END_YEAR,
) -> dict[str, str]:
    """Build the query for one series.

    Args:
        spec: Which series to pull.
        key: Quick Stats API key.
        start_year: First year, inclusive.
        end_year: Last year, inclusive.

    Returns:
        A new parameter mapping, pinned to Iowa at state aggregation.

    Raises:
        ValueError: If the year range is reversed.
    """
    if start_year > end_year:
        raise ValueError(f"start_year {start_year} is after end_year {end_year}")
    return {
        "key": key,
        "format": "JSON",
        "source_desc": "SURVEY",
        "commodity_desc": spec.commodity_desc,
        "statisticcat_desc": spec.statisticcat_desc,
        "short_desc": spec.short_desc,
        "state_alpha": STATE_ALPHA,
        "agg_level_desc": "STATE",
        "freq_desc": "WEEKLY",
        "year__GE": str(start_year),
        "year__LE": str(end_year),
    }


def _parse_value(raw: object) -> float | None:
    """Convert a `Value` cell to a float, or null for a documented marker.

    Raises:
        QuickStatsError: If the cell is neither numeric nor a known marker.
    """
    text = str(raw).strip()
    if text in SUPPRESSION_CODES:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError as exc:
        raise QuickStatsError(
            f"Crop Progress returned Value={text!r}, which is neither numeric nor one of "
            f"the documented markers {sorted(SUPPRESSION_CODES)}. Refusing to guess."
        ) from exc


def _normalize(record: object, *, spec: SeriesSpec, index: int) -> dict[str, Any] | None:
    """Map one record onto the panel schema, or None if its value is suppressed.

    Raises:
        QuickStatsError: If the record is not an object or is missing a field.
    """
    if not isinstance(record, dict):
        raise QuickStatsError(f"record {index} is {type(record)}, expected an object")
    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        raise QuickStatsError(f"record {index} is missing required fields: {missing}")

    value = _parse_value(record["Value"])
    if value is None:
        return None
    return {
        "series_key": spec.key,
        "commodity": str(record.get("commodity_desc", spec.commodity_desc)),
        "year": int(record["year"]),
        "week_ending": date.fromisoformat(str(record["week_ending"])),
        "unit": str(record["unit_desc"]),
        "value": value,
    }


def parse_series(
    payload: object, *, spec: SeriesSpec, record_limit: int = RECORD_LIMIT
) -> pl.DataFrame:
    """Validate one series response and normalize it onto the panel schema.

    Args:
        payload: Decoded JSON body.
        spec: The series this body was requested for.
        record_limit: Row count that indicates the API clipped the result.

    Returns:
        A frame with exactly `PROGRESS_COLUMNS`. Suppressed values are dropped
        rather than nulled — a null percentage is not a data point, and leaving
        it in would put a hole in the middle of an interpolated crossing.

    Raises:
        QuickStatsError: On an error body, an unexpected shape, a missing field,
            an unrecognised value marker, or a result at the record cap.
    """
    if not isinstance(payload, dict):
        raise QuickStatsError(f"expected a JSON object with a 'data' array, got {type(payload)}")
    if "error" in payload:
        raise QuickStatsError(
            f"Quick Stats returned an error: {payload['error']}. "
            "'unauthorized' means NASS_API_KEY is missing or invalid."
        )
    records = payload.get("data")
    if not isinstance(records, list):
        raise QuickStatsError(f"response has no 'data' array; keys present: {sorted(payload)}")
    if len(records) >= record_limit:
        raise QuickStatsError(
            f"got {len(records)} records against a cap of {record_limit} — the result is "
            "truncated. Narrow the query (fewer years, or one series at a time)."
        )

    rows = [
        row
        for index, record in enumerate(records)
        if (row := _normalize(record, spec=spec, index=index)) is not None
    ]
    return pl.DataFrame(rows, schema=PROGRESS_SCHEMA)


def extract(
    cache_dir: Path,
    out_path: Path,
    *,
    session: HttpSession | None = None,
    key: str | None = None,
    start_year: int = DEFAULT_START_YEAR,
    end_year: int = DEFAULT_END_YEAR,
) -> pl.DataFrame:
    """Pull every series and write one parquet panel.

    Args:
        cache_dir: Where raw JSON responses are cached; existing files are reused.
        out_path: Destination parquet file.
        session: HTTP session to reuse.
        key: API key; read from the environment when omitted.
        start_year: First year, inclusive.
        end_year: Last year, inclusive.

    Returns:
        The normalized panel that was written.

    Raises:
        MissingApiKeyError: If no key is available.
        QuickStatsError: If any series comes back empty — a series that returns
            no rows means its `short_desc` no longer matches what NASS files,
            which is silent data loss rather than an error at the HTTP level.
    """
    resolved = key if key is not None else api_key()
    frames: list[pl.DataFrame] = []
    for spec in SERIES:
        body = fetch_bytes(
            API_URL,
            cache_dir / f"crop_progress_{spec.key}_{start_year}_{end_year}.json",
            session=session,
            params=build_params(spec, key=resolved, start_year=start_year, end_year=end_year),
        )
        frame = parse_series(json.loads(body), spec=spec)
        if frame.is_empty():
            raise QuickStatsError(
                f"series {spec.key!r} returned no rows for {start_year}-{end_year}. "
                f"Its short_desc ({spec.short_desc!r}) probably no longer matches what NASS "
                "files — an unmatched short_desc returns an empty result, not an error."
            )
        frames.append(frame)

    panel = pl.concat(frames, how="vertical").sort("series_key", "week_ending")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(out_path)
    return panel

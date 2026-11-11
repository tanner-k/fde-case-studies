"""Open-Meteo historical archive — daily weather at Iowa county centroids.

Two footguns are handled explicitly.

**Units.** Omitting `temperature_unit` / `precipitation_unit` returns Celsius and
millimetres with no error and no implausible-looking numbers. The request states
both, and `parse_archive` then *asserts* them back out of the response's
`daily_units` block rather than trusting the request it just sent.

**Geography.** The API answers from the nearest ~11 km ERA5 grid cell, not the
requested point, so the returned lat/lon is carried on every row. County
centroids come from the Census county gazetteer — no coordinate in this module
is hand-entered.

The service is free and asks only that clients be reasonable: calls go through
`etl.fetch`, which throttles and caches every response to disk, so a re-run
downloads nothing it already has.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from etl.fetch import HttpSession, fetch_bytes

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
#: Census county gazetteer — the source of every centroid used here.
GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer"
    "/2023_Gazetteer/2023_Gaz_counties_national.zip"
)

DAILY_VARIABLES = ("temperature_2m_max", "temperature_2m_min", "precipitation_sum")
TEMPERATURE_UNIT = "fahrenheit"
PRECIPITATION_UNIT = "inch"
TIMEZONE = "America/Chicago"
#: What `daily_units` must report back for the request above to have been honoured.
EXPECTED_UNITS = {
    "temperature_2m_max": "°F",
    "temperature_2m_min": "°F",
    "precipitation_sum": "inch",
}

STATE = "IA"
#: Verified coverage floor for this endpoint; ERA5 itself reaches 1940.
EARLIEST_DATE = date(1980, 1, 1)

_VARIABLE_TO_COLUMN = {
    "temperature_2m_max": "tmax_f",
    "temperature_2m_min": "tmin_f",
    "precipitation_sum": "precip_in",
}

NORMALIZED_SCHEMA: dict[str, pl.DataType] = {
    "county_fips": pl.String(),
    "county_name": pl.String(),
    "date": pl.Date(),
    "tmax_f": pl.Float64(),
    "tmin_f": pl.Float64(),
    "precip_in": pl.Float64(),
    "grid_latitude": pl.Float64(),
    "grid_longitude": pl.Float64(),
}
NORMALIZED_COLUMNS = tuple(NORMALIZED_SCHEMA)


class ArchiveError(RuntimeError):
    """The archive response is an error, or a shape this module cannot trust."""


class UnitMismatchError(ArchiveError):
    """The response came back in units other than the ones requested."""


class GazetteerError(RuntimeError):
    """The gazetteer file is not the shape this module was written against."""


@dataclass(frozen=True)
class Centroid:
    """A county's interior point, from the Census gazetteer."""

    fips: str
    name: str
    latitude: float
    longitude: float


def parse_gazetteer(text: str, *, state: str = STATE) -> tuple[Centroid, ...]:
    """Extract one state's county centroids from the tab-delimited gazetteer.

    Args:
        text: Decoded gazetteer file.
        state: USPS state code, e.g. `IA`.

    Returns:
        Centroids in file order.

    Raises:
        GazetteerError: If a required column is absent or the state has no rows.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise GazetteerError("gazetteer file is empty")

    # The published header pads its final column with trailing spaces.
    header = [column.strip() for column in lines[0].split("\t")]
    required = ("USPS", "GEOID", "NAME", "INTPTLAT", "INTPTLONG")
    missing = [column for column in required if column not in header]
    if missing:
        raise GazetteerError(f"gazetteer is missing columns {missing}; found {header}")
    index = {column: position for position, column in enumerate(header)}

    centroids = tuple(
        Centroid(
            fips=cells[index["GEOID"]].strip(),
            name=cells[index["NAME"]].strip(),
            latitude=float(cells[index["INTPTLAT"]]),
            longitude=float(cells[index["INTPTLONG"]]),
        )
        for cells in (line.split("\t") for line in lines[1:])
        if cells[index["USPS"]].strip() == state
    )
    if not centroids:
        raise GazetteerError(f"gazetteer contains no counties for state {state!r}")
    return centroids


def fetch_centroids(
    cache_dir: Path, *, state: str = STATE, session: HttpSession | None = None
) -> tuple[Centroid, ...]:
    """Download (once) and parse the county gazetteer.

    Args:
        cache_dir: Where the zip is cached.
        state: USPS state code.
        session: HTTP session to reuse.

    Returns:
        The state's county centroids.

    Raises:
        GazetteerError: If the archive does not contain exactly one file.
    """
    raw = fetch_bytes(GAZETTEER_URL, cache_dir / "gaz_counties_national.zip", session=session)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(names) != 1:
            raise GazetteerError(f"expected one file in the gazetteer zip, found {names}")
        text = archive.read(names[0]).decode("utf-8")
    return parse_gazetteer(text, state=state)


def build_params(centroid: Centroid, start: date, end: date) -> dict[str, str]:
    """Build the archive query, stating every unit explicitly.

    Args:
        centroid: Point to query.
        start: First day, inclusive.
        end: Last day, inclusive.

    Returns:
        A new parameter mapping.

    Raises:
        ValueError: If the range is reversed or starts before verified coverage.
    """
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    if start < EARLIEST_DATE:
        raise ValueError(f"start {start} precedes verified archive coverage ({EARLIEST_DATE})")
    return {
        "latitude": str(centroid.latitude),
        "longitude": str(centroid.longitude),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": ",".join(DAILY_VARIABLES),
        "temperature_unit": TEMPERATURE_UNIT,
        "precipitation_unit": PRECIPITATION_UNIT,
        "timezone": TIMEZONE,
    }


def _check_units(payload: dict) -> None:
    """Verify the response's declared units against what was requested.

    Raises:
        ArchiveError: If `daily_units` is absent.
        UnitMismatchError: If any variable came back in the wrong unit.
    """
    units = payload.get("daily_units")
    if not isinstance(units, dict):
        raise ArchiveError(
            "response has no daily_units block, so its units cannot be verified. "
            f"Keys present: {sorted(payload)}"
        )
    for variable, expected in EXPECTED_UNITS.items():
        actual = units.get(variable)
        if actual != expected:
            raise UnitMismatchError(
                f"{variable} came back as {actual!r}, expected {expected!r}. "
                "Open-Meteo defaults to Celsius/mm when the unit parameters are dropped — "
                "check temperature_unit and precipitation_unit on the request."
            )


def parse_archive(payload: object, centroid: Centroid) -> pl.DataFrame:
    """Validate one archive response and normalize it to daily rows.

    Args:
        payload: Decoded JSON body.
        centroid: The county this response was requested for.

    Returns:
        A frame with exactly `NORMALIZED_COLUMNS`, one row per day.

    Raises:
        ArchiveError: On an error body, a missing block, or ragged series.
        UnitMismatchError: If the units are not the ones requested.
    """
    if not isinstance(payload, dict):
        raise ArchiveError(f"expected a JSON object, got {type(payload)}")
    if payload.get("error"):
        raise ArchiveError(f"archive API error: {payload.get('reason', payload['error'])}")

    _check_units(payload)

    daily = payload.get("daily")
    if not isinstance(daily, dict) or "time" not in daily:
        raise ArchiveError(f"response has no daily.time series; keys present: {sorted(payload)}")

    days = daily["time"]
    for variable in DAILY_VARIABLES:
        series = daily.get(variable)
        if not isinstance(series, list) or len(series) != len(days):
            got = len(series) if isinstance(series, list) else series
            raise ArchiveError(
                f"daily.{variable} has length {got}, expected {len(days)} to match daily.time"
            )

    height = len(days)
    return pl.DataFrame(
        {
            "county_fips": [centroid.fips] * height,
            "county_name": [centroid.name] * height,
            "date": days,
            **{
                _VARIABLE_TO_COLUMN[variable]: daily[variable] for variable in DAILY_VARIABLES
            },
            "grid_latitude": [payload.get("latitude")] * height,
            "grid_longitude": [payload.get("longitude")] * height,
        },
        schema={**NORMALIZED_SCHEMA, "date": pl.String()},
    ).with_columns(pl.col("date").str.to_date("%Y-%m-%d"))


def extract(
    centroids: Sequence[Centroid],
    start: date,
    end: date,
    cache_dir: Path,
    out_path: Path,
    *,
    session: HttpSession | None = None,
) -> pl.DataFrame:
    """Pull the daily archive for every centroid and write one parquet panel.

    Each county's raw response is cached under `cache_dir` keyed by FIPS and date
    range, so re-running only fetches what is missing.

    Args:
        centroids: Counties to pull.
        start: First day, inclusive.
        end: Last day, inclusive.
        cache_dir: Where raw JSON responses are cached.
        out_path: Destination parquet file.
        session: HTTP session to reuse.

    Returns:
        The normalized frame that was written.

    Raises:
        ValueError: If `centroids` is empty.
    """
    if not centroids:
        raise ValueError("no centroids given; nothing to extract")

    span = f"{start.isoformat()}_{end.isoformat()}"
    frames = [
        parse_archive(
            json.loads(
                fetch_bytes(
                    ARCHIVE_URL,
                    cache_dir / f"{centroid.fips}_{span}.json",
                    session=session,
                    params=build_params(centroid, start, end),
                )
            ),
            centroid,
        )
        for centroid in centroids
    ]
    panel = pl.concat(frames, how="vertical").sort("county_fips", "date")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(out_path)
    return panel

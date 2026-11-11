"""USDA ERS commodity costs and returns — download and normalize.

Two schemas, one output. The historical files (`corn.csv`, `soybeans.csv`) carry
ten columns and an integer year; the forecast file carries seven and a year like
`2026F`. They are normalized into one frame with an explicit `is_forecast` flag
and nulls where the forecast file genuinely has no column — rather than being
flattened into a shape that implies the forecast rows have a survey base year.

Geography is the ERS **Farm Resource Region** (Iowa falls in `Heartland`). This
is the finest cut ERS publishes; there is no county resolution here and none is
synthesised.

The published URLs carry a `?v=` cache-buster that changes on republication, so
it is omitted — pinning it would break the extractor on the next revision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from etl.fetch import HttpSession, fetch_bytes

BASE_URL = "https://www.ers.usda.gov/media"

HISTORICAL_COLUMNS = (
    "Commodity",
    "Category",
    "Item",
    "Units",
    "Size",
    "Region",
    "Country",
    "Year",
    "Value",
    "Survey base year",
)
FORECAST_COLUMNS = ("Commodity", "Category", "Item", "Units", "Region", "Year", "Value")

NORMALIZED_SCHEMA: dict[str, pl.DataType] = {
    "source": pl.String(),
    "commodity": pl.String(),
    "category": pl.String(),
    "item": pl.String(),
    "units": pl.String(),
    "region": pl.String(),
    "year": pl.Int32(),
    "is_forecast": pl.Boolean(),
    "value": pl.Float64(),
    "size": pl.String(),
    "country": pl.String(),
    "survey_base_year": pl.String(),
}
NORMALIZED_COLUMNS = tuple(NORMALIZED_SCHEMA)

_RENAME = {
    "Commodity": "commodity",
    "Category": "category",
    "Item": "item",
    "Units": "units",
    "Region": "region",
    "Size": "size",
    "Country": "country",
    "Survey base year": "survey_base_year",
}
_YEAR_PATTERN = re.compile(r"^(\d{4})(F?)$")


@dataclass(frozen=True)
class ErsSource:
    """One published ERS CSV."""

    name: str
    url: str
    forecast: bool


SOURCES: tuple[ErsSource, ...] = (
    ErsSource("corn", f"{BASE_URL}/4962/corn.csv", forecast=False),
    ErsSource("soybeans", f"{BASE_URL}/4976/soybeans.csv", forecast=False),
    ErsSource(
        "forecast",
        f"{BASE_URL}/4923/cost-of-production-forecasts-for-major-us-field-crops-2026f-2027f.csv",
        forecast=True,
    ),
)


class SchemaError(ValueError):
    """A downloaded file does not have the schema this module was written against."""


def parse_year(raw: str) -> tuple[int, bool]:
    """Split an ERS year cell into a calendar year and a forecast flag.

    Args:
        raw: `"2025"` for an estimate, `"2026F"` for a forecast.

    Returns:
        `(year, is_forecast)`.

    Raises:
        SchemaError: If the cell is not a four-digit year with an optional `F`.
    """
    match = _YEAR_PATTERN.match(raw.strip())
    if match is None:
        raise SchemaError(f"ERS year cell {raw!r} is not a year (expected '2025' or '2026F')")
    return int(match.group(1)), bool(match.group(2))


def _check_columns(found: list[str], expected: tuple[str, ...], source: str) -> None:
    """Fail loudly on any schema drift, in either direction.

    Raises:
        SchemaError: If the column set differs from `expected`.
    """
    missing = [c for c in expected if c not in found]
    extra = [c for c in found if c not in expected]
    if missing or extra:
        raise SchemaError(
            f"ERS file {source!r} does not match the expected schema. "
            f"Missing: {missing or 'none'}. Unexpected: {extra or 'none'}. "
            f"Expected exactly: {list(expected)}"
        )


def parse_csv(raw: bytes, *, source: str, forecast: bool) -> pl.DataFrame:
    """Normalize one ERS CSV into the shared long-format schema.

    Args:
        raw: File bytes as served.
        source: Short label recorded on every row (`corn`, `soybeans`, `forecast`).
        forecast: Whether to expect the seven-column forecast schema.

    Returns:
        A frame with exactly `NORMALIZED_COLUMNS`.

    Raises:
        SchemaError: If the columns or the year cells are not as expected.
    """
    expected = FORECAST_COLUMNS if forecast else HISTORICAL_COLUMNS
    # Every column is read as text: the year cells are not integers in the
    # forecast file, and inferring types from a moving target invites surprises.
    frame = pl.read_csv(raw, infer_schema=False)
    _check_columns(frame.columns, expected, source)

    years = [parse_year(y) for y in frame["Year"].to_list()]
    absent = [c for c in ("Size", "Country", "Survey base year") if c not in frame.columns]

    return (
        frame.rename({k: v for k, v in _RENAME.items() if k in frame.columns})
        .with_columns(
            pl.lit(source, dtype=pl.String()).alias("source"),
            pl.Series("year", [y for y, _ in years], dtype=pl.Int32()),
            pl.Series("is_forecast", [f for _, f in years], dtype=pl.Boolean()),
            pl.col("Value").cast(pl.Float64(), strict=True).alias("value"),
            *(pl.lit(None, dtype=pl.String()).alias(_RENAME[c]) for c in absent),
        )
        .select(*NORMALIZED_COLUMNS)
    )


def normalize(frames: list[pl.DataFrame]) -> pl.DataFrame:
    """Concatenate normalized frames into the single tidy panel.

    Args:
        frames: Output of `parse_csv`, one per source file.

    Returns:
        One frame, sorted for stable output across runs.

    Raises:
        SchemaError: If `frames` is empty.
    """
    if not frames:
        raise SchemaError("normalize() needs at least one frame")
    return pl.concat(frames, how="vertical").sort(
        "source", "commodity", "region", "year", "category", "item"
    )


def extract(
    cache_dir: Path,
    out_path: Path,
    *,
    session: HttpSession | None = None,
    sources: tuple[ErsSource, ...] = SOURCES,
) -> pl.DataFrame:
    """Download every ERS source and write the normalized panel to parquet.

    Args:
        cache_dir: Where raw CSVs are cached; existing files are not re-fetched.
        out_path: Destination parquet file.
        session: HTTP session to reuse.
        sources: Files to pull. Defaults to `SOURCES`.

    Returns:
        The normalized frame that was written.
    """
    frames = [
        parse_csv(
            fetch_bytes(source.url, cache_dir / f"{source.name}.csv", session=session),
            source=source.name,
            forecast=source.forecast,
        )
        for source in sources
    ]
    panel = normalize(frames)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(out_path)
    return panel

"""Tests for the USDA ERS commodity cost-and-return extractor.

Fixtures are trimmed excerpts of the real published CSVs (16 and 12 rows), so the
quoting, column order, and value formatting are exactly what the endpoint serves.
The interesting case is that the forecast file has a *different* schema from the
historical files — fewer columns and a `2026F` year — and the normalizer has to
reconcile them without pretending the missing columns were ever there.
"""

from pathlib import Path

import polars as pl
import pytest
from etl import ers

FIXTURES = Path(__file__).parent / "fixtures" / "etl"
HISTORICAL = FIXTURES / "ers_corn_sample.csv"
FORECAST = FIXTURES / "ers_forecast_sample.csv"


def test_historical_csv_normalizes_to_the_documented_columns():
    frame = ers.parse_csv(HISTORICAL.read_bytes(), source="corn", forecast=False)
    assert frame.columns == list(ers.NORMALIZED_COLUMNS)
    assert frame.height == 16


def test_historical_values_survive_the_round_trip():
    """2025 Heartland corn net value is -108.05 per the published file."""
    frame = ers.parse_csv(HISTORICAL.read_bytes(), source="corn", forecast=False)
    row = frame.filter(
        (pl.col("region") == "Heartland")
        & (pl.col("year") == 2025)
        & (pl.col("item") == "Value of production less total costs listed")
    )
    assert row.height == 1
    assert row["value"][0] == pytest.approx(-108.05)
    assert row["is_forecast"][0] is False
    assert row["survey_base_year"][0] == "Base survey of 2021"


def test_forecast_year_suffix_becomes_an_integer_plus_a_flag():
    frame = ers.parse_csv(FORECAST.read_bytes(), source="forecast", forecast=True)
    assert frame.columns == list(ers.NORMALIZED_COLUMNS)
    assert set(frame["year"].to_list()) == {2026, 2027}
    assert frame["is_forecast"].all()


def test_forecast_rows_carry_nulls_where_the_schema_has_no_column():
    """Size / Country / Survey base year do not exist in the forecast file."""
    frame = ers.parse_csv(FORECAST.read_bytes(), source="forecast", forecast=True)
    for column in ("size", "country", "survey_base_year"):
        assert frame[column].null_count() == frame.height


def test_both_schemas_concatenate_into_one_frame():
    combined = ers.normalize(
        [
            ers.parse_csv(HISTORICAL.read_bytes(), source="corn", forecast=False),
            ers.parse_csv(FORECAST.read_bytes(), source="forecast", forecast=True),
        ]
    )
    assert combined.height == 28
    assert set(combined["source"].to_list()) == {"corn", "forecast"}
    assert combined.schema == ers.NORMALIZED_SCHEMA


def test_a_missing_column_fails_loudly_and_names_the_column():
    truncated = b'"Commodity","Category","Item"\n"Corn","Operating costs","Seed"\n'
    with pytest.raises(ers.SchemaError) as exc:
        ers.parse_csv(truncated, source="corn", forecast=False)
    assert "Units" in str(exc.value)


def test_an_unexpected_extra_column_also_fails():
    """Silent schema drift on republication must not pass through unnoticed."""
    header = ",".join(f'"{c}"' for c in [*ers.HISTORICAL_COLUMNS, "Surprise"])
    cells = ["Corn", "Operating costs", "Seed", "dollars", "No specific size"]
    cells += ["Heartland", "US", "2025", "1.0", "b", "x"]
    body = ",".join(f'"{c}"' for c in cells)
    with pytest.raises(ers.SchemaError, match="Surprise"):
        ers.parse_csv(f"{header}\n{body}\n".encode(), source="corn", forecast=False)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("2025", (2025, False)), ("2026F", (2026, True)), ("2027F", (2027, True))],
)
def test_parse_year(raw, expected):
    assert ers.parse_year(raw) == expected


def test_parse_year_rejects_junk():
    with pytest.raises(ers.SchemaError, match="not a year"):
        ers.parse_year("next season")


def test_source_urls_carry_no_version_query_parameter():
    """`?v=` changes on republication; pinning it would break the extractor."""
    for source in ers.SOURCES:
        assert "?" not in source.url
        assert source.url.startswith("https://www.ers.usda.gov/media/")

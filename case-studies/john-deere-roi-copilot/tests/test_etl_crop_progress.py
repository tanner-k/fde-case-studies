"""Tests for the NASS Crop Progress extractor.

The window measurement in `engine/timeliness.py` is only as good as the series
underneath it, and two of this module's failure modes are silent: a query that
returns the wrong `short_desc` (NASS files corn grain harvest under
`CORN, GRAIN - PROGRESS...`, not `CORN - PROGRESS...`) and a percentage parsed
out of a suppression marker. Both are pinned here.

The response fixture is SYNTHETIC — hand-written to the record shape confirmed
against the live API on 2026-08-16, not captured wholesale.
"""

import json
from pathlib import Path

import pytest
from etl import crop_progress
from etl.nass import QuickStatsError

FIXTURES = Path(__file__).parent / "fixtures" / "etl"
SYNTHETIC = json.loads((FIXTURES / "nass_crop_progress_SYNTHETIC.json").read_text())
CORN_PLANTED = next(s for s in crop_progress.SERIES if s.key == "corn_planted")
DAYS_SUITABLE = next(s for s in crop_progress.SERIES if s.key == "days_suitable")


def test_all_five_series_are_defined():
    assert {spec.key for spec in crop_progress.SERIES} == {
        "corn_planted",
        "soybean_planted",
        "corn_harvested",
        "soybean_harvested",
        "days_suitable",
    }


def test_corn_harvest_uses_the_grain_qualified_short_desc():
    """NASS files it under `CORN, GRAIN`, not `CORN`. A wrong string returns zero rows."""
    harvested = next(s for s in crop_progress.SERIES if s.key == "corn_harvested")
    assert harvested.short_desc == "CORN, GRAIN - PROGRESS, MEASURED IN PCT HARVESTED"


def test_days_suitable_is_not_a_progress_statistic():
    """It is its own statisticcat under the FIELDWORK commodity."""
    assert DAYS_SUITABLE.commodity_desc == "FIELDWORK"
    assert DAYS_SUITABLE.statisticcat_desc == "DAYS SUITABLE"


def test_params_pin_iowa_state_level_and_the_year_range():
    params = crop_progress.build_params(
        CORN_PLANTED, key="testkey", start_year=2006, end_year=2026
    )
    assert params["state_alpha"] == "IA"
    assert params["agg_level_desc"] == "STATE"
    assert params["short_desc"] == CORN_PLANTED.short_desc
    assert params["year__GE"] == "2006"
    assert params["year__LE"] == "2026"
    assert params["key"] == "testkey"


def test_a_reversed_year_range_is_rejected():
    with pytest.raises(ValueError, match="start_year"):
        crop_progress.build_params(CORN_PLANTED, key="k", start_year=2026, end_year=2008)


def test_parsing_normalizes_to_the_panel_schema():
    frame = crop_progress.parse_series(SYNTHETIC, spec=CORN_PLANTED)
    assert frame.columns == list(crop_progress.PROGRESS_COLUMNS)
    assert frame.height == 3
    assert frame["series_key"].unique().to_list() == ["corn_planted"]


def test_week_ending_parses_to_a_date():
    frame = crop_progress.parse_series(SYNTHETIC, spec=CORN_PLANTED)
    row = frame.sort("week_ending").row(0, named=True)
    assert row["week_ending"].isoformat() == "2024-04-21"
    assert row["value"] == pytest.approx(12.0)


def test_an_error_body_raises_rather_than_returning_an_empty_panel():
    with pytest.raises(QuickStatsError, match="unauthorized"):
        crop_progress.parse_series({"error": ["unauthorized"]}, spec=CORN_PLANTED)


def test_a_result_at_the_record_cap_raises_as_truncated():
    payload = {"data": [SYNTHETIC["data"][0]] * 5}
    with pytest.raises(QuickStatsError, match="truncated"):
        crop_progress.parse_series(payload, spec=CORN_PLANTED, record_limit=5)


def test_a_suppression_marker_is_dropped_not_parsed_as_zero():
    """A `(D)` read as 0% would look like an operation that never started."""
    payload = {
        "data": [
            {**SYNTHETIC["data"][0], "Value": "(D)"},
            SYNTHETIC["data"][1],
        ]
    }
    frame = crop_progress.parse_series(payload, spec=CORN_PLANTED)
    assert frame.height == 1
    assert frame["value"].to_list() == [pytest.approx(59.0)]


def test_an_unparseable_value_raises_rather_than_being_guessed():
    payload = {"data": [{**SYNTHETIC["data"][0], "Value": "about half"}]}
    with pytest.raises(QuickStatsError, match="about half"):
        crop_progress.parse_series(payload, spec=CORN_PLANTED)


def test_a_record_missing_a_required_field_raises():
    incomplete = {k: v for k, v in SYNTHETIC["data"][0].items() if k != "week_ending"}
    with pytest.raises(QuickStatsError, match="week_ending"):
        crop_progress.parse_series({"data": [incomplete]}, spec=CORN_PLANTED)

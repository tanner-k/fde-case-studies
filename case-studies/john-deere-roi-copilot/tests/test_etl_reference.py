"""Tests for the operations reference dataset and its joins.

Two things are pinned here that the pure-math tests cannot pin: that every row
of `operations.json` actually resolves against the archived ISU files, and that
the findings the deck will claim survive contact with the real numbers.

The A3-10 operation strings are PDF-parsed fragments. A silent mis-join would
put a combine's $46/acre rate on a sprayer and nobody would notice, so the
loader raises on anything that does not resolve to exactly one row.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
from engine.landscape import Operation, annual_machine_hours, break_even_acres_vs_custom_rate
from engine.machinery import MachineryRates
from etl.crop_progress import PROGRESS_SCHEMA
from etl.reference import (
    CUSTOM_RATES_PATH,
    ReferenceDataError,
    load_measured_windows,
    load_operations,
)

RATES = MachineryRates(
    interest_rate=0.07,
    engine_pto_hp=400.0,
    diesel_usd_per_gal=3.50,
    labour_usd_per_hour=20.40,
)

OPERATIONS_JSON = Path(__file__).resolve().parent.parent / "data" / "reference" / "operations.json"
OPERATIONS = load_operations()
BY_KEY = {operation.key: operation for operation in OPERATIONS}


def test_every_operation_loads_and_validates():
    assert len(OPERATIONS) == 10
    assert all(isinstance(operation, Operation) for operation in OPERATIONS)


def test_keys_are_unique():
    assert len(BY_KEY) == len(OPERATIONS)


def test_the_sprayer_carries_the_2026_custom_rate_and_its_market_depth():
    """ISU A3-10 2026: $9.35/acre from 121 of 205 respondents."""
    sprayer = BY_KEY["self_propelled_sprayer"]
    assert sprayer.custom_rate_usd_per_acre == pytest.approx(9.35)
    assert sprayer.custom_rate_responses == 121


def test_rated_hours_come_from_the_a3_29_wearout_life():
    """A3-29 puts a self-propelled sprayer's wearout at 1,500 hours."""
    sprayer = BY_KEY["self_propelled_sprayer"]
    assert sprayer.useful_life_years == 10
    assert sprayer.rated_annual_hours == pytest.approx(150.0)


def test_the_sprayer_salvage_fraction_comes_from_the_a3_29_equation_not_the_flat_default():
    """JDRC-22: 40.5% of list at ten years, not the engine's flat 25%."""
    assert BY_KEY["self_propelled_sprayer"].salvage_fraction == pytest.approx(0.4052, abs=0.0005)


def test_sprayer_repair_factors_are_the_sprayer_row_not_the_tractor_default():
    """MachineryRates defaults (0.007 / 2.0) are the A3-29 tractor row."""
    sprayer = BY_KEY["self_propelled_sprayer"]
    assert sprayer.repair_factor_rc1 == pytest.approx(0.1)
    assert sprayer.repair_factor_rc2 == pytest.approx(1.3)


def test_an_unresolvable_custom_rate_row_raises(tmp_path):
    """A mis-typed PDF-parsed fragment must fail loudly, not join to a neighbour."""
    source = json.loads(OPERATIONS_JSON.read_text())
    source["operations"] = [
        {**source["operations"][0], "custom_rate_operation": "Ground, broadcast, teleported / acre"}
    ]
    path = tmp_path / "operations.json"
    path.write_text(json.dumps(source))
    with pytest.raises(ReferenceDataError, match="matched 0 rows"):
        load_operations(operations_path=path)


def test_an_unknown_a3_29_machine_raises(tmp_path):
    source = json.loads(OPERATIONS_JSON.read_text())
    source["operations"] = [{**source["operations"][0], "a3_29_machine": "Flying tractor"}]
    path = tmp_path / "operations.json"
    path.write_text(json.dumps(source))
    with pytest.raises(ReferenceDataError, match="Flying tractor"):
        load_operations(operations_path=path)


# --- The findings, against the real numbers ---------------------------------


def test_a_2400_acre_farm_runs_its_sprayer_twenty_four_hours_a_year():
    """The rescope's opening fact, from the committed dataset."""
    hours = annual_machine_hours(BY_KEY["self_propelled_sprayer"], farm_acres=2_400.0)
    assert hours == pytest.approx(24.4, abs=0.2)


def test_the_sprayer_stays_low_utilization_even_at_ten_thousand_acres():
    """No Iowa row-crop farm reaches applicator utilization on a sprayer."""
    hours = annual_machine_hours(BY_KEY["self_propelled_sprayer"], farm_acres=10_000.0)
    assert hours < 200.0


def test_the_combine_crosses_into_high_utilization_with_scale():
    """The quadrants have to move with farm size or the exhibit says nothing."""
    combine = BY_KEY["corn_combine"]
    assert annual_machine_hours(combine, farm_acres=2_400.0) < 200.0
    assert annual_machine_hours(combine, farm_acres=10_000.0) > 200.0


def test_the_sprayer_break_even_is_thousands_of_acres_above_the_demo_farm():
    acres = break_even_acres_vs_custom_rate(BY_KEY["self_propelled_sprayer"], RATES)
    assert acres is not None
    assert 8_000.0 < acres < 10_500.0


def test_iowa_has_no_bare_rental_market_for_sprayers_planters_or_combines():
    """Iowa has no bare rental market for sprayers, planters, or combines.

    Spec section 1: high-timeliness machines consolidate into custom operators'
    hands, not rental fleets. A3-10's Machinery Rental section lists heads,
    carts, augers and a skid loader — no sprayer, planter or combine.
    """
    rentals = [
        row["operation"].lower()
        for row in json.loads(CUSTOM_RATES_PATH.read_text())["rates"]
        if row["section"] == "Machinery Rental"
    ]
    assert rentals  # the section exists, so absence below is evidence
    assert not [r for r in rentals if "sprayer" in r or "planter" in r]
    assert not [r for r in rentals if r.startswith("combine")]


# --- Measured windows (phase 2) ---------------------------------------------


def test_four_operations_map_to_a_nass_series_and_six_do_not():
    """NASS publishes progress for planting and harvest only, not other operations.

    Spraying, tillage and fertilizer application have no NASS progress series,
    so six rows keep their estimates, including the sprayer, which is the
    exhibit's flagship point.
    """
    mapped = {op.key: op.nass_series_key for op in OPERATIONS if op.nass_series_key}
    assert mapped == {
        "corn_combine": "corn_harvested",
        "soybean_combine": "soybean_harvested",
        "no_till_planter": "corn_planted",
        "high_speed_planter": "corn_planted",
    }
    assert BY_KEY["self_propelled_sprayer"].nass_series_key is None


def test_without_measurements_every_window_stays_an_author_estimate():
    """The loader must not silently invent measurements when the panel is absent."""
    assert all(op.window_confidence == "author_estimate" for op in OPERATIONS)


def test_a_measured_window_replaces_the_estimate_and_is_labelled_measured():
    from engine.timeliness import MeasuredWindow

    measured = {
        "corn_planted": MeasuredWindow(
            series_key="corn_planted",
            low_percentile=25.0,
            high_percentile=75.0,
            years_observed=21,
            median_calendar_days=11.0,
            min_calendar_days=6,
            max_calendar_days=25,
            median_suitable_days=7.4,
            median_closing_day_of_year=135,
        )
    }
    operations = {op.key: op for op in load_operations(measured_windows=measured)}
    planter = operations["no_till_planter"]
    assert planter.window_days == pytest.approx(11.0)
    assert planter.window_confidence == "measured"
    assert "25-75" in planter.window_source or "25–75" in planter.window_source  # noqa: RUF001
    # An unmapped operation is untouched.
    assert operations["self_propelled_sprayer"].window_confidence == "author_estimate"
    assert operations["self_propelled_sprayer"].window_days == pytest.approx(10.0)


def test_a_measurement_for_a_series_no_operation_uses_is_rejected():
    """A typo'd series key must not be silently ignored."""
    from engine.timeliness import MeasuredWindow

    stray = {
        "corn_plantd": MeasuredWindow(
            series_key="corn_plantd",
            low_percentile=25.0,
            high_percentile=75.0,
            years_observed=21,
            median_calendar_days=11.0,
            min_calendar_days=6,
            max_calendar_days=25,
            median_suitable_days=7.4,
            median_closing_day_of_year=135,
        )
    }
    with pytest.raises(ReferenceDataError, match="corn_plantd"):
        load_operations(measured_windows=stray)


def test_mistyped_series_key_in_operations_json_raises_when_correct_key_is_measured(
    tmp_path,
):
    """Guard detects mistyped nass_series_key in operations.json.

    The guard raises on the correct series that is no longer mapped. Without the
    allowlist, unfiltered measured windows would have revealed this typo
    immediately.
    """
    from engine.timeliness import MeasuredWindow

    source = json.loads(OPERATIONS_JSON.read_text())
    # Mistype both planter rows' series keys from "corn_planted" to "corn_plantd".
    source["operations"][3] = {
        **source["operations"][3],
        "nass_series_key": "corn_plantd",
    }
    source["operations"][4] = {
        **source["operations"][4],
        "nass_series_key": "corn_plantd",
    }
    path = tmp_path / "operations.json"
    path.write_text(json.dumps(source))

    # Hand load_operations measurements for both the real series (corn_planted)
    # and the mistyped one (corn_plantd). The guard should raise on corn_planted,
    # which is no longer mapped due to the typo.
    measured = {
        "corn_planted": MeasuredWindow(
            series_key="corn_planted",
            low_percentile=25.0,
            high_percentile=75.0,
            years_observed=21,
            median_calendar_days=11.0,
            min_calendar_days=6,
            max_calendar_days=25,
            median_suitable_days=7.4,
            median_closing_day_of_year=135,
        ),
        "corn_plantd": MeasuredWindow(
            series_key="corn_plantd",
            low_percentile=25.0,
            high_percentile=75.0,
            years_observed=21,
            median_calendar_days=11.0,
            min_calendar_days=6,
            max_calendar_days=25,
            median_suitable_days=7.4,
            median_closing_day_of_year=135,
        ),
    }
    with pytest.raises(ReferenceDataError, match="corn_planted"):
        load_operations(operations_path=path, measured_windows=measured)


def test_soybean_planted_alone_does_not_raise():
    """Measurement for soybean_planted does not raise.

    soybean_planted is measured but deliberately unmapped — both planters use
    corn_planted. A measurement for soybean_planted should not raise an error.
    """
    from engine.timeliness import MeasuredWindow

    soybean_only = {
        "soybean_planted": MeasuredWindow(
            series_key="soybean_planted",
            low_percentile=25.0,
            high_percentile=75.0,
            years_observed=21,
            median_calendar_days=9.0,
            min_calendar_days=4,
            max_calendar_days=20,
            median_suitable_days=6.0,
            median_closing_day_of_year=140,
        )
    }
    # Should not raise.
    load_operations(measured_windows=soybean_only)


# --- load_measured_windows: the parquet-to-engine seam (Finding 4) ----------
#
# This is the one join in `etl/reference.py` no test previously touched: the
# column-to-model mapping, the year grouping, the `days_suitable` exclusion
# from the set of measured series, and the `ReferenceDataError` guard for a
# panel with no days-suitable rows at all. A wrong column name or a broken
# grouping here changes every headline number in assumptions.md section 11.6
# and nothing in the existing suite would fail.


def _write_panel(path: Path, rows: list[dict]) -> None:
    """Write a small parquet panel in the exact shape `etl.crop_progress` writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows, schema=PROGRESS_SCHEMA).write_parquet(path)


#: A clean synthetic season, same shape as `tests/test_timeliness.py`'s SEASON:
#: 0% on 1 May 2024, +25 points a week, so the 25-75 span is an exact 14 days.
_CORN_PLANTED_ROWS = [
    {
        "series_key": "corn_planted",
        "commodity": "CORN",
        "year": 2024,
        "week_ending": date(2024, 5, 1 + 7 * step),
        "unit": "PCT PLANTED",
        "value": 25.0 * step,
    }
    for step in range(5)
]

#: Seven suitable days every week over the same span.
_DAYS_SUITABLE_ROWS = [
    {
        "series_key": "days_suitable",
        "commodity": "FIELDWORK",
        "year": 2024,
        "week_ending": date(2024, 5, 1 + 7 * step),
        "unit": "DAYS / WEEK",
        "value": 7.0,
    }
    for step in range(5)
]


def test_load_measured_windows_builds_one_window_per_progress_series(tmp_path):
    panel_path = tmp_path / "crop_progress.parquet"
    _write_panel(panel_path, _CORN_PLANTED_ROWS + _DAYS_SUITABLE_ROWS)

    windows = load_measured_windows(panel_path, low_percentile=25.0, high_percentile=75.0)

    # days_suitable feeds every window's suitable-days figure but is not
    # itself a measured operation window.
    assert set(windows) == {"corn_planted"}
    window = windows["corn_planted"]
    assert window.series_key == "corn_planted"
    assert (window.low_percentile, window.high_percentile) == (25.0, 75.0)
    assert window.years_observed == 1
    assert window.median_calendar_days == pytest.approx(14.0)
    assert window.median_suitable_days == pytest.approx(14.0, abs=0.05)


def test_load_measured_windows_groups_observations_by_year(tmp_path):
    """A second, later-starting year must not blend into the first year's span."""
    # Weekly cadence (7-day gaps, inside crossing_date's default max_gap_days
    # of 10) but a slower +12.5 points/week: 25% falls in week 2 (day 14),
    # 75% in week 6 (day 42), a 28-day span vs. 2024's 14 days.
    late_year_rows = [
        {
            "series_key": "corn_planted",
            "commodity": "CORN",
            "year": 2025,
            "week_ending": date(2025, 5, 1) + timedelta(days=7 * step),
            "unit": "PCT PLANTED",
            "value": 12.5 * step,
        }
        for step in range(9)
    ]
    days_suitable_2025 = [
        {
            "series_key": "days_suitable",
            "commodity": "FIELDWORK",
            "year": 2025,
            "week_ending": date(2025, 5, 1) + timedelta(days=7 * step),
            "unit": "DAYS / WEEK",
            "value": 7.0,
        }
        for step in range(9)
    ]
    panel_path = tmp_path / "crop_progress.parquet"
    _write_panel(
        panel_path,
        _CORN_PLANTED_ROWS + _DAYS_SUITABLE_ROWS + late_year_rows + days_suitable_2025,
    )

    window = load_measured_windows(panel_path, low_percentile=25.0, high_percentile=75.0)[
        "corn_planted"
    ]

    assert window.years_observed == 2
    assert window.min_calendar_days == 14
    assert window.max_calendar_days == 28
    assert window.median_calendar_days == pytest.approx(21.0)


def test_load_measured_windows_returns_empty_when_the_panel_is_absent(tmp_path):
    """The exhibit still builds, on estimates, when the panel has not been fetched."""
    assert load_measured_windows(tmp_path / "does_not_exist.parquet") == {}


def test_load_measured_windows_raises_without_a_days_suitable_series(tmp_path):
    """A panel missing days_suitable would silently zero every suitable-day count."""
    panel_path = tmp_path / "crop_progress.parquet"
    _write_panel(panel_path, _CORN_PLANTED_ROWS)

    with pytest.raises(ReferenceDataError, match="days_suitable"):
        load_measured_windows(panel_path)

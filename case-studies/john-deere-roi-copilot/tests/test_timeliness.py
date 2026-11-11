"""Tests for measuring an agronomic window out of NASS progress data.

Phase 1 put window length on an axis and filled it with author estimates. This
module replaces four of those ten estimates with a measurement, so the
interpolation that produces it is pinned exactly, on synthetic series where the
right answer is arithmetic rather than agronomy.

The one judgement encoded here is the percentile pair. 25-75 is the declared
primary and the plan states why before any gate was run; 10-90 and 5-95 are
computed as sensitivity. A test asserts the primary has not drifted.
"""

from datetime import date

import pytest
from engine.models import Crop
from engine.timeliness import (
    PRIMARY_PERCENTILES,
    MeasuredWindow,
    PlantingDateCurve,
    ProgressPoint,
    SuitableWeek,
    crossing_date,
    day_of_year_at_max,
    delay_cost_usd_per_acre_per_day,
    fitted_yield,
    measure_window,
    relative_yield,
    suitable_days_between,
    window_calendar_days,
    yield_loss_fraction,
)
from etl.reference import load_planting_date_curves

#: A clean synthetic season: 0% on 1 May, then +25 points a week.
SEASON = tuple(
    ProgressPoint(week_ending=date(2024, 5, 1 + 7 * step), percent_complete=25.0 * step)
    for step in range(5)
)

#: Seven days suitable every week makes prorating arithmetic checkable by hand.
PERFECT_WEEKS = tuple(
    SuitableWeek(week_ending=date(2024, 5, 1 + 7 * step), days_suitable=7.0)
    for step in range(5)
)


# --- The declared definition -------------------------------------------------


def test_the_primary_definition_is_the_interquartile_span():
    """Declared before the gate was run; changing it after is the failure mode."""
    assert PRIMARY_PERCENTILES == (25.0, 75.0)


# --- Crossing interpolation --------------------------------------------------


def test_a_crossing_that_lands_on_an_observation_returns_that_week():
    assert crossing_date(SEASON, percent=25.0) == date(2024, 5, 8)


def test_a_crossing_between_observations_is_interpolated():
    """50% is reported exactly on 15 May, one week after the 25% observation."""
    assert crossing_date(SEASON, percent=50.0) == date(2024, 5, 15)


def test_a_crossing_a_quarter_of_the_way_through_a_week_rounds_to_that_day():
    """31.25% is a quarter of the way from 25% to 50%, i.e. 8 May + 1.75 days."""
    assert crossing_date(SEASON, percent=31.25) == date(2024, 5, 10)


def test_a_percentage_never_reached_has_no_crossing():
    assert crossing_date(SEASON, percent=101.0) is None


def test_a_series_that_starts_above_the_target_returns_its_first_week():
    """A late-starting series must not extrapolate backwards into April."""
    late = (ProgressPoint(week_ending=date(2024, 5, 20), percent_complete=40.0),)
    assert crossing_date(late, percent=25.0) == date(2024, 5, 20)


def test_an_empty_series_has_no_crossing():
    assert crossing_date((), percent=50.0) is None


def test_a_flat_run_at_the_target_returns_the_first_week_reaching_it():
    flat = (
        ProgressPoint(week_ending=date(2024, 5, 1), percent_complete=30.0),
        ProgressPoint(week_ending=date(2024, 5, 8), percent_complete=30.0),
    )
    assert crossing_date(flat, percent=30.0) == date(2024, 5, 1)


def test_a_gap_within_the_default_bound_still_interpolates():
    """A normal weekly gap (7 days) is well inside the 10-day default bound."""
    assert crossing_date(SEASON, percent=50.0, max_gap_days=10.0) == date(2024, 5, 15)


def test_a_gap_wider_than_max_gap_days_is_not_interpolated_across():
    """A suspended-reporting gap must not manufacture a crossing date.

    Straddling observations 21 days apart (a real Iowa harvest-panel gap,
    e.g. 2013-09-29 to 2013-10-20) are far outside a 10-day trust bound.
    """
    gapped = (
        ProgressPoint(week_ending=date(2024, 9, 1), percent_complete=5.0),
        ProgressPoint(week_ending=date(2024, 9, 22), percent_complete=97.0),
    )
    assert crossing_date(gapped, percent=25.0, max_gap_days=10.0) is None


def test_a_gap_exactly_at_the_bound_still_interpolates():
    at_bound = (
        ProgressPoint(week_ending=date(2024, 9, 1), percent_complete=0.0),
        ProgressPoint(week_ending=date(2024, 9, 11), percent_complete=100.0),
    )
    assert crossing_date(at_bound, percent=50.0, max_gap_days=10.0) == date(2024, 9, 6)


# --- Calendar span -----------------------------------------------------------


def test_the_interquartile_span_of_a_steady_season_is_two_weeks():
    assert window_calendar_days(SEASON, low_percentile=25.0, high_percentile=75.0) == 14


def test_a_wider_percentile_pair_gives_a_wider_span():
    narrow = window_calendar_days(SEASON, low_percentile=25.0, high_percentile=75.0)
    wide = window_calendar_days(SEASON, low_percentile=10.0, high_percentile=90.0)
    assert wide > narrow


def test_a_season_that_never_completes_has_no_span():
    partial = SEASON[:2]  # tops out at 25%
    assert window_calendar_days(partial, low_percentile=25.0, high_percentile=75.0) is None


def test_reversed_percentiles_are_rejected():
    with pytest.raises(ValueError, match="low_percentile"):
        window_calendar_days(SEASON, low_percentile=75.0, high_percentile=25.0)


# --- Suitable days -----------------------------------------------------------


def test_a_fortnight_of_perfect_weather_yields_fourteen_suitable_days():
    total = suitable_days_between(
        PERFECT_WEEKS, start=date(2024, 5, 8), end=date(2024, 5, 21)
    )
    assert total == pytest.approx(14.0, abs=0.01)


def test_suitable_days_are_prorated_across_a_partly_covered_week():
    """Half a 4-day week is 2 days, not 4."""
    weeks = (SuitableWeek(week_ending=date(2024, 5, 8), days_suitable=4.0),)
    covered = suitable_days_between(weeks, start=date(2024, 5, 5), end=date(2024, 5, 8))
    assert covered == pytest.approx(4.0 * 4 / 7, abs=0.01)


def test_a_wet_fortnight_yields_fewer_suitable_days_than_a_dry_one():
    """The point of the measure: calendar length is not workable length."""
    wet = tuple(
        SuitableWeek(week_ending=date(2024, 5, 1 + 7 * step), days_suitable=2.0)
        for step in range(5)
    )
    span = {"start": date(2024, 5, 8), "end": date(2024, 5, 21)}
    assert suitable_days_between(wet, **span) < suitable_days_between(PERFECT_WEEKS, **span)


def test_weeks_outside_the_span_contribute_nothing():
    weeks = (SuitableWeek(week_ending=date(2023, 5, 8), days_suitable=7.0),)
    assert suitable_days_between(weeks, start=date(2024, 5, 8), end=date(2024, 5, 21)) == 0.0


def test_a_backwards_span_is_rejected():
    with pytest.raises(ValueError, match="start"):
        suitable_days_between(PERFECT_WEEKS, start=date(2024, 5, 21), end=date(2024, 5, 8))


# --- Reduction across years --------------------------------------------------


def test_a_measured_window_reduces_every_year_to_a_median():
    """Three identical seasons a year apart must give the same span as one."""
    by_year = {
        year: tuple(
            ProgressPoint(
                week_ending=date(year, 5, 1 + 7 * step), percent_complete=25.0 * step
            )
            for step in range(5)
        )
        for year in (2022, 2023, 2024)
    }
    weeks = tuple(
        SuitableWeek(week_ending=date(year, 5, 1 + 7 * step), days_suitable=7.0)
        for year in (2022, 2023, 2024)
        for step in range(5)
    )
    window = measure_window(by_year, weeks, series_key="corn_planted")
    assert isinstance(window, MeasuredWindow)
    assert window.series_key == "corn_planted"
    assert window.years_observed == 3
    assert window.median_calendar_days == pytest.approx(14.0)
    assert window.min_calendar_days == 14
    assert window.max_calendar_days == 14
    assert window.median_suitable_days == pytest.approx(14.0, abs=0.05)


def test_a_measured_window_records_the_median_closing_day_of_year():
    """75% crossing lands on 22 May every year: DOY 142 (2022/23) or 143 (2024, leap)."""
    by_year = {
        year: tuple(
            ProgressPoint(
                week_ending=date(year, 5, 1 + 7 * step), percent_complete=25.0 * step
            )
            for step in range(5)
        )
        for year in (2022, 2023, 2024)
    }
    weeks = tuple(
        SuitableWeek(week_ending=date(year, 5, 1 + 7 * step), days_suitable=7.0)
        for year in (2022, 2023, 2024)
        for step in range(5)
    )
    window = measure_window(by_year, weeks, series_key="corn_planted")
    assert window.median_closing_day_of_year == 142


def test_years_that_never_complete_are_excluded_not_counted_as_zero():
    by_year = {
        2023: SEASON,
        2024: SEASON[:2],  # tops out at 25%
    }
    window = measure_window(by_year, PERFECT_WEEKS, series_key="corn_planted")
    assert window.years_observed == 1
    assert window.years_excluded == (2024,)


def test_a_reporting_gap_excludes_the_year_the_same_way_as_an_incomplete_season():
    """A 21-day gap straddling the 75% crossing must drop the year, not stretch it."""
    gapped_year = (
        ProgressPoint(week_ending=date(2024, 5, 1), percent_complete=0.0),
        ProgressPoint(week_ending=date(2024, 5, 8), percent_complete=25.0),
        ProgressPoint(week_ending=date(2024, 5, 29), percent_complete=97.0),
    )
    by_year = {2023: SEASON, 2024: gapped_year}
    window = measure_window(by_year, PERFECT_WEEKS, series_key="corn_planted")
    assert window.years_observed == 1
    assert window.years_excluded == (2024,)


def test_a_measurement_with_no_usable_year_is_rejected():
    with pytest.raises(ValueError, match="no year"):
        measure_window({2024: SEASON[:2]}, PERFECT_WEEKS, series_key="corn_planted")


def test_the_percentile_pair_is_recorded_on_the_result():
    window = measure_window(
        {2024: SEASON},
        PERFECT_WEEKS,
        series_key="corn_planted",
        low_percentile=10.0,
        high_percentile=90.0,
    )
    assert (window.low_percentile, window.high_percentile) == (10.0, 90.0)


def test_a_year_starting_above_the_high_percentile_produces_zero_day_span():
    """Series whose first observation already exceeds the high percentile."""
    early = (ProgressPoint(week_ending=date(2024, 5, 1), percent_complete=80.0),)
    weeks = (SuitableWeek(week_ending=date(2024, 5, 1), days_suitable=7.0),)
    window = measure_window({2024: early}, weeks, series_key="corn_planted")
    assert window.median_calendar_days == 0
    assert window.median_suitable_days == 0.0


def test_suitable_days_never_exceed_calendar_days():
    """Suitable days within a span must never exceed its calendar days."""
    window = measure_window(
        {2024: SEASON},
        PERFECT_WEEKS,
        series_key="corn_planted",
    )
    assert window.median_suitable_days <= window.median_calendar_days


# --- Planting-date yield response: transcription mechanics -------------------
#
# A hand-computable curve, not the real Iowa data: y = 100 - x^2, vertex at
# DOY 120 by construction (b1 = 0). Good for pinning arithmetic; the real
# transcription is checked separately below, against the committed JSON.

SYNTHETIC_CURVE = PlantingDateCurve(
    crop=Crop.CORN,
    region="TEST",
    b0=100.0,
    b1=0.0,
    b2=-1.0,
    day_of_year_at_max_published=120,
    valid_day_of_year_range=(60, 180),
    source="synthetic, for interpolation arithmetic only",
    retrieved="2026-08-17",
)


def _curve_with(**overrides):
    """`model_copy` skips validators, so build a fresh instance instead."""
    fields = {**SYNTHETIC_CURVE.model_dump(), **overrides}
    return PlantingDateCurve(**fields)


def test_a_non_negative_quadratic_term_is_rejected():
    with pytest.raises(ValueError, match="b2"):
        _curve_with(b2=0.0)


def test_a_positive_quadratic_term_is_rejected():
    with pytest.raises(ValueError, match="b2"):
        _curve_with(b2=1.0)


def test_a_backwards_valid_range_is_rejected():
    with pytest.raises(ValueError, match="valid_day_of_year_range"):
        _curve_with(valid_day_of_year_range=(180, 60))


def test_fitted_yield_matches_the_quadratic_by_hand():
    """X = (160-120)/40 = 1, so y = 100 - 1 = 99."""
    assert fitted_yield(SYNTHETIC_CURVE, day_of_year=160) == pytest.approx(99.0)


def test_fitted_yield_outside_the_valid_range_raises():
    with pytest.raises(ValueError, match="outside"):
        fitted_yield(SYNTHETIC_CURVE, day_of_year=59)
    with pytest.raises(ValueError, match="outside"):
        fitted_yield(SYNTHETIC_CURVE, day_of_year=181)


def test_day_of_year_at_max_is_the_vertex():
    """b1 = 0, so the vertex sits exactly on the transform's center, DOY 120."""
    assert day_of_year_at_max(SYNTHETIC_CURVE) == pytest.approx(120.0)


def test_relative_yield_is_exactly_one_at_the_vertex():
    assert relative_yield(SYNTHETIC_CURVE, day_of_year=120) == 1.0


def test_relative_yield_is_below_one_either_side_of_the_vertex():
    assert relative_yield(SYNTHETIC_CURVE, day_of_year=100) < 1.0
    assert relative_yield(SYNTHETIC_CURVE, day_of_year=140) < 1.0


def test_yield_loss_fraction_is_zero_at_the_vertex():
    assert yield_loss_fraction(SYNTHETIC_CURVE, day_of_year=120) == 0.0


def test_yield_loss_fraction_rises_monotonically_past_the_optimum():
    losses = [yield_loss_fraction(SYNTHETIC_CURVE, day_of_year=doy) for doy in (125, 140, 160)]
    assert losses == sorted(losses)
    assert losses[0] > 0.0


def test_delay_cost_is_zero_on_or_before_the_optimum():
    kwargs = {"optimal_yield_bu_per_acre": 200.0, "price_usd_per_bu": 4.0}
    assert delay_cost_usd_per_acre_per_day(SYNTHETIC_CURVE, day_of_year=120, **kwargs) == 0.0
    assert delay_cost_usd_per_acre_per_day(SYNTHETIC_CURVE, day_of_year=100, **kwargs) == 0.0


def test_delay_cost_rejects_out_of_range_day_of_year_even_before_the_optimum():
    """An out-of-range day_of_year raises ValueError even on or before the optimum.

    The function is a trust boundary — it must validate input before taking
    any branch, regardless of whether an early return applies.
    """
    with pytest.raises(ValueError, match="outside"):
        delay_cost_usd_per_acre_per_day(
            SYNTHETIC_CURVE, day_of_year=59, optimal_yield_bu_per_acre=200.0, price_usd_per_bu=4.0
        )


def test_delay_cost_matches_the_definition_by_hand():
    """40 days after the optimum, x=1, loss=0.01: 0.01*200*4/40 = $0.20/acre/day."""
    cost = delay_cost_usd_per_acre_per_day(
        SYNTHETIC_CURVE, day_of_year=160, optimal_yield_bu_per_acre=200.0, price_usd_per_bu=4.0
    )
    assert cost == pytest.approx(0.2)


def test_delay_cost_rejects_a_negative_yield():
    with pytest.raises(ValueError, match="optimal_yield_bu_per_acre"):
        delay_cost_usd_per_acre_per_day(
            SYNTHETIC_CURVE, day_of_year=160, optimal_yield_bu_per_acre=-1.0, price_usd_per_bu=4.0
        )


def test_delay_cost_rejects_a_negative_price():
    with pytest.raises(ValueError, match="price_usd_per_bu"):
        delay_cost_usd_per_acre_per_day(
            SYNTHETIC_CURVE, day_of_year=160, optimal_yield_bu_per_acre=200.0, price_usd_per_bu=-1.0
        )


# --- Planting-date yield response: acceptance tests on the real transcription
#
# These run against the committed JSON, not a fixture — they are checks on
# the transcription itself (b0/b1/b2 read off Table 2, and the x-transform
# applied to them), so a synthetic curve would defeat the point. If either
# fails, the transformation is wrong; see the module docstring in
# `engine/timeliness.py` and the task report for what "wrong" would look like.

PLANTING_CURVES = {curve.region: curve for curve in load_planting_date_curves()}

#: Table 3's published 98-100% optimum windows, day-of-year. This is the
#: acceptance test's ground truth, quoted from the paper, not derived from
#: the JSON — the JSON stores only Table 2's coefficients, per the brief.
PUBLISHED_98_100_WINDOWS_DOY = {
    "NC-NE": (102, 120),
    "NW-C": (105, 129),
    "SW-SE": (107, 128),
}


def test_all_three_iowa_site_groupings_are_present():
    assert set(PLANTING_CURVES) == {"NC-NE", "NW-C", "SW-SE"}


@pytest.mark.parametrize("region", sorted(PLANTING_CURVES))
def test_the_computed_vertex_matches_the_papers_published_optimum_doy(region):
    """Acceptance check 1: this is the strongest evidence the transform is right.

    day_of_year_at_max is computed from b1/b2 and the transform alone — never
    from day_of_year_at_max_published. If x were left as a raw, untransformed
    DOY, this would not land on an integer day matching the paper by chance
    for all three site-groupings at once.
    """
    curve = PLANTING_CURVES[region]
    assert round(day_of_year_at_max(curve)) == curve.day_of_year_at_max_published


@pytest.mark.parametrize("region", sorted(PLANTING_CURVES))
def test_the_papers_published_98_100_window_sits_at_98_percent_relative_yield(region):
    """Acceptance check 2: corroborating evidence that coefficients reproduce Table 3.

    This check reproduces Table 3 from the Table 2 coefficients alone. It is
    corroborating evidence; the vertex test is the primary proof that the
    transform is correct. Table 2 publishes b0/b1/b2 to one decimal place, so
    re-deriving Table 3's boundaries from them lands within ~1.5 percentage
    points of exactly 98%, not bit-for-bit on it (measured: 0.976-0.995 across
    all six boundaries checked here) — the task report has the per-boundary
    numbers. The 0.02 tolerance below is that measured spread, not a value
    adjusted until the test passed.
    """
    curve = PLANTING_CURVES[region]
    low_doy, high_doy = PUBLISHED_98_100_WINDOWS_DOY[region]
    assert relative_yield(curve, day_of_year=low_doy) == pytest.approx(0.98, abs=0.02)
    assert relative_yield(curve, day_of_year=high_doy) == pytest.approx(0.98, abs=0.02)

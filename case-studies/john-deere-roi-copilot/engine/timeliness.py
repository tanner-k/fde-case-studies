"""Measuring an agronomic window from observed crop progress.

Phase 1 put window length on the landscape exhibit's y-axis and filled it with
author estimates, which left the gate unable to separate a wrong thesis from
wrong inputs (`deliverables/appendix/assumptions.md` §11.3). NASS publishes
weekly percent-complete for planting and harvest, so the window can be
measured instead: the span between the weeks at which the state passed two
progress percentiles, interpolated between observations and reduced to a
median across every year on record.

**Two quantities, and the second is the one that binds.** Calendar days say
how long the operation took. `days_suitable` says how many of those days were
workable at all — NASS surveys it weekly for exactly this reason. A 20-day
window containing 6 workable days is a far harder promise for a service
provider to keep than a 20-day window containing 18, and it is the workable
count that decides whether acres can route to an operator.

**The percentile pair is a declared choice, not a fitted one.** Measured
against Iowa 2006-2026, corn planting spans 11 days at 25-75 and 25 days at
10-90 on opposite sides of the exhibit's 14-day narrow-window cut. The
primary is 25-75, chosen before any gate was run, because what constrains a
service provider is the period when the operation runs at scale and every
provider is busy at once; the wider pairs add early southern-Iowa fields and
late replants, which stretch the statewide span without stretching any single
farm's window. `SENSITIVITY_PERCENTILES` exists so the exhibit can report how
much the answer depends on that choice.

**Every window here is a statewide quantity.** NASS does not publish crop
progress by county, so this measures the dispersion of the whole state, which
aggregates latitude, soil and local weather. A single farm's window is
narrower. Read these as an upper bound.

No I/O: `etl.crop_progress` reads the panel, `etl.reference` does the join.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Self

from pydantic import Field, model_validator

from engine.models import Crop, FrozenModel, NonNegative

#: The declared primary definition. See the module docstring for why, and
#: `deliverables/appendix/assumptions.md` §11.2 for the version a reader sees.
PRIMARY_PERCENTILES: tuple[float, float] = (25.0, 75.0)

#: Reported alongside the primary so the reader can see the answer's
#: sensitivity to a choice the model had to make without a source.
SENSITIVITY_PERCENTILES: tuple[tuple[float, float], ...] = ((10.0, 90.0), (5.0, 95.0))

DAYS_PER_WEEK = 7


class ProgressPoint(FrozenModel):
    """One weekly observation of how far an operation has got."""

    week_ending: date
    percent_complete: float = Field(ge=0.0, le=100.0)


class SuitableWeek(FrozenModel):
    """Days in one week that were suitable for fieldwork."""

    week_ending: date
    days_suitable: float = Field(ge=0.0, le=7.0)


class MeasuredWindow(FrozenModel):
    """One operation's window, measured across every year on record."""

    series_key: str = Field(min_length=1)
    low_percentile: float = Field(gt=0.0, lt=100.0)
    high_percentile: float = Field(gt=0.0, le=100.0)
    years_observed: int = Field(ge=1)
    median_calendar_days: NonNegative
    min_calendar_days: int = Field(ge=0)
    max_calendar_days: int = Field(ge=0)
    #: The median, across years, of each year's own count of workable days
    #: inside that year's own window — not the workable-day count inside the
    #: single window `median_calendar_days` describes; a year with a
    #: below-median span can still contribute an above-median suitable-day
    #: count, and vice versa. Usually at or below `median_calendar_days`, and
    #: the gap is the timeliness risk, but the two are medians of different
    #: per-year series, not two readings off the same window.
    median_suitable_days: NonNegative
    #: Median, across years, of the day-of-year the high-percentile crossing
    #: falls on — i.e. the day the window closes. A `PlantingDateCurve` needs a
    #: single calendar reference day to price a delay against; this is it.
    median_closing_day_of_year: int = Field(ge=1, le=366)
    #: Years present in the input but excluded from the measurement — either
    #: the season never reached `high_percentile`, or its straddling
    #: observations were more than `max_gap_days` apart (a reporting gap, not
    #: observed dispersion). `years_observed` alone hides which is which.
    years_excluded: tuple[int, ...] = Field(default_factory=tuple)


def crossing_date(
    points: Sequence[ProgressPoint], *, percent: float, max_gap_days: float = 10.0
) -> date | None:
    """The date the series first reached `percent`, interpolated between weeks.

    NASS reports weekly, so a crossing almost never lands on an observation.
    Linear interpolation between the two straddling weeks is the same treatment
    the underlying survey's own five-year averages get — but only when NASS
    actually reported both weeks. Iowa's harvest panel has multi-week gaps
    where reporting was suspended (e.g. 2025-09-28 to 2025-11-16, 49 days);
    interpolating a crossing across a hole that wide manufactures dispersion
    that was never observed, not measures it.

    Args:
        points: Weekly observations; sorted internally, so callers need not.
        percent: The progress level to find.
        max_gap_days: The largest gap, in days, between the two observations
            straddling `percent` that interpolation will still trust. A wider
            gap returns `None` rather than a crossing date.

    Returns:
        The date, or `None` if the series never reaches `percent`, or if the
        straddling observations are more than `max_gap_days` apart. A series
        whose first observation is already at or above `percent` returns that
        first week rather than extrapolating backwards — the operation started
        somewhere before it, but nothing here says where.
    """
    previous: ProgressPoint | None = None
    for point in sorted(points, key=lambda p: p.week_ending):
        if point.percent_complete >= percent:
            if previous is None or point.percent_complete == previous.percent_complete:
                return point.week_ending
            span_days = (point.week_ending - previous.week_ending).days
            if span_days > max_gap_days:
                return None
            share = (percent - previous.percent_complete) / (
                point.percent_complete - previous.percent_complete
            )
            return date.fromordinal(
                round(previous.week_ending.toordinal() + share * span_days)
            )
        previous = point
    return None


def window_calendar_days(
    points: Sequence[ProgressPoint], *, low_percentile: float, high_percentile: float
) -> int | None:
    """Calendar days between two percentile crossings in one year.

    Args:
        points: One year's weekly observations.
        low_percentile: Where the window opens.
        high_percentile: Where it closes.

    Returns:
        Days, or `None` if the year never reached `high_percentile` — a season
        cut short by a survey that stopped reporting is not a zero-day window.

    Raises:
        ValueError: If the percentiles are reversed or equal.
    """
    if low_percentile >= high_percentile:
        raise ValueError(
            f"low_percentile {low_percentile} must be below high_percentile {high_percentile}"
        )
    start = crossing_date(points, percent=low_percentile)
    end = crossing_date(points, percent=high_percentile)
    if start is None or end is None:
        return None
    return (end - start).days


def suitable_days_between(
    weeks: Sequence[SuitableWeek], *, start: date, end: date
) -> float:
    """Days suitable for fieldwork inside a span, prorating partial weeks.

    NASS reports days suitable per week, and a window rarely aligns to week
    boundaries. Each week contributes in proportion to how much of it the span
    covers, which assumes suitable days are spread evenly within a week — the
    finest split the published data supports.

    Args:
        weeks: Weekly days-suitable observations, any number of years.
        start: First day of the span, inclusive.
        end: Last day of the span, inclusive.

    Returns:
        Suitable days. Weeks outside the span contribute nothing.

    Raises:
        ValueError: If `end` precedes `start`.
    """
    if end < start:
        raise ValueError(f"start {start} must not be after end {end}")
    total = 0.0
    for week in weeks:
        week_start = date.fromordinal(week.week_ending.toordinal() - (DAYS_PER_WEEK - 1))
        covered = (min(week.week_ending, end) - max(week_start, start)).days + 1
        if covered > 0:
            total += week.days_suitable * min(covered, DAYS_PER_WEEK) / DAYS_PER_WEEK
    return total


def measure_window(
    points_by_year: Mapping[int, Sequence[ProgressPoint]],
    weeks: Sequence[SuitableWeek],
    *,
    series_key: str,
    low_percentile: float = PRIMARY_PERCENTILES[0],
    high_percentile: float = PRIMARY_PERCENTILES[1],
) -> MeasuredWindow:
    """Reduce every year's window to one measurement.

    The median rather than the mean: a single year in which the survey stopped
    early, or in which planting stalled for a month of rain, should not drag
    the figure the exhibit plots.

    Args:
        points_by_year: One year's observations per key.
        weeks: Days-suitable observations spanning the same years.
        series_key: The NASS series being measured, carried onto the result.
        low_percentile: Where the window opens.
        high_percentile: Where it closes.

    Returns:
        A `MeasuredWindow` over every year that reached `high_percentile` with
        its crossings no more than `crossing_date`'s default `max_gap_days`
        apart. Years excluded either way are named on `years_excluded`.

    Raises:
        ValueError: If the percentiles are reversed, or if no year completed.
    """
    if low_percentile >= high_percentile:
        raise ValueError(
            f"low_percentile {low_percentile} must be below high_percentile {high_percentile}"
        )
    spans: list[int] = []
    workable: list[float] = []
    closing_days_of_year: list[int] = []
    excluded_years: list[int] = []
    for year in sorted(points_by_year):
        points = points_by_year[year]
        start = crossing_date(points, percent=low_percentile)
        end = crossing_date(points, percent=high_percentile)
        if start is None or end is None:
            excluded_years.append(year)
            continue
        span_days = (end - start).days
        spans.append(span_days)
        closing_days_of_year.append(end.timetuple().tm_yday)
        # window_calendar_days measures elapsed days (exclusive of end) while
        # suitable_days_between counts inclusively at both ends, so we adjust
        # the end date back one day to align the measurements.
        workable.append(
            0.0
            if span_days == 0
            else suitable_days_between(
                weeks, start=start, end=date.fromordinal(end.toordinal() - 1)
            )
        )

    if not spans:
        raise ValueError(
            f"no year in {sorted(points_by_year)} reached {high_percentile}% for "
            f"{series_key!r}; there is nothing to measure"
        )
    return MeasuredWindow(
        series_key=series_key,
        low_percentile=low_percentile,
        high_percentile=high_percentile,
        years_observed=len(spans),
        median_calendar_days=statistics.median(spans),
        min_calendar_days=min(spans),
        max_calendar_days=max(spans),
        median_suitable_days=statistics.median(workable),
        median_closing_day_of_year=round(statistics.median(closing_days_of_year)),
        years_excluded=tuple(excluded_years),
    )


# --- Planting-date yield response ---------------------------------------------
#
# `measure_window` above answers "how long is the window." This answers "what
# does a day of it cost." Iowa corn is the only operation in the landscape
# exhibit with a controlled-trial curve for that (Abendroth et al. 2017;
# `deliverables/appendix/assumptions.md` §11.7 has the sourcing verdict for
# the other nine). This section stays a standalone capability — it does not
# touch the exhibit's axis or `scripts/figures.py`; that is a later decision.

#: Abendroth et al. (2017) transform their day-of-year before fitting:
#: x = (DOY - _X_CENTER_DOY) / _X_SCALE_DAYS. Centering on the midpoint of the
#: trial's target planting range (DOY 120, 30 April) and scaling by 40 is what
#: "allow[ed] model convergence and [had] the intercept be easily interpreted"
#: (the paper's Statistical Analysis section). Applying the published
#: coefficients to a raw, untransformed DOY produces a curve that looks
#: plausible and is wrong — see `data/reference/planting_date_response.json`'s
#: `x_transform` field for the paper's own wording.
_X_CENTER_DOY = 120
_X_SCALE_DAYS = 40


class PlantingDateCurve(FrozenModel):
    """One Iowa site-grouping's fitted quadratic, transcribed from Table 2.

    `yield = b0 + b1*x + b2*x^2`, x the transformed day-of-year (see
    `_X_CENTER_DOY`/`_X_SCALE_DAYS`). The paper fits three of these for Iowa
    corn — NC-NE, NW-C, SW-SE — one site-grouping, not one farm and not a
    statewide average; picking a different grouping, or averaging them,
    moves every number computed from it.
    """

    crop: Crop
    region: str = Field(min_length=1)
    b0: float
    b1: float
    b2: float
    day_of_year_at_max_published: int = Field(gt=0, le=366)
    valid_day_of_year_range: tuple[int, int]
    source: str = Field(min_length=1)
    retrieved: str = Field(min_length=1)

    @model_validator(mode="after")
    def _reject_convex_curve(self) -> Self:
        """`b2 >= 0` means yield rising without bound — a transcription error, not biology."""
        if self.b2 >= 0:
            raise ValueError(
                f"{self.region}: b2={self.b2} is non-negative; the planting-date yield "
                "response is concave, so a non-negative quadratic term is a mis-transcribed "
                "coefficient, not a real curve"
            )
        return self

    @model_validator(mode="after")
    def _reject_backwards_range(self) -> Self:
        low, high = self.valid_day_of_year_range
        if low >= high:
            raise ValueError(
                f"{self.region}: valid_day_of_year_range {self.valid_day_of_year_range} "
                "must be increasing"
            )
        return self


def _transformed_day_of_year(day_of_year: int) -> float:
    """Table 2's `x`: the trial's own centering and scaling, not a raw DOY."""
    return (day_of_year - _X_CENTER_DOY) / _X_SCALE_DAYS


def _yield_at_x(curve: PlantingDateCurve, x: float) -> float:
    """The quadratic itself, already in transformed-x space."""
    return curve.b0 + curve.b1 * x + curve.b2 * x * x


def _x_star(curve: PlantingDateCurve) -> float:
    """The transformed x-coordinate of the quadratic's vertex."""
    return -curve.b1 / (2 * curve.b2)


def fitted_yield(curve: PlantingDateCurve, *, day_of_year: int) -> float:
    """The paper's fitted quadratic, evaluated at a calendar day-of-year.

    Args:
        curve: The site-grouping's transcribed coefficients.
        day_of_year: 1 = 1 January.

    Returns:
        Grain yield (bu/acre) predicted by the quadratic.

    Raises:
        ValueError: If `day_of_year` falls outside `curve.valid_day_of_year_range`
            — the trial did not test planting there, so the quadratic would be
            extrapolation.
    """
    low, high = curve.valid_day_of_year_range
    if not (low <= day_of_year <= high):
        raise ValueError(
            f"day_of_year {day_of_year} is outside {curve.region}'s tested range "
            f"{curve.valid_day_of_year_range}; the fitted quadratic is extrapolation there"
        )
    return _yield_at_x(curve, _transformed_day_of_year(day_of_year))


def day_of_year_at_max(curve: PlantingDateCurve) -> float:
    """The vertex of the fitted quadratic, in day-of-year.

    Computed from `b1`/`b2` alone, independent of `day_of_year_at_max_published`
    — the acceptance test in `tests/test_timeliness.py` checks this against the
    paper's own published value, which is the proof the transform is right.

    Args:
        curve: The site-grouping's transcribed coefficients.

    Returns:
        The day-of-year of maximum fitted yield, unrounded — unlike the
        paper's published integer.
    """
    return _X_CENTER_DOY + _X_SCALE_DAYS * _x_star(curve)


def relative_yield(curve: PlantingDateCurve, *, day_of_year: int) -> float:
    """Fitted yield as a fraction of the curve's fitted maximum.

    Args:
        curve: The site-grouping's transcribed coefficients.
        day_of_year: 1 = 1 January.

    Returns:
        A value in (0, 1]: exactly 1.0 at the vertex, below 1.0 either side of it.

    Raises:
        ValueError: If `day_of_year` falls outside `curve.valid_day_of_year_range`.
    """
    fitted = fitted_yield(curve, day_of_year=day_of_year)
    y_max = _yield_at_x(curve, _x_star(curve))
    return fitted / y_max


def yield_loss_fraction(curve: PlantingDateCurve, *, day_of_year: int) -> float:
    """`1 - relative_yield`: zero at the optimum, rising away from it.

    Args:
        curve: The site-grouping's transcribed coefficients.
        day_of_year: 1 = 1 January.

    Returns:
        A value in `[0, 1)`.

    Raises:
        ValueError: If `day_of_year` falls outside `curve.valid_day_of_year_range`.
    """
    return 1.0 - relative_yield(curve, day_of_year=day_of_year)


def delay_cost_usd_per_acre_per_day(
    curve: PlantingDateCurve,
    *,
    day_of_year: int,
    optimal_yield_bu_per_acre: float,
    price_usd_per_bu: float,
) -> float:
    """The average dollar cost per day of the delay elapsed since the optimum.

    This is `total loss / days elapsed`, an average rate over the delay — not
    the marginal cost of the next single day, which is the slope of a concave
    loss curve and therefore roughly double this average at any given day (see
    `Returns` below).

    Args:
        curve: The site-grouping's transcribed coefficients.
        day_of_year: The planting date being costed. 1 = 1 January.
        optimal_yield_bu_per_acre: Yield achievable planting at the optimum.
        price_usd_per_bu: Grain price.

    Returns:
        Dollars per acre per day, averaged over the days elapsed since the
        optimum. Zero when `day_of_year` is on or before `day_of_year_at_max(curve)`.

    Raises:
        ValueError: If `optimal_yield_bu_per_acre` or `price_usd_per_bu` is
            negative, or if `day_of_year` falls outside `curve.valid_day_of_year_range`.
    """
    low, high = curve.valid_day_of_year_range
    if not (low <= day_of_year <= high):
        raise ValueError(
            f"day_of_year {day_of_year} is outside {curve.region}'s tested range "
            f"{curve.valid_day_of_year_range}; the fitted quadratic is extrapolation there"
        )
    if optimal_yield_bu_per_acre < 0:
        raise ValueError(f"optimal_yield_bu_per_acre {optimal_yield_bu_per_acre} is negative")
    if price_usd_per_bu < 0:
        raise ValueError(f"price_usd_per_bu {price_usd_per_bu} is negative")
    days_after_optimum = day_of_year - day_of_year_at_max(curve)
    if days_after_optimum <= 0:
        return 0.0
    loss = yield_loss_fraction(curve, day_of_year=day_of_year)
    return loss * optimal_yield_bu_per_acre * price_usd_per_bu / days_after_optimum

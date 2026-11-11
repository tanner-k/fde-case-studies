"""Quantile yield model, and the climatology baseline it has to beat.

The question is narrow: does county-year weather carry information about yield
that a linear time trend does not already contain? The honest way to answer it
is to build the baseline properly and then try to beat it.

**The baseline.** Fit yield against year with a free intercept per county,
detrend, take the empirical quantiles of the training residuals, and forecast
the trend at year *t* plus those quantiles. Fifteen lines, no hyperparameters,
and hard to beat — a county's yield is mostly its own soil plus four decades of
genetics, both of which the trend already captures.

**The challenger.** One `GradientBoostingRegressor(loss="quantile")` per
quantile over year, county, and growing-season weather aggregates.

**The evaluation.** Pinball loss on held-out *years*, expanding window: train on
everything before year *t*, predict year *t*. A random split would put 2012's
drought in both train and test through its neighbouring counties and would
leak the trend besides; both models would look better than they are, and the
challenger would look better than the baseline for the wrong reason.

If the challenger does not win, the baseline ships. That result is recorded in
`deliverables/appendix/model-card.md`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import polars as pl
from sklearn.ensemble import GradientBoostingRegressor

#: Quantiles the engine needs: a central estimate and a plausible range.
QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)

#: Corn growing-degree-day convention: tmax capped, tmin floored, base 50F.
GDD_BASE_F = 50.0
GDD_CAP_F = 86.0
HOT_DAY_F = 90.0

FEATURE_COLUMNS = (
    "year",
    "gdd_50_86",
    "precip_in_apr_oct",
    "precip_in_june",
    "hot_days_jul_aug",
    "tmax_f_july",
    "yield_lag1_bu_per_acre",
)


@dataclass(frozen=True)
class Verdict:
    """Which model won the bake-off, and by how much.

    Attributes:
        baseline_pinball: Mean pinball loss of the climatology baseline.
        gbm_pinball: Mean pinball loss of the gradient booster.
        improvement_pct: Positive when the booster beats the baseline.
        baseline_wins: True when the baseline is the model that ships.
        years_won: Held-out years the booster won outright.
        years_total: Held-out years evaluated.
    """

    baseline_pinball: float
    gbm_pinball: float
    improvement_pct: float
    baseline_wins: bool
    years_won: int
    years_total: int


def pinball_loss(actual: np.ndarray, predicted: np.ndarray, quantile: float) -> float:
    """Mean pinball (quantile) loss.

    The proper scoring rule for a quantile forecast: under-predicting the 90th
    percentile is penalised nine times as hard as over-predicting it, which is
    what makes it minimised at the true quantile rather than the mean.

    Args:
        actual: Observed values.
        predicted: Forecast values, same length.
        quantile: Quantile the forecast claims to be, in (0, 1).

    Returns:
        Mean loss, in the units of `actual`.
    """
    error = actual - predicted
    return float(np.mean(np.maximum(quantile * error, (quantile - 1.0) * error)))


def growing_season_features(daily: pl.DataFrame) -> pl.DataFrame:
    """Aggregate daily county weather into one row per county-year.

    Windows follow Corn Belt agronomy rather than the calendar: degree days
    over May-September, moisture over April-October, heat stress over the
    July-August pollination and grain-fill period.

    Args:
        daily: Rows of `county_fips`, `date`, `tmax_f`, `tmin_f`, `precip_in`.

    Returns:
        One row per county-year with `FEATURE_COLUMNS` minus `year` handling.
    """
    month = pl.col("date").dt.month()
    gdd = (
        (pl.col("tmax_f").clip(upper_bound=GDD_CAP_F) + pl.col("tmin_f").clip(GDD_BASE_F)) / 2.0
        - GDD_BASE_F
    ).clip(0.0)
    return (
        daily.with_columns(year=pl.col("date").dt.year(), month=month, gdd=gdd)
        .group_by("county_fips", "year")
        .agg(
            pl.col("gdd").filter(pl.col("month").is_between(5, 9)).sum().alias("gdd_50_86"),
            pl.col("precip_in")
            .filter(pl.col("month").is_between(4, 10))
            .sum()
            .alias("precip_in_apr_oct"),
            pl.col("precip_in").filter(pl.col("month") == 6).sum().alias("precip_in_june"),
            (pl.col("tmax_f") >= HOT_DAY_F)
            .filter(pl.col("month").is_between(7, 8))
            .sum()
            .cast(pl.Float64)
            .alias("hot_days_jul_aug"),
            pl.col("tmax_f").filter(pl.col("month") == 7).mean().alias("tmax_f_july"),
        )
        .sort("county_fips", "year")
    )


def build_design(yields: pl.DataFrame, features: pl.DataFrame) -> pl.DataFrame:
    """Join county yields to their growing-season weather and last year's yield.

    The lag is taken within a county and only from the immediately preceding
    year, so a county-year whose predecessor NASS suppressed is dropped rather
    than silently given a stale value. Last year's yield is known before this
    year is planted, so using it as a feature is legitimate — this is the
    "historical yield" half of the design brief.

    Args:
        yields: `county_fips`, `year`, `yield_bu_per_acre`.
        features: Output of `growing_season_features`.

    Returns:
        The inner join, sorted, with no null rows. The earliest year per county
        is absent because it has no lag.
    """
    lagged = yields.select(
        "county_fips",
        (pl.col("year") + 1).alias("year"),
        pl.col("yield_bu_per_acre").alias("yield_lag1_bu_per_acre"),
    )
    return (
        yields.join(features, on=["county_fips", "year"], how="inner")
        .join(lagged, on=["county_fips", "year"], how="inner")
        .drop_nulls()
        .sort("year", "county_fips")
    )


def _county_trend(train: pl.DataFrame) -> tuple[float, dict[str, float]]:
    """Fit one shared slope with a free intercept per county.

    Args:
        train: Design rows to fit on.

    Returns:
        The slope and each county's intercept in absolute year units.
    """
    means = train.group_by("county_fips").agg(
        pl.col("yield_bu_per_acre").mean().alias("ym"), pl.col("year").mean().alias("tm")
    )
    joined = train.join(means, on="county_fips")
    dv = (joined["yield_bu_per_acre"] - joined["ym"]).to_numpy()
    dt = (joined["year"] - joined["tm"]).to_numpy()
    slope = float(dv @ dt / (dt @ dt)) if float(dt @ dt) > 0.0 else 0.0
    intercepts = {
        fips: float(ym - slope * tm)
        for fips, ym, tm in zip(
            means["county_fips"].to_list(), means["ym"], means["tm"], strict=True
        )
    }
    return slope, intercepts


def climatology_forecast(
    train: pl.DataFrame, test: pl.DataFrame, quantiles: Sequence[float]
) -> dict[float, np.ndarray]:
    """Forecast quantiles as the fitted trend plus empirical residual quantiles.

    Args:
        train: Rows strictly before the evaluation year.
        test: Rows to predict, in the order predictions are wanted.
        quantiles: Quantiles to forecast.

    Returns:
        Quantile to predictions aligned with `test`.
    """
    train_level, test_level = trend_feature(train, test)
    residuals = train["yield_bu_per_acre"].to_numpy() - train_level
    return {q: test_level + float(np.quantile(residuals, q)) for q in quantiles}


def trend_feature(train: pl.DataFrame, test: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """The baseline's own trend prediction, as a feature for the challenger.

    Fitted on `train` only, so nothing about the evaluation year leaks. Handing
    it over is what makes the bake-off a test of *weather*: the booster starts
    from everything the baseline knows and is asked only whether it can add to
    it. A booster given year and rainfall but not county identity would lose on
    soil quality, which is not the question.

    Args:
        train: Rows strictly before the evaluation year.
        test: Rows to predict.

    Returns:
        Trend levels for `train` and for `test`.
    """
    slope, intercepts = _county_trend(train)
    fallback = float(np.mean(list(intercepts.values()))) if intercepts else 0.0

    def level(frame: pl.DataFrame) -> np.ndarray:
        base = np.array([intercepts.get(f, fallback) for f in frame["county_fips"].to_list()])
        return base + slope * frame["year"].to_numpy()

    return level(train), level(test)


def design_matrices(train: pl.DataFrame, test: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Build the booster's feature matrices: `FEATURE_COLUMNS` plus the trend.

    Args:
        train: Rows strictly before the evaluation year.
        test: Rows to predict.

    Returns:
        Train and test matrices, trend in the final column.
    """
    train_trend, test_trend = trend_feature(train, test)
    return (
        np.column_stack([train.select(FEATURE_COLUMNS).to_numpy(), train_trend]),
        np.column_stack([test.select(FEATURE_COLUMNS).to_numpy(), test_trend]),
    )


def gbm_forecast(
    train: pl.DataFrame, test: pl.DataFrame, quantiles: Sequence[float], seed: int
) -> dict[float, np.ndarray]:
    """Forecast quantiles with one gradient-boosted quantile regressor each.

    Library defaults throughout. The brief was to find out whether weather adds
    signal, not to tune until it appears to.

    Args:
        train: Rows strictly before the evaluation year.
        test: Rows to predict.
        quantiles: Quantiles to forecast.
        seed: Fixed for reproducibility.

    Returns:
        Quantile to predictions aligned with `test`.
    """
    x_train, x_test = design_matrices(train, test)
    y_train = train["yield_bu_per_acre"].to_numpy()
    predictions = {}
    for quantile in quantiles:
        model = GradientBoostingRegressor(
            loss="quantile", alpha=quantile, random_state=seed
        ).fit(x_train, y_train)
        predictions[quantile] = model.predict(x_test)
    return predictions


def backtest(
    design: pl.DataFrame,
    *,
    holdout_years: Sequence[int],
    quantiles: Sequence[float] = QUANTILES,
    seed: int = 0,
    _observer: Callable[[pl.DataFrame, pl.DataFrame], None] | None = None,
) -> pl.DataFrame:
    """Score both models on each held-out year with an expanding window.

    Args:
        design: Output of `build_design`.
        holdout_years: Years to evaluate, each trained on everything before it.
        quantiles: Quantiles to score, averaged into one loss per year.
        seed: Passed to the booster.
        _observer: Test hook receiving each (train, test) split.

    Returns:
        One row per held-out year, ascending.

    Raises:
        ValueError: If a holdout year has no history before it.
    """
    rows = []
    for year in sorted(holdout_years):
        train = design.filter(pl.col("year") < year)
        test = design.filter(pl.col("year") == year)
        if train.is_empty():
            raise ValueError(f"holdout year {year} has no training rows before it")
        if test.is_empty():
            raise ValueError(f"holdout year {year} has no rows to score")
        if _observer is not None:
            _observer(train, test)

        actual = test["yield_bu_per_acre"].to_numpy()
        baseline = climatology_forecast(train, test, quantiles)
        gbm = gbm_forecast(train, test, quantiles, seed)
        rows.append(
            {
                "year": year,
                "n_counties": test.height,
                "baseline_pinball": float(
                    np.mean([pinball_loss(actual, baseline[q], q) for q in quantiles])
                ),
                "gbm_pinball": float(
                    np.mean([pinball_loss(actual, gbm[q], q) for q in quantiles])
                ),
            }
        )
    return pl.DataFrame(rows)


def verdict(result: pl.DataFrame) -> Verdict:
    """Reduce a backtest to the decision it implies.

    Args:
        result: Output of `backtest`.

    The challenger must win on **both** mean pinball loss and a majority of
    held-out years. Mean alone is not a decision rule: a mean over years is
    dominated by whichever year had the largest spread, so one anomalous season
    can carry a model that is worse in most years.

    That is not hypothetical. On the real Iowa corn backtest the booster beat the
    baseline by 3.2% on the mean while losing 6 of 10 years — the whole margin
    came from 2016, and excluding that year it was 6.8% worse. Under a
    mean-only rule it would have shipped.

    Returns:
        Which model ships, and the margin.
    """
    baseline = float(result["baseline_pinball"].mean())
    gbm = float(result["gbm_pinball"].mean())
    won = int((result["gbm_pinball"] < result["baseline_pinball"]).sum())
    wins_on_mean = gbm < baseline
    wins_majority = won * 2 > result.height
    return Verdict(
        baseline_pinball=baseline,
        gbm_pinball=gbm,
        improvement_pct=100.0 * (baseline - gbm) / baseline,
        baseline_wins=not (wins_on_mean and wins_majority),
        years_won=won,
        years_total=result.height,
    )

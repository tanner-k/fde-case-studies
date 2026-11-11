"""Tests for the quantile yield model and its climatology baseline.

Small synthetic frames, no network, no `data/raw`. The point of these tests is
not that the gradient booster is accurate — it may well lose the bake-off — but
that the comparison is *fair*: the loss function is correct, the baseline is
competently built rather than strawmanned, and no evaluation year leaks into
its own training set.

A random train/test split would leak the trend, which is most of the signal in
county yield, and would flatter both models. The split here is always temporal.
"""

import numpy as np
import polars as pl
import pytest
from ml import yield_model as ym

QUANTILES = (0.1, 0.5, 0.9)
COUNTIES = tuple(f"19{2 * i + 1:03d}" for i in range(8))
YEARS = tuple(range(2006, 2026))


def linear_panel(*, noise_sd: float = 0.0, seed: int = 11) -> pl.DataFrame:
    """A design frame whose yield is a pure linear trend plus optional noise."""
    rng = np.random.default_rng(seed)
    return pl.DataFrame(
        [
            {
                "county_fips": fips,
                "year": year,
                "yield_bu_per_acre": 100.0 + 2.0 * (year - 2006) + rng.normal(0.0, noise_sd),
                "yield_lag1_bu_per_acre": 98.0 + 2.0 * (year - 2006) + rng.normal(0.0, noise_sd),
                "gdd_50_86": 2500.0 + rng.normal(0.0, 50.0),
                "precip_in_apr_oct": 24.0 + rng.normal(0.0, 2.0),
                "hot_days_jul_aug": 8.0 + rng.normal(0.0, 1.0),
                "tmax_f_july": 85.0 + rng.normal(0.0, 1.0),
                "precip_in_june": 5.0 + rng.normal(0.0, 1.0),
            }
            for year in YEARS
            for fips in COUNTIES
        ]
    )


def daily_frame() -> pl.DataFrame:
    """Two counties of daily weather with values chosen to be checkable by hand."""
    rows = []
    for fips in ("19001", "19003"):
        for month, days in ((4, 30), (7, 31), (11, 30)):
            for day in range(1, days + 1):
                rows.append(
                    {
                        "county_fips": fips,
                        "date": f"2010-{month:02d}-{day:02d}",
                        "tmax_f": 95.0 if month == 7 else 60.0,
                        "tmin_f": 45.0,
                        "precip_in": 0.1,
                    }
                )
    return pl.DataFrame(rows).with_columns(pl.col("date").str.to_date("%Y-%m-%d"))


# --- pinball loss -----------------------------------------------------------


def test_pinball_loss_penalizes_under_and_over_prediction_asymmetrically():
    # q=0.9: being 10 under costs 0.9 * 10; being 10 over costs 0.1 * 10.
    under = ym.pinball_loss(np.array([100.0]), np.array([90.0]), 0.9)
    over = ym.pinball_loss(np.array([100.0]), np.array([110.0]), 0.9)
    assert under == pytest.approx(9.0)
    assert over == pytest.approx(1.0)


def test_pinball_loss_at_the_median_is_half_the_absolute_error():
    actual = np.array([10.0, 20.0, 30.0])
    predicted = np.array([12.0, 17.0, 30.0])
    assert ym.pinball_loss(actual, predicted, 0.5) == pytest.approx(np.mean([2, 3, 0]) / 2)


def test_pinball_loss_is_minimized_at_the_true_quantile():
    sample = np.random.default_rng(0).normal(50.0, 10.0, 20_000)
    truth = float(np.quantile(sample, 0.9))
    best = ym.pinball_loss(sample, np.full_like(sample, truth), 0.9)
    for wrong in (truth - 4.0, truth + 4.0):
        assert ym.pinball_loss(sample, np.full_like(sample, wrong), 0.9) > best


# --- weather features -------------------------------------------------------


def test_build_design_adds_last_years_yield_and_drops_the_year_that_has_none():
    """Lag-1 yield is known at prediction time, so the challenger may use it."""
    yields = pl.DataFrame(
        {
            "county_fips": ["19001", "19001", "19003", "19003"],
            "year": [2010, 2011, 2010, 2011],
            "yield_bu_per_acre": [100.0, 110.0, 200.0, 220.0],
        }
    ).with_columns(pl.col("year").cast(pl.Int32))
    features = pl.DataFrame(
        {
            "county_fips": ["19001", "19001", "19003", "19003"],
            "year": [2010, 2011, 2010, 2011],
            "gdd_50_86": [2500.0] * 4,
            "precip_in_apr_oct": [24.0] * 4,
            "precip_in_june": [5.0] * 4,
            "hot_days_jul_aug": [8.0] * 4,
            "tmax_f_july": [85.0] * 4,
        }
    ).with_columns(pl.col("year").cast(pl.Int32))

    design = ym.build_design(yields, features)
    assert design["year"].to_list() == [2011, 2011]
    assert design.sort("county_fips")["yield_lag1_bu_per_acre"].to_list() == [100.0, 200.0]


def test_the_lag_never_reaches_across_a_county_boundary():
    yields = pl.DataFrame(
        {
            "county_fips": ["19001", "19003"],
            "year": [2010, 2011],
            "yield_bu_per_acre": [100.0, 200.0],
        }
    ).with_columns(pl.col("year").cast(pl.Int32))
    features = yields.select("county_fips", "year").with_columns(
        gdd_50_86=pl.lit(2500.0),
        precip_in_apr_oct=pl.lit(24.0),
        precip_in_june=pl.lit(5.0),
        hot_days_jul_aug=pl.lit(8.0),
        tmax_f_july=pl.lit(85.0),
    )
    # 19003's only year is 2011 and it has no 2010 row of its own to borrow from.
    assert ym.build_design(yields, features).is_empty()


def test_growing_season_features_use_the_right_windows_and_caps():
    features = ym.growing_season_features(daily_frame()).sort("county_fips")
    row = features.row(0, named=True)
    # April + July only; November is outside the April-October window.
    assert row["precip_in_apr_oct"] == pytest.approx(0.1 * 61)
    assert row["precip_in_june"] == pytest.approx(0.0)
    # July tmax 95F is capped at 86F, tmin 45F floored at 50F: (86+50)/2 - 50 = 18/day.
    # April: (60+50)/2 - 50 = 5/day. Window is May-September, so April is excluded.
    assert row["gdd_50_86"] == pytest.approx(18.0 * 31)
    assert row["hot_days_jul_aug"] == pytest.approx(31.0)
    assert row["tmax_f_july"] == pytest.approx(95.0)
    assert features.height == 2


# --- climatology baseline ---------------------------------------------------


def test_baseline_on_a_noiseless_trend_predicts_the_trend_at_every_quantile():
    panel = linear_panel(noise_sd=0.0)
    train = panel.filter(pl.col("year") < 2020)
    test = panel.filter(pl.col("year") == 2020)
    predictions = ym.climatology_forecast(train, test, QUANTILES)
    for quantile in QUANTILES:
        assert predictions[quantile] == pytest.approx(np.full(test.height, 128.0), abs=1e-6)


def test_baseline_quantiles_are_ordered_and_spread_with_the_noise():
    panel = linear_panel(noise_sd=15.0)
    train = panel.filter(pl.col("year") < 2020)
    test = panel.filter(pl.col("year") == 2020)
    predictions = ym.climatology_forecast(train, test, QUANTILES)
    assert (predictions[0.1] < predictions[0.5]).all()
    assert (predictions[0.5] < predictions[0.9]).all()
    assert predictions[0.9][0] - predictions[0.1][0] == pytest.approx(2 * 1.2816 * 15.0, rel=0.4)


def test_baseline_carries_county_level_differences_through():
    panel = linear_panel(noise_sd=0.0).with_columns(
        pl.when(pl.col("county_fips") == COUNTIES[0])
        .then(pl.col("yield_bu_per_acre") + 30.0)
        .otherwise(pl.col("yield_bu_per_acre"))
        .alias("yield_bu_per_acre")
    )
    train = panel.filter(pl.col("year") < 2020)
    test = panel.filter(pl.col("year") == 2020).sort("county_fips")
    median = ym.climatology_forecast(train, test, (0.5,))[0.5]
    assert median[0] == pytest.approx(158.0, abs=1e-6)
    assert median[1] == pytest.approx(128.0, abs=1e-6)


# --- backtest ---------------------------------------------------------------


def test_no_evaluation_year_ever_appears_in_its_own_training_set():
    seen = []
    panel = linear_panel(noise_sd=8.0)

    def spy(train: pl.DataFrame, test: pl.DataFrame) -> None:
        seen.append((train["year"].max(), test["year"].unique().to_list()))

    ym.backtest(panel, holdout_years=(2023, 2024), quantiles=QUANTILES, seed=0, _observer=spy)
    assert seen == [(2022, [2023]), (2023, [2024])]


def test_backtest_scores_both_models_on_every_holdout_year():
    result = ym.backtest(
        linear_panel(noise_sd=8.0), holdout_years=(2023, 2024, 2025), quantiles=QUANTILES, seed=0
    )
    assert result["year"].to_list() == [2023, 2024, 2025]
    assert {"baseline_pinball", "gbm_pinball", "n_counties"} <= set(result.columns)
    assert (result["baseline_pinball"] > 0).all()
    assert (result["gbm_pinball"] > 0).all()


def test_backtest_is_seeded_and_repeatable():
    panel = linear_panel(noise_sd=8.0)
    kwargs = {"holdout_years": (2024, 2025), "quantiles": QUANTILES, "seed": 4}
    assert ym.backtest(panel, **kwargs).equals(ym.backtest(panel, **kwargs))


def test_the_gbm_is_handed_the_baselines_own_trend_so_the_bakeoff_is_fair():
    """Without this the challenger cannot see which county it is predicting.

    The baseline gets a free intercept per county. A booster fed only year and
    weather would have to infer the county's soil from its rainfall, and would
    lose for a reason that says nothing about whether weather carries signal.
    """
    panel = linear_panel(noise_sd=0.0)
    train = panel.filter(pl.col("year") < 2020)
    test = panel.filter(pl.col("year") == 2020)

    train_trend, test_trend = ym.trend_feature(train, test)
    assert test_trend == pytest.approx(np.full(test.height, 128.0), abs=1e-6)
    assert train_trend.shape == (train.height,)

    x_train, x_test = ym.design_matrices(train, test)
    assert x_train.shape[1] == len(ym.FEATURE_COLUMNS) + 1
    assert x_test[:, -1] == pytest.approx(test_trend)


def test_backtest_refuses_a_holdout_year_with_no_history_before_it():
    with pytest.raises(ValueError, match="2006"):
        ym.backtest(linear_panel(), holdout_years=(2006,), quantiles=QUANTILES, seed=0)


def test_verdict_reports_the_baseline_when_it_wins():
    result = pl.DataFrame(
        {"year": [2024, 2025], "baseline_pinball": [1.0, 1.0], "gbm_pinball": [2.0, 2.0]}
    )
    verdict = ym.verdict(result)
    assert verdict.baseline_wins
    assert verdict.improvement_pct < 0


def test_a_mean_win_driven_by_one_year_does_not_ship_the_challenger():
    """Observed on the real Iowa corn backtest (2026-08-12).

    The GBM beat the baseline on mean pinball loss by 3.2% while losing 6 of 10
    years. The entire margin came from 2016. Dropping that single year, the GBM
    was 6.8% *worse*. A mean over years is dominated by whichever year had the
    largest spread, so the mean alone is not a decision rule — the challenger
    must also win a majority of years.
    """
    result = pl.DataFrame(
        {
            "year": [2016, 2017, 2018, 2019, 2020],
            "baseline_pinball": [10.0, 3.0, 3.0, 3.0, 3.0],
            "gbm_pinball": [4.0, 3.5, 3.5, 3.5, 3.5],
        }
    )
    verdict = ym.verdict(result)
    assert verdict.improvement_pct > 0, "challenger does win on the mean"
    assert verdict.years_won == 1
    assert verdict.baseline_wins, "but it loses 4 of 5 years, so the baseline ships"


def test_the_challenger_ships_only_when_it_wins_on_both_mean_and_majority():
    result = pl.DataFrame(
        {
            "year": [2021, 2022, 2023],
            "baseline_pinball": [3.0, 3.0, 3.0],
            "gbm_pinball": [2.0, 2.0, 2.5],
        }
    )
    verdict = ym.verdict(result)
    assert verdict.years_won == 3
    assert not verdict.baseline_wins

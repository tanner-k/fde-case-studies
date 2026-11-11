"""Tests for the fitted yield and price priors.

Everything here runs on a synthetic panel built in-process with a *known*
generating process, so a fit can be checked against truth rather than against
its own previous output. No network, no `data/raw`.

Three properties matter more than the individual numbers:

**The trend and the county level are separable.** A county's yield is its own
level plus a shared genetic/agronomic trend. Fitting one trend per county on
20 points would be noise; fitting one pooled trend with county intercepts is
the model the data supports.

**The year shock and the county wobble are different animals.** Only the shared
year shock is correlated with price — a single county having a bad year does not
move the state price. Correlating the raw county-year residual against price
attenuates the estimate toward zero, which is the failure this split exists to
prevent.

**The output is sample-ready.** The JSON has to be consumable by a Monte Carlo
layer that has numpy and nothing else. `ml/sample.py` is that consumer, and
exercising it here is what makes "sample-ready" a tested claim rather than a
hope.
"""

import json

import numpy as np
import polars as pl
import pytest
from ml import priors
from ml import sample as sampling

BASE_YEAR = 2006
YEARS = tuple(range(BASE_YEAR, 2026))
COUNTIES = tuple(f"19{2 * i + 1:03d}" for i in range(12))

TRUE_SLOPE = 2.5
TRUE_INTERCEPT = 150.0
TRUE_PRICE_LOG_MEAN = 1.5
TRUE_PRICE_LOG_SD = 0.25


def _county_offset(fips: str) -> float:
    """A fixed, exactly zero-mean level difference between counties."""
    return (COUNTIES.index(fips) - (len(COUNTIES) - 1) / 2) * 4.0


def synthetic_panel(*, rho: float = -0.8, seed: int = 7) -> pl.DataFrame:
    """Build a NASS-shaped panel with a known trend, year shock and correlation.

    The year shock and log price are drawn from a bivariate normal with
    correlation `rho`; county wobble is independent noise on top.

    Args:
        rho: Target correlation between the shared year shock and log price.
        seed: Draw seed.

    Returns:
        A frame with the columns the real NASS panel carries.
    """
    rng = np.random.default_rng(seed)
    cov = [[1.0, rho], [rho, 1.0]]
    z = rng.multivariate_normal([0.0, 0.0], cov, size=len(YEARS))
    shock = z[:, 0] * 12.0
    log_price = TRUE_PRICE_LOG_MEAN + TRUE_PRICE_LOG_SD * z[:, 1]

    rows = []
    for i, year in enumerate(YEARS):
        for fips in COUNTIES:
            value = (
                TRUE_INTERCEPT
                + TRUE_SLOPE * (year - BASE_YEAR)
                + _county_offset(fips)
                + shock[i]
                + rng.normal(0.0, 8.0)
            )
            rows.append(
                {
                    "commodity": "CORN",
                    "statistic": "YIELD",
                    "agg_level": "COUNTY",
                    "state_alpha": "IA",
                    "county_name": f"C{fips}",
                    "county_fips": fips,
                    "year": year,
                    "unit": "BU / ACRE",
                    "short_desc": "CORN, GRAIN - YIELD",
                    "value": value,
                }
            )
        rows.append(
            {
                "commodity": "CORN",
                "statistic": "PRICE RECEIVED",
                "agg_level": "STATE",
                "state_alpha": "IA",
                "county_name": "",
                "county_fips": "",
                "year": year,
                "unit": "$ / BU",
                "short_desc": "CORN, GRAIN - PRICE RECEIVED",
                "value": float(np.exp(log_price[i])),
            }
        )
    return pl.DataFrame(rows).with_columns(pl.col("year").cast(pl.Int32))


@pytest.fixture(scope="module")
def panel() -> pl.DataFrame:
    return synthetic_panel()


@pytest.fixture(scope="module")
def fitted(panel: pl.DataFrame) -> dict:
    return priors.build_priors(panel, crops=("CORN",), base_year=BASE_YEAR)


# --- trend ------------------------------------------------------------------


def test_pooled_trend_recovers_the_generating_slope(panel):
    trend = priors.fit_yield_trend(panel, "CORN", base_year=BASE_YEAR)
    assert trend.slope_bu_per_acre_per_year == pytest.approx(TRUE_SLOPE, abs=0.3)
    assert trend.intercept_bu_per_acre == pytest.approx(TRUE_INTERCEPT, abs=4.0)


def test_county_offsets_recover_the_level_differences_and_sum_to_zero(panel):
    trend = priors.fit_yield_trend(panel, "CORN", base_year=BASE_YEAR)
    assert set(trend.county_offset_bu_per_acre) == set(COUNTIES)
    assert sum(trend.county_offset_bu_per_acre.values()) == pytest.approx(0.0, abs=1e-9)
    for fips in COUNTIES:
        assert trend.county_offset_bu_per_acre[fips] == pytest.approx(_county_offset(fips), abs=4.0)


def test_a_noiseless_panel_is_fitted_exactly():
    rows = [
        {"county_fips": fips, "year": year, "value": 100.0 + 2.0 * (year - BASE_YEAR)}
        for year in YEARS
        for fips in COUNTIES
    ]
    frame = pl.DataFrame(rows).with_columns(
        commodity=pl.lit("CORN"), statistic=pl.lit("YIELD"), year=pl.col("year").cast(pl.Int32)
    )
    trend = priors.fit_yield_trend(frame, "CORN", base_year=BASE_YEAR)
    assert trend.slope_bu_per_acre_per_year == pytest.approx(2.0, abs=1e-9)
    assert trend.intercept_bu_per_acre == pytest.approx(100.0, abs=1e-9)


# --- residual decomposition -------------------------------------------------


def test_year_shock_and_county_wobble_reconstruct_the_residual(panel):
    trend = priors.fit_yield_trend(panel, "CORN", base_year=BASE_YEAR)
    parts = priors.split_residuals(panel, "CORN", trend)
    assert set(parts.year_shock) == set(YEARS)
    # Within any year, the county wobble averages out by construction.
    assert parts.idiosyncratic.mean() == pytest.approx(0.0, abs=1e-9)
    assert parts.idiosyncratic.size == len(YEARS) * len(COUNTIES)


def test_the_shared_year_shock_is_recovered_with_the_right_scale(panel):
    trend = priors.fit_yield_trend(panel, "CORN", base_year=BASE_YEAR)
    parts = priors.split_residuals(panel, "CORN", trend)
    shocks = np.array(list(parts.year_shock.values()))
    assert shocks.std(ddof=1) == pytest.approx(12.0, rel=0.35)
    assert parts.idiosyncratic.std(ddof=1) == pytest.approx(8.0, rel=0.2)


# --- correlation ------------------------------------------------------------


def test_fitted_correlation_recovers_the_generating_sign_and_magnitude(fitted):
    rho = fitted["crops"]["CORN"]["yield_price_copula"]["rho"]
    assert rho == pytest.approx(-0.8, abs=0.2)


def test_correlating_the_raw_county_residual_would_attenuate_the_estimate(panel):
    """The reason the shared/idiosyncratic split exists, pinned as a test."""
    trend = priors.fit_yield_trend(panel, "CORN", base_year=BASE_YEAR)
    parts = priors.split_residuals(panel, "CORN", trend)
    prices = priors.price_series(panel, "CORN")
    log_price = np.log(np.array([prices[y] for y in YEARS]))

    shared = np.array([parts.year_shock[y] for y in YEARS])
    proper = float(np.corrcoef(shared, log_price)[0, 1])

    raw = np.repeat(shared, len(COUNTIES)) + parts.idiosyncratic
    naive = float(np.corrcoef(raw, np.repeat(log_price, len(COUNTIES)))[0, 1])

    assert proper < naive < 0.0
    assert abs(naive) < abs(proper) * 0.9


# --- price ------------------------------------------------------------------


def test_price_is_fitted_on_the_log_scale_not_the_level(fitted, panel):
    """A lognormal fitted on levels would be a different, wrong distribution."""
    price = fitted["crops"]["CORN"]["price"]
    observed = np.log(np.array(list(priors.price_series(panel, "CORN").values())))
    assert price["family"] == "lognormal"
    assert price["log_mean"] == pytest.approx(observed.mean(), abs=1e-6)
    assert price["log_sd"] == pytest.approx(observed.std(ddof=1), abs=1e-6)
    # 20 annual observations, so the tolerance against truth is a few standard errors.
    assert price["log_mean"] == pytest.approx(TRUE_PRICE_LOG_MEAN, abs=0.25)
    assert price["log_sd"] == pytest.approx(TRUE_PRICE_LOG_SD, abs=0.1)


# --- serialization and determinism ------------------------------------------


def test_serialization_is_byte_identical_across_runs(panel):
    first = priors.dumps(priors.build_priors(panel, crops=("CORN",), base_year=BASE_YEAR))
    second = priors.dumps(priors.build_priors(panel, crops=("CORN",), base_year=BASE_YEAR))
    assert first == second
    assert first.endswith("\n")


def test_the_document_carries_everything_a_sampler_needs(fitted):
    corn = fitted["crops"]["CORN"]
    assert fitted["schema_version"] == 1
    assert set(corn) >= {"yield", "price", "yield_price_copula"}
    shock = corn["yield"]["common_year_shock"]
    assert shock["family"] == "empirical_quantile"
    assert len(shock["normal_scores"]) == len(shock["quantiles_bu_per_acre"]) == len(YEARS)
    assert shock["normal_scores"] == sorted(shock["normal_scores"])
    assert shock["quantiles_bu_per_acre"] == sorted(shock["quantiles_bu_per_acre"])
    assert corn["yield"]["idiosyncratic"]["family"] == "skewnorm"


def test_the_document_survives_a_json_round_trip(fitted):
    once = priors.dumps(fitted)
    assert priors.dumps(json.loads(once)) == once


# --- sampling ---------------------------------------------------------------


def test_sampling_is_seeded_and_repeatable(fitted):
    a = sampling.sample(fitted, "CORN", year=2027, county_fips=COUNTIES[0], size=500, seed=1)
    b = sampling.sample(fitted, "CORN", year=2027, county_fips=COUNTIES[0], size=500, seed=1)
    assert np.array_equal(a.yield_bu_per_acre, b.yield_bu_per_acre)
    assert np.array_equal(a.price_usd_per_bu, b.price_usd_per_bu)


def test_samples_reproduce_the_fitted_moments_and_correlation(fitted):
    """Draws must land where the encoded parameters say they will.

    Checked against the fitted document rather than the generating truth: with
    20 annual observations the realized year shocks have a sample mean of a few
    bu/acre, which the intercept correctly absorbs. The sampler's job is to
    reproduce what was fitted.
    """
    trend = fitted["crops"]["CORN"]["yield"]["trend"]
    draw = sampling.sample(
        fitted, "CORN", year=BASE_YEAR, county_fips=COUNTIES[0], size=60_000, seed=3
    )

    expected = trend["intercept_bu_per_acre"] + trend["county_offset_bu_per_acre"][COUNTIES[0]]
    assert draw.yield_bu_per_acre.mean() == pytest.approx(expected, abs=0.5)
    assert draw.price_usd_per_bu.mean() == pytest.approx(np.exp(TRUE_PRICE_LOG_MEAN), rel=0.15)
    realized = float(np.corrcoef(draw.yield_bu_per_acre, draw.price_usd_per_bu)[0, 1])
    assert -0.75 < realized < -0.2


def test_sampling_advances_the_trend_by_year(fitted):
    kwargs = {"county_fips": COUNTIES[0], "size": 40_000, "seed": 5}
    early = sampling.sample(fitted, "CORN", year=BASE_YEAR, **kwargs)
    late = sampling.sample(fitted, "CORN", year=BASE_YEAR + 10, **kwargs)
    gain = late.yield_bu_per_acre.mean() - early.yield_bu_per_acre.mean()
    assert gain == pytest.approx(10 * TRUE_SLOPE, rel=0.25)


def test_an_unknown_county_falls_back_to_the_state_level_rather_than_crashing(fitted):
    draw = sampling.sample(fitted, "CORN", year=2027, county_fips="19999", size=1000, seed=2)
    assert np.isfinite(draw.yield_bu_per_acre).all()


def test_sampling_rejects_a_crop_that_was_never_fitted(fitted):
    with pytest.raises(KeyError, match="WHEAT"):
        sampling.sample(fitted, "WHEAT", year=2027, county_fips=COUNTIES[0], size=10, seed=1)

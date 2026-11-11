"""Fit the yield and price distributions the Monte Carlo layer samples from.

The model, stated once:

    yield[county, year] = intercept + slope * (year - base_year)
                        + county_offset[county]        level, time-invariant
                        + year_shock[year]             shared across Iowa
                        + wobble                       independent, per county-year

    price[year]         = exp(log_mean + log_sd * z)

`year_shock` and `z` are drawn together from a Gaussian copula with a fitted
negative correlation; `wobble` is independent of both.

**Why the residual is split in two.** Only the shared component moves price. A
single county having a bad year does not shift the state price received; the
whole state having a bad year does. Correlating the raw county-year residual
against price mixes in roughly an equal amount of pure noise and attenuates the
estimate toward zero — measured at -0.48 instead of -0.71 for corn on the real
panel. Revenue variance depends on that correlation directly, so the
attenuation is not cosmetic.

**Why the marginals are what they are.** The shared year shock gets an
empirical marginal: 20 annual observations do not support a three-parameter
shape, and the one observation that matters most for downside risk (2012, -41
bu/ac) is exactly the one a fitted normal would erase. The county wobble gets a
skew-normal: ~1,900 observations do support a shape, and by AIC skew-normal
beats both normal and Student-t, with left skew — bad years cost more than good
years pay, which is what an agronomist would predict.

Price is a stationary lognormal. A trend was tested and is not significant
(corn p=0.54, soybeans p=0.34 over 2006-2025), and extrapolating a commodity
price trend across a ten-year investment horizon would be indefensible even if
it were.

**Sample-ready, not fit-ready.** Every marginal is encoded so it can be sampled
with numpy alone — hence normal scores rather than probabilities on the
empirical marginal, since interpolating in z-space needs no normal CDF.
`ml/sample.py` is the reference consumer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

SCHEMA_VERSION = 1
DEFAULT_BASE_YEAR = 2006
DEFAULT_CROPS = ("CORN", "SOYBEANS")
#: Every stored float is rounded here so a re-run is byte-identical regardless
#: of BLAS summation order. Well past the precision any of these numbers carry.
ROUND_DP = 8

SHOCK_NOTE = (
    "Iowa-wide deviation from trend. Stored against normal scores rather than "
    "probabilities so sampling needs no normal CDF. numpy.interp clamps, so draws "
    "cannot fall outside the observed extremes."
)
WOBBLE_NOTE = "County-year wobble around the state shock, independent of price."
PRICE_NOTE = (
    "State price received; NASS publishes no county price. Stationary — a year trend "
    "is not significant over 2006-2025."
)
COPULA_NOTE = (
    "Correlation between the normal score of the shared year shock and log price. "
    "Negative by construction of the market: a big Iowa harvest is part of a big "
    "national harvest, which depresses the price received."
)
DOC_COMMENT = (
    "Fitted yield and price priors for the Monte Carlo layer. Sample from these "
    "parameters using sampling_recipe; never refit at runtime. Reference consumer: "
    "ml/sample.py. Method, and why the yield residual is split into a shared year "
    "shock and county wobble: ml/priors.py. Regenerate with scripts/fit_priors.py."
)
SAMPLING_RECIPE = (
    "z = rng.multivariate_normal([0, 0], [[1, rho], [rho, 1]], size=n)",
    "shock = numpy.interp(z[:, 0], normal_scores, quantiles_bu_per_acre)",
    "d = a / sqrt(1 + a*a); u0, u1 = rng.standard_normal((2, n))",
    "wobble = loc + scale * (d * abs(u0) + sqrt(1 - d*d) * u1)",
    "yield = intercept + slope * (year - base_year) + county_offset + shock + wobble",
    "price = exp(log_mean + log_sd * z[:, 1])",
    "Years are independent: draw a fresh z per simulated year, never reuse one across "
    "a multi-year path.",
)


@dataclass(frozen=True)
class YieldTrend:
    """Pooled linear trend with county-level intercepts.

    Attributes:
        intercept_bu_per_acre: Fitted state-average yield at `base_year`.
        slope_bu_per_acre_per_year: Shared genetic/agronomic gain per year.
        base_year: Year the intercept is stated at.
        county_offset_bu_per_acre: Per-county level, summing to zero.
    """

    intercept_bu_per_acre: float
    slope_bu_per_acre_per_year: float
    base_year: int
    county_offset_bu_per_acre: dict[str, float]


@dataclass(frozen=True)
class ResidualParts:
    """Yield residual split into its shared and idiosyncratic components.

    Attributes:
        year_shock: Iowa-wide deviation for each year, in bu/acre.
        idiosyncratic: County-year wobble with the year shock removed.
    """

    year_shock: dict[int, float]
    idiosyncratic: np.ndarray


def _yield_frame(panel: pl.DataFrame, crop: str) -> pl.DataFrame:
    """Select one crop's county yield rows.

    Args:
        panel: NASS panel.
        crop: `commodity` value, e.g. `CORN`.

    Returns:
        Columns `county_fips`, `year`, `value`, sorted for stable ordering.

    Raises:
        ValueError: If the crop has no yield rows.
    """
    frame = panel.filter(
        (pl.col("statistic") == "YIELD") & (pl.col("commodity") == crop)
    ).select("county_fips", "year", "value")
    if frame.is_empty():
        raise ValueError(f"panel has no YIELD rows for {crop!r}")
    return frame.sort("county_fips", "year")


def price_series(panel: pl.DataFrame, crop: str) -> dict[int, float]:
    """Extract the state price-received series for one crop.

    NASS publishes `PRICE RECEIVED` at state level only — there is no county
    price to be had, and the model must not imply one.

    Args:
        panel: NASS panel.
        crop: `commodity` value.

    Returns:
        Year to $/bu, ascending by year.

    Raises:
        ValueError: If the crop has no price rows.
    """
    frame = (
        panel.filter((pl.col("statistic") == "PRICE RECEIVED") & (pl.col("commodity") == crop))
        .select("year", "value")
        .sort("year")
    )
    if frame.is_empty():
        raise ValueError(f"panel has no PRICE RECEIVED rows for {crop!r}")
    return dict(zip(frame["year"].to_list(), frame["value"].to_list(), strict=True))


def fit_yield_trend(
    panel: pl.DataFrame, crop: str, *, base_year: int = DEFAULT_BASE_YEAR
) -> YieldTrend:
    """Fit one shared slope with a free intercept per county.

    Estimated by within-county demeaning, which is algebraically identical to
    least squares with county dummies but does not build a 99-column design
    matrix. One slope per county would be fitting 20 points each; one slope for
    all of them is the model twenty years of data supports.

    Args:
        panel: NASS panel.
        crop: `commodity` value.
        base_year: Year the returned intercept is stated at.

    Returns:
        The fitted trend, with county offsets centred on zero.
    """
    frame = _yield_frame(panel, crop)
    means = frame.group_by("county_fips").agg(
        pl.col("value").mean().alias("value_mean"), pl.col("year").mean().alias("year_mean")
    )
    centred = frame.join(means, on="county_fips").with_columns(
        (pl.col("value") - pl.col("value_mean")).alias("dv"),
        (pl.col("year") - pl.col("year_mean")).alias("dy"),
    )
    dv = centred["dv"].to_numpy()
    dy = centred["dy"].to_numpy()
    slope = float(dv @ dy / (dy @ dy))

    means = means.sort("county_fips")
    alpha = means["value_mean"].to_numpy() - slope * means["year_mean"].to_numpy()
    grand = float(alpha.mean())
    return YieldTrend(
        intercept_bu_per_acre=grand + slope * base_year,
        slope_bu_per_acre_per_year=slope,
        base_year=base_year,
        county_offset_bu_per_acre=dict(
            zip(means["county_fips"].to_list(), (alpha - grand).tolist(), strict=True)
        ),
    )


def split_residuals(panel: pl.DataFrame, crop: str, trend: YieldTrend) -> ResidualParts:
    """Split the trend residual into a shared year shock and county wobble.

    Args:
        panel: NASS panel.
        crop: `commodity` value.
        trend: Trend fitted on the same panel and crop.

    Returns:
        The two components. They sum back to the trend residual.
    """
    frame = _yield_frame(panel, crop)
    offsets = trend.county_offset_bu_per_acre
    fitted = (
        trend.intercept_bu_per_acre
        + trend.slope_bu_per_acre_per_year * (frame["year"].to_numpy() - trend.base_year)
        + np.array([offsets.get(fips, 0.0) for fips in frame["county_fips"].to_list()])
    )
    with_resid = frame.with_columns(pl.Series("resid", frame["value"].to_numpy() - fitted))
    shocks = with_resid.group_by("year").agg(pl.col("resid").mean().alias("shock")).sort("year")
    shock_by_year = dict(zip(shocks["year"].to_list(), shocks["shock"].to_list(), strict=True))
    idiosyncratic = with_resid["resid"].to_numpy() - np.array(
        [shock_by_year[year] for year in with_resid["year"].to_list()]
    )
    return ResidualParts(year_shock=shock_by_year, idiosyncratic=idiosyncratic)


def _normal_scores(count: int) -> np.ndarray:
    """Blom-style plotting positions mapped to the standard normal scale."""
    return stats.norm.ppf((np.arange(count) + 0.5) / count)


def _yield_block(trend: YieldTrend, parts: ResidualParts, shocks: np.ndarray) -> dict:
    """Assemble the yield half of a crop's block.

    Args:
        trend: Fitted trend.
        parts: Residual decomposition from the same fit.
        shocks: Year shocks in year order.

    Returns:
        The `yield` mapping: trend, shared shock marginal, wobble marginal.
    """
    shape, loc, scale = stats.skewnorm.fit(parts.idiosyncratic)
    return {
        "units": "BU / ACRE",
        "trend": {
            "base_year": trend.base_year,
            "intercept_bu_per_acre": trend.intercept_bu_per_acre,
            "slope_bu_per_acre_per_year": trend.slope_bu_per_acre_per_year,
            "county_offset_bu_per_acre": trend.county_offset_bu_per_acre,
        },
        "common_year_shock": {
            "family": "empirical_quantile",
            "note": SHOCK_NOTE,
            "normal_scores": _normal_scores(len(shocks)).tolist(),
            "quantiles_bu_per_acre": np.sort(shocks).tolist(),
            "sd_bu_per_acre": float(shocks.std(ddof=1)),
            "observations": len(shocks),
        },
        "idiosyncratic": {
            "family": "skewnorm",
            "note": WOBBLE_NOTE,
            "a": float(shape),
            "loc": float(loc),
            "scale": float(scale),
            "sd_bu_per_acre": float(parts.idiosyncratic.std(ddof=1)),
            "observations": int(parts.idiosyncratic.size),
        },
    }


def _price_block(log_price: np.ndarray) -> dict:
    """Assemble the price half of a crop's block.

    Args:
        log_price: Log state price received, in year order.

    Returns:
        The `price` mapping.
    """
    return {
        "family": "lognormal",
        "units": "$ / BU",
        "note": PRICE_NOTE,
        "log_mean": float(log_price.mean()),
        "log_sd": float(log_price.std(ddof=1)),
        "observed_min_usd_per_bu": float(np.exp(log_price.min())),
        "observed_max_usd_per_bu": float(np.exp(log_price.max())),
        "observations": len(log_price),
    }


def _fit_crop(panel: pl.DataFrame, crop: str, base_year: int) -> dict:
    """Fit every distribution for one crop.

    Args:
        panel: NASS panel.
        crop: `commodity` value.
        base_year: Year the yield intercept is stated at.

    Returns:
        The crop's block of the priors document.
    """
    trend = fit_yield_trend(panel, crop, base_year=base_year)
    parts = split_residuals(panel, crop, trend)
    prices = price_series(panel, crop)

    years = sorted(parts.year_shock)
    shocks = np.array([parts.year_shock[year] for year in years])
    log_price = np.log(np.array([prices[year] for year in years]))

    # The copula correlation is between the *normal scores* of the shared shock
    # and log price, which is exactly the parameter the sampler consumes.
    scores_by_rank = np.empty_like(shocks)
    scores_by_rank[np.argsort(shocks)] = _normal_scores(len(shocks))

    return {
        "yield": _yield_block(trend, parts, shocks),
        "price": _price_block(log_price),
        "yield_price_copula": {
            "family": "gaussian",
            "note": COPULA_NOTE,
            "rho": float(np.corrcoef(scores_by_rank, log_price)[0, 1]),
            "observations": len(shocks),
        },
    }


def build_priors(
    panel: pl.DataFrame,
    *,
    crops: tuple[str, ...] = DEFAULT_CROPS,
    base_year: int = DEFAULT_BASE_YEAR,
    source_digest: str | None = None,
) -> dict:
    """Fit every crop and assemble the priors document.

    Args:
        panel: NASS panel with county yield and state price rows.
        crops: `commodity` values to fit.
        base_year: Year the yield intercepts are stated at.
        source_digest: SHA-256 of the input file, recorded for provenance.

    Returns:
        The complete document, ready for `dumps`.
    """
    years = panel["year"]
    return {
        "$comment": DOC_COMMENT,
        "schema_version": SCHEMA_VERSION,
        "source": {
            "dataset": "USDA NASS Quick Stats, Iowa county yield and state price received",
            "sha256": source_digest,
            "rows": panel.height,
            "year_min": int(years.min()),
            "year_max": int(years.max()),
        },
        "sampling_recipe": list(SAMPLING_RECIPE),
        "crops": {crop: _fit_crop(panel, crop, base_year) for crop in crops},
    }


def _round(value: object) -> object:
    """Round every float in a nested structure so serialization is stable."""
    if isinstance(value, float):
        return round(value, ROUND_DP)
    if isinstance(value, dict):
        return {key: _round(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round(item) for item in value]
    return value


def dumps(document: dict) -> str:
    """Serialize a priors document deterministically.

    Args:
        document: The output of `build_priors`.

    Returns:
        JSON text. Byte-identical for equal inputs — the golden-file test
        downstream is impossible otherwise.
    """
    return json.dumps(_round(document), indent=2, sort_keys=True) + "\n"


def digest(path: Path) -> str:
    """Return the SHA-256 of a file, for recording input provenance."""
    return hashlib.sha256(path.read_bytes()).hexdigest()

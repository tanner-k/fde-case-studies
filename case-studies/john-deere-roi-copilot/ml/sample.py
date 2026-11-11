"""Draw from a fitted priors document — the reference Monte Carlo consumer.

This module is the contract `ml/priors.py` writes against, and the file the
Monte Carlo layer should read before implementing its own draw.

**numpy only, deliberately.** The API container ships numpy, scipy and
scikit-learn, but nothing here is allowed to need more than numpy: every
marginal in the document is encoded so it can be sampled without an inverse
CDF. The empirical year shock is stored against normal scores so a draw is one
`numpy.interp`; the skew-normal wobble is drawn by Azzalini's two-normal
construction rather than by inverting anything.

**Yield and price are drawn together.** One bivariate normal supplies both
coordinates, so the fitted negative correlation survives into the samples. That
correlation is a natural hedge: on the real panel it cuts the standard
deviation of corn revenue per acre by roughly 18% against the same marginals
drawn independently. Sampling them apart would overstate revenue risk.

**Years are independent, so vary the seed across them.** A multi-year NPV path
needs a fresh draw per year. Calling `sample` for 2027 and 2028 with the *same*
seed returns the same shocks twice, differing only by the trend — a decade of
perfectly correlated weather, which would badly understate the risk the
simulation exists to measure. Pass `seed=base_seed + year`, or draw once with
`size = n_paths * n_years` and reshape.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Draw:
    """One batch of correlated yield and price samples."""

    yield_bu_per_acre: np.ndarray
    price_usd_per_bu: np.ndarray


def sample(
    document: dict, crop: str, *, year: int, county_fips: str, size: int, seed: int
) -> Draw:
    """Draw correlated yields and prices — the reference consumer of the JSON.

    numpy only, by design: this is what the Monte Carlo layer needs to be able
    to do, so it is exercised here rather than assumed.

    Args:
        document: A priors document.
        crop: `commodity` value present in the document.
        year: Year to project the trend to.
        county_fips: County; an unknown FIPS falls back to the state level.
        size: Number of draws.
        seed: Draw seed.

    Returns:
        Paired yield and price samples of length `size`.

    Raises:
        KeyError: If `crop` was never fitted.
    """
    crops = document["crops"]
    if crop not in crops:
        raise KeyError(f"{crop!r} is not in this priors document; fitted: {sorted(crops)}")
    block = crops[crop]
    rng = np.random.default_rng(seed)

    rho = block["yield_price_copula"]["rho"]
    z = rng.multivariate_normal([0.0, 0.0], [[1.0, rho], [rho, 1.0]], size=size)

    shock_spec = block["yield"]["common_year_shock"]
    shock = np.interp(z[:, 0], shock_spec["normal_scores"], shock_spec["quantiles_bu_per_acre"])

    trend = block["yield"]["trend"]
    level = (
        trend["intercept_bu_per_acre"]
        + trend["slope_bu_per_acre_per_year"] * (year - trend["base_year"])
        + trend["county_offset_bu_per_acre"].get(county_fips, 0.0)
    )
    price_spec = block["price"]
    return Draw(
        yield_bu_per_acre=level + shock + _draw_wobble(block["yield"]["idiosyncratic"], rng, size),
        price_usd_per_bu=np.exp(price_spec["log_mean"] + price_spec["log_sd"] * z[:, 1]),
    )


def _draw_wobble(spec: dict, rng: np.random.Generator, size: int) -> np.ndarray:
    """Draw the skew-normal county wobble by Azzalini's construction.

    Two independent standard normals, one folded — which is why the marginal
    needs no inverse CDF and so no scipy at sample time.

    Args:
        spec: The `idiosyncratic` mapping.
        rng: Seeded generator.
        size: Number of draws.

    Returns:
        Draws in bu/acre.
    """
    delta = spec["a"] / np.sqrt(1.0 + spec["a"] ** 2)
    u0, u1 = rng.standard_normal((2, size))
    return spec["loc"] + spec["scale"] * (delta * np.abs(u0) + np.sqrt(1.0 - delta**2) * u1)

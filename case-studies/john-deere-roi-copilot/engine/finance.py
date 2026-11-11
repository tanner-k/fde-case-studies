"""Discounted cash-flow math: NPV, IRR, payback, and break-even acreage.

Pure numpy, no scipy. IRR and break-even are solved by bisection rather than by
a root-finder library: both functions are monotone over the bracket used here,
bisection cannot diverge, and it returns `None` honestly when no root is
bracketed instead of returning whatever the last Newton step happened to land
on. A decision tool that invents an IRR for a series that never turns positive
is worse than one that says "there isn't one".

**Break-even acreage is the headline output of this project.** UADA FSA2225
(`deliverables/appendix/sources.md` §4) reports See & Spray payback in acres,
not years, because acreage is what a grower actually controls. `break_even_acreage`
takes a callable so that costs which scale with acres — machine hours, labour —
are captured, not just the ones that do not.

Convention: `cashflows[0]` occurs at t=0 and is **not** discounted. Element `t`
is discounted by `(1 + r)**t`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Annotated

import numpy as np
from pydantic import Field

from engine.models import FrozenModel, NonNegative

#: Bisection bracket for `irr`. Below -100% a cash-flow series is meaningless;
#: above 1000% the answer is "absurdly good" and the precise figure is noise.
_IRR_BRACKET = (-0.9999, 10.0)

#: Upper bound for `break_even_acreage`. 10 million acres is ~28x Iowa's entire
#: corn crop; anything past it is "never" for a farm-level decision.
_MAX_ACRES = 1e7

_TOLERANCE = 1e-10
_MAX_ITERATIONS = 200


class InvestmentResult(FrozenModel):
    """The four numbers a purchase decision turns on.

    `irr` and `payback_years` are `None` rather than a sentinel when the cash
    flows do not define them — a machine that never repays has no payback
    period, and writing one down as 999 invites it being averaged.
    """

    npv_usd: float
    irr: float | None
    payback_years: float | None
    discount_rate: Annotated[float, Field(ge=0.0, lt=1.0)]
    horizon_years: int = Field(gt=0)
    capital_usd: NonNegative
    annual_net_benefit_usd: float


def npv(discount_rate: float, cashflows: Sequence[float]) -> float:
    """Net present value of a cash-flow series.

    Args:
        discount_rate: Per-period rate, e.g. 0.07 for 7%.
        cashflows: Element 0 occurs at t=0 and is not discounted.

    Returns:
        Present value in the currency of `cashflows`.

    Raises:
        ValueError: If `cashflows` is empty or `discount_rate` <= -1.
    """
    flows = np.asarray(cashflows, dtype=float)
    if flows.size == 0:
        raise ValueError("npv() needs at least one cash flow")
    if discount_rate <= -1.0:
        raise ValueError(f"discount_rate must be > -1, got {discount_rate}")
    periods = np.arange(flows.size, dtype=float)
    return float(np.sum(flows / (1.0 + discount_rate) ** periods))


def annuity_factor(discount_rate: float, years: int) -> float:
    """Present value of $1 received at the end of each of `years` years.

    Args:
        discount_rate: Per-period rate.
        years: Number of payments, starting at t=1.

    Returns:
        The annuity factor. Equals `years` when the rate is zero.

    Raises:
        ValueError: If `years` is not positive.
    """
    if years <= 0:
        raise ValueError(f"years must be positive, got {years}")
    if discount_rate == 0.0:
        return float(years)
    return float((1.0 - (1.0 + discount_rate) ** -years) / discount_rate)


def _bisect(func: Callable[[float], float], low: float, high: float) -> float | None:
    """Find a root of `func` in `[low, high]`, or `None` if none is bracketed.

    Args:
        func: Continuous, monotone over the bracket.
        low: Lower bound.
        high: Upper bound.

    Returns:
        The root, or `None` when `func(low)` and `func(high)` share a sign.
    """
    f_low, f_high = func(low), func(high)
    if f_low == 0.0:
        return low
    if f_high == 0.0:
        return high
    if np.sign(f_low) == np.sign(f_high):
        return None
    for _ in range(_MAX_ITERATIONS):
        mid = 0.5 * (low + high)
        f_mid = func(mid)
        if f_mid == 0.0 or (high - low) < _TOLERANCE * max(1.0, abs(mid)):
            return mid
        if np.sign(f_mid) == np.sign(f_low):
            low, f_low = mid, f_mid
        else:
            high = mid
    return 0.5 * (low + high)


def irr(cashflows: Sequence[float]) -> float | None:
    """Internal rate of return: the discount rate at which NPV is zero.

    Args:
        cashflows: Element 0 at t=0. Conventionally negative then positive.

    Returns:
        The rate, or `None` if no root lies in (-100%, 1000%]. A series that
        never turns positive has no IRR and must not be given one.
    """
    low, high = _IRR_BRACKET
    return _bisect(lambda rate: npv(rate, cashflows), low, high)


def payback_period_years(cashflows: Sequence[float]) -> float | None:
    """Years until cumulative (undiscounted) cash flow first reaches zero.

    Linear interpolation within the crossing year, which assumes cash arrives
    evenly across it. For an annual farm cash flow that is a convenient fiction,
    so the figure is reported to one decimal downstream, not two.

    Args:
        cashflows: Element 0 at t=0.

    Returns:
        Years, or `None` if the series never reaches zero within its horizon.

    Raises:
        ValueError: If `cashflows` is empty.
    """
    flows = np.asarray(cashflows, dtype=float)
    if flows.size == 0:
        raise ValueError("payback_period_years() needs at least one cash flow")
    cumulative = np.cumsum(flows)
    repaid = np.flatnonzero(cumulative >= 0.0)
    if repaid.size == 0:
        return None
    year = int(repaid[0])
    if year == 0:
        return 0.0
    shortfall, this_year = -cumulative[year - 1], flows[year]
    if this_year <= 0.0:  # cumulative crossed zero without positive cash: no interpolation
        return float(year)
    return float(year - 1 + shortfall / this_year)


def break_even_acreage(
    npv_of_acres: Callable[[float], float],
    *,
    max_acres: float = _MAX_ACRES,
) -> float | None:
    """Acreage at which NPV is zero.

    Takes a callable rather than a `$/acre` benefit so that acreage-dependent
    costs are honoured: a slower machine needs more hours to cover more acres,
    and those hours carry labour and repair cost that a per-acre constant hides.

    Args:
        npv_of_acres: NPV of the investment when the farm covers that many acres.
            Must be monotone non-decreasing in acres, which it is whenever the
            per-acre net benefit has a single sign.
        max_acres: Upper search bound. Beyond it the answer is "never".

    Returns:
        Acres, or `None` if no acreage in `[0, max_acres]` makes NPV zero —
        which is the answer for any investment with a non-positive per-acre
        benefit, including a zero-benefit one.
    """
    if npv_of_acres(0.0) >= 0.0:
        return 0.0
    return _bisect(npv_of_acres, 0.0, max_acres)


def evaluate_investment(
    *,
    capital_usd: float,
    annual_net_benefit_usd: float,
    discount_rate: float,
    horizon_years: int,
) -> InvestmentResult:
    """Score a flat-benefit investment: capital out at t=0, benefit each year.

    Args:
        capital_usd: Incremental purchase price, paid at t=0.
        annual_net_benefit_usd: Net of every recurring cost, positive or not.
        discount_rate: Per-period rate.
        horizon_years: Ownership horizon.

    Returns:
        An `InvestmentResult`. Salvage is not credited here — it belongs in the
        machinery depreciation charge, and crediting it twice is a classic way
        to make an equipment case look better than it is.
    """
    flows = [-capital_usd, *([annual_net_benefit_usd] * horizon_years)]
    return InvestmentResult(
        npv_usd=npv(discount_rate, flows),
        irr=irr(flows),
        payback_years=payback_period_years(flows),
        discount_rate=discount_rate,
        horizon_years=horizon_years,
        capital_usd=capital_usd,
        annual_net_benefit_usd=annual_net_benefit_usd,
    )

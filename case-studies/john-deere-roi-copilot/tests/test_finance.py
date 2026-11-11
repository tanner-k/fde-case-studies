"""Property tests for the money math.

These are the tests that matter most in the project. Every other module feeds a
cash-flow series into here, and an error in discounting is invisible — it
produces a wrong number that still looks like a plausible NPV.

So the assertions here are properties rather than golden values: NPV must fall
as the discount rate rises, payback must agree with the cumulative series it was
derived from, a break-even acreage must actually zero the NPV when substituted
back, and an investment with no benefit must never look profitable.
"""

import itertools

import numpy as np
import pytest
from engine.finance import (
    InvestmentResult,
    annuity_factor,
    break_even_acreage,
    evaluate_investment,
    irr,
    npv,
    payback_period_years,
)

# --- NPV ---------------------------------------------------------------------


def test_npv_at_zero_discount_is_the_plain_sum():
    flows = [-100.0, 30.0, 40.0, 50.0]
    assert npv(0.0, flows) == pytest.approx(20.0)


def test_npv_discounts_from_period_one_not_period_zero():
    """The first element is spent today and must not be discounted."""
    assert npv(0.10, [-100.0]) == pytest.approx(-100.0)
    assert npv(0.10, [0.0, 110.0]) == pytest.approx(100.0)


@pytest.mark.parametrize("flows", [
    [-500.0, 100.0, 150.0, 200.0, 250.0],
    [-1_000_000.0, 220_000.0, 220_000.0, 220_000.0, 220_000.0, 220_000.0],
])
def test_npv_is_strictly_decreasing_in_the_discount_rate(flows):
    rates = np.linspace(0.0, 0.5, 26)
    values = [npv(float(r), flows) for r in rates]
    assert all(b < a for a, b in itertools.pairwise(values))


def test_npv_rejects_an_empty_series():
    with pytest.raises(ValueError, match="at least one"):
        npv(0.07, [])


def test_annuity_factor_matches_a_summed_discount_series():
    rate, years = 0.07, 10
    expected = sum(1.0 / (1.0 + rate) ** t for t in range(1, years + 1))
    assert annuity_factor(rate, years) == pytest.approx(expected)


def test_annuity_factor_at_zero_rate_is_the_year_count():
    assert annuity_factor(0.0, 12) == pytest.approx(12.0)


# --- IRR ---------------------------------------------------------------------


def test_irr_zeroes_the_npv():
    flows = [-1000.0, 300.0, 400.0, 500.0, 300.0]
    rate = irr(flows)
    assert rate is not None
    assert npv(rate, flows) == pytest.approx(0.0, abs=1e-6)


def test_irr_of_a_single_doubling_is_one_hundred_percent():
    assert irr([-100.0, 200.0]) == pytest.approx(1.0, abs=1e-6)


def test_irr_is_none_when_the_series_never_turns_positive():
    """No sign change means no rate solves it — return None, do not guess."""
    assert irr([-1000.0, -50.0, -50.0]) is None


# --- Payback -----------------------------------------------------------------


def test_payback_is_consistent_with_the_cumulative_series():
    """Cumulative cash must be negative before payback and non-negative after."""
    flows = [-1000.0, 300.0, 400.0, 500.0, 600.0]
    years = payback_period_years(flows)
    assert years is not None
    cumulative = np.cumsum(flows)
    before, after = int(np.floor(years)), int(np.ceil(years))
    assert cumulative[before] < 0.0
    assert cumulative[after] >= 0.0


def test_payback_lands_exactly_on_a_year_boundary_when_it_should():
    assert payback_period_years([-900.0, 300.0, 300.0, 300.0]) == pytest.approx(3.0)


def test_payback_interpolates_within_the_year():
    """Half the third year's cash repays the remaining half of the outlay."""
    assert payback_period_years([-150.0, 100.0, 100.0]) == pytest.approx(1.5)


def test_payback_is_none_when_the_investment_never_repays():
    assert payback_period_years([-1000.0, 100.0, 100.0]) is None


# --- Break-even acreage ------------------------------------------------------


def _npv_of_acres(acres: float) -> float:
    """A 100k machine returning $4/acre/year for 10 years at 7%."""
    return npv(0.07, [-100_000.0, *([4.0 * acres] * 10)])


def test_break_even_acreage_actually_zeroes_the_npv():
    acres = break_even_acreage(_npv_of_acres)
    assert acres is not None
    assert _npv_of_acres(acres) == pytest.approx(0.0, abs=1e-3)


def test_break_even_acreage_matches_the_closed_form():
    acres = break_even_acreage(_npv_of_acres)
    assert acres == pytest.approx(100_000.0 / (4.0 * annuity_factor(0.07, 10)), rel=1e-6)


def test_break_even_acreage_is_none_when_no_acreage_ever_pays():
    """A zero-benefit investment has no break-even — it must not invent one."""
    assert break_even_acreage(lambda acres: -100_000.0 + 0.0 * acres) is None


def test_break_even_acreage_is_none_when_the_benefit_is_negative():
    assert break_even_acreage(lambda acres: -100_000.0 - 2.0 * acres) is None


def test_break_even_acreage_is_zero_when_the_investment_is_free():
    assert break_even_acreage(lambda acres: 1.0 * acres) == pytest.approx(0.0, abs=1e-6)


# --- The whole-investment wrapper -------------------------------------------


def test_a_zero_benefit_investment_never_shows_a_positive_npv():
    """The single most important guard rail: no benefit, no case."""
    result = evaluate_investment(
        capital_usd=250_000.0,
        annual_net_benefit_usd=0.0,
        discount_rate=0.07,
        horizon_years=10,
    )
    assert result.npv_usd < 0.0
    assert result.irr is None
    assert result.payback_years is None


def test_a_negative_benefit_investment_never_shows_a_positive_npv():
    result = evaluate_investment(
        capital_usd=100_000.0,
        annual_net_benefit_usd=-5_000.0,
        discount_rate=0.07,
        horizon_years=10,
    )
    assert result.npv_usd < -100_000.0


def test_evaluate_investment_returns_a_frozen_result():
    result = evaluate_investment(
        capital_usd=100_000.0,
        annual_net_benefit_usd=20_000.0,
        discount_rate=0.07,
        horizon_years=10,
    )
    assert isinstance(result, InvestmentResult)
    assert result.npv_usd == pytest.approx(20_000.0 * annuity_factor(0.07, 10) - 100_000.0)
    assert result.payback_years == pytest.approx(5.0)
    with pytest.raises(Exception):  # noqa: B017 — pydantic raises ValidationError
        result.npv_usd = 1.0

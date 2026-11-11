"""Tests for the ASABE machinery cost method.

The point of this module is field capacity. UADA publishes See & Spray Premium
at 12 mph against a base sprayer's 18 — two-thirds the acres per hour, which is
more machine hours, more labour, and a narrower spray window. That has to be a
computed cost, not a footnote, so the first block below pins it numerically.

The second thing pinned here is direction: ownership cost per acre must fall as
the machine is used more, because a fixed annual charge spread over more acres
is the whole reason a 2,400-acre farm and a custom applicator reach opposite
conclusions about the same sprayer.
"""

import pytest
from engine.machinery import (
    MachineryCost,
    MachineryRates,
    RemainingValue,
    annual_cost_usd,
    field_capacity,
    field_capacity_acres_per_hour,
    hours_for_acres,
    machinery_cost,
    remaining_value_fraction,
)
from engine.models import Machine, SprayerConfig

BASE = Machine(
    name="base sprayer",
    config=SprayerConfig.BASE,
    purchase_price_usd=650_000.0,
    working_speed_mph=18.0,
    boom_width_ft=120.0,
    field_efficiency=0.75,
    useful_life_years=10,
    annual_use_hours=400.0,
)
PREMIUM = BASE.model_copy(
    update={
        "name": "See & Spray Premium",
        "config": SprayerConfig.PREMIUM,
        "purchase_price_usd": 750_000.0,
        "working_speed_mph": 12.0,
        "subscription_usd_per_acre": 5.0,
    }
)
RATES = MachineryRates(
    interest_rate=0.07,
    engine_pto_hp=400.0,
    diesel_usd_per_gal=3.50,
    labour_usd_per_hour=20.40,
)


# --- Field capacity: the point of the module --------------------------------


def test_field_capacity_uses_the_asabe_constant():
    """18 mph x 120 ft x 0.75 / 8.25 = 196.36 acres/hour."""
    assert field_capacity_acres_per_hour(BASE) == pytest.approx(196.3636, rel=1e-5)


def test_premium_covers_exactly_two_thirds_the_acres_per_hour_of_the_base_machine():
    """JDRC-15. 12 mph against 18 is the cost the naive model misses."""
    ratio = field_capacity_acres_per_hour(PREMIUM) / field_capacity_acres_per_hour(BASE)
    assert ratio == pytest.approx(2.0 / 3.0)


def test_the_speed_penalty_shows_up_as_extra_hours():
    base_hours = hours_for_acres(BASE, 2_400.0)
    premium_hours = hours_for_acres(PREMIUM, 2_400.0)
    assert premium_hours == pytest.approx(base_hours * 1.5)
    assert premium_hours - base_hours == pytest.approx(6.11, abs=0.01)


def test_the_speed_penalty_costs_real_money_not_zero():
    """More hours means more labour, fuel and repairs — a computed cost."""
    same_price_but_slow = BASE.model_copy(update={"working_speed_mph": 12.0})
    fast = annual_cost_usd(BASE, RATES, acres_covered=2_400.0)
    slow = annual_cost_usd(same_price_but_slow, RATES, acres_covered=2_400.0)
    assert slow > fast


# --- Ownership --------------------------------------------------------------


def test_straight_line_depreciation_net_of_salvage():
    cost = machinery_cost(BASE, RATES)
    assert cost.depreciation_usd_per_year == pytest.approx(650_000.0 * 0.75 / 10)


def test_interest_is_charged_on_the_average_investment_not_the_full_price():
    """ASABE EP496 / ISU A3-29: (purchase + salvage) / 2."""
    cost = machinery_cost(BASE, RATES)
    average_investment = (650_000.0 + 162_500.0) / 2
    assert cost.interest_usd_per_year == pytest.approx(average_investment * 0.07)


def test_ownership_is_the_sum_of_its_three_parts():
    cost = machinery_cost(BASE, RATES)
    assert cost.ownership_usd_per_year == pytest.approx(
        cost.depreciation_usd_per_year
        + cost.interest_usd_per_year
        + cost.tax_insurance_housing_usd_per_year
    )


def test_repairs_follow_the_asabe_power_law_over_accumulated_hours():
    """D497: accumulated repairs = RF1 x price x (hours/1000) ** RF2."""
    cost = machinery_cost(BASE, RATES)
    lifetime_hours = 400.0 * 10
    accumulated = 0.007 * 650_000.0 * (lifetime_hours / 1000.0) ** 2.0
    assert cost.repairs_usd_per_hour == pytest.approx(accumulated / lifetime_hours)


def test_a_more_expensive_machine_costs_more_to_own():
    assert (
        machinery_cost(PREMIUM, RATES).ownership_usd_per_year
        > machinery_cost(BASE, RATES).ownership_usd_per_year
    )


# --- Per-acre behaviour ------------------------------------------------------


def test_cost_per_acre_falls_as_the_machine_is_used_more():
    """The fixed annual charge is spread wider. This is the ownership-vs-hire crux."""
    lightly_used = annual_cost_usd(BASE, RATES, acres_covered=2_400.0) / 2_400.0
    heavily_used = annual_cost_usd(BASE, RATES, acres_covered=60_000.0) / 60_000.0
    assert lightly_used > heavily_used


def test_annual_cost_is_ownership_plus_operating_hours():
    cost = machinery_cost(BASE, RATES)
    acres = 2_400.0
    expected = cost.ownership_usd_per_year + cost.operating_usd_per_hour * hours_for_acres(
        BASE, acres
    )
    assert annual_cost_usd(BASE, RATES, acres_covered=acres) == pytest.approx(expected)


def test_zero_acres_still_costs_the_full_ownership_charge():
    cost = machinery_cost(BASE, RATES)
    assert annual_cost_usd(BASE, RATES, acres_covered=0.0) == pytest.approx(
        cost.ownership_usd_per_year
    )


def test_negative_acreage_is_rejected():
    with pytest.raises(ValueError, match="acres_covered"):
        annual_cost_usd(BASE, RATES, acres_covered=-1.0)


# --- Cross-check against the published Iowa custom rate ----------------------


def test_at_custom_applicator_utilisation_the_cost_lands_near_the_iowa_custom_rate():
    """ISU A3-10 2025: self-propelled spraying $10.00/acre.

    That rate is quoted by operators who run the machine hard. At this
    machine's rated 400 hours a year — roughly 78,000 acres — the modelled
    owner cost must sit *below* $10, since the custom rate also carries the
    applicator's overhead, tender logistics, travel and margin.
    """
    cost = machinery_cost(BASE, RATES)
    assert 0.5 < cost.total_usd_per_acre < 10.0


def test_at_the_demo_farms_utilisation_ownership_costs_far_more_than_hiring():
    """2,400 acres a year cannot carry a $650,000 sprayer. This is a finding."""
    per_acre = annual_cost_usd(BASE, RATES, acres_covered=2_400.0) / 2_400.0
    assert per_acre > 10.0


def test_the_cost_breakdown_is_a_frozen_model():
    cost = machinery_cost(BASE, RATES)
    assert isinstance(cost, MachineryCost)
    with pytest.raises(Exception):  # noqa: B017 — pydantic raises ValidationError
        cost.total_usd_per_acre = 0.0


# --- ASABE primitives: field capacity and remaining value --------------------


def test_field_capacity_primitive_matches_the_machine_wrapper():
    """The Machine-shaped call must be a thin wrapper, not a second formula."""
    assert field_capacity(speed_mph=18.0, width_ft=120.0, field_efficiency=0.75) == pytest.approx(
        field_capacity_acres_per_hour(BASE)
    )


def test_a_ten_year_sprayer_retains_forty_percent_of_list_not_twenty_five():
    """JDRC-22. A3-29 SP sprayer: intercept 0.8826, age 0.0778, hours 0."""
    sprayer = RemainingValue(
        machine_type="SP sprayer",
        rv_intercept=0.8826,
        rv_age_coeff=0.0778,
        rv_hours_coeff=0.0,
    )
    fraction = remaining_value_fraction(sprayer, age_years=10.0, annual_hours=150.0)
    assert fraction == pytest.approx(0.4052, abs=0.0005)
    assert fraction > 0.25  # the flat assumption the engine shipped with


def test_a_sprayers_resale_ignores_hours_entirely():
    """rv_hours_coeff is zero for sprayers, planters and every implement."""
    sprayer = RemainingValue(
        machine_type="SP sprayer",
        rv_intercept=0.8826,
        rv_age_coeff=0.0778,
        rv_hours_coeff=0.0,
    )
    light = remaining_value_fraction(sprayer, age_years=10.0, annual_hours=100.0)
    hard = remaining_value_fraction(sprayer, age_years=10.0, annual_hours=1_000.0)
    assert light == pytest.approx(hard)


def test_a_combines_resale_does_fall_with_hours():
    """A3-29 Combine SP unit carries a non-zero hours coefficient."""
    combine = RemainingValue(
        machine_type="Combine SP unit",
        rv_intercept=1.1318,
        rv_age_coeff=0.1645,
        rv_hours_coeff=0.0079,
    )
    light = remaining_value_fraction(combine, age_years=10.0, annual_hours=200.0)
    hard = remaining_value_fraction(combine, age_years=10.0, annual_hours=800.0)
    assert light > hard


def test_remaining_value_never_goes_negative():
    """Squaring a negative base would make a scrapped machine look valuable."""
    combine = RemainingValue(
        machine_type="Combine SP unit",
        rv_intercept=1.1318,
        rv_age_coeff=0.1645,
        rv_hours_coeff=0.0079,
    )
    assert remaining_value_fraction(combine, age_years=90.0, annual_hours=5_000.0) == 0.0

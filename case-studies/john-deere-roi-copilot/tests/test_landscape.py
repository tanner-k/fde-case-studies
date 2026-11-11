"""Tests for the landscape quadrant math.

The number this module exists to produce is 24. A 2,400-acre Iowa farm making
two herbicide passes covers 4,800 sprayed acres, and a 120-foot self-propelled
sprayer at 18 mph clears 196 acres an hour — so a $650,000 machine runs
**24 hours a year**. That is the rescope's opening fact and it is pinned first.

Everything here is built by hand. The data file and its loader are tested
separately in `test_etl_reference.py`; this module must stay I/O-free so a
failure here means the math is wrong, not that a JSON row moved.
"""

import pytest
from engine.landscape import (
    LandscapePoint,
    Operation,
    Quadrant,
    annual_machine_hours,
    break_even_acres_vs_custom_rate,
    landscape_points,
    market_depth_agreement,
    quadrant,
)
from engine.machinery import MachineryRates

RATES = MachineryRates(
    interest_rate=0.07,
    engine_pto_hp=400.0,
    diesel_usd_per_gal=3.50,
    labour_usd_per_hour=20.40,
)

SPRAYER = Operation(
    key="self_propelled_sprayer",
    label="Self-propelled sprayer",
    custom_rate_section="Spraying",
    custom_rate_operation="Ground, broadcast, not incorporated, self-propelled / acre",
    a3_29_machine="SP sprayer",
    nass_series_key=None,
    width_ft=120.0,
    speed_mph=18.0,
    field_efficiency=0.75,
    passes_per_farm_acre_per_year=2.0,
    passes_source="test fixture",
    passes_confidence="author_estimate",
    window_days=10.0,
    window_source="test fixture",
    window_confidence="author_estimate",
    machine_source="test fixture",
    machine_confidence="sourced",
    list_price_usd=650_000.0,
    price_source="test fixture",
    useful_life_years=10,
    life_source="test fixture",
    life_confidence="author_estimate",
    custom_rate_usd_per_acre=9.35,
    custom_rate_responses=121,
    rated_annual_hours=150.0,
    salvage_fraction=0.4052,
    repair_factor_rc1=0.1,
    repair_factor_rc2=1.3,
)

COMBINE = SPRAYER.model_copy(
    update={
        "key": "corn_combine",
        "label": "Corn combine",
        "custom_rate_section": "Harvesting, Drying, and Hauling Grain",
        "custom_rate_operation": "Corn combining / acre",
        "a3_29_machine": "Combine SP unit",
        "width_ft": 30.0,
        "speed_mph": 3.5,
        "field_efficiency": 0.70,
        "passes_per_farm_acre_per_year": 0.5,
        "window_days": 30.0,
        "list_price_usd": None,
        "price_source": None,
        "custom_rate_usd_per_acre": 46.05,
        "custom_rate_responses": 119,
        "rated_annual_hours": 300.0,
    }
)


# --- Utilization: the finding -----------------------------------------------


def test_a_650k_sprayer_runs_twenty_four_hours_a_year_on_a_2400_acre_farm():
    """The rescope's opening fact. 4,800 sprayed acres / 196.4 acres per hour."""
    assert annual_machine_hours(SPRAYER, farm_acres=2_400.0) == pytest.approx(24.4, abs=0.1)


def test_field_capacity_uses_the_asabe_formula():
    assert SPRAYER.field_capacity_acres_per_hour == pytest.approx(196.3636, rel=1e-5)


def test_passes_multiply_the_acres_covered():
    """Two herbicide passes on 2,400 acres is 4,800 sprayed acres."""
    assert SPRAYER.acres_covered_per_year(2_400.0) == pytest.approx(4_800.0)
    assert COMBINE.acres_covered_per_year(2_400.0) == pytest.approx(1_200.0)


def test_hours_scale_linearly_with_farm_size():
    small = annual_machine_hours(SPRAYER, farm_acres=500.0)
    large = annual_machine_hours(SPRAYER, farm_acres=10_000.0)
    assert large == pytest.approx(small * 20.0)


def test_negative_acreage_is_rejected():
    with pytest.raises(ValueError, match="farm_acres"):
        annual_machine_hours(SPRAYER, farm_acres=-1.0)


# --- Quadrants ---------------------------------------------------------------


def test_the_thesis_quadrant_is_low_hours_and_a_narrow_window():
    assert quadrant(annual_hours=24.0, window_days=10.0) is Quadrant.LOW_USE_NARROW_WINDOW


def test_a_wide_window_moves_the_point_out_of_the_thesis_quadrant():
    assert quadrant(annual_hours=24.0, window_days=30.0) is Quadrant.LOW_USE_WIDE_WINDOW


def test_high_utilization_moves_the_point_out_of_the_thesis_quadrant():
    assert quadrant(annual_hours=400.0, window_days=10.0) is Quadrant.HIGH_USE_NARROW_WINDOW
    assert quadrant(annual_hours=400.0, window_days=30.0) is Quadrant.HIGH_USE_WIDE_WINDOW


def test_the_thresholds_are_inclusive_on_the_thesis_side():
    """Exactly at the cut counts as low use and a narrow window."""
    assert quadrant(annual_hours=200.0, window_days=14.0) is Quadrant.LOW_USE_NARROW_WINDOW
    assert quadrant(annual_hours=200.01, window_days=14.01) is Quadrant.HIGH_USE_WIDE_WINDOW


def test_thresholds_are_overridable_so_sensitivity_can_be_shown():
    assert (
        quadrant(annual_hours=24.0, window_days=10.0, narrow_window_days=5.0)
        is Quadrant.LOW_USE_WIDE_WINDOW
    )


# --- Break-even against the published custom rate ----------------------------


def test_break_even_needs_a_list_price():
    """Most operations have no sourced price, and the label is then absent."""
    assert break_even_acres_vs_custom_rate(COMBINE, RATES) is None


def test_the_sprayer_break_even_is_around_nine_thousand_acres():
    """ISU A3-10 2026 self-propelled spraying is $9.35/acre."""
    acres = break_even_acres_vs_custom_rate(SPRAYER, RATES)
    assert acres is not None
    assert 8_000.0 < acres < 10_500.0


def test_the_demo_farm_is_nowhere_near_break_even():
    """4,800 sprayed acres against a ~9,000-acre break-even. This is the finding."""
    acres = break_even_acres_vs_custom_rate(SPRAYER, RATES)
    assert acres is not None
    assert SPRAYER.acres_covered_per_year(2_400.0) < acres / 1.5


def test_no_break_even_exists_when_operating_cost_alone_beats_the_custom_rate():
    """A rate below the machine's per-acre operating cost is never recoverable."""
    underpriced = SPRAYER.model_copy(update={"custom_rate_usd_per_acre": 0.10})
    assert break_even_acres_vs_custom_rate(underpriced, RATES) is None


# --- Points ------------------------------------------------------------------


def test_landscape_points_carries_every_plot_channel():
    points = landscape_points((SPRAYER, COMBINE), farm_acres=2_400.0, rates=RATES)
    assert [p.operation_key for p in points] == ["self_propelled_sprayer", "corn_combine"]
    sprayer = points[0]
    assert isinstance(sprayer, LandscapePoint)
    assert sprayer.annual_machine_hours == pytest.approx(24.4, abs=0.1)  # x
    assert sprayer.window_days == 10.0  # y
    assert sprayer.custom_rate_responses == 121  # point size
    assert sprayer.break_even_acres is not None  # annotation
    assert sprayer.quadrant is Quadrant.LOW_USE_NARROW_WINDOW


def test_the_quadrants_move_with_farm_size():
    """Spec section 4: the plot only says anything if scale reorders it."""
    small = landscape_points((COMBINE,), farm_acres=2_400.0, rates=RATES)[0]
    large = landscape_points((COMBINE,), farm_acres=10_000.0, rates=RATES)[0]
    assert small.quadrant is Quadrant.LOW_USE_WIDE_WINDOW
    assert large.quadrant is Quadrant.HIGH_USE_WIDE_WINDOW


# --- Market-depth overlay ----------------------------------------------------


def test_market_depth_agreement_counts_deep_markets_in_the_thesis_quadrant():
    points = landscape_points((SPRAYER, COMBINE), farm_acres=2_400.0, rates=RATES)
    agreement = market_depth_agreement(points)
    assert agreement.deep_market_operations == ("self_propelled_sprayer", "corn_combine")
    assert agreement.agreeing == ("self_propelled_sprayer",)
    assert agreement.disagreeing == ("corn_combine",)
    assert agreement.agreement_rate == pytest.approx(0.5)


def test_shallow_markets_are_excluded_from_the_overlay():
    shallow = SPRAYER.model_copy(update={"key": "rare_job", "custom_rate_responses": 8})
    agreement = market_depth_agreement(
        landscape_points((shallow,), farm_acres=2_400.0, rates=RATES)
    )
    assert agreement.deep_market_operations == ()
    assert agreement.agreement_rate == 0.0


def test_mixing_farm_sizes_in_one_overlay_is_rejected():
    """Agreement is a statement about one panel, not about three at once."""
    mixed = (
        *landscape_points((SPRAYER,), farm_acres=500.0, rates=RATES),
        *landscape_points((COMBINE,), farm_acres=10_000.0, rates=RATES),
    )
    with pytest.raises(ValueError, match="farm_acres"):
        market_depth_agreement(mixed)

"""Tests for the See & Spray savings model.

Three effects, all first-order, all asserted here:

1. Savings apply to **addressable** spend — non-residual herbicide — not to the
   whole chemical bill.
2. **Premium is single-tank.** A grower running overlapping residuals in the
   post pass has near-zero addressable spend on Premium no matter how large
   their herbicide bill is. Ultimate's dual tank removes the constraint.
3. The subscription is charged on acres **not** sprayed, so it scales with the
   benefit and compresses the upside instead of acting as a fixed hurdle.

The block at the bottom reproduces UADA FSA2225 Table 1 arithmetically. Table 1
turns out to be exactly `(targeted herbicide - subscription) x unsprayed
fraction - opportunity cost`, with the unsprayed fraction equal to Deere's
published area-treated figures and a per-configuration opportunity cost of
$3.07 (Premium) and $5.84 (Ultimate). Pinning that identity means any later
change to this module that silently stops agreeing with the published table
fails a test instead of shipping.
"""

import pytest
from engine.models import Crop, Machine, SprayerConfig
from engine.precision import (
    UADA_TREATED_AREA,
    HerbicideProgram,
    PrecisionSavings,
    TreatedArea,
    addressable_usd_per_acre,
    break_even_targeted_herbicide_usd_per_acre,
    crop_savings,
)

CORN_TREATED = UADA_TREATED_AREA[Crop.CORN]
SOY_TREATED = UADA_TREATED_AREA[Crop.SOYBEANS]

#: Opportunity cost per acre implied by UADA FSA2225 Table 1. Recovered, not
#: published: the table is linear in herbicide cost and this is its intercept.
UADA_OPPORTUNITY_COST = {SprayerConfig.PREMIUM: 3.07, SprayerConfig.ULTIMATE: 5.84}

#: A grower who has restructured to a broadcast PRE and a clean foliar POST
#: (Werle 2024): every addressable dollar sits in a residual-free tank.
RESTRUCTURED = HerbicideProgram(
    crop=Crop.CORN, addressable_share=0.30, residual_free_tank_share=1.0
)
#: UNL #060 as written: two of three tanks carry a residual, so only the $9.27
#: burndown of $57.52 is Premium-addressable. 0.161 / 0.60 = 0.268.
OVERLAPPING_RESIDUALS = HerbicideProgram(
    crop=Crop.CORN, addressable_share=0.30, residual_free_tank_share=0.268
)


def _machine(config: SprayerConfig, subscription: float = 5.0) -> Machine:
    return Machine(
        name=config.value,
        config=config,
        purchase_price_usd=750_000.0,
        working_speed_mph=12.0,
        boom_width_ft=120.0,
        field_efficiency=0.75,
        useful_life_years=10,
        annual_use_hours=400.0,
        subscription_usd_per_acre=subscription,
    )


PREMIUM = _machine(SprayerConfig.PREMIUM)
ULTIMATE = _machine(SprayerConfig.ULTIMATE)
BASE = _machine(SprayerConfig.BASE, subscription=0.0)


# --- 1. Addressable spend only ----------------------------------------------


def test_savings_apply_to_addressable_spend_not_the_whole_herbicide_bill():
    """$41.85 of corn herbicide at a 30% addressable share is $12.55, not $41.85."""
    assert addressable_usd_per_acre(41.85, RESTRUCTURED, SprayerConfig.ULTIMATE) == pytest.approx(
        12.555
    )


def test_a_base_sprayer_addresses_nothing():
    assert addressable_usd_per_acre(41.85, RESTRUCTURED, SprayerConfig.BASE) == 0.0


def test_a_base_sprayer_earns_no_savings_and_pays_no_subscription():
    savings = crop_savings(
        crop=Crop.CORN,
        acres=1_200.0,
        herbicide_usd_per_acre=41.85,
        program=RESTRUCTURED,
        treated=CORN_TREATED,
        machine=BASE,
    )
    assert savings.gross_savings_usd_per_acre == 0.0
    assert savings.subscription_usd_per_acre == 0.0
    assert savings.net_savings_usd_per_acre == 0.0


# --- 2. The single-tank constraint ------------------------------------------


def test_premium_cannot_address_dollars_sitting_in_a_tank_with_a_residual():
    """The constraint that decides the case, per Werle 2024 and assumptions §4.1."""
    premium = addressable_usd_per_acre(57.52, OVERLAPPING_RESIDUALS, SprayerConfig.PREMIUM)
    ultimate = addressable_usd_per_acre(57.52, OVERLAPPING_RESIDUALS, SprayerConfig.ULTIMATE)
    assert premium < ultimate
    assert premium == pytest.approx(ultimate * 0.268)


def test_ultimates_dual_tank_ignores_the_tank_constraint_entirely():
    constrained = addressable_usd_per_acre(57.52, OVERLAPPING_RESIDUALS, SprayerConfig.ULTIMATE)
    restructured = HerbicideProgram(
        crop=Crop.CORN, addressable_share=0.30, residual_free_tank_share=1.0
    )
    assert constrained == addressable_usd_per_acre(
        57.52, restructured, SprayerConfig.ULTIMATE
    )


def test_overlapping_residuals_put_premium_below_the_uada_break_even():
    """A big herbicide bill does not rescue Premium if the residuals overlap.

    UNL #060: $57.52/acre of soybean herbicide, of which Premium can only reach
    the $9.27 burndown — under UADA's $11/acre break-even on its own.
    """
    addressable = addressable_usd_per_acre(
        57.52,
        HerbicideProgram(
            crop=Crop.SOYBEANS, addressable_share=0.60, residual_free_tank_share=0.268
        ),
        SprayerConfig.PREMIUM,
    )
    assert addressable == pytest.approx(9.25, abs=0.1)
    assert addressable < 11.0


def test_premium_and_ultimate_agree_when_no_tank_carries_a_residual():
    program = HerbicideProgram(
        crop=Crop.CORN, addressable_share=0.30, residual_free_tank_share=1.0
    )
    assert addressable_usd_per_acre(41.85, program, SprayerConfig.PREMIUM) == pytest.approx(
        addressable_usd_per_acre(41.85, program, SprayerConfig.ULTIMATE)
    )


# --- 3. Subscription is charged on acres NOT sprayed ------------------------


def test_subscription_is_charged_on_the_unsprayed_area():
    """$5/acre x 55.4% of the field going untouched = $2.77/acre."""
    savings = crop_savings(
        crop=Crop.CORN,
        acres=1_200.0,
        herbicide_usd_per_acre=41.85,
        program=RESTRUCTURED,
        treated=CORN_TREATED,
        machine=PREMIUM,
    )
    assert savings.subscription_usd_per_acre == pytest.approx(5.0 * 0.554)


def test_subscription_scales_with_the_benefit_rather_than_being_a_fixed_hurdle():
    """A machine that skips more acres saves more and is billed more."""
    skips_more = CORN_TREATED.model_copy(update={"mean_treated_fraction": 0.30})
    a = crop_savings(
        crop=Crop.CORN, acres=1_200.0, herbicide_usd_per_acre=41.85,
        program=RESTRUCTURED, treated=CORN_TREATED, machine=PREMIUM,
    )
    b = crop_savings(
        crop=Crop.CORN, acres=1_200.0, herbicide_usd_per_acre=41.85,
        program=RESTRUCTURED, treated=skips_more, machine=PREMIUM,
    )
    assert b.gross_savings_usd_per_acre > a.gross_savings_usd_per_acre
    assert b.subscription_usd_per_acre > a.subscription_usd_per_acre
    assert b.subscription_usd_per_acre / b.gross_savings_usd_per_acre == pytest.approx(
        a.subscription_usd_per_acre / a.gross_savings_usd_per_acre
    )


def test_net_savings_go_negative_when_addressable_spend_is_below_the_subscription():
    """Below $5/acre addressable, the technology loses money before any machine cost."""
    savings = crop_savings(
        crop=Crop.CORN,
        acres=1_200.0,
        herbicide_usd_per_acre=10.0,
        program=HerbicideProgram(
            crop=Crop.CORN, addressable_share=0.30, residual_free_tank_share=1.0
        ),
        treated=CORN_TREATED,
        machine=PREMIUM,
    )
    assert savings.addressable_usd_per_acre == pytest.approx(3.0)
    assert savings.net_savings_usd_per_acre < 0.0


def test_annual_savings_scale_with_acres():
    savings = crop_savings(
        crop=Crop.CORN, acres=1_200.0, herbicide_usd_per_acre=41.85,
        program=RESTRUCTURED, treated=CORN_TREATED, machine=PREMIUM,
    )
    assert savings.annual_net_savings_usd == pytest.approx(
        savings.net_savings_usd_per_acre * 1_200.0
    )
    assert isinstance(savings, PrecisionSavings)


# --- Boundary validation -----------------------------------------------------


def test_a_program_for_the_wrong_crop_is_rejected():
    with pytest.raises(ValueError, match="crop"):
        crop_savings(
            crop=Crop.SOYBEANS, acres=1_200.0, herbicide_usd_per_acre=41.85,
            program=RESTRUCTURED, treated=SOY_TREATED, machine=PREMIUM,
        )


def test_treated_area_bounds_must_bracket_the_mean():
    with pytest.raises(ValueError, match="low"):
        TreatedArea(
            crop=Crop.CORN,
            mean_treated_fraction=0.446,
            low_treated_fraction=0.90,
            high_treated_fraction=0.64,
        )


# --- Reproducing UADA FSA2225 Table 1 ---------------------------------------


@pytest.mark.parametrize(
    ("targeted", "published"),
    [(10.0, -0.30), (11.0, 0.25), (15.0, 2.49), (20.0, 5.24), (30.0, 10.74)],
)
def test_reproduces_uada_table_1_premium_corn(targeted, published):
    savings = crop_savings(
        crop=Crop.CORN, acres=1.0, herbicide_usd_per_acre=targeted,
        program=HerbicideProgram(
            crop=Crop.CORN, addressable_share=1.0, residual_free_tank_share=1.0
        ),
        treated=CORN_TREATED, machine=PREMIUM,
    )
    modelled = savings.net_savings_usd_per_acre - UADA_OPPORTUNITY_COST[SprayerConfig.PREMIUM]
    assert modelled == pytest.approx(published, abs=0.05)


@pytest.mark.parametrize(
    ("targeted", "published"),
    [(10.0, -0.40), (11.0, 0.16), (15.0, 2.32), (20.0, 4.96), (30.0, 10.52)],
)
def test_reproduces_uada_table_1_premium_soybean(targeted, published):
    savings = crop_savings(
        crop=Crop.SOYBEANS, acres=1.0, herbicide_usd_per_acre=targeted,
        program=HerbicideProgram(
            crop=Crop.SOYBEANS, addressable_share=1.0, residual_free_tank_share=1.0
        ),
        treated=SOY_TREATED, machine=PREMIUM,
    )
    modelled = savings.net_savings_usd_per_acre - UADA_OPPORTUNITY_COST[SprayerConfig.PREMIUM]
    assert modelled == pytest.approx(published, abs=0.15)


@pytest.mark.parametrize(
    ("targeted", "published"),
    [(10.0, -3.07), (15.0, -0.28), (20.0, 2.47), (30.0, 7.97)],
)
def test_reproduces_uada_table_1_ultimate_corn(targeted, published):
    savings = crop_savings(
        crop=Crop.CORN, acres=1.0, herbicide_usd_per_acre=targeted,
        program=HerbicideProgram(
            crop=Crop.CORN, addressable_share=1.0, residual_free_tank_share=1.0
        ),
        treated=CORN_TREATED, machine=ULTIMATE,
    )
    modelled = savings.net_savings_usd_per_acre - UADA_OPPORTUNITY_COST[SprayerConfig.ULTIMATE]
    assert modelled == pytest.approx(published, abs=0.05)


# --- Break-even on targeted herbicide ---------------------------------------


def test_break_even_matches_uadas_eleven_dollars_at_their_opportunity_cost():
    """UADA Premium corn: break-even is between the $10 and $11 table rows."""
    break_even = break_even_targeted_herbicide_usd_per_acre(
        machine_cost_usd_per_acre=UADA_OPPORTUNITY_COST[SprayerConfig.PREMIUM],
        subscription_usd_per_acre=5.0,
        unsprayed_fraction=CORN_TREATED.unsprayed_fraction,
    )
    assert 10.0 < break_even < 11.0


def test_break_even_matches_uadas_fifteen_to_sixteen_dollars_for_ultimate():
    break_even = break_even_targeted_herbicide_usd_per_acre(
        machine_cost_usd_per_acre=UADA_OPPORTUNITY_COST[SprayerConfig.ULTIMATE],
        subscription_usd_per_acre=5.0,
        unsprayed_fraction=CORN_TREATED.unsprayed_fraction,
    )
    assert 15.0 <= break_even <= 16.0


def test_break_even_rises_with_machine_cost():
    cheap = break_even_targeted_herbicide_usd_per_acre(
        machine_cost_usd_per_acre=3.0, subscription_usd_per_acre=5.0, unsprayed_fraction=0.554
    )
    dear = break_even_targeted_herbicide_usd_per_acre(
        machine_cost_usd_per_acre=6.0, subscription_usd_per_acre=5.0, unsprayed_fraction=0.554
    )
    assert dear > cheap

"""Tests for per-acre revenue and operating cost.

The interesting behaviour here is the **cost anchor**. Herbicide comes from ISU
A1-20 2026 by default — Iowa-specific, current, and itemised separately from the
rest of crop protection — while everything else comes from the ERS Heartland
budget. The two sources measure different things: ERS surveys what growers
actually spent, ISU prices a recommended program. That gap decides the project's
headline, so it has to be swappable and the swap has to be visible in the output.

The ERS reconciliation test at the bottom is the real check on the arithmetic:
running the ERS anchor with ERS's own price and yield must reproduce ERS's own
published net value for Heartland corn 2025.
"""

import pytest
from engine.economics import (
    CostAnchor,
    CropBudget,
    CropEconomics,
    crop_economics,
    farm_economics,
    herbicide_usd_per_acre,
)
from engine.models import Crop, CropAcreage, Farm, Tillage

# ERS Heartland 2025, $/planted acre, from data/raw/ers/commodity_budgets.parquet.
# ISU herbicide from data/reference/isu_a1_20_2026.json. Herbicide share from
# data/priors/crop_protection_split.json.
CORN = CropBudget(
    crop=Crop.CORN,
    yield_bu_per_acre=214.0,
    ers_chemicals_usd_per_acre=49.23,
    ers_herbicide_share=0.85,
    ers_operating_ex_chemicals_usd_per_acre=457.96 - 49.23,
    ers_overhead_usd_per_acre=489.33,
    isu_herbicide_usd_per_acre={
        Tillage.CONVENTIONAL: 56.00,
        Tillage.STRIP_TILL: 83.00,
        Tillage.LOW_TILL: 83.00,
    },
)
SOY = CropBudget(
    crop=Crop.SOYBEANS,
    yield_bu_per_acre=60.0,
    ers_chemicals_usd_per_acre=52.61,
    ers_herbicide_share=0.84,
    ers_operating_ex_chemicals_usd_per_acre=249.19 - 52.61,
    ers_overhead_usd_per_acre=448.32,
    isu_herbicide_usd_per_acre={
        Tillage.CONVENTIONAL: 75.00,
        Tillage.STRIP_TILL: 89.00,
        Tillage.LOW_TILL: 89.00,
    },
)
BUDGETS = {Crop.CORN: CORN, Crop.SOYBEANS: SOY}
PRICES = {Crop.CORN: 3.92, Crop.SOYBEANS: 9.80}

FARM = Farm(
    name="Story County demo",
    state="IA",
    county_fips="19169",
    tillage=Tillage.CONVENTIONAL,
    acreage=[
        CropAcreage(crop=Crop.CORN, acres=1200.0),
        CropAcreage(crop=Crop.SOYBEANS, acres=1200.0),
    ],
)


# --- The cost anchor ---------------------------------------------------------


def test_the_isu_anchor_selects_herbicide_by_tillage():
    """A1-20 2026: Iowa corn herbicide $56 conventional, $83 strip-till."""
    assert herbicide_usd_per_acre(CORN, Tillage.CONVENTIONAL, CostAnchor.ISU_A1_20) == 56.00
    assert herbicide_usd_per_acre(CORN, Tillage.STRIP_TILL, CostAnchor.ISU_A1_20) == 83.00


def test_the_ers_anchor_derives_herbicide_from_the_chemicals_line():
    """$49.23 of chemicals x an 0.85 herbicide share = $41.85."""
    assert herbicide_usd_per_acre(
        CORN, Tillage.CONVENTIONAL, CostAnchor.ERS_DERIVED
    ) == pytest.approx(41.8455)


def test_the_anchors_disagree_and_that_disagreement_is_the_headline():
    """ISU prescriptive corn herbicide alone exceeds the whole ERS chemicals line."""
    isu = herbicide_usd_per_acre(CORN, Tillage.CONVENTIONAL, CostAnchor.ISU_A1_20)
    ers = herbicide_usd_per_acre(CORN, Tillage.CONVENTIONAL, CostAnchor.ERS_DERIVED)
    assert isu > ers
    assert isu / ers == pytest.approx(1.34, abs=0.01)


def test_a_missing_isu_tillage_row_fails_loudly_rather_than_defaulting():
    sparse = CORN.model_copy(update={"isu_herbicide_usd_per_acre": {Tillage.CONVENTIONAL: 56.0}})
    with pytest.raises(ValueError, match="strip_till"):
        herbicide_usd_per_acre(sparse, Tillage.STRIP_TILL, CostAnchor.ISU_A1_20)


def test_switching_the_anchor_moves_only_the_herbicide_line():
    isu = crop_economics(
        budget=CORN, acres=1200.0, price_usd_per_bu=3.92,
        tillage=Tillage.CONVENTIONAL, anchor=CostAnchor.ISU_A1_20,
    )
    ers = crop_economics(
        budget=CORN, acres=1200.0, price_usd_per_bu=3.92,
        tillage=Tillage.CONVENTIONAL, anchor=CostAnchor.ERS_DERIVED,
    )
    assert isu.revenue_usd_per_acre == ers.revenue_usd_per_acre
    assert isu.other_operating_usd_per_acre == ers.other_operating_usd_per_acre
    assert isu.non_herbicide_chemicals_usd_per_acre == ers.non_herbicide_chemicals_usd_per_acre
    assert isu.herbicide_usd_per_acre != ers.herbicide_usd_per_acre
    delta = isu.herbicide_usd_per_acre - ers.herbicide_usd_per_acre
    assert isu.operating_cost_usd_per_acre - ers.operating_cost_usd_per_acre == pytest.approx(
        delta
    )


def test_the_result_records_which_anchor_produced_it():
    """Both sources must be citable from the returned structure."""
    result = crop_economics(
        budget=CORN, acres=1200.0, price_usd_per_bu=3.92,
        tillage=Tillage.CONVENTIONAL, anchor=CostAnchor.ISU_A1_20,
    )
    assert result.herbicide_anchor is CostAnchor.ISU_A1_20
    assert isinstance(result, CropEconomics)


# --- Revenue and cost arithmetic --------------------------------------------


def test_revenue_is_yield_times_price():
    result = crop_economics(
        budget=CORN, acres=1200.0, price_usd_per_bu=4.10,
        tillage=Tillage.CONVENTIONAL, anchor=CostAnchor.ISU_A1_20,
    )
    assert result.revenue_usd_per_acre == pytest.approx(214.0 * 4.10)


def test_non_herbicide_chemicals_are_the_remainder_of_the_ers_line():
    result = crop_economics(
        budget=CORN, acres=1200.0, price_usd_per_bu=3.92,
        tillage=Tillage.CONVENTIONAL, anchor=CostAnchor.ISU_A1_20,
    )
    assert result.non_herbicide_chemicals_usd_per_acre == pytest.approx(49.23 * 0.15)


def test_total_cost_is_operating_plus_overhead():
    result = crop_economics(
        budget=CORN, acres=1200.0, price_usd_per_bu=3.92,
        tillage=Tillage.CONVENTIONAL, anchor=CostAnchor.ISU_A1_20,
    )
    assert result.total_cost_usd_per_acre == pytest.approx(
        result.operating_cost_usd_per_acre + result.overhead_usd_per_acre
    )
    assert result.net_usd_per_acre == pytest.approx(
        result.revenue_usd_per_acre - result.total_cost_usd_per_acre
    )


def test_the_ers_anchor_reproduces_the_published_ers_net_value():
    """Heartland corn 2025: ERS publishes -$108.05/planted acre. Reproduce it."""
    result = crop_economics(
        budget=CORN, acres=1.0, price_usd_per_bu=3.92,
        tillage=Tillage.CONVENTIONAL, anchor=CostAnchor.ERS_DERIVED,
    )
    assert result.operating_cost_usd_per_acre == pytest.approx(457.96)
    assert result.total_cost_usd_per_acre == pytest.approx(947.29)
    assert result.net_usd_per_acre == pytest.approx(-108.05, abs=1.0)


# --- Farm roll-up ------------------------------------------------------------


def test_farm_economics_covers_every_crop_the_farm_grows():
    result = farm_economics(FARM, BUDGETS, PRICES, anchor=CostAnchor.ISU_A1_20)
    assert {c.crop for c in result.crops} == {Crop.CORN, Crop.SOYBEANS}
    assert result.total_acres == pytest.approx(2400.0)


def test_farm_totals_are_the_acre_weighted_sum_of_the_crops():
    result = farm_economics(FARM, BUDGETS, PRICES, anchor=CostAnchor.ISU_A1_20)
    assert result.revenue_usd == pytest.approx(
        sum(c.revenue_usd_per_acre * c.acres for c in result.crops)
    )
    assert result.operating_cost_usd == pytest.approx(
        sum(c.operating_cost_usd_per_acre * c.acres for c in result.crops)
    )


def test_the_farm_herbicide_figure_is_acre_weighted_not_a_plain_mean():
    lopsided = Farm(
        name="mostly corn", state="IA", county_fips="19169", tillage=Tillage.CONVENTIONAL,
        acreage=[
            CropAcreage(crop=Crop.CORN, acres=2000.0),
            CropAcreage(crop=Crop.SOYBEANS, acres=400.0),
        ],
    )
    result = farm_economics(lopsided, BUDGETS, PRICES, anchor=CostAnchor.ISU_A1_20)
    plain_mean = (56.00 + 75.00) / 2
    assert result.herbicide_usd_per_acre == pytest.approx((2000 * 56.0 + 400 * 75.0) / 2400)
    assert result.herbicide_usd_per_acre != pytest.approx(plain_mean)


def test_a_missing_budget_fails_loudly():
    with pytest.raises(ValueError, match="SOYBEANS"):
        farm_economics(FARM, {Crop.CORN: CORN}, PRICES, anchor=CostAnchor.ISU_A1_20)


def test_a_missing_price_fails_loudly():
    with pytest.raises(ValueError, match="SOYBEANS"):
        farm_economics(FARM, BUDGETS, {Crop.CORN: 3.92}, anchor=CostAnchor.ISU_A1_20)


def test_tillage_flows_through_from_the_farm():
    """A strip-till farm must pick up ISU's higher herbicide figures."""
    strip = FARM.model_copy(update={"tillage": Tillage.STRIP_TILL})
    conventional = farm_economics(FARM, BUDGETS, PRICES, anchor=CostAnchor.ISU_A1_20)
    reduced = farm_economics(strip, BUDGETS, PRICES, anchor=CostAnchor.ISU_A1_20)
    assert reduced.herbicide_usd_per_acre > conventional.herbicide_usd_per_acre

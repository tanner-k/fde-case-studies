"""Contract tests for the engine's shared types.

Every other engine module codes against these. The tests here pin three things:
units are named and cannot be silently swapped, invalid states are rejected at
construction rather than propagating into a plausible-looking number, and
applying a scenario override returns a new object instead of mutating.

That last one is the LLM boundary. Claude produces a `ScenarioOverride`; if
applying one could mutate the base scenario, a second question would answer
against a scenario the first question had quietly rewritten.
"""

import pytest
from engine.models import (
    Crop,
    CropAcreage,
    Farm,
    Machine,
    Scenario,
    ScenarioOverride,
    SprayerConfig,
    Tillage,
)
from pydantic import ValidationError


def _machine(**overrides: object) -> Machine:
    """A base sprayer at UADA's published values."""
    defaults = {
        "name": "base sprayer",
        "config": SprayerConfig.BASE,
        "purchase_price_usd": 650_000.0,
        "working_speed_mph": 18.0,
        "boom_width_ft": 120.0,
        "field_efficiency": 0.75,
        "useful_life_years": 10,
        "annual_use_hours": 400.0,
    }
    return Machine(**{**defaults, **overrides})


def _farm() -> Farm:
    return Farm(
        name="Story County demo",
        state="IA",
        county_fips="19169",
        tillage=Tillage.CONVENTIONAL,
        acreage=[
            CropAcreage(crop=Crop.CORN, acres=1200.0),
            CropAcreage(crop=Crop.SOYBEANS, acres=1200.0),
        ],
    )


# --- Validation at the boundary --------------------------------------------


def test_negative_acreage_is_rejected():
    with pytest.raises(ValidationError):
        CropAcreage(crop=Crop.CORN, acres=-1.0)


def test_zero_working_speed_is_rejected_because_it_divides_field_capacity():
    with pytest.raises(ValidationError):
        _machine(working_speed_mph=0.0)


def test_field_efficiency_above_one_is_rejected():
    with pytest.raises(ValidationError):
        _machine(field_efficiency=1.2)


def test_a_farm_cannot_list_the_same_crop_twice():
    """Duplicate crops would double-count acres in every downstream total."""
    with pytest.raises(ValidationError):
        Farm(
            name="dup",
            state="IA",
            county_fips="19169",
            tillage=Tillage.CONVENTIONAL,
            acreage=[
                CropAcreage(crop=Crop.CORN, acres=100.0),
                CropAcreage(crop=Crop.CORN, acres=200.0),
            ],
        )


def test_county_fips_must_be_five_digits():
    with pytest.raises(ValidationError):
        Farm(
            name="bad fips",
            state="IA",
            county_fips="19",
            tillage=Tillage.CONVENTIONAL,
            acreage=[CropAcreage(crop=Crop.CORN, acres=100.0)],
        )


# --- Immutability -----------------------------------------------------------


def test_models_are_frozen():
    farm = _farm()
    with pytest.raises(ValidationError):
        farm.name = "renamed"


def test_total_acres_sums_the_acreage_rows():
    assert _farm().total_acres == 2400.0


def test_acres_of_returns_zero_for_a_crop_the_farm_does_not_grow():
    assert _farm().acres_of(Crop.WHEAT) == 0.0


# --- Scenario override: the LLM boundary ------------------------------------


def _scenario() -> Scenario:
    return Scenario(
        farm=_farm(),
        current_machine=_machine(),
        proposed_machine=_machine(
            name="See & Spray Premium",
            config=SprayerConfig.PREMIUM,
            purchase_price_usd=750_000.0,
            working_speed_mph=12.0,
        ),
        crop_prices_usd_per_bu={Crop.CORN: 4.10, Crop.SOYBEANS: 10.20},
        discount_rate=0.07,
        horizon_years=7,
    )


def test_an_empty_override_leaves_the_scenario_unchanged():
    base = _scenario()
    assert base.with_override(ScenarioOverride()) == base


def test_override_replaces_only_the_named_field():
    base = _scenario()
    changed = base.with_override(ScenarioOverride(discount_rate=0.09))
    assert changed.discount_rate == 0.09
    assert changed.horizon_years == base.horizon_years
    assert changed.farm == base.farm


def test_override_does_not_mutate_the_base_scenario():
    """A second question must not answer against a scenario the first rewrote."""
    base = _scenario()
    base.with_override(ScenarioOverride(discount_rate=0.09, horizon_years=15))
    assert base.discount_rate == 0.07
    assert base.horizon_years == 7


def test_crop_price_override_merges_rather_than_replacing_the_whole_map():
    """"What if corn falls to $3.50" must not silently blank the soybean price."""
    base = _scenario()
    changed = base.with_override(
        ScenarioOverride(crop_prices_usd_per_bu={Crop.CORN: 3.50})
    )
    assert changed.crop_prices_usd_per_bu[Crop.CORN] == 3.50
    assert changed.crop_prices_usd_per_bu[Crop.SOYBEANS] == 10.20


def test_override_is_validated_like_any_other_input():
    """The LLM populates this type; it gets the same checks as a human would."""
    with pytest.raises(ValidationError):
        ScenarioOverride(discount_rate=-0.5)


def test_override_records_which_fields_were_set():
    """Narration needs to say what changed without diffing two whole scenarios."""
    override = ScenarioOverride(discount_rate=0.09)
    assert override.changed_fields() == ("discount_rate",)

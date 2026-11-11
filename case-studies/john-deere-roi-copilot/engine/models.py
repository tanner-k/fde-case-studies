"""Shared types for the decision engine.

Every other engine module codes against these. Three conventions hold throughout
and are enforced by tests:

**Units live in field names.** `working_speed_mph`, `purchase_price_usd`,
`crop_prices_usd_per_bu`. A units mix-up is the classic failure in agricultural
models — this project already hit one, where an unparameterised weather request
silently returned Celsius and millimetres. Naming the unit makes the mistake
visible at the call site instead of in the output.

**Everything is frozen.** Engine functions take models and return new models.
Nothing is edited in place.

**Invalid states are rejected at construction.** A zero working speed divides
field capacity; a duplicate crop double-counts acres. Both are cheap to catch
here and expensive to notice three layers down, where the result is merely a
plausible wrong number.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Converts mph by feet into acres per hour: 43,560 sq ft/acre / 5,280 ft/mile.
#: The ASABE field-capacity constant; see machinery.py.
FIELD_CAPACITY_CONSTANT = 8.25

UnitInterval = Annotated[float, Field(gt=0.0, le=1.0)]
NonNegative = Annotated[float, Field(ge=0.0)]
Positive = Annotated[float, Field(gt=0.0)]


class Crop(StrEnum):
    """Crops the engine can budget.

    Values match USDA `commodity_desc` so they join against extracted panels
    without a translation table.
    """

    CORN = "CORN"
    SOYBEANS = "SOYBEANS"
    WHEAT = "WHEAT"


class Tillage(StrEnum):
    """Tillage system.

    Not cosmetic: ISU A1-20 2026 prices Iowa corn herbicide at $56/acre under
    conventional tillage and $83 under strip- or low-till, because tillage
    substitutes for chemical weed control. Reduced-till operations also lean
    harder on residual chemistry, which is the part See & Spray cannot target.
    The two effects pull in opposite directions on precision-spray economics.
    """

    CONVENTIONAL = "conventional"
    STRIP_TILL = "strip_till"
    LOW_TILL = "low_till"


class SprayerConfig(StrEnum):
    """Sprayer capability tier.

    `PREMIUM` is single-tank: it cannot spot-spray a foliar herbicide while
    broadcasting a residual in the same pass. `ULTIMATE` is dual-tank and can.
    That distinction, not the price difference, is what decides addressable
    spend for a grower running overlapping residuals.
    """

    BASE = "base"
    PREMIUM = "premium"
    ULTIMATE = "ultimate"


class FrozenModel(BaseModel):
    """Base for every engine type: immutable, strict, no silent extra fields."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


class CropAcreage(FrozenModel):
    """Acres of one crop on one farm."""

    crop: Crop
    acres: NonNegative


class Farm(FrozenModel):
    """The operation a decision is being made for."""

    name: str = Field(min_length=1)
    state: str = Field(min_length=2, max_length=2)
    county_fips: str = Field(pattern=r"^\d{5}$")
    tillage: Tillage
    acreage: tuple[CropAcreage, ...]

    @model_validator(mode="after")
    def _reject_duplicate_crops(self) -> Self:
        """A crop listed twice would double-count acres in every total."""
        crops = [row.crop for row in self.acreage]
        if len(crops) != len(set(crops)):
            duplicated = sorted({c for c in crops if crops.count(c) > 1})
            raise ValueError(f"crop listed more than once: {duplicated}")
        return self

    @property
    def total_acres(self) -> float:
        """Sum of all crop acres."""
        return sum(row.acres for row in self.acreage)

    def acres_of(self, crop: Crop) -> float:
        """Acres of `crop`, or 0.0 if the farm does not grow it."""
        return next((row.acres for row in self.acreage if row.crop == crop), 0.0)


class Machine(FrozenModel):
    """A sprayer, described well enough to cost out ownership and operation.

    Reference values (UADA FSA2225, September 2025): base $650,000 at 18 mph,
    See & Spray Premium $750,000 at 12 mph, Ultimate $900,000 at 15 mph. The
    speed difference is a real cost — Premium covers two-thirds the acres per
    hour of the base machine.
    """

    name: str = Field(min_length=1)
    config: SprayerConfig
    purchase_price_usd: NonNegative
    working_speed_mph: Positive
    boom_width_ft: Positive
    field_efficiency: UnitInterval
    useful_life_years: int = Field(gt=0)
    annual_use_hours: Positive
    salvage_fraction: UnitInterval = 0.25
    #: Per-acre subscription charged on acres the machine declines to spray.
    #: UADA: $5/acre in crop, $1/acre fallow. Zero for a base machine.
    subscription_usd_per_acre: NonNegative = 0.0


class Scenario(FrozenModel):
    """A complete, self-contained question for the engine.

    Everything the deterministic layer needs. No I/O, no lookups, no globals —
    two identical scenarios produce identical results, which is what makes the
    golden-file test meaningful.
    """

    farm: Farm
    current_machine: Machine
    proposed_machine: Machine
    crop_prices_usd_per_bu: dict[Crop, NonNegative]
    discount_rate: Annotated[float, Field(ge=0.0, lt=1.0)]
    horizon_years: int = Field(gt=0, le=30)

    def with_override(self, override: ScenarioOverride) -> Scenario:
        """Return a new scenario with the override's set fields applied.

        Args:
            override: Sparse changes; unset fields are left alone.

        Returns:
            A new `Scenario`. The receiver is never modified.
        """
        changes = override.model_dump(exclude_unset=True, exclude_none=True)
        # Prices merge rather than replace: "what if corn falls to $3.50" must
        # not blank out the soybean price the farm also depends on.
        if "crop_prices_usd_per_bu" in changes:
            changes["crop_prices_usd_per_bu"] = {
                **self.crop_prices_usd_per_bu,
                **changes["crop_prices_usd_per_bu"],
            }
        return self.model_copy(update=changes)


class ScenarioOverride(FrozenModel):
    """A sparse change to a scenario — the LLM's only writable surface.

    Claude populates this from a natural-language question via tool use. It is
    validated exactly like human input, and it is the *only* thing the model
    contributes to a calculation: every number the user sees comes out of the
    deterministic engine, never out of the model.
    """

    crop_prices_usd_per_bu: dict[Crop, NonNegative] | None = None
    discount_rate: Annotated[float, Field(ge=0.0, lt=1.0)] | None = None
    horizon_years: Annotated[int, Field(gt=0, le=30)] | None = None
    proposed_machine: Machine | None = None

    def changed_fields(self) -> tuple[str, ...]:
        """Names of the fields this override actually sets.

        Lets narration say what changed without diffing two whole scenarios.
        """
        return tuple(self.model_dump(exclude_unset=True, exclude_none=True))

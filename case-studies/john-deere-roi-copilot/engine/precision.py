"""See & Spray savings: what the technology actually gets paid for.

Three effects, all first-order and all modelled here rather than noted.

**1. Addressable spend only.** Savings apply to non-residual herbicide, not to
the whole chemical bill. USDA ERS publishes one `Chemicals` line — herbicide
plus insecticide plus fungicide — and See & Spray addresses only herbicide
applied to *emerged* weeds. Residual chemistry is broadcast regardless, because
its job is to kill weeds that have not germinated and there is nothing on the
ground for a camera to see. `deliverables/appendix/assumptions.md` §5 derives
the decomposition; `data/priors/crop_protection_split.json` is the machine-
readable form. Treating the whole line as addressable overstates the savings
base by ~3.9x for corn and ~2.8x for soybeans.

**2. The single-tank constraint.** `SprayerConfig.PREMIUM` is one tank and one
boom: it cannot spot-spray a foliar herbicide while broadcasting a residual in
the same pass. Only passes whose tank carries *no* residual are addressable at
all. `ULTIMATE` is dual-tank and has no such limit. This is not a spec detail —
a grower running overlapping residuals in the post pass, standard Iowa waterhemp
practice, has near-zero addressable spend on Premium regardless of how large
their herbicide bill is. `HerbicideProgram.residual_free_tank_share` is the
knob, and UNL budget #060 is the worked case: $57.52/acre of herbicide,
~60% non-residual by chemistry, but only the $9.27 burndown reachable by
Premium. Source: Werle, R., University of Wisconsin-Madison, 2024
(`assumptions.md` §4.1).

**3. The subscription is charged on acres NOT sprayed** — $5/acre in crop,
$1/acre fallow (UADA FSA2225). It scales with the benefit rather than acting as
a fixed hurdle, so it compresses upside: every dollar of chemical saved comes
with a subscription charge in proportion.

Area actually treated, Deere commercial data via UADA (1.26M acres covered,
524k sprayed): corn 44.6% mean, 24-64% at the 50% range; soybean 46.1%, 25-66%.
Roughly 55% of the field goes unsprayed.

**What this module deliberately excludes.** The machine's own cost — the extra
capital and the hours lost to a slower working speed — is `machinery.py`'s job.
UADA's Table 1 bundles it into a per-configuration "opportunity cost" of $3.07
(Premium) and $5.84 (Ultimate) per acre; keeping it separate here is what lets
the model answer the acreage question, since that cost per acre depends on how
many acres the machine covers and UADA's constant does not.

No I/O: the priors arrive as `HerbicideProgram` and `TreatedArea` values.
"""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from engine.models import (
    Crop,
    FrozenModel,
    Machine,
    NonNegative,
    SprayerConfig,
    UnitInterval,
)


class TreatedArea(FrozenModel):
    """Share of covered area a See & Spray machine actually sprays.

    Deere commercial data reported in UADA FSA2225 (September 2025), from
    1.26 million acres covered and 524,000 sprayed. `low`/`high` bracket the
    published 50% range, not a confidence interval.
    """

    crop: Crop
    mean_treated_fraction: UnitInterval
    low_treated_fraction: UnitInterval
    high_treated_fraction: UnitInterval

    @model_validator(mode="after")
    def _bounds_must_bracket_the_mean(self) -> Self:
        """A mean outside its own range would silently invert the savings."""
        if not (
            self.low_treated_fraction
            <= self.mean_treated_fraction
            <= self.high_treated_fraction
        ):
            raise ValueError(
                f"treated-area bounds must bracket the mean: low="
                f"{self.low_treated_fraction}, mean={self.mean_treated_fraction}, "
                f"high={self.high_treated_fraction}"
            )
        return self

    @property
    def unsprayed_fraction(self) -> float:
        """Share of the field the machine declines to spray — the savings base."""
        return 1.0 - self.mean_treated_fraction


#: UADA FSA2225 Table, area actually treated. Published figures, not a prior.
UADA_TREATED_AREA: dict[Crop, TreatedArea] = {
    Crop.CORN: TreatedArea(
        crop=Crop.CORN,
        mean_treated_fraction=0.446,
        low_treated_fraction=0.24,
        high_treated_fraction=0.64,
    ),
    Crop.SOYBEANS: TreatedArea(
        crop=Crop.SOYBEANS,
        mean_treated_fraction=0.461,
        low_treated_fraction=0.25,
        high_treated_fraction=0.66,
    ),
}


class HerbicideProgram(FrozenModel):
    """How a grower's herbicide dollars sit across chemistry and across passes.

    The two shares answer different questions and both are needed:

    * `addressable_share` — what fraction of herbicide dollars is non-residual
      chemistry at all. Estimated at 0.30 for corn (0.18-0.45) and 0.42 for
      soybeans (0.25-0.60) in `assumptions.md` §4.4. The least certain number in
      the model, and dominated by program design rather than measurement error.
    * `residual_free_tank_share` — of those non-residual dollars, what fraction
      is carried in a pass whose tank contains no residual product. 1.0 for a
      grower who has restructured to a broadcast PRE plus a clean foliar POST;
      about 0.27 for UNL #060 as written. Only `PREMIUM` is subject to it.
    """

    crop: Crop
    addressable_share: UnitInterval
    residual_free_tank_share: UnitInterval


class PrecisionSavings(FrozenModel):
    """Savings for one crop on one farm, before any machinery cost.

    `net_savings_usd_per_acre` is gross chemical saving less subscription. It is
    deliberately *not* net of the machine — that is `machinery.py` and depends on
    acreage, which is the question being asked.
    """

    crop: Crop
    acres: NonNegative
    config: SprayerConfig
    herbicide_usd_per_acre: NonNegative
    addressable_usd_per_acre: NonNegative
    unsprayed_fraction: NonNegative
    gross_savings_usd_per_acre: NonNegative
    subscription_usd_per_acre: NonNegative
    net_savings_usd_per_acre: float

    @property
    def annual_net_savings_usd(self) -> float:
        """Net saving across the crop's acres, before machinery cost."""
        return self.net_savings_usd_per_acre * self.acres

    @property
    def annual_gross_savings_usd(self) -> float:
        """Chemical saving across the crop's acres, before the subscription."""
        return self.gross_savings_usd_per_acre * self.acres


def addressable_usd_per_acre(
    herbicide_usd_per_acre: float,
    program: HerbicideProgram,
    config: SprayerConfig,
) -> float:
    """Herbicide spend this machine can actually target.

    Args:
        herbicide_usd_per_acre: Total herbicide, not total chemicals.
        program: The grower's chemistry and pass structure.
        config: `BASE` addresses nothing. `PREMIUM` is limited to dollars in
            residual-free tanks. `ULTIMATE`'s dual tank removes that limit.

    Returns:
        Dollars per acre of targeted, spot-sprayable herbicide.
    """
    if config is SprayerConfig.BASE:
        return 0.0
    addressable = herbicide_usd_per_acre * program.addressable_share
    if config is SprayerConfig.PREMIUM:
        return addressable * program.residual_free_tank_share
    return addressable


def crop_savings(
    *,
    crop: Crop,
    acres: float,
    herbicide_usd_per_acre: float,
    program: HerbicideProgram,
    treated: TreatedArea,
    machine: Machine,
) -> PrecisionSavings:
    """Per-acre and annual See & Spray savings for one crop.

    Args:
        crop: The crop being sprayed.
        acres: Acres of it.
        herbicide_usd_per_acre: Herbicide only — see `economics.py` for the
            split out of the ERS `Chemicals` line or the ISU A1-20 anchor.
        program: Chemistry and pass structure for this crop.
        treated: Published area-actually-treated for this crop.
        machine: Supplies the configuration and the subscription rate.

    Returns:
        A `PrecisionSavings`, before machinery cost.

    Raises:
        ValueError: If `program` or `treated` describes a different crop, which
            would quietly apply soybean shares to corn acres.
    """
    if program.crop != crop or treated.crop != crop:
        raise ValueError(
            f"crop mismatch: asked for {crop}, program is {program.crop}, "
            f"treated area is {treated.crop}"
        )
    addressable = addressable_usd_per_acre(herbicide_usd_per_acre, program, machine.config)
    unsprayed = treated.unsprayed_fraction
    is_base = machine.config is SprayerConfig.BASE
    gross = addressable * unsprayed
    # Billed on the area the machine declined to spray, so it tracks the benefit.
    subscription = 0.0 if is_base else machine.subscription_usd_per_acre * unsprayed
    return PrecisionSavings(
        crop=crop,
        acres=acres,
        config=machine.config,
        herbicide_usd_per_acre=herbicide_usd_per_acre,
        addressable_usd_per_acre=addressable,
        unsprayed_fraction=unsprayed,
        gross_savings_usd_per_acre=gross,
        subscription_usd_per_acre=subscription,
        net_savings_usd_per_acre=gross - subscription,
    )


def break_even_targeted_herbicide_usd_per_acre(
    *,
    machine_cost_usd_per_acre: float,
    subscription_usd_per_acre: float,
    unsprayed_fraction: float,
) -> float:
    """Targeted herbicide spend at which See & Spray exactly pays for itself.

    Solves `(H - subscription) x unsprayed = machine_cost` for `H`. Expressed in
    *targeted* dollars so it is directly comparable to UADA FSA2225 Table 1,
    which breaks even at about $11/acre for Premium and $15-16 for Ultimate.

    Args:
        machine_cost_usd_per_acre: Incremental cost of the precision machine
            over the base machine, per acre covered. UADA's implied figures are
            $3.07 (Premium) and $5.84 (Ultimate); yours will differ with
            acreage, which is the point.
        subscription_usd_per_acre: Rate charged on unsprayed area, $5 in crop.
        unsprayed_fraction: Share of the field the machine skips.

    Returns:
        Dollars per acre of targeted herbicide.

    Raises:
        ValueError: If `unsprayed_fraction` is not positive — a machine that
            sprays everything can never break even, and dividing by zero would
            report that as infinity rather than as a contradiction.
    """
    if unsprayed_fraction <= 0.0:
        raise ValueError(
            f"unsprayed_fraction must be positive, got {unsprayed_fraction}; "
            "a machine that sprays the whole field saves nothing"
        )
    return subscription_usd_per_acre + machine_cost_usd_per_acre / unsprayed_fraction

"""The landscape exhibit's math: utilization, window, quadrant, break-even.

The rescope's argument (`docs/superpowers/specs/2026-08-13-capability-segment-targeting-design.md`)
turns on one observation: a 2,400-acre farm covering 4,800 sprayed acres runs a
$650,000 sprayer **24 hours a year**. Utilization, not technology, decides the
case. This module computes the four channels of the opening exhibit:

| Channel | Function |
|---|---|
| **x** — annual machine hours | `annual_machine_hours` |
| **y** — agronomic window, days | `Operation.window_days` (data) |
| **point size** — custom-market depth | `Operation.custom_rate_responses` (data) |
| **annotation** — break-even acreage | `break_even_acres_vs_custom_rate` |

**Utilization is on x, not break-even acreage,** because break-even already
embeds price and custom rate: putting the answer on the axis states a conclusion
instead of diagnosing one. It also means the plot is not blocked on list-price
sourcing — capacity needs only width, speed and efficiency.

**Market depth is an overlay, never an axis.** Using observed consolidation as a
model input would make the exhibit circular. As an overlay it is free
validation: a machine the model puts in the low-utilization / narrow-window
quadrant that *also* has 100+ custom providers is a machine Iowa growers already
resolved this way. `market_depth_agreement` is the Phase-1 gate — and the
thresholds below must not be tuned to make it pass.

No I/O: `etl.reference.load_operations` assembles `Operation` from the archived
ISU files at the boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Literal

from pydantic import Field

from engine.machinery import MachineryRates, field_capacity, machinery_cost
from engine.models import (
    FrozenModel,
    Machine,
    NonNegative,
    Positive,
    SprayerConfig,
    UnitInterval,
)

#: A round number, chosen before the plot was run, at which the fixed
#: ownership charge per acre is materially higher than the published per-acre
#: custom rate. Not derived from a sourced rated-annual-hours figure: 400 h/yr,
#: the number this cut was once described as "half of", appears nowhere in
#: this repository except four test fixtures (`tests/test_machinery.py`,
#: `test_precision.py`, `test_models.py`, `test_engine_demo.py`) and has no
#: source document behind it. The A3-29 join on this branch derives 150 h/yr
#: for the self-propelled sprayer itself (1,500 wearout hours / 10 years) — a
#: 2.7x disagreement — so this cut sits above the sprayer's own
#: wearout-derived annual use, not at half of some larger sourced figure. An
#: author-chosen cut, not a computed one — see
#: `deliverables/appendix/assumptions.md` section 11.
LOW_UTILIZATION_HOURS = 200.0

#: Two weeks. An operation that cannot slip a fortnight cannot be rescheduled
#: around a service provider's queue, so its acres cannot route to an operator
#: however good the ROI. Declared, not derived; see assumptions.md section 11.
NARROW_WINDOW_DAYS = 14.0

#: A3-10 response count above which Iowa growers demonstrably consolidate an
#: operation into custom operators' hands. 70 of 205 respondents is roughly a
#: third of the survey offering the service.
DEEP_MARKET_RESPONSES = 70

#: How much weight a hand-entered number carries. `author_estimate` values are
#: the ones phase 2 replaces with NASS Crop Progress; `measured` marks the ones
#: it already has.
Confidence = Literal["sourced", "typical_published", "author_estimate", "measured"]


class Quadrant(StrEnum):
    """Where an operation lands on the utilization / window plane.

    `LOW_USE_NARROW_WINDOW` is the thesis: machines a farm cannot justify owning
    but must have on the day it needs them.
    """

    LOW_USE_NARROW_WINDOW = "low_use_narrow_window"
    LOW_USE_WIDE_WINDOW = "low_use_wide_window"
    HIGH_USE_NARROW_WINDOW = "high_use_narrow_window"
    HIGH_USE_WIDE_WINDOW = "high_use_wide_window"


class Operation(FrozenModel):
    """One field operation, described well enough to place it on the landscape.

    The first block is hand-curated and lives in `data/reference/operations.json`
    with a source and a confidence tag on every number. The second block is
    joined in by `etl.reference.load_operations` from the already-parsed ISU
    files, and has no defaults on purpose: a row that fails to join should raise,
    not silently inherit a plausible constant.
    """

    key: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1)
    #: A3-10 section and row, together the join key into the custom rate survey.
    custom_rate_section: str = Field(min_length=1)
    custom_rate_operation: str = Field(min_length=1)
    #: A3-29 `description`, the join key into the machine-data table.
    a3_29_machine: str = Field(min_length=1)
    #: `etl.crop_progress` series whose observed spread measures this
    #: operation's window, or None where NASS publishes no progress series —
    #: spraying, tillage and fertilizer application have none, so those rows
    #: keep an author estimate.
    nass_series_key: str | None
    width_ft: Positive
    speed_mph: Positive
    field_efficiency: UnitInterval
    #: Passes over each *farm* acre per year, assuming a 50/50 corn-soybean
    #: rotation. Spraying is 2.0 (pre and post); corn combining is 0.5, because
    #: only half the farm is in corn.
    passes_per_farm_acre_per_year: Positive
    passes_source: str = Field(min_length=1)
    passes_confidence: Confidence
    window_days: Positive
    window_source: str = Field(min_length=1)
    window_confidence: Confidence
    machine_source: str = Field(min_length=1)
    machine_confidence: Confidence
    list_price_usd: Positive | None
    price_source: str | None
    useful_life_years: int = Field(gt=0)
    life_source: str = Field(min_length=1)
    life_confidence: Confidence
    # --- joined in by the loader ---
    custom_rate_usd_per_acre: NonNegative
    custom_rate_responses: int = Field(ge=1)
    #: A3-29 wearout hours spread over `useful_life_years`.
    rated_annual_hours: Positive
    #: From the A3-29 remaining-value equation at that age and use.
    salvage_fraction: UnitInterval
    repair_factor_rc1: NonNegative
    repair_factor_rc2: Positive

    @property
    def field_capacity_acres_per_hour(self) -> float:
        """Acres covered per productive machine hour, ASABE EP496."""
        return field_capacity(
            speed_mph=self.speed_mph,
            width_ft=self.width_ft,
            field_efficiency=self.field_efficiency,
        )

    def acres_covered_per_year(self, farm_acres: float) -> float:
        """Acres the machine passes over in a year, counting every pass.

        Args:
            farm_acres: Total crop acres on the farm.

        Returns:
            Acres covered. A farm making two herbicide passes on 2,400 acres
            covers 4,800.
        """
        return farm_acres * self.passes_per_farm_acre_per_year


class LandscapePoint(FrozenModel):
    """One operation, at one farm size, ready to plot."""

    operation_key: str
    label: str
    farm_acres: NonNegative
    annual_machine_hours: NonNegative
    window_days: Positive
    custom_rate_usd_per_acre: NonNegative
    custom_rate_responses: int
    break_even_acres: Positive | None
    quadrant: Quadrant


class MarketDepthAgreement(FrozenModel):
    """Whether the model agrees with what Iowa growers already did.

    The Phase-1 gate. Deep custom markets that land in the thesis quadrant are
    agreements; deep markets that land elsewhere are the model's problem, not
    the market's.
    """

    farm_acres: NonNegative
    min_responses: int
    deep_market_operations: tuple[str, ...]
    agreeing: tuple[str, ...]
    disagreeing: tuple[str, ...]

    @property
    def agreement_rate(self) -> float:
        """Share of deep markets in the thesis quadrant; 0.0 when there are none."""
        if not self.deep_market_operations:
            return 0.0
        return len(self.agreeing) / len(self.deep_market_operations)


def annual_machine_hours(operation: Operation, *, farm_acres: float) -> float:
    """Hours the machine runs in a year on a farm of this size.

    Args:
        operation: The field operation.
        farm_acres: Total crop acres on the farm.

    Returns:
        Machine hours per year. For a 120-foot sprayer at 18 mph on a
        2,400-acre farm making two passes, 24.4.

    Raises:
        ValueError: If `farm_acres` is negative.
    """
    if farm_acres < 0.0:
        raise ValueError(f"farm_acres must be non-negative, got {farm_acres}")
    return operation.acres_covered_per_year(farm_acres) / operation.field_capacity_acres_per_hour


def quadrant(
    *,
    annual_hours: float,
    window_days: float,
    low_utilization_hours: float = LOW_UTILIZATION_HOURS,
    narrow_window_days: float = NARROW_WINDOW_DAYS,
) -> Quadrant:
    """Assign an operation to a quadrant of the utilization / window plane.

    Both cuts are inclusive on the thesis side: exactly at the threshold counts
    as low use and as a narrow window.

    Args:
        annual_hours: Machine hours per year at the farm size being plotted.
        window_days: Length of the agronomic window.
        low_utilization_hours: Cut between low and high utilization.
        narrow_window_days: Cut between a narrow and a wide window.

    Returns:
        The quadrant. `LOW_USE_NARROW_WINDOW` is the thesis.
    """
    low_use = annual_hours <= low_utilization_hours
    narrow = window_days <= narrow_window_days
    if low_use:
        return Quadrant.LOW_USE_NARROW_WINDOW if narrow else Quadrant.LOW_USE_WIDE_WINDOW
    return Quadrant.HIGH_USE_NARROW_WINDOW if narrow else Quadrant.HIGH_USE_WIDE_WINDOW


def break_even_acres_vs_custom_rate(
    operation: Operation, rates: MachineryRates
) -> float | None:
    """Acres per year at which owning beats the published custom rate.

    Owner cost per acre is `ownership / acres + operating_per_acre`, so it meets
    the custom rate at a closed form:

    ```
    acres* = ownership_usd_per_year / (custom_rate - operating_usd_per_acre)
    ```

    No root-finding — unlike `finance.break_even_acreage`, which solves an NPV.

    Args:
        operation: The field operation. Needs a sourced `list_price_usd`.
        rates: Prices and ASABE factors. The operation's own A3-29 repair
            factors are substituted in: the `MachineryRates` defaults are the
            *tractor* row, and a sprayer's accumulated repairs are several times
            a tractor's for the same list price.

    Returns:
        Acres per year, or `None` when no list price is sourced, or when the
        machine's operating cost per acre alone already exceeds the custom rate
        — in which case ownership never wins at any acreage.
    """
    if operation.list_price_usd is None:
        return None
    machine = Machine(
        name=operation.label,
        # `config` is a sprayer-only tag the ASABE cost method never reads. When
        # a non-sprayer list price is sourced, this is the seam to widen.
        config=SprayerConfig.BASE,
        purchase_price_usd=operation.list_price_usd,
        working_speed_mph=operation.speed_mph,
        boom_width_ft=operation.width_ft,
        field_efficiency=operation.field_efficiency,
        useful_life_years=operation.useful_life_years,
        annual_use_hours=operation.rated_annual_hours,
        salvage_fraction=operation.salvage_fraction,
    )
    cost = machinery_cost(
        machine,
        rates.model_copy(
            update={
                "repair_factor_rf1": operation.repair_factor_rc1,
                "repair_factor_rf2": operation.repair_factor_rc2,
            }
        ),
    )
    operating_usd_per_acre = cost.operating_usd_per_hour / cost.field_capacity_acres_per_hour
    margin = operation.custom_rate_usd_per_acre - operating_usd_per_acre
    if margin <= 0.0:
        return None
    return cost.ownership_usd_per_year / margin


def landscape_points(
    operations: Sequence[Operation],
    *,
    farm_acres: float,
    rates: MachineryRates,
) -> tuple[LandscapePoint, ...]:
    """Place every operation on the plane for one farm size — one plot panel.

    Args:
        operations: The operations to plot, in the order they should be drawn.
        farm_acres: Total crop acres of the farm this panel represents.
        rates: Prices and ASABE factors for the break-even annotation.

    Returns:
        One point per operation, in input order.
    """
    points = []
    for operation in operations:
        hours = annual_machine_hours(operation, farm_acres=farm_acres)
        points.append(
            LandscapePoint(
                operation_key=operation.key,
                label=operation.label,
                farm_acres=farm_acres,
                annual_machine_hours=hours,
                window_days=operation.window_days,
                custom_rate_usd_per_acre=operation.custom_rate_usd_per_acre,
                custom_rate_responses=operation.custom_rate_responses,
                break_even_acres=break_even_acres_vs_custom_rate(operation, rates),
                quadrant=quadrant(annual_hours=hours, window_days=operation.window_days),
            )
        )
    return tuple(points)


def market_depth_agreement(
    points: Sequence[LandscapePoint],
    *,
    min_responses: int = DEEP_MARKET_RESPONSES,
) -> MarketDepthAgreement:
    """Check the model's quadrants against revealed market behaviour.

    Args:
        points: One panel's worth of points — all at the same farm size.
        min_responses: A3-10 response count that counts as a deep custom market.

    Returns:
        Which deep markets the model placed in the thesis quadrant and which it
        did not. A low agreement rate is a finding about the model, not a bug.

    Raises:
        ValueError: If `points` is empty, or mixes farm sizes — agreement is a
            statement about one panel, not about three at once.
    """
    if not points:
        raise ValueError("market_depth_agreement() needs at least one point")
    sizes = {point.farm_acres for point in points}
    if len(sizes) > 1:
        raise ValueError(f"points mix farm_acres values {sorted(sizes)}; pass one panel at a time")

    deep = [point for point in points if point.custom_rate_responses >= min_responses]
    return MarketDepthAgreement(
        farm_acres=points[0].farm_acres,
        min_responses=min_responses,
        deep_market_operations=tuple(point.operation_key for point in deep),
        agreeing=tuple(
            point.operation_key
            for point in deep
            if point.quadrant is Quadrant.LOW_USE_NARROW_WINDOW
        ),
        disagreeing=tuple(
            point.operation_key
            for point in deep
            if point.quadrant is not Quadrant.LOW_USE_NARROW_WINDOW
        ),
    )

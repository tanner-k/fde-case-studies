"""Machinery ownership and operating cost, by the published ASABE method.

**Standard:** ASABE EP496 *Agricultural Machinery Management* (ownership cost
structure, field capacity) and ASABE D497 *Agricultural Machinery Management
Data* (repair factors, fuel consumption). Iowa State University Extension
AgDM **A3-29** *Estimating Farm Machinery Costs* is the same method with US
customary defaults, and is where the 1% taxes/insurance/housing charge, the
0.044 gal per PTO hp-hour fuel rate, the 15%-of-fuel lubrication charge and the
1.1 labour-hours-per-machine-hour factor come from. The $20.40/hour wage is ISU
A1-20 2026. See `deliverables/appendix/sources.md` §5.

**Field capacity is the reason this module exists.**

```
acres/hour = speed_mph x boom_width_ft x field_efficiency / 8.25
```

8.25 = 43,560 sq ft per acre / 5,280 ft per mile, and lives in `models.py` as
`FIELD_CAPACITY_CONSTANT`. UADA FSA2225 publishes See & Spray Premium at 12 mph
against a base sprayer's 18, so Premium covers **two-thirds** the acres per
hour. That is more machine hours, more labour, and a narrower spray window —
a real cost the naive "chemical savings x 50%" model omits entirely.

**Cross-check.** ISU AgDM A3-10 (2025 Iowa Farm Custom Rate Survey) puts
self-propelled spraying at **$10.00/acre**. A modelled owner cost should sit
below that at applicator-scale utilisation, since the custom rate also carries
the applicator's overhead, tender logistics, road time and margin — and well
*above* it at farm-scale utilisation, which is the honest reason a 2,400-acre
operation hires the job out. Both directions are asserted in the tests.

No I/O: rates come in as a `MachineryRates`, assembled at the boundary.
"""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import Field

from engine.models import FIELD_CAPACITY_CONSTANT, FrozenModel, Machine, NonNegative, Positive


class MachineryRates(FrozenModel):
    """Prices and factors the ASABE method needs but a machine does not carry.

    Defaults are the published ISU AgDM A3-29 / ASABE D497 values. The three
    fields without defaults are prices and a machine specification: they change
    every year and every model, so a caller must state them rather than inherit
    a stale constant.
    """

    #: Real opportunity cost of capital tied up in the machine.
    interest_rate: Annotated[float, Field(ge=0.0, lt=1.0)]
    #: Engine PTO horsepower. **Not sourced in this repository** — see the
    #: report accompanying this module. Fuel is under $0.50/acre for a sprayer
    #: at any plausible value, so the model is insensitive to it.
    engine_pto_hp: NonNegative
    diesel_usd_per_gal: NonNegative
    labour_usd_per_hour: NonNegative
    #: ISU A3-29: taxes, insurance and housing together, as a share of price.
    tax_insurance_housing_rate: NonNegative = 0.01
    #: ASABE D497 repair factors for a sprayer: accumulated repair cost is
    #: `rf1 x price x (hours/1000) ** rf2`.
    repair_factor_rf1: NonNegative = 0.007
    repair_factor_rf2: Positive = 2.0
    #: ISU A3-29: average diesel use per maximum PTO horsepower-hour.
    fuel_gal_per_hp_hour: NonNegative = 0.044
    #: ASABE D497 / ISU A3-29: lubrication as a share of fuel cost.
    lubrication_fraction_of_fuel: NonNegative = 0.15
    #: ISU A3-29: setup, turning and transport beyond productive machine time.
    labour_hours_per_machine_hour: Positive = 1.1


class MachineryCost(FrozenModel):
    """Costed-out ownership and operation for one machine.

    Per-hour figures are annual charges divided by `machine.annual_use_hours`;
    per-acre figures divide those by field capacity. Both are the ISU A3-29
    convention and both assume the machine is used as much as it is rated for.
    For a farm that uses it less, `annual_cost_usd` is the honest function.
    """

    machine_name: str
    field_capacity_acres_per_hour: Positive
    depreciation_usd_per_year: NonNegative
    interest_usd_per_year: NonNegative
    tax_insurance_housing_usd_per_year: NonNegative
    ownership_usd_per_year: NonNegative
    ownership_usd_per_hour: NonNegative
    repairs_usd_per_hour: NonNegative
    fuel_usd_per_hour: NonNegative
    lubrication_usd_per_hour: NonNegative
    labour_usd_per_hour: NonNegative
    operating_usd_per_hour: NonNegative
    total_usd_per_hour: NonNegative
    total_usd_per_acre: NonNegative


def field_capacity(*, speed_mph: float, width_ft: float, field_efficiency: float) -> float:
    """Effective field capacity by the ASABE EP496 formula.

    The bare-numbers form. `landscape.py` costs out combines, planters and
    toolbars, none of which are a `Machine` — that model is sprayer-shaped.

    Args:
        speed_mph: Working speed.
        width_ft: Effective working width.
        field_efficiency: Share of theoretical capacity actually achieved.

    Returns:
        Acres covered per productive machine hour.
    """
    return speed_mph * width_ft * field_efficiency / FIELD_CAPACITY_CONSTANT


def field_capacity_acres_per_hour(machine: Machine) -> float:
    """Effective field capacity for a `Machine`.

    Args:
        machine: Speed, boom width and field efficiency.

    Returns:
        Acres covered per productive machine hour.
    """
    return field_capacity(
        speed_mph=machine.working_speed_mph,
        width_ft=machine.boom_width_ft,
        field_efficiency=machine.field_efficiency,
    )


def hours_for_acres(machine: Machine, acres: float) -> float:
    """Machine hours needed to cover `acres` once.

    Args:
        machine: The sprayer.
        acres: Area to cover, in acres.

    Returns:
        Hours. This is where the 12-vs-18 mph difference becomes a cost.

    Raises:
        ValueError: If `acres` is negative.
    """
    if acres < 0.0:
        raise ValueError(f"acres must be non-negative, got {acres}")
    return acres / field_capacity_acres_per_hour(machine)


def _salvage_usd(machine: Machine) -> float:
    """Remaining value at the end of `useful_life_years`."""
    return machine.purchase_price_usd * machine.salvage_fraction


def _repairs_usd_per_hour(machine: Machine, rates: MachineryRates) -> float:
    """Lifetime-average repair cost per hour, ASABE D497.

    D497 states accumulated repairs against *list* price; purchase price is
    used here as the closest available proxy, which understates repairs on a
    heavily discounted machine.

    Args:
        machine: The sprayer.
        rates: Repair factors.

    Returns:
        Dollars per machine hour, averaged over the machine's whole life.
    """
    lifetime_hours = machine.annual_use_hours * machine.useful_life_years
    accumulated = (
        rates.repair_factor_rf1
        * machine.purchase_price_usd
        * (lifetime_hours / 1000.0) ** rates.repair_factor_rf2
    )
    return accumulated / lifetime_hours


def machinery_cost(machine: Machine, rates: MachineryRates) -> MachineryCost:
    """Full ownership and operating cost for one machine at its rated use.

    Args:
        machine: The sprayer, including its rated annual hours and useful life.
        rates: Prices and ASABE factors.

    Returns:
        A `MachineryCost` broken out far enough to argue with. Ownership is
        straight-line depreciation over `useful_life_years` net of salvage,
        interest on the average investment `(price + salvage) / 2`, and a
        taxes/insurance/housing charge on purchase price.
    """
    salvage = _salvage_usd(machine)
    depreciation = (machine.purchase_price_usd - salvage) / machine.useful_life_years
    interest = 0.5 * (machine.purchase_price_usd + salvage) * rates.interest_rate
    tih = machine.purchase_price_usd * rates.tax_insurance_housing_rate
    ownership = depreciation + interest + tih

    fuel = rates.engine_pto_hp * rates.fuel_gal_per_hp_hour * rates.diesel_usd_per_gal
    lubrication = fuel * rates.lubrication_fraction_of_fuel
    labour = rates.labour_usd_per_hour * rates.labour_hours_per_machine_hour
    repairs = _repairs_usd_per_hour(machine, rates)
    operating = repairs + fuel + lubrication + labour

    capacity = field_capacity_acres_per_hour(machine)
    total_per_hour = ownership / machine.annual_use_hours + operating
    return MachineryCost(
        machine_name=machine.name,
        field_capacity_acres_per_hour=capacity,
        depreciation_usd_per_year=depreciation,
        interest_usd_per_year=interest,
        tax_insurance_housing_usd_per_year=tih,
        ownership_usd_per_year=ownership,
        ownership_usd_per_hour=ownership / machine.annual_use_hours,
        repairs_usd_per_hour=repairs,
        fuel_usd_per_hour=fuel,
        lubrication_usd_per_hour=lubrication,
        labour_usd_per_hour=labour,
        operating_usd_per_hour=operating,
        total_usd_per_hour=total_per_hour,
        total_usd_per_acre=total_per_hour / capacity,
    )


def annual_cost_usd(machine: Machine, rates: MachineryRates, *, acres_covered: float) -> float:
    """Annual cost of owning the machine and covering `acres_covered` with it.

    The distinction from `MachineryCost.total_usd_per_acre` is the whole
    ownership-versus-custom-hire argument. Ownership is an annual charge that
    lands whether or not the machine leaves the shed; operating cost accrues by
    the hour. A farm covering 2,400 acres a year pays the same depreciation as
    an applicator covering 78,000, and pays it over one-thirtieth the acres.

    Args:
        machine: The sprayer.
        rates: Prices and ASABE factors.
        acres_covered: Total acres the machine passes over in a year, counting
            every pass — a farm making two herbicide passes on 2,400 acres
            covers 4,800.

    Returns:
        Dollars per year.

    Raises:
        ValueError: If `acres_covered` is negative.
    """
    if acres_covered < 0.0:
        raise ValueError(f"acres_covered must be non-negative, got {acres_covered}")
    cost = machinery_cost(machine, rates)
    return cost.ownership_usd_per_year + cost.operating_usd_per_hour * hours_for_acres(
        machine, acres_covered
    )


class RemainingValue(FrozenModel):
    """ASABE remaining-value coefficients for one A3-29 machine type.

    Read out of `data/reference/isu_a3_29_machine_data.json`, which is parsed
    from the archived A3-29 calculator by `scripts/extract_isu_reference.py`.
    """

    machine_type: str = Field(min_length=1)
    rv_intercept: Positive
    rv_age_coeff: NonNegative
    rv_hours_coeff: NonNegative


def remaining_value_fraction(
    coefficients: RemainingValue,
    *,
    age_years: float,
    annual_hours: float,
) -> float:
    """Share of list price a machine retains, by the ASABE remaining-value equation.

    ```
    RV = list_price x (intercept - age_coeff*sqrt(age) - hours_coeff*sqrt(hours))^2
    ```

    `rv_hours_coeff` is **zero** for sprayers, planters and every implement:
    their resale depends on age alone, not on how hard they were worked. The
    engine's flat `Machine.salvage_fraction` default of 0.25 cannot express
    that — for a 10-year sprayer the equation returns 0.405, which makes
    ownership meaningfully cheaper than the flat assumption says (JDRC-22).

    Args:
        coefficients: The machine type's A3-29 row.
        age_years: Age at resale.
        annual_hours: Hours per year over that life.

    Returns:
        A non-negative fraction, clamped at zero before squaring so a negative
        base cannot square back into a positive residual value. **Not bounded
        above at 1.0**: at `age_years=0` and `annual_hours=0` this equals
        `rv_intercept ** 2`, and four A3-29 machine types carry
        `rv_intercept > 1.0` (e.g. `Combine SP unit` at 1.1318), so a new,
        unused machine of those types returns up to ~1.28. `load_operations`
        never hits this — `useful_life_years` is constrained `> 0` — but a
        caller who feeds the result straight into `Operation.salvage_fraction`
        (a `UnitInterval`, bounded at 1.0) at `age_years=0` gets an opaque
        pydantic validation error, not a clamp. Clamp the upper bound
        yourself if the caller's age can be zero.

    Raises:
        ValueError: If `age_years` or `annual_hours` is negative.
    """
    if age_years < 0.0 or annual_hours < 0.0:
        raise ValueError(
            f"age_years and annual_hours must be non-negative, got {age_years}, {annual_hours}"
        )
    base = (
        coefficients.rv_intercept
        - coefficients.rv_age_coeff * math.sqrt(age_years)
        - coefficients.rv_hours_coeff * math.sqrt(annual_hours)
    )
    return max(base, 0.0) ** 2

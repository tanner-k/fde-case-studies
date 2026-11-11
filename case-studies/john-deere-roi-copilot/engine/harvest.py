"""Pure workload and sourced-input helpers for one shared combine."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from numbers import Real
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from engine.finance import annuity_factor


class CombineScenarioError(ValueError):
    """The scenario file cannot support a traceable calculation."""


@dataclass(frozen=True)
class HarvestWorkload:
    """Crop acres and productive hours for one combine."""

    corn_acres: float
    soy_acres: float
    corn_hours: float
    soy_hours: float
    base_combine_hours: float


@dataclass(frozen=True)
class HarvestWindow:
    """One crop's dated harvest interval and workable days within it."""

    start: date
    end: date
    workable_days: float


@dataclass(frozen=True)
class ContractorCommitments:
    """Dated, crop-specific contractor hours promised under stated weather inputs."""

    corn_window: HarvestWindow | None
    soy_window: HarvestWindow | None
    corn_hours: float
    soy_hours: float
    hours_per_workable_day: float | None
    crew_hours: float | None
    service_scope: str | None
    parallel_capacity: bool | None


@dataclass(frozen=True)
class CropFeasibility:
    """One crop's owned-combine timing result."""

    status: str
    required_hours: float
    gross_available_hours: float | None
    explanation: str


@dataclass(frozen=True)
class Feasibility:
    """Owned and documented-hire timing classifications for two crops."""

    corn: CropFeasibility
    soy: CropFeasibility
    owner_status: str
    hire_status: str
    hire_corn_status: str
    hire_soy_status: str
    usable_machine_hours: float | None
    explanation: str


@dataclass(frozen=True)
class Asset:
    """One owned asset with a sourced terminal-resale assumption."""

    purchase_usd: float
    terminal_resale_usd: float
    starting_hours: float
    list_price_usd: float
    repair_rc1: float
    repair_rc2: float
    starting_age_years: float
    terminal_age_years: float
    terminal_hours: float
    meter_convention: str
    wearout_hours: float
    terminal_resale_source: str


@dataclass(frozen=True)
class HarvestOption:
    """Inputs for one comparable ownership or combining-only hire option."""

    kind: str
    horizon_years: int
    service_scope: str
    base: Asset | None = None
    corn_head: Asset | None = None
    draper_head: Asset | None = None
    fuel_gallons_per_base_hour: float | None = None
    fuel_usd_per_gallon: float | None = None
    lubrication_fraction_of_fuel: float | None = None
    labor_hours_per_base_hour: float | None = None
    labor_usd_per_hour: float | None = None
    annual_insurance_tax_storage_usd: float | None = None
    annual_equivalent_services_usd: float | None = None
    corn_hire_usd_per_acre: float | None = None
    soy_hire_usd_per_acre: float | None = None


@dataclass(frozen=True)
class CostBreakdown:
    """Annual economic-cost lines, all in USD/year."""

    workload: HarvestWorkload
    horizon_years: int
    service_scope: str
    base_capital_usd_per_year: float = 0.0
    corn_head_capital_usd_per_year: float = 0.0
    draper_head_capital_usd_per_year: float = 0.0
    fuel_lube_usd_per_year: float = 0.0
    repairs_usd_per_year: float = 0.0
    labor_usd_per_year: float = 0.0
    insurance_tax_storage_usd_per_year: float = 0.0
    equivalent_services_usd_per_year: float = 0.0
    hired_harvest_usd_per_year: float = 0.0
    total_usd_per_year: float | None = None


@dataclass(frozen=True)
class BreakEvenResult:
    """A sampled fixed-mix cost-gap root, or the reason one was not found."""

    status: str
    acres: float | None
    explanation: str


@dataclass(frozen=True)
class HarvestChoice:
    """A timing-gated choice among the three scoped harvest options."""

    choice: str
    explanation: str


def _finite_nonnegative(name: str, value: float) -> None:
    if not isinstance(value, Real) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")


def _validate_asset(asset: Asset, annual_hours: float, horizon_years: int) -> None:
    for name in (
        "purchase_usd",
        "terminal_resale_usd",
        "starting_hours",
        "list_price_usd",
        "repair_rc1",
        "repair_rc2",
        "starting_age_years",
        "terminal_age_years",
        "terminal_hours",
        "wearout_hours",
    ):
        value = getattr(asset, name)
        _finite_nonnegative(name, value)
    if asset.repair_rc2 <= 0:
        raise ValueError("repair_rc2 must be positive")
    if asset.meter_convention != "productive_machine_hours":
        raise ValueError("meter_convention must be productive_machine_hours")
    if not isinstance(asset.terminal_resale_source, str) or not asset.terminal_resale_source.strip():
        raise ValueError("terminal_resale_source must be non-empty")
    if asset.terminal_hours > asset.wearout_hours:
        raise ValueError("terminal_hours exceeds supported wearout_hours")
    if not math.isclose(asset.terminal_age_years, asset.starting_age_years + horizon_years):
        raise ValueError("terminal_age_years must match horizon_years")
    expected_terminal_hours = asset.starting_hours + annual_hours * horizon_years
    if not math.isclose(asset.terminal_hours, expected_terminal_hours):
        raise ValueError("terminal_hours must match workload and horizon_years")


def _asset_capital_eac(asset: Asset, rate: float, horizon_years: int) -> float:
    return (asset.purchase_usd - asset.terminal_resale_usd / (1.0 + rate) ** horizon_years) / annuity_factor(rate, horizon_years)


def _accumulated_repairs(asset: Asset, hours: float) -> float:
    return asset.repair_rc1 * asset.list_price_usd * (hours / 1_000.0) ** asset.repair_rc2


def _repair_eac(asset: Asset, annual_hours: float, rate: float, horizon_years: int) -> float:
    repairs_pv = sum(
        (
            _accumulated_repairs(asset, asset.starting_hours + year * annual_hours)
            - _accumulated_repairs(asset, asset.starting_hours + (year - 1) * annual_hours)
        )
        / (1.0 + rate) ** year
        for year in range(1, horizon_years + 1)
    )
    return repairs_pv / annuity_factor(rate, horizon_years)


def _annualize_constant_charge(charge_usd: float, rate: float, horizon_years: int) -> float:
    return sum(charge_usd / (1.0 + rate) ** year for year in range(1, horizon_years + 1)) / annuity_factor(rate, horizon_years)


def annual_option_cost(
    workload: HarvestWorkload, option: HarvestOption, rate: float
) -> CostBreakdown:
    """Return one option's economic cost, with capital and cash charges separate."""
    _finite_nonnegative("rate", rate)
    if not isinstance(option.horizon_years, int) or isinstance(option.horizon_years, bool) or option.horizon_years <= 0:
        raise ValueError("horizon_years must be a positive integer")
    if not isinstance(option.service_scope, str) or not option.service_scope:
        raise ValueError("service_scope must be non-empty")
    for name, value in vars(workload).items():
        _finite_nonnegative(name, value)

    if option.kind == "hire":
        if option.corn_hire_usd_per_acre is None or option.soy_hire_usd_per_acre is None:
            raise ValueError("hire option needs corn and soybean rates")
        _finite_nonnegative("corn_hire_usd_per_acre", option.corn_hire_usd_per_acre)
        _finite_nonnegative("soy_hire_usd_per_acre", option.soy_hire_usd_per_acre)
        hired = (
            workload.corn_acres * option.corn_hire_usd_per_acre
            + workload.soy_acres * option.soy_hire_usd_per_acre
        )
        return CostBreakdown(
            workload=workload,
            horizon_years=option.horizon_years,
            service_scope=option.service_scope,
            hired_harvest_usd_per_year=hired,
            total_usd_per_year=hired,
        )

    if option.kind != "own":
        raise ValueError("kind must be 'own' or 'hire'")
    if option.base is None or option.corn_head is None or option.draper_head is None:
        raise ValueError("owner option needs base, corn_head, and draper_head")
    for asset, hours in (
        (option.base, workload.base_combine_hours),
        (option.corn_head, workload.corn_hours),
        (option.draper_head, workload.soy_hours),
    ):
        _validate_asset(asset, hours, option.horizon_years)
    for name in (
        "fuel_gallons_per_base_hour",
        "fuel_usd_per_gallon",
        "lubrication_fraction_of_fuel",
        "labor_hours_per_base_hour",
        "labor_usd_per_hour",
        "annual_insurance_tax_storage_usd",
        "annual_equivalent_services_usd",
    ):
        value = getattr(option, name)
        if value is None:
            raise ValueError(f"{name} must be explicit for an owner option")
        _finite_nonnegative(name, value)

    base_capital = _asset_capital_eac(option.base, rate, option.horizon_years)
    corn_capital = _asset_capital_eac(option.corn_head, rate, option.horizon_years)
    draper_capital = _asset_capital_eac(option.draper_head, rate, option.horizon_years)
    fuel = workload.base_combine_hours * option.fuel_gallons_per_base_hour * option.fuel_usd_per_gallon
    fuel_lube = fuel * (1.0 + option.lubrication_fraction_of_fuel)
    repairs = sum(
        _repair_eac(asset, hours, rate, option.horizon_years)
        for asset, hours in (
            (option.base, workload.base_combine_hours),
            (option.corn_head, workload.corn_hours),
            (option.draper_head, workload.soy_hours),
        )
    )
    labor = workload.base_combine_hours * option.labor_hours_per_base_hour * option.labor_usd_per_hour
    insurance = _annualize_constant_charge(option.annual_insurance_tax_storage_usd, rate, option.horizon_years)
    services = _annualize_constant_charge(option.annual_equivalent_services_usd, rate, option.horizon_years)
    total = base_capital + corn_capital + draper_capital + fuel_lube + repairs + labor + insurance + services
    return CostBreakdown(
        workload=workload,
        horizon_years=option.horizon_years,
        service_scope=option.service_scope,
        base_capital_usd_per_year=base_capital,
        corn_head_capital_usd_per_year=corn_capital,
        draper_head_capital_usd_per_year=draper_capital,
        fuel_lube_usd_per_year=fuel_lube,
        repairs_usd_per_year=repairs,
        labor_usd_per_year=labor,
        insurance_tax_storage_usd_per_year=insurance,
        equivalent_services_usd_per_year=services,
        total_usd_per_year=total,
    )


def cost_gap_usd_per_year(own: CostBreakdown, hire: CostBreakdown) -> float | None:
    """Return owner minus hire cost only for equal economic scopes and horizons."""
    if (
        own.workload != hire.workload
        or
        own.horizon_years != hire.horizon_years
        or own.service_scope != hire.service_scope
        or own.total_usd_per_year is None
        or hire.total_usd_per_year is None
    ):
        return None
    return own.total_usd_per_year - hire.total_usd_per_year


def break_even_acres(
    sampled_acres: list[float],
    cost_gap_for_acres: Any,
    tolerance_acres: float = 1e-6,
    max_iterations: int = 80,
) -> BreakEvenResult:
    """Find one fixed-crop-mix cost crossing in a supplied acreage grid.

    A sampled sign-change bracket is bisected to ``tolerance_acres``. This
    requires a continuous gap inside that bracket and only detects roots or
    ties visible in the supplied grid.
    """
    if len(sampled_acres) < 2:
        raise ValueError("sampled_acres needs at least two points")
    if not callable(cost_gap_for_acres):
        raise ValueError("cost_gap_for_acres must be callable")
    if not isinstance(tolerance_acres, Real) or isinstance(tolerance_acres, bool) or not math.isfinite(tolerance_acres) or tolerance_acres <= 0:
        raise ValueError("tolerance_acres must be finite and positive")
    if not isinstance(max_iterations, int) or isinstance(max_iterations, bool) or max_iterations <= 0:
        raise ValueError("max_iterations must be a positive integer")
    for index, acres in enumerate(sampled_acres):
        _finite_nonnegative(f"sampled_acres[{index}]", acres)
        if index and acres <= sampled_acres[index - 1]:
            raise ValueError("sampled_acres must be strictly increasing")

    def evaluate(acres: float) -> float:
        gap = cost_gap_for_acres(acres)
        if not isinstance(gap, Real) or isinstance(gap, bool) or not math.isfinite(gap):
            raise ValueError("cost_gap_for_acres must return a finite number")
        return float(gap)

    gaps = [evaluate(acres) for acres in sampled_acres]
    zero_indexes = [index for index, gap in enumerate(gaps) if gap == 0]
    if any(right == left + 1 for left, right in zip(zero_indexes, zero_indexes[1:])):
        return BreakEvenResult("tie", None, "a sampled cost tie prevents a unique crossing")

    crossings = [
        (sampled_acres[index], sampled_acres[index + 1], gaps[index], gaps[index + 1])
        for index in range(len(sampled_acres) - 1)
        if gaps[index] * gaps[index + 1] < 0
    ]
    root_count = len(zero_indexes) + len(crossings)
    if root_count == 0:
        return BreakEvenResult("none_in_range", None, "no sampled cost-gap sign change")
    if root_count > 1:
        return BreakEvenResult("multiple_crossings", None, "multiple sampled cost-gap sign changes")
    if zero_indexes:
        return BreakEvenResult("crossing", sampled_acres[zero_indexes[0]], "exact sampled cost equality")
    left_acres, right_acres, left_gap, _right_gap = crossings[0]
    for _ in range(max_iterations):
        midpoint = (left_acres + right_acres) / 2
        midpoint_gap = evaluate(midpoint)
        if midpoint_gap == 0 or right_acres - left_acres <= tolerance_acres:
            return BreakEvenResult("crossing", midpoint, "bisected sampled sign-change bracket")
        if left_gap * midpoint_gap < 0:
            right_acres = midpoint
        else:
            left_acres = midpoint
            left_gap = midpoint_gap
    return BreakEvenResult("nonconvergent", None, "bisection iteration limit reached")


def _cost_bounds_are_numeric(cost_bounds: tuple[float, float] | None) -> bool:
    if cost_bounds is None or not isinstance(cost_bounds, tuple) or len(cost_bounds) != 2:
        return False
    lower, upper = cost_bounds
    return (
        isinstance(lower, Real)
        and not isinstance(lower, bool)
        and math.isfinite(lower)
        and isinstance(upper, Real)
        and not isinstance(upper, bool)
        and math.isfinite(upper)
        and lower <= upper
    )


def classify_harvest_choice(
    *,
    new_own_cost: tuple[float, float] | None,
    used_own_cost: tuple[float, float] | None,
    hire_both_cost: tuple[float, float] | None,
    new_own_timing: str,
    used_own_timing: str,
    hire_both_timing: str,
) -> HarvestChoice:
    """Choose only a uniquely lower-cost option with documented feasible timing."""
    valid_statuses = {"feasible", "infeasible", "unknown"}
    timings = (new_own_timing, used_own_timing, hire_both_timing)
    if any(timing not in valid_statuses for timing in timings):
        raise ValueError("timing statuses must be feasible, infeasible, or unknown")
    if all(timing == "infeasible" for timing in timings):
        return HarvestChoice("infeasible", "all ownership and hire options fail timing")
    if "unknown" in timings:
        return HarvestChoice("indeterminate", "timing is unknown for at least one option")

    options = {
        "new_own": (new_own_cost, new_own_timing),
        "used_own": (used_own_cost, used_own_timing),
        "hire_both": (hire_both_cost, hire_both_timing),
    }
    feasible = {
        name: cost for name, (cost, timing) in options.items() if timing == "feasible"
    }
    assert feasible
    if not all(_cost_bounds_are_numeric(cost) for cost in feasible.values()):
        return HarvestChoice("indeterminate", "every feasible option needs numeric, ordered cost bounds")
    winners = [
        name
        for name, bounds in feasible.items()
        if all(bounds[1] < other_bounds[0] for other_name, other_bounds in feasible.items() if other_name != name)
    ]
    if len(winners) == 1:
        public_choices = {"new_own": "new", "used_own": "used", "hire_both": "hire"}
        return HarvestChoice(public_choices[winners[0]], "cost bounds are separated and timing is feasible")
    return HarvestChoice("indeterminate", "feasible cost bounds overlap or tie")


def acreage_crop_mix_grid(
    total_acres: list[float], corn_shares: list[float], evaluator: Any
) -> dict[tuple[float, float], Any]:
    """Evaluate caller-provided cases across acreage and crop-share inputs."""
    if not callable(evaluator):
        raise ValueError("evaluator must be callable")
    for acres in total_acres:
        _finite_nonnegative("total_acres", acres)
    for corn_share in corn_shares:
        if (
            not isinstance(corn_share, Real)
            or isinstance(corn_share, bool)
            or not math.isfinite(corn_share)
            or not 0 <= corn_share <= 1
        ):
            raise ValueError("corn_share must be finite and between 0 and 1")
    return {(acres, corn_share): evaluator(acres, corn_share) for acres in total_acres for corn_share in corn_shares}


def harvest_workload(
    total_acres: float,
    corn_share: float,
    corn_capacity: float,
    soy_capacity: float,
) -> HarvestWorkload:
    """Calculate one-pass corn and soybean workload using exact capacities."""
    for name, value in {
        "total_acres": total_acres,
        "corn_share": corn_share,
        "corn_capacity": corn_capacity,
        "soy_capacity": soy_capacity,
    }.items():
        if not isinstance(value, Real) or isinstance(value, bool) or not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if total_acres < 0:
        raise ValueError("total_acres must be non-negative")
    if not 0 <= corn_share <= 1:
        raise ValueError("corn_share must be between 0 and 1")
    if corn_capacity <= 0 or soy_capacity <= 0:
        raise ValueError("capacity must be positive")

    corn_acres = total_acres * corn_share
    soy_acres = total_acres - corn_acres
    corn_hours = corn_acres / corn_capacity
    soy_hours = soy_acres / soy_capacity
    return HarvestWorkload(
        corn_acres=corn_acres,
        soy_acres=soy_acres,
        corn_hours=corn_hours,
        soy_hours=soy_hours,
        base_combine_hours=corn_hours + soy_hours,
    )


def _validate_window(name: str, window: HarvestWindow) -> None:
    if not isinstance(window, HarvestWindow):
        raise ValueError(f"{name} must be a HarvestWindow")
    if not isinstance(window.start, date) or not isinstance(window.end, date) or window.end < window.start:
        raise ValueError(f"{name} must have an ordered date interval")
    _finite_nonnegative(f"{name}.workable_days", window.workable_days)
    calendar_days = (window.end - window.start).days + 1
    if window.workable_days > calendar_days:
        raise ValueError(f"{name}.workable_days cannot exceed its date interval")


def _overlap_days(first: HarvestWindow, second: HarvestWindow) -> int:
    start = max(first.start, second.start)
    end = min(first.end, second.end)
    return max(0, (end - start).days + 1)


def _head_changes(
    corn_window: HarvestWindow | None,
    soy_window: HarvestWindow | None,
    corn_hours: float,
    soy_hours: float,
    corn_gross_hours: float,
    soy_gross_hours: float,
) -> int:
    if not corn_hours or not soy_hours:
        return 0
    assert corn_window is not None and soy_window is not None
    if (
        corn_window.start < soy_window.start
        and corn_window.end > soy_window.end
        and corn_hours
        > max(
            corn_gross_hours * (soy_window.start - corn_window.start).days
            / ((corn_window.end - corn_window.start).days + 1),
            corn_gross_hours * (corn_window.end - soy_window.end).days
            / ((corn_window.end - corn_window.start).days + 1),
        )
    ) or (
        soy_window.start < corn_window.start
        and soy_window.end > corn_window.end
        and soy_hours
        > max(
            soy_gross_hours * (corn_window.start - soy_window.start).days
            / ((soy_window.end - soy_window.start).days + 1),
            soy_gross_hours * (soy_window.end - corn_window.end).days
            / ((soy_window.end - soy_window.start).days + 1),
        )
    ):
        return 2
    return 1


def harvest_feasibility(
    workload: HarvestWorkload,
    corn_window: HarvestWindow | None,
    soy_window: HarvestWindow | None,
    hours_per_workable_day: float | None,
    downtime_days: float,
    head_change_hours: float,
    crew_hours: float | None,
    contractor_commitments: ContractorCommitments | None,
) -> Feasibility:
    """Classify crop timing using dated windows and one shared machine.

    Workable days are allocated proportionally across each dated interval. The
    overlapping portion is shared once; no crop receives priority there.
    """
    for name, value in vars(workload).items():
        _finite_nonnegative(name, value)
    _finite_nonnegative("downtime_days", downtime_days)
    _finite_nonnegative("head_change_hours", head_change_hours)
    if hours_per_workable_day is not None:
        _finite_nonnegative("hours_per_workable_day", hours_per_workable_day)
    if crew_hours is not None:
        _finite_nonnegative("crew_hours", crew_hours)
    if corn_window is not None:
        _validate_window("corn_window", corn_window)
    if soy_window is not None:
        _validate_window("soy_window", soy_window)

    missing_owner_inputs = hours_per_workable_day is None or crew_hours is None
    missing_corn_window = workload.corn_hours > 0 and corn_window is None
    missing_soy_window = workload.soy_hours > 0 and soy_window is None
    if missing_owner_inputs or missing_corn_window or missing_soy_window:
        corn_status = "feasible" if workload.corn_hours == 0 else "unknown"
        soy_status = "feasible" if workload.soy_hours == 0 else "unknown"
        corn = CropFeasibility(corn_status, workload.corn_hours, None, "owner timing inputs are incomplete")
        soy = CropFeasibility(soy_status, workload.soy_hours, None, "owner timing inputs are incomplete")
        owner_status = "unknown" if "unknown" in (corn_status, soy_status) else "feasible"
    else:
        corn_window = corn_window if workload.corn_hours else None
        soy_window = soy_window if workload.soy_hours else None
        assert corn_window is not None or workload.corn_hours == 0
        assert soy_window is not None or workload.soy_hours == 0
        hours = hours_per_workable_day
        corn_days = (corn_window.end - corn_window.start).days + 1 if corn_window else 0
        soy_days = (soy_window.end - soy_window.start).days + 1 if soy_window else 0
        overlap_days = _overlap_days(corn_window, soy_window) if corn_window and soy_window else 0
        corn_total = (corn_window.workable_days if corn_window else 0) * hours
        soy_total = (soy_window.workable_days if soy_window else 0) * hours
        corn_overlap = corn_total * overlap_days / corn_days if corn_days else 0
        soy_overlap = soy_total * overlap_days / soy_days if soy_days else 0
        shared_overlap = min(corn_overlap, soy_overlap)
        corn_only = corn_total - corn_overlap
        soy_only = soy_total - soy_overlap
        sequencing_unknown = overlap_days > 0 and corn_window != soy_window
        head_changes = 0 if sequencing_unknown else _head_changes(
            corn_window,
            soy_window,
            workload.corn_hours,
            workload.soy_hours,
            corn_total,
            soy_total,
        )
        lost_hours = downtime_days * hours + head_changes * head_change_hours
        machine_hours = corn_only + soy_only + shared_overlap - lost_hours
        if machine_hours < 0 and not sequencing_unknown:
            raise ValueError("available machine time cannot be negative")
        crew_harvest_hours = max(0.0, crew_hours - head_changes * head_change_hours)
        total_available = None if sequencing_unknown else min(machine_hours, crew_harvest_hours)
        corn_needs_overlap = max(0.0, workload.corn_hours - corn_only)
        soy_needs_overlap = max(0.0, workload.soy_hours - soy_only)
        corn_capacity_failure = workload.corn_hours > corn_total
        soy_capacity_failure = workload.soy_hours > soy_total
        shared_capacity_failure = corn_needs_overlap + soy_needs_overlap > shared_overlap
        total_capacity_failure = (
            False if sequencing_unknown else workload.base_combine_hours > total_available
        )
        capacity_failure = (
            corn_capacity_failure
            or soy_capacity_failure
            or (not sequencing_unknown and (shared_capacity_failure or total_capacity_failure))
        )
        owner_status = "infeasible" if capacity_failure else "unknown" if sequencing_unknown else "feasible"
        explanation = (
            "shared overlap capacity is insufficient"
            if not sequencing_unknown and shared_capacity_failure
            else "available machine or crew hours are insufficient"
            if corn_capacity_failure or soy_capacity_failure or (not sequencing_unknown and total_capacity_failure)
            else "overlapping crop windows need a dated executable sequence"
            if sequencing_unknown
            else "dated crop windows, shared overlap, outages, head changes, and crew hours fit"
        )
        corn_status = "feasible" if workload.corn_hours == 0 else (
            "infeasible"
            if corn_capacity_failure or (not sequencing_unknown and (shared_capacity_failure or total_capacity_failure))
            else "unknown"
            if sequencing_unknown
            else "feasible"
        )
        soy_status = "feasible" if workload.soy_hours == 0 else (
            "infeasible"
            if soy_capacity_failure or (not sequencing_unknown and (shared_capacity_failure or total_capacity_failure))
            else "unknown"
            if sequencing_unknown
            else "feasible"
        )
        corn = CropFeasibility(corn_status, workload.corn_hours, corn_total, explanation)
        soy = CropFeasibility(soy_status, workload.soy_hours, soy_total, explanation)

    if contractor_commitments is None:
        hire_corn_status = "feasible" if workload.corn_hours == 0 else "unknown"
        hire_soy_status = "feasible" if workload.soy_hours == 0 else "unknown"
        hire_status = "unknown" if "unknown" in (hire_corn_status, hire_soy_status) else "feasible"
    else:
        if not isinstance(contractor_commitments, ContractorCommitments):
            raise ValueError("contractor_commitments must be ContractorCommitments or None")
        _finite_nonnegative("contractor_commitments.corn_hours", contractor_commitments.corn_hours)
        _finite_nonnegative("contractor_commitments.soy_hours", contractor_commitments.soy_hours)
        if contractor_commitments.hours_per_workable_day is not None:
            _finite_nonnegative(
                "contractor_commitments.hours_per_workable_day",
                contractor_commitments.hours_per_workable_day,
            )
        if contractor_commitments.crew_hours is not None:
            _finite_nonnegative("contractor_commitments.crew_hours", contractor_commitments.crew_hours)
        if contractor_commitments.corn_window is not None:
            _validate_window("contractor_commitments.corn_window", contractor_commitments.corn_window)
        if contractor_commitments.soy_window is not None:
            _validate_window("contractor_commitments.soy_window", contractor_commitments.soy_window)
        corn_matches_weather = corn_window is not None and contractor_commitments.corn_window == corn_window
        soy_matches_weather = soy_window is not None and contractor_commitments.soy_window == soy_window
        documented_capacity = (
            contractor_commitments.hours_per_workable_day is not None
            and contractor_commitments.crew_hours is not None
            and isinstance(contractor_commitments.service_scope, str)
            and contractor_commitments.service_scope.strip()
        )
        corn_weather_capacity = (
            contractor_commitments.corn_window.workable_days * contractor_commitments.hours_per_workable_day
            if documented_capacity and contractor_commitments.corn_window is not None
            else 0.0
        )
        soy_weather_capacity = (
            contractor_commitments.soy_window.workable_days * contractor_commitments.hours_per_workable_day
            if documented_capacity and contractor_commitments.soy_window is not None
            else 0.0
        )
        commitments_exceed_capacity = documented_capacity and (
            workload.corn_hours > 0 and contractor_commitments.corn_hours > corn_weather_capacity
            or workload.soy_hours > 0 and contractor_commitments.soy_hours > soy_weather_capacity
            or contractor_commitments.corn_hours + contractor_commitments.soy_hours > contractor_commitments.crew_hours
        )
        overlapping_commitments = (
            workload.corn_hours > 0
            and workload.soy_hours > 0
            and corn_window is not None
            and soy_window is not None
            and _overlap_days(corn_window, soy_window) > 0
            and contractor_commitments.parallel_capacity is not True
        )
        hire_corn_status = (
            "feasible"
            if workload.corn_hours == 0
            else "unknown"
            if not corn_matches_weather or not documented_capacity
            else "infeasible"
            if commitments_exceed_capacity
            else "unknown"
            if overlapping_commitments
            else "feasible"
            if contractor_commitments.corn_hours >= workload.corn_hours
            else "infeasible"
        )
        hire_soy_status = (
            "feasible"
            if workload.soy_hours == 0
            else "unknown"
            if not soy_matches_weather or not documented_capacity
            else "infeasible"
            if commitments_exceed_capacity
            else "unknown"
            if overlapping_commitments
            else "feasible"
            if contractor_commitments.soy_hours >= workload.soy_hours
            else "infeasible"
        )
        hire_status = (
            "unknown"
            if "unknown" in (hire_corn_status, hire_soy_status)
            else "feasible"
            if hire_corn_status == hire_soy_status == "feasible"
            else "infeasible"
        )

    return Feasibility(
        corn=corn,
        soy=soy,
        owner_status=owner_status,
        hire_status=hire_status,
        hire_corn_status=hire_corn_status,
        hire_soy_status=hire_soy_status,
        usable_machine_hours=(
            0.0
            if workload.base_combine_hours == 0
            else None
            if owner_status == "unknown"
            else total_available
        ),
        explanation=(
            f"owner: {corn.explanation}; contractor timing is unknown without matching dated crop commitments"
            if contractor_commitments is None
            else f"owner: {corn.explanation}; contractor: {hire_status}"
        ),
    )


_SOURCE_FIELDS = {
    "id",
    "effective_or_as_of_date",
    "accessed_date",
    "geography",
    "equipment_or_scope",
    "source_url_or_archive_path",
    "evidence_class",
    "confidence",
    "uncertainty_range",
}
_EVIDENCE_CLASSES = {"published", "listing", "quote", "author_assumption"}


def _require_string(record: dict[str, Any], field: str) -> str:
    value = record[field]
    if not isinstance(value, str) or not value.strip():
        raise CombineScenarioError(f"source record {field} must be a non-empty string")
    return value


def _validate_date(record: dict[str, Any], field: str) -> None:
    value = _require_string(record, field)
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise CombineScenarioError(f"source record {field} must be an ISO date") from error


def _validate_source_location(record: dict[str, Any]) -> None:
    field = "source_url_or_archive_path"
    value = _require_string(record, field)
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return
    if parsed.scheme or Path(value).is_absolute() or ".." in Path(value).parts:
        raise CombineScenarioError(f"source record {field} must be an HTTP(S) URL or relative path")


def load_combine_scenarios(path: Path) -> dict[str, Any]:
    """Load scenario inputs only when every value has a complete provenance record."""
    data = json.loads(path.read_text())
    source_records = data.get("source_records")
    assumptions = data.get("numeric_assumptions")
    readiness_records = data.get("readiness_records")
    if (
        not isinstance(source_records, list)
        or not isinstance(assumptions, list)
        or not isinstance(readiness_records, list)
    ):
        raise CombineScenarioError(
            "scenario file needs source_records, numeric_assumptions, and readiness_records lists"
        )

    sources = {}
    for source in source_records:
        if not isinstance(source, dict):
            raise CombineScenarioError("source record must be an object")
        missing = _SOURCE_FIELDS - source.keys()
        if missing:
            raise CombineScenarioError(f"source record missing {sorted(missing)!r}")
        source_id = _require_string(source, "id")
        for field in ("geography", "equipment_or_scope", "confidence"):
            _require_string(source, field)
        _validate_date(source, "effective_or_as_of_date")
        _validate_date(source, "accessed_date")
        _validate_source_location(source)
        if not isinstance(source["evidence_class"], str) or source["evidence_class"] not in _EVIDENCE_CLASSES:
            raise CombineScenarioError("source record has an invalid evidence_class")
        if source_id in sources:
            raise CombineScenarioError(f"duplicate source id {source_id!r}")
        sources[source_id] = source

    for assumption in assumptions:
        if not isinstance(assumption, dict):
            raise CombineScenarioError("numeric assumption must be an object")
        missing = {"key", "value", "unit", "source_id"} - assumption.keys()
        if missing:
            raise CombineScenarioError(f"numeric assumption missing {sorted(missing)!r}")
        for field in ("key", "unit", "source_id"):
            value = assumption[field]
            if not isinstance(value, str) or not value.strip():
                raise CombineScenarioError(
                    f"numeric assumption {field} must be a non-empty string"
                )
        value = assumption["value"]
        if not isinstance(value, Real) or isinstance(value, bool) or not math.isfinite(value):
            raise CombineScenarioError("numeric assumption value must be finite")
        if assumption["source_id"] not in sources:
            raise CombineScenarioError(
                f"numeric assumption {assumption['key']!r} has unknown source_id"
            )
    for readiness in readiness_records:
        if not isinstance(readiness, dict):
            raise CombineScenarioError("readiness record must be an object")
        missing = {"id", "status", "timing_status", "source_ids", "timing_source_ids", "missing_inputs"} - readiness.keys()
        if missing:
            raise CombineScenarioError(f"readiness record missing {sorted(missing)!r}")
        for field in ("id", "status", "timing_status"):
            _require_string(readiness, field)
        for field in ("source_ids", "timing_source_ids", "missing_inputs"):
            values = readiness[field]
            if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
                raise CombineScenarioError(f"readiness record {field} must be a list of non-empty strings")
        for source_id in readiness["source_ids"] + readiness["timing_source_ids"]:
            if source_id not in sources:
                raise CombineScenarioError(f"readiness record has unknown source_id {source_id!r}")
    return data

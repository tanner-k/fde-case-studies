"""Tests for a single combine shared by corn and soybean harvest."""

import json
import math
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from engine.harvest import (
    Asset,
    CombineScenarioError,
    ContractorCommitments,
    HarvestOption,
    HarvestWindow,
    HarvestWorkload,
    acreage_crop_mix_grid,
    annual_option_cost,
    break_even_acres,
    classify_harvest_choice,
    cost_gap_usd_per_year,
    harvest_feasibility,
    harvest_workload,
    load_combine_scenarios,
)
from etl.reference import load_operations

CAPACITIES = {
    "corn": 8.909090909090908,
    "soy": 13.575757575757576,
}
SCENARIOS_PATH = Path(__file__).resolve().parent.parent / "data" / "reference" / "combine_scenarios.json"


def _window(start: date, end: date, workable_days: float) -> HarvestWindow:
    return HarvestWindow(start=start, end=end, workable_days=workable_days)


def _commitment(
    corn_window: HarvestWindow | None,
    soy_window: HarvestWindow | None,
    corn_hours: float,
    soy_hours: float,
) -> ContractorCommitments:
    return ContractorCommitments(
        corn_window,
        soy_window,
        corn_hours,
        soy_hours,
        hours_per_workable_day=4.0,
        crew_hours=corn_hours + soy_hours,
        service_scope="combine_only",
        parallel_capacity=False,
    )


def test_overlapping_crop_windows_can_fail_when_each_crop_alone_fits():
    workload = HarvestWorkload(1.0, 1.0, 6.0, 6.0, 12.0)
    corn_window = _window(date(2026, 10, 1), date(2026, 10, 2), 2.0)
    soy_window = _window(date(2026, 10, 1), date(2026, 10, 2), 2.0)

    result = harvest_feasibility(
        workload, corn_window, soy_window, 4.0, 0.0, 0.0, 20.0, None
    )

    assert result.corn.status == "infeasible"
    assert result.soy.status == "infeasible"
    assert result.hire_status == "unknown"
    assert "overlap" in result.explanation


def test_nonidentical_overlapping_owner_windows_are_unknown_without_a_sequence():
    result = harvest_feasibility(
        HarvestWorkload(1.0, 1.0, 4.0, 4.0, 8.0),
        _window(date(2026, 10, 1), date(2026, 10, 3), 3.0),
        _window(date(2026, 10, 2), date(2026, 10, 2), 1.0),
        4.0,
        0.0,
        3.0,
        20.0,
        None,
    )

    assert result.owner_status == "unknown"


def test_nonidentical_overlap_does_not_assign_workable_days_to_the_overlap():
    result = harvest_feasibility(
        HarvestWorkload(1.0, 1.0, 4.0, 4.0, 8.0),
        _window(date(2026, 10, 1), date(2026, 10, 2), 1.0),
        _window(date(2026, 10, 2), date(2026, 10, 3), 1.0),
        4.0,
        0.0,
        0.0,
        20.0,
        None,
    )

    assert result.owner_status == "unknown"


def test_disjoint_crop_windows_fit_with_one_shared_machine():
    workload = HarvestWorkload(1.0, 1.0, 6.0, 6.0, 12.0)

    result = harvest_feasibility(
        workload,
        _window(date(2026, 10, 1), date(2026, 10, 2), 2.0),
        _window(date(2026, 10, 3), date(2026, 10, 4), 2.0),
        4.0,
        0.0,
        0.0,
        20.0,
        _commitment(
            _window(date(2026, 10, 1), date(2026, 10, 2), 2.0),
            _window(date(2026, 10, 3), date(2026, 10, 4), 2.0),
            6.0,
            6.0,
        ),
    )

    assert result.corn.status == "feasible"
    assert result.soy.status == "feasible"
    assert result.owner_status == "feasible"
    assert result.hire_status == "feasible"


def test_downtime_deduction_can_flip_an_otherwise_feasible_result():
    workload = HarvestWorkload(1.0, 1.0, 3.75, 3.75, 7.5)
    corn_window = _window(date(2026, 10, 1), date(2026, 10, 1), 1.0)
    soy_window = _window(date(2026, 10, 2), date(2026, 10, 2), 1.0)

    baseline = harvest_feasibility(workload, corn_window, soy_window, 4.0, 0.0, 0.0, 20.0, None)
    result = harvest_feasibility(workload, corn_window, soy_window, 4.0, 0.25, 0.0, 20.0, None)

    assert baseline.owner_status == "feasible"
    assert result.owner_status == "infeasible"
    assert "machine" in result.explanation


def test_head_change_deduction_can_flip_an_otherwise_feasible_result():
    workload = HarvestWorkload(1.0, 1.0, 3.75, 3.75, 7.5)
    corn_window = _window(date(2026, 10, 1), date(2026, 10, 1), 1.0)
    soy_window = _window(date(2026, 10, 2), date(2026, 10, 2), 1.0)

    baseline = harvest_feasibility(workload, corn_window, soy_window, 4.0, 0.0, 0.0, 20.0, None)
    result = harvest_feasibility(workload, corn_window, soy_window, 4.0, 0.0, 1.0, 20.0, None)

    assert baseline.owner_status == "feasible"
    assert result.owner_status == "infeasible"
    assert "machine" in result.explanation


def test_head_change_labor_reduces_the_crew_harvest_budget():
    window = _window(date(2026, 10, 1), date(2026, 10, 1), 1.0)

    result = harvest_feasibility(
        HarvestWorkload(1.0, 1.0, 3.0, 3.0, 6.0),
        window,
        window,
        8.0,
        0.0,
        2.0,
        6.0,
        None,
    )

    assert result.owner_status == "infeasible"
    assert "crew" in result.explanation


def test_nested_window_is_unknown_without_an_executable_sequence():
    workload = HarvestWorkload(1.0, 1.0, 14.0, 1.0, 15.0)

    result = harvest_feasibility(
        workload,
        _window(date(2026, 10, 1), date(2026, 10, 4), 4.0),
        _window(date(2026, 10, 2), date(2026, 10, 2), 1.0),
        4.0,
        0.0,
        1.0,
        20.0,
        None,
    )

    assert result.owner_status == "unknown"


def test_nested_window_is_unknown_even_when_outer_crop_needs_both_sides():
    workload = HarvestWorkload(1.0, 1.0, 7.0, 4.0, 11.0)

    result = harvest_feasibility(
        workload,
        _window(date(2026, 10, 1), date(2026, 10, 3), 3.0),
        _window(date(2026, 10, 2), date(2026, 10, 2), 1.0),
        4.0,
        0.0,
        1.0,
        20.0,
        None,
    )

    assert result.owner_status == "unknown"


def test_nonidentical_overlap_does_not_assume_a_costly_head_change_sequence():
    result = harvest_feasibility(
        HarvestWorkload(1.0, 1.0, 5.0, 1.0, 6.0),
        _window(date(2026, 10, 1), date(2026, 10, 4), 4.0),
        _window(date(2026, 10, 2), date(2026, 10, 3), 2.0),
        4.0,
        0.0,
        6.0,
        20.0,
        None,
    )

    assert result.owner_status == "unknown"


def test_zero_crop_uses_no_crop_time_or_window():
    workload = HarvestWorkload(0.0, 1.0, 0.0, 4.0, 4.0)

    result = harvest_feasibility(
        workload,
        None,
        _window(date(2026, 10, 1), date(2026, 10, 1), 1.0),
        4.0,
        0.0,
        0.0,
        4.0,
        None,
    )

    assert result.corn.status == "feasible"
    assert result.soy.status == "feasible"
    assert result.hire_corn_status == "feasible"
    assert result.hire_soy_status == "unknown"


def test_contractor_commitment_needs_matching_dated_weather_capacity():
    workload = HarvestWorkload(1.0, 1.0, 4.0, 4.0, 8.0)
    corn_window = _window(date(2026, 10, 1), date(2026, 10, 1), 1.0)
    soy_window = _window(date(2026, 10, 2), date(2026, 10, 2), 1.0)

    result = harvest_feasibility(
        workload,
        corn_window,
        soy_window,
        4.0,
        0.0,
        0.0,
        20.0,
        _commitment(
            _window(date(2026, 10, 1), date(2026, 10, 1), 0.5), soy_window, 4.0, 4.0
        ),
    )

    assert result.hire_status == "unknown"


def test_contractor_cannot_promise_positive_hours_in_zero_workable_days():
    window = _window(date(2026, 10, 1), date(2026, 10, 1), 0.0)
    workload = HarvestWorkload(1.0, 0.0, 1.0, 0.0, 1.0)

    result = harvest_feasibility(
        workload,
        window,
        None,
        4.0,
        0.0,
        0.0,
        20.0,
        ContractorCommitments(window, None, 1.0, 0.0, 4.0, 1.0, "combine_only", False),
    )

    assert result.hire_status == "infeasible"


@pytest.mark.parametrize(
    ("workload", "corn_window", "soy_window", "commitment"),
    [
        (
            HarvestWorkload(1.0, 0.0, 4.0, 0.0, 4.0),
            _window(date(2026, 10, 1), date(2026, 10, 1), 1.0),
            None,
            _commitment(_window(date(2026, 10, 1), date(2026, 10, 1), 1.0), None, 4.0, 0.0),
        ),
        (
            HarvestWorkload(0.0, 1.0, 0.0, 4.0, 4.0),
            None,
            _window(date(2026, 10, 1), date(2026, 10, 1), 1.0),
            _commitment(None, _window(date(2026, 10, 1), date(2026, 10, 1), 1.0), 0.0, 4.0),
        ),
    ],
)
def test_single_crop_contractor_commitment_is_feasible(
    workload, corn_window, soy_window, commitment
):
    result = harvest_feasibility(
        workload, corn_window, soy_window, 4.0, 0.0, 0.0, 20.0, commitment
    )

    assert result.hire_status == "feasible"


def test_overlapping_contractor_windows_need_documented_parallel_capacity():
    window = _window(date(2026, 10, 1), date(2026, 10, 1), 1.0)
    result = harvest_feasibility(
        HarvestWorkload(1.0, 1.0, 4.0, 4.0, 8.0),
        window,
        window,
        4.0,
        0.0,
        0.0,
        20.0,
        ContractorCommitments(window, window, 4.0, 4.0, 4.0, 8.0, "combine_only", False),
    )

    assert result.hire_status == "unknown"


def test_all_zero_workload_is_feasible_without_owner_inputs():
    result = harvest_feasibility(
        HarvestWorkload(0.0, 0.0, 0.0, 0.0, 0.0),
        None,
        None,
        None,
        0.0,
        0.0,
        None,
        None,
    )

    assert result.owner_status == "feasible"
    assert result.hire_status == "feasible"
    assert result.usable_machine_hours == 0.0


@pytest.mark.parametrize(
    ("hours_per_workable_day", "downtime_days", "head_change_hours", "crew_hours"),
    [(-1.0, 0.0, 0.0, 1.0), (1.0, -1.0, 0.0, 1.0), (1.0, 0.0, -1.0, 1.0), (1.0, 0.0, 0.0, -1.0)],
)
def test_negative_timing_inputs_are_rejected(
    hours_per_workable_day, downtime_days, head_change_hours, crew_hours
):
    with pytest.raises(ValueError, match="finite and non-negative"):
        harvest_feasibility(
            HarvestWorkload(1.0, 0.0, 1.0, 0.0, 1.0),
            _window(date(2026, 10, 1), date(2026, 10, 1), 1.0),
            None,
            hours_per_workable_day,
            downtime_days,
            head_change_hours,
            crew_hours,
            None,
        )


def test_timing_rejects_downtime_that_makes_machine_time_negative():
    with pytest.raises(ValueError, match="available machine time cannot be negative"):
        harvest_feasibility(
            HarvestWorkload(1.0, 1.0, 1.0, 1.0, 2.0),
            _window(date(2026, 10, 1), date(2026, 10, 1), 1.0),
            _window(date(2026, 10, 2), date(2026, 10, 2), 1.0),
            4.0,
            3.0,
            0.0,
            20.0,
            None,
        )


def test_missing_owner_inputs_and_contractor_commitment_are_unknown():
    workload = HarvestWorkload(1.0, 1.0, 1.0, 1.0, 2.0)

    result = harvest_feasibility(workload, None, None, None, 0.0, 0.0, None, None)

    assert result.corn.status == "unknown"
    assert result.soy.status == "unknown"
    assert result.owner_status == "unknown"
    assert result.hire_status == "unknown"


def test_shared_combine_workload_at_the_2400_acre_anchor():
    workload = harvest_workload(2_400, 0.5, CAPACITIES["corn"], CAPACITIES["soy"])

    assert workload.corn_acres == 1_200
    assert workload.soy_acres == 1_200
    assert workload.corn_hours == pytest.approx(134.6938775510)
    assert workload.soy_hours == pytest.approx(88.3928571429)
    assert workload.base_combine_hours == pytest.approx(223.0867346939)


@pytest.mark.parametrize(
    ("total_acres", "expected_hours"),
    [(500, 46.4764030612), (10_000, 929.5280612245)],
)
def test_shared_combine_hours_scale_with_total_acres(total_acres, expected_hours):
    workload = harvest_workload(total_acres, 0.5, CAPACITIES["corn"], CAPACITIES["soy"])

    assert workload.base_combine_hours == pytest.approx(expected_hours)


@pytest.mark.parametrize(
    ("corn_share", "expected_corn_hours", "expected_soy_hours"),
    [(1.0, 269.3877551020, 0.0), (0.0, 0.0, 176.7857142857)],
)
def test_all_one_crop_has_no_hours_for_the_other_crop(
    corn_share, expected_corn_hours, expected_soy_hours
):
    workload = harvest_workload(2_400, corn_share, CAPACITIES["corn"], CAPACITIES["soy"])

    assert workload.corn_hours == pytest.approx(expected_corn_hours)
    assert workload.soy_hours == pytest.approx(expected_soy_hours)


@pytest.mark.parametrize("total_acres", [-1.0, -0.01])
def test_negative_total_acres_are_rejected(total_acres):
    with pytest.raises(ValueError, match="total_acres must be non-negative"):
        harvest_workload(total_acres, 0.5, CAPACITIES["corn"], CAPACITIES["soy"])


@pytest.mark.parametrize("corn_share", [-0.01, 1.01])
def test_crop_share_outside_zero_to_one_is_rejected(corn_share):
    with pytest.raises(ValueError, match="corn_share must be between 0 and 1"):
        harvest_workload(2_400, corn_share, CAPACITIES["corn"], CAPACITIES["soy"])


@pytest.mark.parametrize("capacity", [0.0, -1.0])
def test_nonpositive_crop_capacity_is_rejected(capacity):
    with pytest.raises(ValueError, match="capacity must be positive"):
        harvest_workload(2_400, 0.5, capacity, CAPACITIES["soy"])


def test_scenario_file_has_provenance_for_every_input():
    scenarios = load_combine_scenarios(SCENARIOS_PATH)

    assert scenarios["numeric_assumptions"]
    assert scenarios["source_records"]


def test_scenario_loader_rejects_an_input_without_provenance(tmp_path):
    scenarios = json.loads(SCENARIOS_PATH.read_text())
    scenarios["numeric_assumptions"][0].pop("source_id")
    path = tmp_path / "combine_scenarios.json"
    path.write_text(json.dumps(scenarios))

    with pytest.raises(CombineScenarioError, match="source_id"):
        load_combine_scenarios(path)


def test_scenario_loader_requires_source_confidence(tmp_path):
    scenarios = json.loads(SCENARIOS_PATH.read_text())
    scenarios["source_records"][0].pop("confidence")
    path = tmp_path / "combine_scenarios.json"
    path.write_text(json.dumps(scenarios))

    with pytest.raises(CombineScenarioError, match="confidence"):
        load_combine_scenarios(path)


def test_scenario_loader_requires_readiness_timing_sources_to_resolve(tmp_path):
    scenarios = json.loads(SCENARIOS_PATH.read_text())
    scenarios["readiness_records"][0]["timing_source_ids"] = ["missing_timing_source"]
    path = tmp_path / "combine_scenarios.json"
    path.write_text(json.dumps(scenarios))

    with pytest.raises(CombineScenarioError, match="missing_timing_source"):
        load_combine_scenarios(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", ""),
        ("id", None),
        ("id", 1),
        ("geography", ""),
        ("equipment_or_scope", None),
        ("source_url_or_archive_path", ""),
        ("source_url_or_archive_path", 1),
    ],
)
def test_scenario_loader_rejects_missing_or_invalid_source_provenance(field, value, tmp_path):
    scenarios = json.loads(SCENARIOS_PATH.read_text())
    scenarios["source_records"][0][field] = value
    path = tmp_path / "combine_scenarios.json"
    path.write_text(json.dumps(scenarios))

    with pytest.raises(CombineScenarioError, match=field):
        load_combine_scenarios(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("effective_or_as_of_date", "2026"),
        ("accessed_date", "2026-13-40"),
        ("source_url_or_archive_path", "../outside.json"),
    ],
)
def test_scenario_loader_rejects_invalid_source_date_or_path(field, value, tmp_path):
    scenarios = json.loads(SCENARIOS_PATH.read_text())
    scenarios["source_records"][0][field] = value
    path = tmp_path / "combine_scenarios.json"
    path.write_text(json.dumps(scenarios))

    with pytest.raises(CombineScenarioError, match=field):
        load_combine_scenarios(path)


def test_scenario_loader_rejects_duplicate_source_ids(tmp_path):
    scenarios = json.loads(SCENARIOS_PATH.read_text())
    scenarios["source_records"][1]["id"] = scenarios["source_records"][0]["id"]
    path = tmp_path / "combine_scenarios.json"
    path.write_text(json.dumps(scenarios))

    with pytest.raises(CombineScenarioError, match="duplicate source id"):
        load_combine_scenarios(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("value", "not-a-number"),
        ("value", math.nan),
        ("value", True),
        ("unit", ""),
        ("unit", None),
        ("unit", 1),
    ],
)
def test_scenario_loader_rejects_invalid_numeric_assumption(field, value, tmp_path):
    scenarios = json.loads(SCENARIOS_PATH.read_text())
    scenarios["numeric_assumptions"][0][field] = value
    path = tmp_path / "combine_scenarios.json"
    path.write_text(json.dumps(scenarios))

    with pytest.raises(CombineScenarioError, match=field):
        load_combine_scenarios(path)


def test_scenario_workload_benchmarks_reconcile_to_live_operation_capacities():
    scenarios = load_combine_scenarios(SCENARIOS_PATH)
    assumptions = {row["key"]: row["value"] for row in scenarios["numeric_assumptions"]}
    operations = {operation.key: operation for operation in load_operations()}
    corn_capacity = operations["corn_combine"].field_capacity_acres_per_hour
    soy_capacity = operations["soybean_combine"].field_capacity_acres_per_hour

    assert assumptions["corn_capacity"] == corn_capacity
    assert assumptions["soy_capacity"] == soy_capacity

    workload = harvest_workload(
        assumptions["anchor_total_acres"],
        assumptions["corn_share"],
        corn_capacity,
        soy_capacity,
    )
    assert workload.corn_acres == assumptions["benchmark_corn_acres"]
    assert workload.soy_acres == assumptions["benchmark_soy_acres"]
    assert workload.corn_hours == pytest.approx(assumptions["benchmark_corn_hours"])
    assert workload.soy_hours == pytest.approx(assumptions["benchmark_soy_hours"])
    assert workload.base_combine_hours == pytest.approx(assumptions["benchmark_base_combine_hours"])


@pytest.mark.parametrize(
    ("total_acres", "corn_share", "corn_capacity", "soy_capacity"),
    [
        (math.nan, 0.5, CAPACITIES["corn"], CAPACITIES["soy"]),
        (math.inf, 0.5, CAPACITIES["corn"], CAPACITIES["soy"]),
        (2_400, math.nan, CAPACITIES["corn"], CAPACITIES["soy"]),
        (2_400, math.inf, CAPACITIES["corn"], CAPACITIES["soy"]),
        (2_400, 0.5, math.nan, CAPACITIES["soy"]),
        (2_400, 0.5, CAPACITIES["corn"], math.inf),
    ],
)
def test_nonfinite_workload_inputs_are_rejected(
    total_acres, corn_share, corn_capacity, soy_capacity
):
    with pytest.raises(ValueError, match="must be finite"):
        harvest_workload(total_acres, corn_share, corn_capacity, soy_capacity)


def _asset(
    purchase_usd: float,
    resale_usd: float,
    *,
    starting_hours: float = 0.0,
    list_price_usd: float | None = None,
    repair_rc1: float = 0.0,
    repair_rc2: float = 1.0,
    starting_age_years: float = 0.0,
    annual_hours: float = 0.0,
    horizon_years: int = 2,
    meter_convention: str = "productive_machine_hours",
    wearout_hours: float = 10_000.0,
) -> Asset:
    return Asset(
        purchase_usd=purchase_usd,
        terminal_resale_usd=resale_usd,
        starting_hours=starting_hours,
        list_price_usd=list_price_usd or purchase_usd,
        repair_rc1=repair_rc1,
        repair_rc2=repair_rc2,
        starting_age_years=starting_age_years,
        terminal_age_years=starting_age_years + horizon_years,
        terminal_hours=starting_hours + annual_hours * horizon_years,
        meter_convention=meter_convention,
        wearout_hours=wearout_hours,
        terminal_resale_source="synthetic terminal resale assumption",
    )


def _owner_option(
    *,
    base_hours: float,
    corn_head_hours: float,
    draper_head_hours: float,
    scope: str = "combine_only",
    horizon_years: int = 2,
) -> HarvestOption:
    return HarvestOption(
        kind="own",
        horizon_years=horizon_years,
        service_scope=scope,
        base=_asset(100.0, 40.0, annual_hours=base_hours, horizon_years=horizon_years),
        corn_head=_asset(200.0, 80.0, annual_hours=corn_head_hours, horizon_years=horizon_years),
        draper_head=_asset(300.0, 120.0, annual_hours=draper_head_hours, horizon_years=horizon_years),
        fuel_gallons_per_base_hour=2.0,
        fuel_usd_per_gallon=3.0,
        lubrication_fraction_of_fuel=0.1,
        labor_hours_per_base_hour=1.5,
        labor_usd_per_hour=20.0,
        annual_insurance_tax_storage_usd=50.0,
        annual_equivalent_services_usd=0.0,
    )


def test_owner_cost_counts_shared_base_once_and_each_head_once():
    workload = HarvestWorkload(10.0, 20.0, 4.0, 6.0, 10.0)

    result = annual_option_cost(
        workload, _owner_option(base_hours=10.0, corn_head_hours=4.0, draper_head_hours=6.0), rate=0.0
    )

    assert result.base_capital_usd_per_year == pytest.approx(30.0)
    assert result.corn_head_capital_usd_per_year == pytest.approx(60.0)
    assert result.draper_head_capital_usd_per_year == pytest.approx(90.0)
    assert result.fuel_lube_usd_per_year == pytest.approx(66.0)
    assert result.labor_usd_per_year == pytest.approx(300.0)
    assert result.insurance_tax_storage_usd_per_year == pytest.approx(50.0)
    assert result.total_usd_per_year == pytest.approx(596.0)


def test_owner_repairs_are_year_by_year_incremental_and_unused_draper_has_no_use_repairs():
    workload = HarvestWorkload(10.0, 0.0, 10.0, 0.0, 10.0)
    option = HarvestOption(
        kind="own",
        horizon_years=2,
        service_scope="combine_only",
        base=_asset(0.0, 0.0, starting_hours=1_000.0, list_price_usd=1_000.0, repair_rc1=1.0, repair_rc2=2.0, annual_hours=10.0),
        corn_head=_asset(0.0, 0.0, list_price_usd=2_000.0, repair_rc1=1.0, repair_rc2=2.0, annual_hours=10.0),
        draper_head=_asset(300.0, 100.0, list_price_usd=3_000.0, repair_rc1=1.0, repair_rc2=2.0),
        fuel_gallons_per_base_hour=0.0,
        fuel_usd_per_gallon=0.0,
        lubrication_fraction_of_fuel=0.0,
        labor_hours_per_base_hour=0.0,
        labor_usd_per_hour=0.0,
        annual_insurance_tax_storage_usd=0.0,
        annual_equivalent_services_usd=0.0,
    )

    result = annual_option_cost(workload, option, rate=0.0)

    # Base: R(1,020)-R(1,000) = 40.4 over two years; corn head: R(20)=0.8.
    assert result.repairs_usd_per_year == pytest.approx(20.6)
    assert result.draper_head_capital_usd_per_year == pytest.approx(100.0)


def test_survey_hire_baseline_and_draper_sensitivity_have_no_owner_add_ons():
    workload = HarvestWorkload(1_200.0, 1_200.0, 1.0, 1.0, 2.0)
    baseline = HarvestOption(
        kind="hire",
        horizon_years=1,
        service_scope="combine_only",
        corn_hire_usd_per_acre=46.05,
        soy_hire_usd_per_acre=43.05,
    )
    draper = HarvestOption(
        kind="hire",
        horizon_years=1,
        service_scope="combine_only",
        corn_hire_usd_per_acre=46.05,
        soy_hire_usd_per_acre=48.20,
    )

    assert annual_option_cost(workload, baseline, rate=0.07).hired_harvest_usd_per_year == pytest.approx(106_920.0)
    assert annual_option_cost(workload, draper, rate=0.07).total_usd_per_year == pytest.approx(113_100.0)


def test_cost_gap_requires_matching_scope():
    workload = HarvestWorkload(1.0, 1.0, 1.0, 1.0, 2.0)
    own = annual_option_cost(
        workload, _owner_option(base_hours=2.0, corn_head_hours=1.0, draper_head_hours=1.0, scope="combine_only"), rate=0.0
    )
    hire = annual_option_cost(
        workload,
        HarvestOption(
            kind="hire",
            horizon_years=2,
            service_scope="complete_harvest",
            corn_hire_usd_per_acre=1.0,
            soy_hire_usd_per_acre=1.0,
        ),
        rate=0.0,
    )

    assert cost_gap_usd_per_year(own, hire) is None


def test_cost_gap_requires_matching_horizon():
    workload = HarvestWorkload(1.0, 1.0, 1.0, 1.0, 2.0)
    own = annual_option_cost(
        workload, _owner_option(base_hours=2.0, corn_head_hours=1.0, draper_head_hours=1.0), rate=0.0
    )
    hire = annual_option_cost(
        workload,
        HarvestOption(
            kind="hire",
            horizon_years=1,
            service_scope="combine_only",
            corn_hire_usd_per_acre=1.0,
            soy_hire_usd_per_acre=1.0,
        ),
        rate=0.0,
    )

    assert cost_gap_usd_per_year(own, hire) is None


def test_discounted_capital_and_repair_eac_match_explicit_cashflows():
    workload = HarvestWorkload(0.0, 0.0, 10.0, 0.0, 10.0)
    asset = _asset(1_000.0, 200.0, list_price_usd=1_000.0, repair_rc1=1.0, repair_rc2=2.0, annual_hours=10.0)
    option = HarvestOption(
        kind="own",
        horizon_years=2,
        service_scope="combine_only",
        base=asset,
        corn_head=_asset(0.0, 0.0, annual_hours=10.0),
        draper_head=_asset(0.0, 0.0),
        fuel_gallons_per_base_hour=0.0,
        fuel_usd_per_gallon=0.0,
        lubrication_fraction_of_fuel=0.0,
        labor_hours_per_base_hour=0.0,
        labor_usd_per_hour=0.0,
        annual_insurance_tax_storage_usd=0.0,
        annual_equivalent_services_usd=0.0,
    )
    rate = 0.10
    factor = 1 / 1.1 + 1 / 1.1**2

    result = annual_option_cost(workload, option, rate)

    assert result.base_capital_usd_per_year == pytest.approx((1_000.0 - 200.0 / 1.1**2) / factor)
    assert result.repairs_usd_per_year == pytest.approx((0.1 / 1.1 + 0.3 / 1.1**2) / factor)


def test_cost_gap_requires_the_same_workload_and_is_positive_when_owner_costs_more():
    workload = HarvestWorkload(1.0, 1.0, 1.0, 1.0, 2.0)
    own = annual_option_cost(
        workload, _owner_option(base_hours=2.0, corn_head_hours=1.0, draper_head_hours=1.0), rate=0.0
    )
    hire = annual_option_cost(
        workload,
        HarvestOption(
            kind="hire",
            horizon_years=2,
            service_scope="combine_only",
            corn_hire_usd_per_acre=1.0,
            soy_hire_usd_per_acre=1.0,
        ),
        rate=0.0,
    )
    other_workload_hire = annual_option_cost(
        HarvestWorkload(2.0, 1.0, 2.0, 1.0, 3.0),
        HarvestOption(
            kind="hire",
            horizon_years=2,
            service_scope="combine_only",
            corn_hire_usd_per_acre=1.0,
            soy_hire_usd_per_acre=1.0,
        ),
        rate=0.0,
    )

    assert cost_gap_usd_per_year(own, hire) == pytest.approx(301.2)
    assert cost_gap_usd_per_year(own, other_workload_hire) is None


def test_owner_option_rejects_implicit_operating_costs():
    workload = HarvestWorkload(1.0, 1.0, 1.0, 1.0, 2.0)
    option = replace(
        _owner_option(base_hours=2.0, corn_head_hours=1.0, draper_head_hours=1.0),
        fuel_usd_per_gallon=None,
    )

    with pytest.raises(ValueError, match="fuel_usd_per_gallon must be explicit"):
        annual_option_cost(workload, option, rate=0.0)


def test_used_asset_repairs_exceed_new_asset_repairs_for_equal_future_hours():
    workload = HarvestWorkload(10.0, 0.0, 10.0, 0.0, 10.0)
    common = dict(
        kind="own",
        horizon_years=2,
        service_scope="combine_only",
        corn_head=_asset(0.0, 0.0, annual_hours=10.0),
        draper_head=_asset(0.0, 0.0),
        fuel_gallons_per_base_hour=0.0,
        fuel_usd_per_gallon=0.0,
        lubrication_fraction_of_fuel=0.0,
        labor_hours_per_base_hour=0.0,
        labor_usd_per_hour=0.0,
        annual_insurance_tax_storage_usd=0.0,
        annual_equivalent_services_usd=0.0,
    )
    new = HarvestOption(
        base=_asset(0.0, 0.0, list_price_usd=1_000.0, repair_rc1=1.0, repair_rc2=2.0, annual_hours=10.0),
        **common,
    )
    used = HarvestOption(
        base=_asset(0.0, 0.0, starting_hours=1_000.0, starting_age_years=5.0, list_price_usd=1_000.0, repair_rc1=1.0, repair_rc2=2.0, annual_hours=10.0),
        **common,
    )

    assert annual_option_cost(workload, used, rate=0.0).repairs_usd_per_year > annual_option_cost(workload, new, rate=0.0).repairs_usd_per_year


def test_sourced_terminal_resale_must_stay_within_wearout_and_match_horizon():
    workload = HarvestWorkload(10.0, 0.0, 10.0, 0.0, 10.0)
    option = _owner_option(base_hours=10.0, corn_head_hours=10.0, draper_head_hours=0.0)
    beyond_wearout = replace(option, base=replace(option.base, wearout_hours=15.0))
    inconsistent_terminal = replace(option, base=replace(option.base, terminal_hours=19.0))

    with pytest.raises(ValueError, match="wearout_hours"):
        annual_option_cost(workload, beyond_wearout, rate=0.0)
    with pytest.raises(ValueError, match="terminal_hours"):
        annual_option_cost(workload, inconsistent_terminal, rate=0.0)


def test_terminal_resale_requires_a_source_and_productive_hour_meter():
    workload = HarvestWorkload(10.0, 0.0, 10.0, 0.0, 10.0)
    option = _owner_option(base_hours=10.0, corn_head_hours=10.0, draper_head_hours=0.0)
    unsourced_resale = replace(option, base=replace(option.base, terminal_resale_source=""))
    engine_hour_meter = replace(option, base=replace(option.base, meter_convention="engine_hours"))

    with pytest.raises(ValueError, match="terminal_resale_source"):
        annual_option_cost(workload, unsourced_resale, rate=0.0)
    with pytest.raises(ValueError, match="productive_machine_hours"):
        annual_option_cost(workload, engine_hour_meter, rate=0.0)


def test_sourced_resale_cannot_bypass_terminal_horizon_or_wearout_checks():
    workload = HarvestWorkload(10.0, 0.0, 10.0, 0.0, 10.0)
    option = _owner_option(base_hours=10.0, corn_head_hours=10.0, draper_head_hours=0.0)
    mismatched = replace(option, base=replace(option.base, terminal_hours=0.0))
    beyond_wearout = replace(option, base=replace(option.base, wearout_hours=15.0))

    with pytest.raises(ValueError, match="terminal_hours"):
        annual_option_cost(workload, mismatched, rate=0.0)
    with pytest.raises(ValueError, match="wearout_hours"):
        annual_option_cost(workload, beyond_wearout, rate=0.0)


def test_horizon_sensitivity_changes_owner_eac_with_a_common_workload():
    workload = HarvestWorkload(1.0, 1.0, 1.0, 1.0, 2.0)
    one_year = annual_option_cost(
        workload,
        _owner_option(base_hours=2.0, corn_head_hours=1.0, draper_head_hours=1.0, horizon_years=1),
        rate=0.0,
    )
    three_year = annual_option_cost(
        workload,
        _owner_option(base_hours=2.0, corn_head_hours=1.0, draper_head_hours=1.0, horizon_years=3),
        rate=0.0,
    )

    assert one_year.total_usd_per_year > three_year.total_usd_per_year


def test_break_even_interpolates_one_synthetic_cost_crossing_inside_the_grid():
    result = break_even_acres(
        [1_000.0, 1_500.0, 2_000.0],
        lambda acres: acres - 1_250.0,
    )

    assert result.status == "crossing"
    assert result.acres == pytest.approx(1_250.0)


def test_break_even_bisects_a_nonlinear_synthetic_cost_crossing():
    result = break_even_acres(
        [1_000.0, 1_500.0, 2_000.0],
        lambda acres: (acres - 1_234.5) ** 3,
    )

    assert result.status == "crossing"
    assert result.acres == pytest.approx(1_234.5, abs=1e-6)


def test_break_even_reports_nonconvergence_when_the_iteration_limit_is_exhausted():
    result = break_even_acres(
        [0.0, 1_000.0],
        lambda acres: acres - 900.0,
        max_iterations=1,
    )

    assert result.status == "nonconvergent"
    assert result.acres is None


def test_break_even_reports_none_when_a_synthetic_gap_never_changes_sign():
    result = break_even_acres([1_000.0, 1_500.0, 2_000.0], lambda acres: acres + 1.0)

    assert result.status == "none_in_range"
    assert result.acres is None


def test_break_even_reports_multiple_sampled_crossings():
    result = break_even_acres(
        [1_000.0, 1_500.0, 2_000.0, 2_500.0],
        lambda acres: (acres - 1_250.0) * (acres - 2_250.0),
    )

    assert result.status == "multiple_crossings"
    assert result.acres is None


def test_break_even_reports_an_isolated_sampled_cost_tie_as_a_single_root():
    result = break_even_acres([1_000.0, 1_500.0, 2_000.0], lambda acres: acres - 1_500.0)

    assert result.status == "crossing"
    assert result.acres == 1_500.0


def test_break_even_reports_a_flat_sampled_tie_interval_without_picking_a_root():
    result = break_even_acres(
        [1_000.0, 1_500.0, 2_000.0],
        lambda acres: 0.0 if 1_000.0 <= acres <= 1_500.0 else 1.0,
    )

    assert result.status == "tie"
    assert result.acres is None


def test_choice_classifier_requires_a_feasible_timing_and_separated_cost_bounds():
    result = classify_harvest_choice(
        new_own_cost=(100.0, 110.0),
        used_own_cost=(120.0, 130.0),
        hire_both_cost=(140.0, 150.0),
        new_own_timing="feasible",
        used_own_timing="feasible",
        hire_both_timing="feasible",
    )

    assert result.choice == "new"


def test_choice_classifier_never_picks_a_low_cost_owner_when_timing_fails():
    result = classify_harvest_choice(
        new_own_cost=(100.0, 110.0),
        used_own_cost=(120.0, 130.0),
        hire_both_cost=(140.0, 150.0),
        new_own_timing="infeasible",
        used_own_timing="infeasible",
        hire_both_timing="feasible",
    )

    assert result.choice == "hire"


def test_choice_classifier_is_indeterminate_without_a_contractor_commitment():
    result = classify_harvest_choice(
        new_own_cost=(140.0, 150.0),
        used_own_cost=(130.0, 140.0),
        hire_both_cost=(100.0, 110.0),
        new_own_timing="feasible",
        used_own_timing="feasible",
        hire_both_timing="unknown",
    )

    assert result.choice == "indeterminate"


def test_choice_classifier_is_indeterminate_for_overlapping_uncertainty_ranges():
    result = classify_harvest_choice(
        new_own_cost=(100.0, 130.0),
        used_own_cost=(120.0, 140.0),
        hire_both_cost=(150.0, 160.0),
        new_own_timing="feasible",
        used_own_timing="feasible",
        hire_both_timing="feasible",
    )

    assert result.choice == "indeterminate"


def test_choice_classifier_reports_infeasible_when_all_three_options_fail_timing():
    result = classify_harvest_choice(
        new_own_cost=(100.0, 110.0),
        used_own_cost=(120.0, 130.0),
        hire_both_cost=(140.0, 150.0),
        new_own_timing="infeasible",
        used_own_timing="infeasible",
        hire_both_timing="infeasible",
    )

    assert result.choice == "infeasible"


def test_choice_classifier_ignores_missing_cost_for_an_infeasible_option():
    result = classify_harvest_choice(
        new_own_cost=None,
        used_own_cost=(120.0, 130.0),
        hire_both_cost=(140.0, 150.0),
        new_own_timing="infeasible",
        used_own_timing="feasible",
        hire_both_timing="feasible",
    )

    assert result.choice == "used"


def test_acreage_crop_mix_grid_keeps_each_crop_mix_case_separate():
    grid = acreage_crop_mix_grid(
        [500.0, 1_000.0],
        [0.25, 0.75],
        lambda acres, corn_share: f"{acres}:{corn_share}",
    )

    assert grid == {
        (500.0, 0.25): "500.0:0.25",
        (500.0, 0.75): "500.0:0.75",
        (1_000.0, 0.25): "1000.0:0.25",
        (1_000.0, 0.75): "1000.0:0.75",
    }

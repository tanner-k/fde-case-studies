"""Render evidence-gated shared-combine exhibits and the annual survey table.

This exhibit is deliberately limited to productive machine hours.  Crop
windows remain unknown until dated evidence is added; the 200-hour line is a
descriptive author cut and does not represent a cost break-even.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from engine.harvest import harvest_workload, load_combine_scenarios
from etl.reference import load_operations

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "deliverables" / "figures" / "combine-shared-use.png"
DECISION_MAP_PATH = ROOT / "deliverables" / "figures" / "combine-decision-map.png"
OPTIONS_PATH = ROOT / "deliverables" / "tables" / "combine-options.csv"
SCENARIOS_PATH = ROOT / "data" / "reference" / "combine_scenarios.json"
FARM_SIZES = (500.0, 2_400.0, 10_000.0)

# These are dated statewide survey averages.  They are deliberately separate
# cases because soybean-with-draper service is a different survey line, not a
# local bid or an ownership-cost input.
SURVEY_CASES = (
    {
        "case_id": "hire_generic_survey_2026",
        "option": "hire_both",
        "label": "Hire survey baseline — generic combine-only",
        "corn_rate": 46.05,
        "soy_rate": 43.05,
        "corn_rate_range": "$25-$80 per acre survey range",
        "soy_rate_range": "$24-$70 per acre survey range",
        "annual_cost_range": "$58,800-$180,000/year from published crop-rate ranges; not a local quote",
        "corn_source_id": "a3_10_corn_combine_only_2026",
        "soy_source_id": "a3_10_soy_combine_only_2026",
    },
    {
        "case_id": "hire_draper_service_survey_2026",
        "option": "hire_both",
        "label": "Hire survey baseline — soybean draper service",
        "corn_rate": 46.05,
        "soy_rate": 48.20,
        "corn_rate_range": "$25-$80 per acre survey range",
        "soy_rate_range": "$24-$80 per acre survey range",
        "annual_cost_range": "$58,800-$192,000/year from published crop-rate ranges; not a local quote",
        "corn_source_id": "a3_10_corn_combine_only_2026",
        "soy_source_id": "a3_10_soy_draper_service_2026",
    },
)


def _anchor_workload():
    """Use the exact capacities from the curated operations data."""
    operations = {operation.key: operation for operation in load_operations()}
    return harvest_workload(
        2_400.0,
        0.5,
        operations["corn_combine"].field_capacity_acres_per_hour,
        operations["soybean_combine"].field_capacity_acres_per_hour,
    )


def write_options_table() -> list[dict[str, object]]:
    """Write the anchor table without turning missing ownership inputs into zero."""
    scenarios = load_combine_scenarios(SCENARIOS_PATH)
    readiness = {record["id"]: record for record in scenarios["readiness_records"]}
    workload = _anchor_workload()
    rows: list[dict[str, object]] = []
    common = {
        "total_farm_acres": workload.corn_acres + workload.soy_acres,
        "corn_acres": workload.corn_acres,
        "soy_acres": workload.soy_acres,
        "corn_hours": workload.corn_hours,
        "soy_hours": workload.soy_hours,
        "base_combine_hours": workload.base_combine_hours,
        "year_basis": "2026",
        "currency_basis": "nominal USD",
        "service_scope": "combine harvest only; excludes grain cart, hauling/trucking, and drying",
        "local_quote": "no",
        "timing_status": "unknown",
        "classification": "indeterminate",
    }
    for case in SURVEY_CASES:
        corn = workload.corn_acres * case["corn_rate"]
        soy = workload.soy_acres * case["soy_rate"]
        rows.append(
            common
            | {
                "case_id": case["case_id"],
                "option": case["option"],
                "label": case["label"],
                "base_capital_usd_per_year": "",
                "corn_head_capital_usd_per_year": "",
                "draper_head_capital_usd_per_year": "",
                "fuel_lube_usd_per_year": "",
                "repairs_usd_per_year": "",
                "labor_usd_per_year": "",
                "insurance_tax_storage_usd_per_year": "",
                "equivalent_services_usd_per_year": "",
                "corn_hire_rate_usd_per_crop_acre": case["corn_rate"],
                "soy_hire_rate_usd_per_crop_acre": case["soy_rate"],
                "corn_hire_rate_uncertainty_range": case["corn_rate_range"],
                "soy_hire_rate_uncertainty_range": case["soy_rate_range"],
                "corn_hire_usd_per_year": corn,
                "soy_hire_usd_per_year": soy,
                "annual_cost_usd_per_year": corn + soy,
                "annual_cost_uncertainty_range_usd_per_year": case["annual_cost_range"],
                "cost_status": "survey baseline; not a local quote",
                "provenance_ids": f"{case['corn_source_id']};{case['soy_source_id']};timing_research_gate_2026",
                "missing_inputs": "; ".join(readiness["hire_both"]["missing_inputs"]),
            }
        )
    for option in ("new_own", "used_own"):
        record = readiness[option]
        rows.append(
            common
            | {
                "case_id": option,
                "option": option,
                "label": "New ownership input gap" if option == "new_own" else "Used ownership input gap",
                "base_capital_usd_per_year": "",
                "corn_head_capital_usd_per_year": "",
                "draper_head_capital_usd_per_year": "",
                "fuel_lube_usd_per_year": "",
                "repairs_usd_per_year": "",
                "labor_usd_per_year": "",
                "insurance_tax_storage_usd_per_year": "",
                "equivalent_services_usd_per_year": "",
                "corn_hire_rate_usd_per_crop_acre": "",
                "soy_hire_rate_usd_per_crop_acre": "",
                "corn_hire_rate_uncertainty_range": "unknown",
                "soy_hire_rate_uncertainty_range": "unknown",
                "corn_hire_usd_per_year": "",
                "soy_hire_usd_per_year": "",
                "annual_cost_usd_per_year": "",
                "annual_cost_uncertainty_range_usd_per_year": "unknown",
                "cost_status": "indeterminate: no supported annual ownership cost",
                "provenance_ids": ";".join(record["source_ids"] + record["timing_source_ids"]),
                "missing_inputs": "; ".join(record["missing_inputs"]),
            }
        )
    OPTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OPTIONS_PATH.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def build_decision_map(rows: list[dict[str, object]]) -> matplotlib.figure.Figure:
    """Show the evidence gate across acreage and mix; no unsupported regions exist."""
    figure, (map_axis, cost_axis) = plt.subplots(1, 2, figsize=(12, 5.6), gridspec_kw={"width_ratios": (1.35, 1)})
    # Every cell is indeterminate because ownership costs and timing inputs are
    # missing for all acreage/mix cases.  A single neutral category makes that
    # gate visible without manufacturing a cost comparison.
    map_axis.imshow([[0] * 11 for _ in range(11)], origin="lower", aspect="auto", cmap=matplotlib.colors.ListedColormap(["#d9d9d9"]), extent=(500, 10_000, 0, 100))
    map_axis.set_xlabel("total farm acres")
    map_axis.set_ylabel("corn share of total acres (%)")
    map_axis.set_title("Choice status by acreage and crop mix")
    map_axis.text(5_250, 50, "ALL CASES: INDETERMINATE\nannual ownership inputs absent;\ntiming unknown", ha="center", va="center", fontsize=10, weight="bold")
    map_axis.plot([500, 2_400, 10_000], [50, 50, 50], "o", color="#555555", markersize=4)
    map_axis.annotate("2,400 acres / 50% corn", (2_400, 50), xytext=(3_100, 15), arrowprops={"arrowstyle": "-", "color": "#555555"}, fontsize=8)
    map_axis.set_yticks(range(0, 101, 20))
    map_axis.set_xlim(500, 10_000)
    map_axis.set_xticks([500, 2_400, 10_000], ["500", "2,400", "10,000"])
    map_axis.grid(alpha=0.15)
    map_axis.legend([Patch(facecolor="#d9d9d9")], ["indeterminate — do not infer a winner"], loc="lower right", frameon=False, fontsize=8)

    survey_rows = [row for row in rows if row["option"] == "hire_both"]
    values = [float(row["annual_cost_usd_per_year"]) for row in survey_rows]
    labels = ["Hire\ngeneric", "Hire\ndraper service"]
    cost_axis.bar(labels, values, color=["#5b8db8", "#3d6f9e"])
    for index, value in enumerate(values):
        cost_axis.text(index, value + 2_500, f"${value:,.0f}", ha="center", fontsize=10)
    cost_axis.set_ylabel("nominal 2026 USD/year")
    cost_axis.set_title("2,400 acres: sourced annual survey baselines")
    cost_axis.set_ylim(0, max(values) * 1.25)
    cost_axis.grid(axis="y", alpha=0.18)
    cost_axis.text(0.5, 0.95, "New / used ownership: indeterminate\n(no annual cost; timing unknown)\nNo local quote.", transform=cost_axis.transAxes, ha="center", va="top", fontsize=8, color="#555555")
    figure.suptitle("Dual-use combine decision map is evidence-gated", fontsize=13)
    figure.text(0.5, 0.01, "Survey baselines use A3-10 crop-specific averages; the generic and draper-service soybean lines are separately labeled. No purchase price, repair/resale range, crop window, or contractor commitment is available to establish a feasible winner.", ha="center", fontsize=8, color="#555555", wrap=True)
    figure.tight_layout(rect=(0, 0.06, 1, 0.93))
    return figure


def build_figure() -> matplotlib.figure.Figure:
    """Build the crop-only and shared-base hours exhibit."""
    operations = {operation.key: operation for operation in load_operations()}
    corn_capacity = operations["corn_combine"].field_capacity_acres_per_hour
    soy_capacity = operations["soybean_combine"].field_capacity_acres_per_hour
    workloads = [
        harvest_workload(acres, 0.5, corn_capacity, soy_capacity)
        for acres in FARM_SIZES
    ]

    figure, (hours_axis, windows_axis) = plt.subplots(
        1, 2, figsize=(11.5, 5.4), gridspec_kw={"width_ratios": (2.4, 1.1)}
    )
    labels = [f"{acres:,.0f}" for acres in FARM_SIZES]
    corn_hours = [workload.corn_hours for workload in workloads]
    soy_hours = [workload.soy_hours for workload in workloads]
    shared_hours = [workload.base_combine_hours for workload in workloads]
    positions = range(len(FARM_SIZES))

    hours_axis.bar(positions, soy_hours, label="soybean-only hours", color="#6b8e23")
    hours_axis.bar(
        positions,
        corn_hours,
        bottom=soy_hours,
        label="corn-only hours",
        color="#d99a2b",
    )
    hours_axis.axhline(200.0, color="#555555", linestyle="--", linewidth=1.2)
    hours_axis.text(2.43, 204, "200 h descriptive author cut", color="#555555", fontsize=8)
    for index, (soy, corn, shared) in enumerate(zip(soy_hours, corn_hours, shared_hours)):
        if index != 0:
            hours_axis.text(index, soy / 2, f"{soy:.1f}", ha="center", va="center", fontsize=8)
            hours_axis.text(index, soy + corn / 2, f"{corn:.1f}", ha="center", va="center", fontsize=8)
        hours_axis.text(index, shared + 18, f"shared base: {shared:.1f} h", ha="center", fontsize=8)
    hours_axis.set_xticks(list(positions), labels)
    hours_axis.set_xlabel("total farm acres (50/50 corn and soybean mix)")
    hours_axis.set_ylabel("productive combine hours")
    hours_axis.set_title("One base combine serves both crops")
    hours_axis.legend(frameon=False, loc="upper left")
    hours_axis.grid(axis="y", alpha=0.18)
    hours_axis.set_ylim(0, max(shared_hours) * 1.18)

    windows_axis.axis("off")
    windows_axis.set_title("Crop windows", loc="left")
    windows_axis.text(
        0.0,
        0.77,
        "Corn window\nUNKNOWN — pending dated evidence",
        transform=windows_axis.transAxes,
        fontsize=10,
        color="#9a5b00",
        va="top",
    )
    windows_axis.text(
        0.0,
        0.49,
        "Soybean window\nUNKNOWN — pending dated evidence",
        transform=windows_axis.transAxes,
        fontsize=10,
        color="#4d6b16",
        va="top",
    )
    windows_axis.text(
        0.0,
        0.21,
        "Combined window\nNot assigned",
        transform=windows_axis.transAxes,
        fontsize=10,
        color="#555555",
        va="top",
    )

    figure.suptitle("Shared-use combine workload: crop hours add on one base machine", fontsize=13)
    figure.text(
        0.5,
        0.015,
        "Curated operation geometry joined to archived ISU references: corn 8.9091 ac/h; soybean 13.5758 ac/h. "
        "The 200-hour line is descriptive, never a cost break-even.",
        ha="center",
        fontsize=8,
        color="#555555",
    )
    figure.tight_layout(rect=(0.0, 0.05, 1.0, 0.94))
    return figure


def main() -> int:
    figure = build_figure()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(OUT_PATH, dpi=160)
    plt.close(figure)
    rows = write_options_table()
    decision_map = build_decision_map(rows)
    decision_map.savefig(DECISION_MAP_PATH, dpi=160)
    plt.close(decision_map)
    print(f"wrote {OUT_PATH.relative_to(ROOT)}")
    print(f"wrote {OPTIONS_PATH.relative_to(ROOT)}")
    print(f"wrote {DECISION_MAP_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

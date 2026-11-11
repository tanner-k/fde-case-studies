"""Build the landscape exhibit and print the phase-1 gate report.

Three panels, identical axes, one per farm size: 500 / 2,400 / 10,000 acres.
Small multiples, readable at a glance, and the quadrants visibly move with
scale — a combine that is a low-utilization machine on a 2,400-acre farm is a
high-utilization one on 10,000 acres, which is the whole argument about who
should own what.

| Channel | Encodes |
|---|---|
| x | annual machine hours at that farm size (log scale — two orders of magnitude) |
| y | agronomic window, days |
| point size | A3-10 custom-market depth, survey responses |
| annotation | break-even acreage against the published custom rate |

The gate this script exists to settle: do the deep custom markets land in the
low-utilization / narrow-window quadrant? If they do not, the thesis is wrong.
The answer is printed, not asserted — a gate that always passes is not a gate.

    uv run python case-studies/john-deere-roi-copilot/scripts/figures.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
from engine.landscape import (
    LOW_UTILIZATION_HOURS,
    NARROW_WINDOW_DAYS,
    Operation,
    Quadrant,
    landscape_points,
    market_depth_agreement,
)
from engine.machinery import MachineryRates
from engine.timeliness import (
    PRIMARY_PERCENTILES,
    SENSITIVITY_PERCENTILES,
    MeasuredWindow,
    delay_cost_usd_per_acre_per_day,
)
from etl.reference import load_measured_windows, load_operations, load_planting_date_curves
from matplotlib.figure import Figure

# Headless: this script runs in CI and from a terminal, never against a display.
matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "deliverables" / "figures" / "landscape-quadrants.png"

#: The site-grouping designated in `assumptions.md` §11.7.2: earliest optimum,
#: one of the two most curvature-sensitive, both reasons to prefer it for an
#: exhibit making a timeliness argument. Not wired to the axis — see §11.7.
CORN_CURVE_REGION = "NC-NE"

#: ISU A1-20 2026, continuous corn, conventional tillage, page 2:
#: `yield_levels_bu_per_acre` = [174, 193, 212] (low/medium/high). The medium
#: tier is the representative yield for the delay-cost caption figure.
ISU_A1_20_PATH = ROOT / "data" / "reference" / "isu_a1_20_2026.json"
ISU_A1_20_YIELD_TIER_INDEX = 1

#: `data/priors/yield_price.json`: CORN price is a fitted stationary lognormal,
#: `price = exp(log_mean + log_sd * z)`. `z = 0` — no shock — is the fitted
#: central price, used here as the point price for the caption figure.
YIELD_PRICE_PATH = ROOT / "data" / "priors" / "yield_price.json"

#: The three panels. 2,400 acres is the demo farm; 500 and 10,000 bracket it.
FARM_SIZES: tuple[float, float, float] = (500.0, 2_400.0, 10_000.0)

#: Prices for the break-even annotation. Wage is ISU A1-20 2026. PTO horsepower
#: is not sourced in this repository and fuel is under $0.50/acre for a sprayer
#: at any plausible value — see engine/machinery.py.
RATES = MachineryRates(
    interest_rate=0.07,
    engine_pto_hp=400.0,
    diesel_usd_per_gal=3.50,
    labour_usd_per_hour=20.40,
)

THESIS_COLOUR = "#c8102e"
OTHER_COLOUR = "#4a4a4a"

#: Label placement overrides for operations whose points sit close enough in
#: x, at every farm size, that the default `(0, 12)` centered-above offset
#: stacks their labels on top of a neighbour's. Keyed by `Operation.key` to
#: `(xytext, ha)`; unlisted operations use the default `((0, 12), "center")`.
#: The data never moves — only where its label is drawn relative to it.
#:
#: Measurement (Task 3) put both planters at window=11 and the two combine
#: heads at window=19 (corn) and window=14.5 (soybean) — the crowded band
#: moved from the old window=21 estimate row down to window=11/14/14.5/19.
#: x-order is the same at every farm size: sprayer < vertical_tillage <
#: high_speed_planter < field_cultivator < anhydrous < soybean_combine <
#: no_till_planter < corn_combine.
LABEL_OFFSETS: dict[str, tuple[tuple[float, float], str]] = {
    # window=21 pair (dry-fertilizer spreader / anhydrous applicator, both
    # author estimates, unmeasured) sit close enough in x that two centered-
    # above labels collide, and dry-fertilizer sits too close to the y-axis
    # to push further left. Lift anhydrous into the clear gap between this
    # row and chisel plow (window=35) instead, leaving dry-fertilizer's
    # default in place.
    "anhydrous_toolbar": ((0, 34), "center"),
    # window=11 pair (no-till / high-speed planter, both `corn_planted`) —
    # same y at every farm size, ~10-20 annual hours apart on the log axis.
    # Two stacked-above labels collide; split them left/right of their own
    # points instead so neither crosses the other's marker.
    "high_speed_planter": ((-6, 8), "right"),
    "no_till_planter": ((6, 8), "left"),
    # window=14 pair (vertical tillage / field cultivator) sit ~3 annual
    # hours apart, directly below the window=19-21 row (corn-head combine,
    # anhydrous applicator). Vertical tillage keeps the default above;
    # field cultivator drops into the open space below, between the
    # window=11 pair and the x-axis, clear of both rows.
    "vertical_tillage": ((0, 12), "center"),
    "field_cultivator": ((0, -34), "center"),
    # Draper-head combine (window=14.5) is always the rightmost of the
    # window=11/14/14.5 cluster (highest annual hours of the three, every
    # farm size), so a sideways offset clears the row without stacking.
    "soybean_combine": ((10, 0), "left"),
    # Sprayer sits at window=10, just under the window=11 pair. Nothing
    # occupies the open space below the sprayer's own point down to the
    # x-axis, so the label drops there instead of stacking into the row
    # above.
    "self_propelled_sprayer": ((0, -30), "center"),
}


class FigureDataError(RuntimeError):
    """A reference file this figure depends on is missing an expected row."""


def corn_planting_delay_cost_usd_per_acre_per_day(corn_planted_window: MeasuredWindow) -> float:
    """Price a day of corn-planting delay, evaluated at the primary window's close.

    The corn planting-date curve (`engine/timeliness.py`) is the one place the
    exhibit's narrow-window claim can be priced (`assumptions.md` §11.7). The
    reference day is where the measured 25-75 window closes — the last day the
    bulk of Iowa's corn is still going in — not an arbitrary later date.

    Args:
        corn_planted_window: The `corn_planted` measurement at the primary
            (25-75) percentile pair.

    Returns:
        Dollars per acre per day of delay past the NC-NE optimum, priced at
        ISU A1-20 2026's medium corn yield tier and the fitted corn price's
        central value from `data/priors/yield_price.json`.

    Raises:
        FigureDataError: If `CORN_CURVE_REGION` names no curve in
            `planting_date_response.json`, or `ISU_A1_20_PATH` carries no
            continuous-corn budget row.
    """
    curve = next(
        (c for c in load_planting_date_curves() if c.region == CORN_CURVE_REGION), None
    )
    if curve is None:
        raise FigureDataError(
            f"no planting-date curve for region {CORN_CURVE_REGION!r} in "
            "data/reference/planting_date_response.json"
        )
    isu_budget = next(
        (
            b
            for b in json.loads(ISU_A1_20_PATH.read_text())["budgets"]
            if b["crop"] == "corn" and b["rotation"] == "continuous corn"
        ),
        None,
    )
    if isu_budget is None:
        raise FigureDataError(
            f"no 'corn' / 'continuous corn' budget row in {ISU_A1_20_PATH.name}"
        )
    yield_bu_per_acre = isu_budget["yield_levels_bu_per_acre"][ISU_A1_20_YIELD_TIER_INDEX]
    corn_price = json.loads(YIELD_PRICE_PATH.read_text())["crops"]["CORN"]["price"]
    price_usd_per_bu = math.exp(corn_price["log_mean"])
    return delay_cost_usd_per_acre_per_day(
        curve,
        day_of_year=corn_planted_window.median_closing_day_of_year,
        optimal_yield_bu_per_acre=yield_bu_per_acre,
        price_usd_per_bu=price_usd_per_bu,
    )


def build_landscape_figure(
    operations: tuple[Operation, ...],
    *,
    farm_sizes: tuple[float, ...] = FARM_SIZES,
    rates: MachineryRates = RATES,
    corn_delay_cost_usd_per_acre_per_day: float | None = None,
) -> Figure:
    """Render the three-panel landscape plot.

    Args:
        operations: Operations to plot, drawn in the order given.
        farm_sizes: One panel per size, left to right.
        rates: Prices and ASABE factors for the break-even annotation.
        corn_delay_cost_usd_per_acre_per_day: If given, appended to the
            caption as a sentence — not plotted as a point label. `None` when
            no crop-progress panel is available to measure the window closes.

    Returns:
        The figure. Not saved — `main` decides where it goes.
    """
    figure, axes = plt.subplots(
        1, len(farm_sizes), figsize=(15.0, 5.5), sharex=True, sharey=True
    )
    for axis, farm_acres in zip(axes, farm_sizes, strict=True):
        points = landscape_points(operations, farm_acres=farm_acres, rates=rates)
        axis.axvline(LOW_UTILIZATION_HOURS, color="#999999", linewidth=0.8, linestyle="--")
        axis.axhline(NARROW_WINDOW_DAYS, color="#999999", linewidth=0.8, linestyle="--")
        for point in points:
            thesis = point.quadrant is Quadrant.LOW_USE_NARROW_WINDOW
            axis.scatter(
                point.annual_machine_hours,
                point.window_days,
                s=point.custom_rate_responses * 4.0,
                color=THESIS_COLOUR if thesis else OTHER_COLOUR,
                alpha=0.55,
                edgecolors="white",
                linewidths=0.8,
                zorder=3,
            )
            label = point.label
            if point.break_even_acres is not None:
                label += f"\nbreak-even {point.break_even_acres:,.0f} ac"
            xytext, ha = LABEL_OFFSETS.get(point.operation_key, ((0, 12), "center"))
            axis.annotate(
                label,
                (point.annual_machine_hours, point.window_days),
                textcoords="offset points",
                xytext=xytext,
                ha=ha,
                fontsize=7,
                color="#222222",
            )
        axis.set_xscale("log")
        axis.set_xlim(1.0, 3_000.0)
        axis.set_ylim(0.0, 40.0)
        axis.set_title(f"{farm_acres:,.0f} acres", fontsize=11)
        axis.set_xlabel("annual machine hours")
        axis.grid(alpha=0.15, zorder=0)
    axes[0].set_ylabel("agronomic window, days")
    figure.suptitle(
        "Which machines a farm cannot justify owning — and must have on the day it needs them",
        fontsize=13,
    )
    caption = (
        "Point size: ISU A3-10 2026 custom-market depth (survey responses). "
        "Bottom-left quadrant is the thesis: low utilization, narrow window."
    )
    if corn_delay_cost_usd_per_acre_per_day is not None:
        caption += (
            f" Corn planted past the primary window's close has averaged an estimated "
            f"${corn_delay_cost_usd_per_acre_per_day:.2f}/acre/day of loss over the days "
            f"since the NC-NE optimum (Abendroth et al. 2017) — the marginal cost on that "
            f"day is roughly double."
        )
    figure.text(
        0.5,
        0.005,
        caption,
        ha="center",
        fontsize=8,
        color="#555555",
        wrap=True,
    )
    figure.tight_layout(rect=(0.0, 0.03, 1.0, 0.95))
    return figure


def gate_report(
    operations: tuple[Operation, ...],
    *,
    farm_sizes: tuple[float, ...] = FARM_SIZES,
    rates: MachineryRates = RATES,
) -> str:
    """Tabulate every point and the market-depth agreement, per panel.

    Args:
        operations: Operations to report on.
        farm_sizes: One block per size.
        rates: Prices and ASABE factors.

    Returns:
        The report, ready to print or paste into the appendix.
    """
    lines: list[str] = []
    for farm_acres in farm_sizes:
        points = landscape_points(operations, farm_acres=farm_acres, rates=rates)
        agreement = market_depth_agreement(points)
        lines.append(f"\n{farm_acres:,.0f} acres")
        lines.append(f"  {'operation':26} {'hours':>8} {'window':>7} {'n':>4}  quadrant")
        for point in points:
            lines.append(
                f"  {point.label:26} {point.annual_machine_hours:8.1f} "
                f"{point.window_days:7.0f} {point.custom_rate_responses:4d}  "
                f"{point.quadrant.value}"
            )
        lines.append(
            f"  market-depth agreement (n >= {agreement.min_responses}): "
            f"{len(agreement.agreeing)}/{len(agreement.deep_market_operations)} "
            f"= {agreement.agreement_rate:.0%}"
        )
        if agreement.disagreeing:
            lines.append(f"  disagreeing: {', '.join(agreement.disagreeing)}")
    return "\n".join(lines)


def main() -> int:
    """Build the figure on the primary definition, then report all three.

    Returns:
        Process exit status.
    """
    windows = load_measured_windows(
        low_percentile=PRIMARY_PERCENTILES[0], high_percentile=PRIMARY_PERCENTILES[1]
    )
    if not windows:
        print(
            "no crop-progress panel found — plotting author-estimated windows. "
            "Run scripts/fetch_crop_progress.py to measure them.",
            file=sys.stderr,
        )
    operations = load_operations(measured_windows=windows)

    corn_delay_cost = None
    if "corn_planted" in windows:
        corn_delay_cost = corn_planting_delay_cost_usd_per_acre_per_day(windows["corn_planted"])
        print(
            f"corn planting delay: ${corn_delay_cost:.2f}/acre/day, averaged over the days "
            f"elapsed since the {CORN_CURVE_REGION} optimum, evaluated at the 25-75 window's "
            f"close (day of year {windows['corn_planted'].median_closing_day_of_year})"
        )

    figure = build_landscape_figure(
        operations, corn_delay_cost_usd_per_acre_per_day=corn_delay_cost
    )
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(OUT_PATH, dpi=160)
    print(f"{len(operations)} operations -> {OUT_PATH.relative_to(ROOT)}")
    measured = sum(1 for op in operations if op.window_confidence == "measured")
    print(f"{measured} of {len(operations)} windows measured, the rest author-estimated")
    print(gate_report(operations))

    for low, high in SENSITIVITY_PERCENTILES:
        alternative = load_measured_windows(low_percentile=low, high_percentile=high)
        if not alternative:
            break
        print(f"\n=== sensitivity: {low:.0f}-{high:.0f} percentile window ===")
        print(gate_report(load_operations(measured_windows=alternative)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Smoke test for the landscape figure.

The math is tested in `test_landscape.py` and the data in `test_etl_reference.py`.
What is left to break here is the plotting itself — a mislabelled axis or a
matplotlib call that throws on an empty panel — so this test only asserts that
the figure builds, has one panel per farm size, and shares its axes.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import matplotlib
import pytest

matplotlib.use("Agg")  # headless; the script sets this too, belt and braces

FIGURES = Path(__file__).resolve().parent.parent / "scripts" / "figures.py"


def _load_figures() -> ModuleType:
    """Import the figure script by path — `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location("figures", FIGURES)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


figures = _load_figures()


def test_the_figure_has_one_panel_per_farm_size():
    from etl.reference import load_operations

    figure = figures.build_landscape_figure(load_operations())
    assert len(figure.axes) == len(figures.FARM_SIZES) == 3


def test_the_panels_share_identical_axes():
    """Spec section 4: three panels, identical axes.

    Small multiples only work if the reader can compare positions across them.
    """
    from etl.reference import load_operations

    figure = figures.build_landscape_figure(load_operations())
    first, *rest = figure.axes
    assert all(axis.get_xlim() == first.get_xlim() for axis in rest)
    assert all(axis.get_ylim() == first.get_ylim() for axis in rest)


def test_the_gate_report_names_every_farm_size_and_every_operation():
    from etl.reference import load_operations

    operations = load_operations()
    report = figures.gate_report(operations)
    assert "500" in report and "2,400" in report and "10,000" in report
    assert all(operation.label in report for operation in operations)
    assert "agreement" in report.lower()


# --- corn_planting_delay_cost_usd_per_acre_per_day (Finding 4) --------------
#
# Untested before this fix: it joins three committed reference files (the
# planting-date curve, the ISU corn budget, and the fitted price prior) that
# nothing else in the suite reads together. A wrong JSON edit to any of the
# three would move `assumptions.md` section 11.7.5's headline $3.05/acre/day
# without a single test failing.

_CORN_PLANTED_WINDOW_KWARGS = {
    "series_key": "corn_planted",
    "low_percentile": 25.0,
    "high_percentile": 75.0,
    "years_observed": 21,
    "median_calendar_days": 11.0,
    "min_calendar_days": 7,
    "max_calendar_days": 25,
    "median_suitable_days": 6.8,
    "median_closing_day_of_year": 131,
}


def test_corn_planting_delay_cost_is_pinned_at_the_measured_closing_day():
    """Regression pin, `assumptions.md` section 11.7.5: $3.05/acre/day at DOY 131."""
    from engine.timeliness import MeasuredWindow

    window = MeasuredWindow(**_CORN_PLANTED_WINDOW_KWARGS)
    cost = figures.corn_planting_delay_cost_usd_per_acre_per_day(window)
    assert cost == pytest.approx(3.05, abs=0.01)


def test_corn_planting_delay_cost_raises_for_an_unmatched_curve_region(monkeypatch):
    from engine.timeliness import MeasuredWindow

    monkeypatch.setattr(figures, "CORN_CURVE_REGION", "not-a-real-region")
    window = MeasuredWindow(**_CORN_PLANTED_WINDOW_KWARGS)
    with pytest.raises(figures.FigureDataError, match="not-a-real-region"):
        figures.corn_planting_delay_cost_usd_per_acre_per_day(window)


def test_corn_planting_delay_cost_raises_for_a_missing_budget_row(monkeypatch):
    from engine.timeliness import MeasuredWindow

    monkeypatch.setattr(figures, "ISU_A1_20_YIELD_TIER_INDEX", 1)
    monkeypatch.setattr(
        figures,
        "ISU_A1_20_PATH",
        Path(__file__).resolve().parent / "fixtures" / "isu_a1_20_no_continuous_corn.json",
    )
    window = MeasuredWindow(**_CORN_PLANTED_WINDOW_KWARGS)
    with pytest.raises(figures.FigureDataError, match="continuous corn"):
        figures.corn_planting_delay_cost_usd_per_acre_per_day(window)

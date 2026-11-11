"""Load the archived ISU reference files into engine models.

`engine/` does no file I/O, so the join between the three archived JSON files
lives here. Nothing in this module touches the network — the ISU documents were
downloaded by hand (`extension.iastate.edu` serves an Anubis proof-of-work
challenge to scripted clients) and `scripts/extract_isu_reference.py` turned
them into the JSON this module reads.

The join is deliberately strict. A3-10's operation names are PDF-parsed
fragments — `"without attachments / acre"` is a planter, because the survey's
section heading carried the machine name — and two of them repeat across
sections. A fuzzy match would put a combine's $46/acre rate on a sprayer and
nothing downstream would notice, so anything that does not resolve to exactly
one row raises.

No network: the ISU joins are stdlib-only JSON; `load_measured_windows` reads
the already-fetched crop-progress parquet with polars, phase 2's one addition
to this module's dependencies.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import polars as pl
from engine.landscape import Operation
from engine.machinery import RemainingValue, remaining_value_fraction
from engine.timeliness import (
    MeasuredWindow,
    PlantingDateCurve,
    ProgressPoint,
    SuitableWeek,
    measure_window,
)

REFERENCE_DIR = Path(__file__).resolve().parent.parent / "data" / "reference"
OPERATIONS_PATH = REFERENCE_DIR / "operations.json"
CUSTOM_RATES_PATH = REFERENCE_DIR / "isu_a3_10_2026_custom_rates.json"
MACHINE_DATA_PATH = REFERENCE_DIR / "isu_a3_29_machine_data.json"
PLANTING_RESPONSE_PATH = REFERENCE_DIR / "planting_date_response.json"

CROP_PROGRESS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "raw" / "nass" / "crop_progress.parquet"
)

#: NASS series the panel measures but no operation maps to, by design. Both
#: planter rows map to `corn_planted` — corn is planted first and is the
#: timeliness-critical half of the rotation — so `soybean_planted` is measured
#: and deliberately unused. Anything outside this set that goes unmapped is a
#: mistyped `nass_series_key`, not a design choice, which is what the guard in
#: `load_operations` is for.
KNOWN_UNMAPPED_SERIES = frozenset({"soybean_planted"})


class ReferenceDataError(RuntimeError):
    """A reference row points at something the archived sources do not contain."""


def _resolve_rate(
    rates: list[dict[str, Any]], *, section: str, operation: str
) -> dict[str, Any]:
    """Find the one A3-10 row an operation names.

    Raises:
        ReferenceDataError: If the pair matches zero rows or more than one.
    """
    matches = [
        row for row in rates if row["section"] == section and row["operation"] == operation
    ]
    if len(matches) != 1:
        raise ReferenceDataError(
            f"custom rate {section!r} / {operation!r} matched {len(matches)} rows in A3-10; "
            "operations.json must name a row that resolves to exactly one. The names are "
            "PDF-parsed fragments — copy them verbatim, including double spaces."
        )
    return matches[0]


def _resolve_machine(machines: list[dict[str, Any]], *, description: str) -> dict[str, Any]:
    """Find the one A3-29 machine-type row an operation names.

    Raises:
        ReferenceDataError: If the description matches zero rows or more than one.
    """
    matches = [row for row in machines if row["description"] == description]
    if len(matches) != 1:
        raise ReferenceDataError(
            f"a3_29_machine {description!r} matched {len(matches)} rows in A3-29; "
            f"known types: {sorted(row['description'] for row in machines)}"
        )
    return matches[0]


def load_measured_windows(
    panel_path: Path = CROP_PROGRESS_PATH,
    *,
    low_percentile: float = 25.0,
    high_percentile: float = 75.0,
) -> dict[str, MeasuredWindow]:
    """Measure every progress series in the crop-progress panel.

    Args:
        panel_path: The parquet written by `scripts/fetch_crop_progress.py`.
        low_percentile: Where each window opens.
        high_percentile: Where it closes.

    Returns:
        One `MeasuredWindow` per progress series, keyed by series key. Empty if
        the panel has not been fetched — the exhibit still builds, on estimates,
        and says so.

    Raises:
        ReferenceDataError: If the panel exists but carries no days-suitable
            series, which would silently make every suitable-day count zero.
    """
    if not panel_path.exists():
        return {}
    panel = pl.read_parquet(panel_path)

    suitable_rows = panel.filter(pl.col("series_key") == "days_suitable")
    if suitable_rows.is_empty():
        raise ReferenceDataError(
            f"{panel_path.name} has no 'days_suitable' series; re-run "
            "scripts/fetch_crop_progress.py rather than measuring against zero workable days"
        )
    weeks = tuple(
        SuitableWeek(week_ending=row["week_ending"], days_suitable=row["value"])
        for row in suitable_rows.iter_rows(named=True)
    )

    windows: dict[str, MeasuredWindow] = {}
    for series_key in sorted(set(panel["series_key"].to_list()) - {"days_suitable"}):
        rows = panel.filter(pl.col("series_key") == series_key)
        points_by_year: dict[int, list[ProgressPoint]] = {}
        for row in rows.iter_rows(named=True):
            points_by_year.setdefault(row["year"], []).append(
                ProgressPoint(week_ending=row["week_ending"], percent_complete=row["value"])
            )
        windows[series_key] = measure_window(
            points_by_year,
            weeks,
            series_key=series_key,
            low_percentile=low_percentile,
            high_percentile=high_percentile,
        )
    return windows


def load_planting_date_curves(
    path: Path = PLANTING_RESPONSE_PATH,
) -> tuple[PlantingDateCurve, ...]:
    """Read the transcribed Iowa corn planting-date response curves.

    Args:
        path: The curated JSON, one entry per Table 2 site-grouping.

    Returns:
        One validated `PlantingDateCurve` per site-grouping, in file order.
    """
    rows = json.loads(path.read_text())["curves"]
    return tuple(PlantingDateCurve(**row) for row in rows)


def load_operations(
    *,
    operations_path: Path = OPERATIONS_PATH,
    custom_rates_path: Path = CUSTOM_RATES_PATH,
    machine_data_path: Path = MACHINE_DATA_PATH,
    measured_windows: Mapping[str, MeasuredWindow] | None = None,
) -> tuple[Operation, ...]:
    """Read `operations.json` and join it against A3-10 and A3-29.

    Four fields are derived rather than hand-entered, which is one fewer
    assumption each:

    | Field | Derivation |
    |---|---|
    | `custom_rate_usd_per_acre`, `custom_rate_responses` | the A3-10 row |
    | `rated_annual_hours` | A3-29 wearout hours / `useful_life_years` |
    | `salvage_fraction` | the A3-29 remaining-value equation at that age and use |
    | `repair_factor_rc1`, `repair_factor_rc2` | the A3-29 row for this machine type |

    A row whose `nass_series_key` appears in `measured_windows` takes its
    `window_days` from that measurement and is relabelled `measured`. Rows
    without a series — spraying, tillage, fertilizer application — keep the
    author estimate the file carries.

    Args:
        operations_path: The curated operations file.
        custom_rates_path: Parsed ISU A3-10.
        machine_data_path: Parsed ISU A3-29.
        measured_windows: NASS-measured windows, keyed by series key. `None`
            or empty leaves every row an author estimate.

    Returns:
        One validated `Operation` per row, in file order.

    Raises:
        ReferenceDataError: If any row fails to resolve against the sources,
            or if `measured_windows` carries a series key no row maps to.
    """
    rows = json.loads(operations_path.read_text())["operations"]
    rates = json.loads(custom_rates_path.read_text())["rates"]
    machines = json.loads(machine_data_path.read_text())["machines"]

    measured = dict(measured_windows or {})
    mapped_keys = {row["nass_series_key"] for row in rows if row["nass_series_key"]}
    unused = sorted(set(measured) - mapped_keys - KNOWN_UNMAPPED_SERIES)
    if unused:
        raise ReferenceDataError(
            f"measured windows supplied for series no operation maps to: {unused}. "
            f"operations.json maps {sorted(mapped_keys)} — a mistyped nass_series_key "
            "would otherwise leave the estimate silently in place."
        )

    operations = []
    for row in rows:
        rate = _resolve_rate(
            rates,
            section=row["custom_rate_section"],
            operation=row["custom_rate_operation"],
        )
        machine = _resolve_machine(machines, description=row["a3_29_machine"])
        rated_annual_hours = machine["wearout_hours"] / row["useful_life_years"]
        salvage = remaining_value_fraction(
            RemainingValue(
                machine_type=machine["description"],
                rv_intercept=machine["rv_intercept"],
                rv_age_coeff=machine["rv_age_coeff"],
                rv_hours_coeff=machine["rv_hours_coeff"],
            ),
            age_years=row["useful_life_years"],
            annual_hours=rated_annual_hours,
        )
        window = measured.get(row["nass_series_key"]) if row["nass_series_key"] else None
        if window is not None:
            excluded_note = (
                f" Years excluded (never reached the high percentile, or its crossing "
                f"straddled a reporting gap too wide to trust): "
                f"{', '.join(str(y) for y in window.years_excluded)}."
                if window.years_excluded
                else ""
            )
            row = {
                **row,
                "window_days": window.median_calendar_days,
                "window_confidence": "measured",
                "window_source": (
                    f"NASS Crop Progress {window.series_key}, Iowa: median "
                    f"{window.low_percentile:.0f}-{window.high_percentile:.0f} percentile "
                    f"span over {window.years_observed} years "
                    f"({window.min_calendar_days}-{window.max_calendar_days} d observed); "
                    f"a typical year's own window had {window.median_suitable_days:.1f} "
                    "suitable fieldwork days (median of each year's own count, not the "
                    "workable days inside the calendar span above). Statewide dispersion, "
                    "so an upper bound on one farm's window."
                    f"{excluded_note}"
                ),
            }
        operations.append(
            Operation(
                **row,
                custom_rate_usd_per_acre=rate["average"],
                custom_rate_responses=rate["responses"],
                rated_annual_hours=rated_annual_hours,
                salvage_fraction=salvage,
                repair_factor_rc1=machine["repair_factor_rc1"],
                repair_factor_rc2=machine["repair_factor_rc2"],
            )
        )
    return tuple(operations)

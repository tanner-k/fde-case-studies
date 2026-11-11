#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pypdf>=5.0", "openpyxl>=3.1"]
# ///
"""Extract structured reference data from the two manually-downloaded ISU files.

`extension.iastate.edu` serves an Anubis proof-of-work challenge to scripted
clients, so neither source can be fetched automatically. Both are archived under
`data/reference/`; this script turns them into JSON the engine can consume, so
the hand-download happens once and the parse stays reproducible and reviewable.

Sources:
    A3-10  2026 Iowa Farm Custom Rate Survey (FM 1698, revised March 2026)
           205 respondents, 4,698 rates. Rates include fuel, repairs,
           depreciation, interest, and operator labour unless noted.
    A3-29  Machinery Cost Calculator, "Data" sheet — ASABE repair factors,
           wearout hours, and remaining-value coefficients by machine type.

Usage:
    ./scripts/extract_isu_reference.py
"""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path
from typing import Any

import openpyxl
from pypdf import PdfReader

REFERENCE_DIR = Path(__file__).resolve().parent.parent / "data" / "reference"
CUSTOM_RATES_PDF = REFERENCE_DIR / "isu-a3-10-2026-iowa-farm-custom-rate-survey.pdf"
MACHINERY_XLSX = REFERENCE_DIR / "isu-a3-29-machinery-cost-calculator.xlsx"

#: "<description> <avg> <median> <low> - <high> <n>", dollar signs optional.
_MONEY = r"\$?([\d,]+\.\d{2})"
RATE_LINE = re.compile(
    rf"^(?P<name>.+?)\s+{_MONEY}\s+{_MONEY}\s+{_MONEY}\s*-\s*{_MONEY}\s+(?P<n>\d+)\s*$"
)

#: Section headings in A3-10, in document order. Rows inherit the last one seen.
SECTIONS = (
    "Tillage",
    "Planting, Drilling, and Seeding",
    "Spraying",
    "Fertilizer Application",
    "Harvesting, Drying, and Hauling Grain",
    "Harvesting Forages",
    "Miscellaneous",
    "Machinery Rental",
)


def _money(value: str) -> float:
    """Parse a survey money string into a float."""
    return float(value.replace(",", ""))


def parse_custom_rates(pdf_path: Path) -> list[dict[str, Any]]:
    """Extract every custom-rate row from A3-10.

    Args:
        pdf_path: Archived A3-10 PDF.

    Returns:
        One record per rate: section, operation, unit, average, median, range,
        and the number of survey responses behind it.

    Raises:
        FileNotFoundError: If the archived PDF is absent.
    """
    reader = PdfReader(pdf_path)
    section = "Unknown"
    rows: list[dict[str, Any]] = []
    for page in reader.pages:
        for raw in (page.extract_text() or "").splitlines():
            line = raw.strip()
            matched_section = next((s for s in SECTIONS if line.startswith(s)), None)
            if matched_section:
                section = matched_section
                continue
            match = RATE_LINE.match(line)
            if not match:
                continue
            name = match.group("name").strip(" -")
            unit = name.rsplit("/", 1)[-1].strip() if "/" in name else "acre"
            rows.append(
                {
                    "section": section,
                    "operation": name,
                    "unit": unit,
                    "average": _money(match.group(2)),
                    "median": _money(match.group(3)),
                    "range_low": _money(match.group(4)),
                    "range_high": _money(match.group(5)),
                    "responses": int(match.group("n")),
                }
            )
    return rows


def parse_machinery_data(xlsx_path: Path) -> list[dict[str, Any]]:
    """Extract the ASABE machine-type table from A3-29's `Data` sheet.

    The remaining-value coefficients implement
    `RV = list_price * (intercept - agecoeff*sqrt(age) - hrscoeff*sqrt(annual_hours))^2`
    — note that a zero `hrscoeff` (sprayers, planters, all implements) means
    resale depends on age alone, not on how hard the machine was worked.

    Returns:
        One record per machine type, tagged `power_unit` or `implement`.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        workbook = openpyxl.load_workbook(xlsx_path, data_only=True)
    sheet = workbook["Data"]

    machines: list[dict[str, Any]] = []
    category = "power_unit"
    seen_first_block = False
    for row in sheet.iter_rows(min_row=5, max_row=44, values_only=True):
        type_no, description = row[0], row[1]
        if not isinstance(type_no, int) or not isinstance(description, str):
            continue
        # The sheet restarts numbering at 1 for implements.
        if type_no == 1 and seen_first_block:
            category = "implement"
        seen_first_block = True
        machines.append(
            {
                "type_no": type_no,
                "category": category,
                "description": description.strip(),
                "repair_factor_rc1": row[2],
                "repair_factor_rc2": row[3],
                "wearout_hours": row[4],
                "rv_intercept": row[5],
                "rv_age_coeff": row[6],
                "rv_hours_coeff": row[7],
            }
        )
    return machines


def main() -> None:
    """Parse both archived sources and write the JSON the engine consumes."""
    rates = parse_custom_rates(CUSTOM_RATES_PDF)
    machines = parse_machinery_data(MACHINERY_XLSX)

    (REFERENCE_DIR / "isu_a3_10_2026_custom_rates.json").write_text(
        json.dumps(
            {
                "$comment": (
                    "2026 Iowa Farm Custom Rate Survey (A3-10, FM 1698, rev. March "
                    "2026). 205 respondents, 4,698 rates. Includes fuel, repairs, "
                    "depreciation, interest and operator labour unless noted; diesel "
                    "assumed $2.89/gal. `responses` is the count behind each rate and "
                    "is the market-depth signal: an operation with 100+ providers is "
                    "one Iowa growers already consolidate."
                ),
                "source": {
                    "id": "isu_a3_10_2026",
                    "publication": "Iowa State University Extension, Ag Decision Maker A3-10",
                    "revised": "2026-03",
                    "retrieved": "2026-08-13",
                    "archived_pdf": CUSTOM_RATES_PDF.name,
                    "access_note": "Manual download only; scripted access is blocked.",
                },
                "rates": rates,
            },
            indent=2,
        )
    )

    (REFERENCE_DIR / "isu_a3_29_machine_data.json").write_text(
        json.dumps(
            {
                "$comment": (
                    "ASABE machine-type data from the A3-29 Machinery Cost Calculator "
                    "'Data' sheet. remaining value = list_price * (rv_intercept - "
                    "rv_age_coeff*sqrt(age_years) - rv_hours_coeff*sqrt(annual_hours))^2. "
                    "rv_hours_coeff is ZERO for sprayers, planters and every implement: "
                    "their resale depends on age alone, not accumulated hours."
                ),
                "source": {
                    "id": "isu_a3_29",
                    "publication": "Iowa State University Extension, Ag Decision Maker A3-29",
                    "underlying_standard": "ASABE (repair factors, wearout hours, remaining value)",
                    "retrieved": "2026-08-13",
                    "archived_xlsx": MACHINERY_XLSX.name,
                    "access_note": "Manual download only; scripted access is blocked.",
                },
                "machines": machines,
            },
            indent=2,
        )
    )
    print(f"custom rates: {len(rates)} rows")
    print(f"machine types: {len(machines)}")


if __name__ == "__main__":
    main()

"""Fit the yield and price priors and write `data/priors/yield_price.json`.

Offline. Reads the extracted NASS panel, writes one committed JSON artifact.

Deterministic by construction: no seeds are drawn, no timestamp is recorded,
and every stored float is rounded well inside its own precision, so a second
run on the same panel produces byte-identical output. The panel's SHA-256 goes
in the document instead of a build date — it says *which* input produced this
file, which is the question a reviewer actually has.

    uv run python scripts/fit_priors.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
from ml import priors

ROOT = Path(__file__).resolve().parent.parent
PANEL_PATH = ROOT / "data" / "raw" / "nass" / "panel.parquet"
OUT_PATH = ROOT / "data" / "priors" / "yield_price.json"


def main() -> int:
    """Fit and write the priors, reporting what was fitted.

    Returns:
        Process exit status.
    """
    if not PANEL_PATH.exists():
        print(f"missing {PANEL_PATH}; run the NASS extractor first", file=sys.stderr)
        return 1

    panel = pl.read_parquet(PANEL_PATH)
    document = priors.build_priors(panel, source_digest=priors.digest(PANEL_PATH))
    text = priors.dumps(document)

    unchanged = OUT_PATH.exists() and OUT_PATH.read_text() == text
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(text)

    print(f"{PANEL_PATH.name}: {panel.height} rows -> {OUT_PATH.relative_to(ROOT)}")
    print("byte-identical to the previous run" if unchanged else "content changed")
    for crop, block in document["crops"].items():
        trend = block["yield"]["trend"]
        print(
            f"  {crop:9s} trend {trend['slope_bu_per_acre_per_year']:+.3f} bu/ac/yr "
            f"from {trend['intercept_bu_per_acre']:.1f} @ {trend['base_year']}"
            f" | shock sd {block['yield']['common_year_shock']['sd_bu_per_acre']:.2f}"
            f" | wobble sd {block['yield']['idiosyncratic']['sd_bu_per_acre']:.2f}"
            f" | price ${block['price']['observed_min_usd_per_bu']:.2f}"
            f"-${block['price']['observed_max_usd_per_bu']:.2f}"
            f" | rho {block['yield_price_copula']['rho']:+.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

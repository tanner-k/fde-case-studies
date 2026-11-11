"""Pull NASS Crop Progress for Iowa and write `data/raw/nass/crop_progress.parquet`.

Offline. Raw responses are cached under `data/raw/nass/cache/`, so a re-run
after the first costs no requests and produces an identical panel.

    uv run python case-studies/john-deere-roi-copilot/scripts/fetch_crop_progress.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
from etl import crop_progress
from etl.nass import MissingApiKeyError

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "raw" / "nass" / "cache"
OUT_PATH = ROOT / "data" / "raw" / "nass" / "crop_progress.parquet"


def main() -> int:
    """Extract every series and report what landed.

    Returns:
        Process exit status.
    """
    try:
        panel = crop_progress.extract(CACHE_DIR, OUT_PATH)
    except MissingApiKeyError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"{panel.height} rows -> {OUT_PATH.relative_to(ROOT)}")
    summary = panel.group_by("series_key").agg(
        rows=pl.len(),
        first_year=pl.col("year").min(),
        last_year=pl.col("year").max(),
    )
    for row in summary.sort("series_key").iter_rows(named=True):
        print(
            f"  {row['series_key']:18} {row['rows']:>5} rows  "
            f"{row['first_year']}-{row['last_year']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

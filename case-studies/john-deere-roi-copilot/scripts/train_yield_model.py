"""Run the yield model bake-off and record the result.

Offline. Scores a quantile gradient booster against the climatology baseline on
held-out years and writes `data/models/yield_bakeoff.json`.

No model artifact is written here. If the booster loses, there is nothing to
ship but the baseline, and committing a pickle nobody scores would be worse
than committing nothing. The numbers this prints are the ones quoted in
`deliverables/appendix/model-card.md`.

    uv run python scripts/train_yield_model.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
from ml import priors
from ml import yield_model as ym

ROOT = Path(__file__).resolve().parent.parent
PANEL_PATH = ROOT / "data" / "raw" / "nass" / "panel.parquet"
WEATHER_PATH = ROOT / "data" / "raw" / "weather" / "daily.parquet"
OUT_PATH = ROOT / "data" / "models" / "yield_bakeoff.json"

CROPS = ("CORN", "SOYBEANS")
#: Ten held-out years, leaving ten years of history before the first of them.
HOLDOUT_YEARS = tuple(range(2016, 2026))
SEED = 0


def _report(crop: str, design: pl.DataFrame) -> dict:
    """Backtest one crop and print its per-year table.

    Args:
        crop: `commodity` value.
        design: Output of `ym.build_design`.

    Returns:
        The crop's block of the results document.
    """
    result = ym.backtest(design, holdout_years=HOLDOUT_YEARS, quantiles=ym.QUANTILES, seed=SEED)
    call = ym.verdict(result)

    print(f"\n{crop} — pinball loss, bu/acre, mean over quantiles {ym.QUANTILES}")
    print(f"  {'year':>6} {'counties':>9} {'baseline':>10} {'gbm':>10} {'delta':>9}  winner")
    for row in result.iter_rows(named=True):
        delta = row["gbm_pinball"] - row["baseline_pinball"]
        winner = "gbm" if delta < 0 else "baseline"
        print(
            f"  {row['year']:>6} {row['n_counties']:>9} {row['baseline_pinball']:>10.3f} "
            f"{row['gbm_pinball']:>10.3f} {delta:>+9.3f}  {winner}"
        )
    print(
        f"  {'mean':>6} {'':>9} {call.baseline_pinball:>10.3f} {call.gbm_pinball:>10.3f} "
        f"{call.gbm_pinball - call.baseline_pinball:>+9.3f}  "
        f"gbm improvement {call.improvement_pct:+.2f}% | gbm won "
        f"{call.years_won}/{call.years_total} years"
    )
    print(f"  SHIPS: {'climatology baseline' if call.baseline_wins else 'gradient booster'}")
    return {
        "ships": "climatology_baseline" if call.baseline_wins else "gradient_booster",
        "baseline_pinball": call.baseline_pinball,
        "gbm_pinball": call.gbm_pinball,
        "gbm_improvement_pct": call.improvement_pct,
        "gbm_years_won": call.years_won,
        "years_evaluated": call.years_total,
        "per_year": result.to_dicts(),
    }


def main() -> int:
    """Run the bake-off for every crop and write the results.

    Returns:
        Process exit status.
    """
    for path in (PANEL_PATH, WEATHER_PATH):
        if not path.exists():
            print(f"missing {path}; run the extractors first", file=sys.stderr)
            return 1

    features = ym.growing_season_features(pl.read_parquet(WEATHER_PATH))
    panel = pl.read_parquet(PANEL_PATH)
    print(f"weather features: {features.height} county-years, {features['year'].n_unique()} years")

    crops = {}
    for crop in CROPS:
        yields = (
            panel.filter((pl.col("statistic") == "YIELD") & (pl.col("commodity") == crop))
            .select("county_fips", "year", pl.col("value").alias("yield_bu_per_acre"))
        )
        design = ym.build_design(yields, features)
        print(f"{crop}: {design.height} county-year rows")
        crops[crop] = _report(crop, design)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        priors.dumps(
            {
                "$comment": (
                    "Yield model bake-off: quantile gradient boosting against a climatology "
                    "baseline, pinball loss on held-out years. Method and interpretation: "
                    "deliverables/appendix/model-card.md. Regenerate with "
                    "scripts/train_yield_model.py."
                ),
                "schema_version": 1,
                "quantiles": list(ym.QUANTILES),
                "features": list(ym.FEATURE_COLUMNS),
                "holdout_years": list(HOLDOUT_YEARS),
                "seed": SEED,
                "source": {
                    "nass_sha256": priors.digest(PANEL_PATH),
                    "weather_sha256": priors.digest(WEATHER_PATH),
                },
                "crops": crops,
            }
        )
    )
    print(f"\nwrote {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

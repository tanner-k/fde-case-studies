# Model Card — County Yield Quantiles

**Scope:** predicting the distribution of corn and soybean yield for an Iowa
county in a given year. Used by the Monte Carlo layer to turn a point-estimate
ROI into a distribution of outcomes.

**Status:** Results in §4. The climatology baseline ships for both crops.

---

## 1. What this model is for

The equipment decision depends on revenue per acre, which is yield times price.
Neither is known when the machine is bought. This model supplies the yield half
as a distribution rather than a number, so the engine can report *P(NPV > 0)*
instead of a single NPV that pretends the future is known.

It is **not** a field-level agronomic recommendation, and it is not calibrated
against any Deere data. It predicts a county-year aggregate from public data.

---

## 2. Data

| | |
|---|---|
| Yield | USDA NASS Quick Stats, `YIELD`, county level, Iowa, 2006–2025 |
| Rows | 1,876 corn county-years, 1,843 soybean county-years, 99 counties |
| Weather | Open-Meteo ERA5 historical archive at Census county centroids, daily, 2006-01-01 to 2025-12-31 |
| Units | Yield BU/ACRE; temperature °F; precipitation inches |

NASS suppresses some county-years, so the panel is not a complete
99 × 20 rectangle. Rows are dropped rather than imputed.

Weather is sampled at the county **centroid** from the nearest ~11 km ERA5 grid
cell — it is not an area average over the county polygon. PRISM at 800 m is the
documented upgrade path if the model ever turns out to be weather-limited; see
`sources.md` §3.

### Features

| Feature | Window | Rationale |
|---|---|---|
| `year` | — | Genetic and agronomic gain |
| `gdd_50_86` | May–Sep | Growing degree days, base 50 °F, tmax capped at 86 °F |
| `precip_in_apr_oct` | Apr–Oct | Season moisture |
| `precip_in_june` | June | Vegetative-stage moisture |
| `hot_days_jul_aug` | Jul–Aug | Days ≥ 90 °F: pollination and grain-fill heat stress |
| `tmax_f_july` | July | Mean daily maximum during pollination |
| `yield_lag1_bu_per_acre` | prior year | Same county, previous year — known before planting |
| *trend* | — | The baseline's own prediction, fitted on training years only |

The last row matters for fairness. The baseline gets a free intercept per
county; a booster given only weather would have to infer soil quality from
rainfall and would lose for a reason that says nothing about weather. Handing it
the baseline's prediction makes the question the right one: *given everything
the baseline knows, does weather add anything?*

---

## 3. Method

### Baseline — climatology

1. Fit `yield ~ year` with a free intercept per county, on training years only.
2. Detrend; take the empirical quantiles of the training residuals.
3. Forecast quantile *q* for year *t* = trend at *t* + residual quantile *q*.

No hyperparameters. About fifteen lines. It is hard to beat because county-level
annual weather is largely already priced into the trend and the county intercept.

### Challenger — quantile gradient boosting

`sklearn.ensemble.GradientBoostingRegressor(loss="quantile", alpha=q)`, one
model per quantile, library defaults, `random_state=0`.

Defaults were not tuned. Tuning until the challenger wins, on ten held-out
years, would be selecting a hyperparameter on the test set — the result would
not survive contact with 2026.

Deep learning was considered and rejected: ~1,900 county-year rows will not
support it, and an ML reviewer would rightly ask why a neural net was used here.
Recorded in the design doc §5.3.

### Evaluation

**Pinball loss** at quantiles 0.1, 0.25, 0.5, 0.75, 0.9, averaged.

**Held-out years, expanding window.** For each evaluation year *t*, train on
every row with `year < t` and score year *t*. Held-out years: 2016–2025, so the
smallest training window is ten years.

A random train/test split was rejected. It would put a year's rows in both train
and test through neighbouring counties, and would leak the time trend, which is
most of the signal. Both models would look better than they are, and the
challenger would gain more from the leak than the baseline.

---

## 4. Results

**The climatology baseline ships for both crops.** The gradient booster did not
earn its place.

Pinball loss, bu/acre, mean over quantiles (0.1, 0.25, 0.5, 0.75, 0.9), ten
held-out years 2016–2025. Lower is better.

| | Baseline | GBM | Mean change | Years GBM won |
|---|---|---|---|---|
| Corn | 5.244 | 5.076 | +3.21% | **4 of 10** |
| Soybeans | 1.464 | 1.521 | −3.93% | **4 of 10** |

Soybeans is unambiguous: worse on the mean, worse in most years.

Corn is the interesting case, and it is why the ship rule is not a mean
comparison. The booster beats the baseline by 3.21% on mean pinball loss — and
loses six of ten years. The entire margin comes from **2016**, where the baseline
scored 10.46 against the GBM's 5.95. Drop that one year and the booster is
**6.75% worse**. Its median per-year advantage is **−0.250 bu/acre**.

A mean over years is dominated by whichever year had the largest spread, so one
anomalous season can carry a model that is worse in most years. `verdict()`
therefore requires the challenger to win on **both** mean loss and a majority of
held-out years. Under a mean-only rule, corn would have shipped a model that is
worse in six years out of ten.

Excluding each crop's best GBM year:

| | Baseline | GBM | Change |
|---|---|---|---|
| Corn, excl. 2016 | 4.664 | 4.979 | **−6.75%** |
| Soybeans, excl. 2016 | 1.274 | 1.500 | **−17.72%** |

### Why this is the expected outcome

County-level annual weather aggregates are largely already priced into the trend.
The trend absorbs genetics, agronomy, and management jointly, and what remains is
dominated by within-season timing — whether rain arrived during pollination, not
how much fell over the year. A yearly total cannot see that.

This is a negative result, reported as one. The baseline is roughly fifteen lines
and has no hyperparameters. It was not tuned against, and the booster was not
tuned until it won.

### Fitted priors that do ship

| | Corn | Soybeans |
|---|---|---|
| Trend | 2.606 bu/ac/yr | 0.725 bu/ac/yr |
| Year-shock SD | 13.36 bu/ac | — |
| Price (lognormal median) | $4.32/bu | $10.48/bu |
| **Yield–price ρ** | **−0.706** | **−0.382** |

Both correlations are negative, as they must be: a large harvest depresses price.
Corn's is far stronger because Iowa is a large enough share of US corn supply for
state yield to move the national price, while soybean prices respond more to
export demand than to Iowa's crop. Modelling these as independent would
materially overstate revenue variance.

### A data caveat worth recording

Counties reporting per year fall over the window — corn 95 → 63, soybeans
97 → 57. That is NASS disclosure suppression increasing in recent years, not
counties ceasing to grow the crop. Recent years therefore rest on a smaller and
possibly non-random sample, which is a further reason not to over-read a
single-year result like 2016.

---

## 5. Limitations

- **County resolution, not field.** A 2,400-acre operation spans soil types this
  model cannot see. County yield is the right scale for an equipment decision and
  the wrong scale for an agronomic one.
- **Twenty years is a short trend window.** The fitted Iowa corn trend over
  2006–2025 is steeper than the long-run national figure usually quoted
  (~1.8 bu/ac/yr). The Theil–Sen confidence interval is wide and contains both.
  Projecting the trend ten years forward is the single largest source of model
  risk in the ROI engine, and it is an extrapolation, not a prediction.
- **Weather at a centroid, not a polygon.** See §2.
- **No CO₂, no cultivar, no management.** The trend absorbs all three jointly and
  cannot separate them, so it cannot say whether gains will continue at the same
  rate.
- **Prices are state-level.** NASS publishes no county price. The revenue model
  therefore pairs county yield with a state price and must not imply otherwise.
- **The empirical year-shock marginal cannot extrapolate.** Draws are clamped to
  the 2006–2025 observed range, so a drought worse than 2012 is outside what the
  simulation can produce.

---

## 6. Reproducing

```
uv run python scripts/fit_priors.py         # data/priors/yield_price.json
uv run python scripts/train_yield_model.py  # data/models/yield_bakeoff.json
```

Both are deterministic: seeds are fixed, no timestamps are recorded, and the
input file digests are written into the output. `fit_priors.py` is
byte-reproducible and reports whether the output changed.

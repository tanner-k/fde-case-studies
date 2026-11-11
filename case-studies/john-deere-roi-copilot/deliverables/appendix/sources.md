# Data Sources

Every dataset the model touches, with access method, coverage, and licence.
Verified 2026-08-10. Endpoints marked **verified** were called successfully; the
response shape quoted here is what actually came back, not what the docs promise.

---

## 1. USDA ERS — Commodity Costs and Returns

The per-acre cost and revenue budget underneath every scenario.

| | |
|---|---|
| Corn | `https://www.ers.usda.gov/media/4962/corn.csv` — **verified**, 926 KB, 5,665 rows |
| Soybeans | `https://www.ers.usda.gov/media/4976/soybeans.csv` — **verified**, 1.0 MB, 6,026 rows |
| Forecasts 2026F–2027F | `https://www.ers.usda.gov/media/4923/cost-of-production-forecasts-for-major-us-field-crops-2026f-2027f.csv` — **verified**, 306 rows, 9 crops |
| Access | Plain HTTPS GET. No key, no auth, no rate limit encountered. |
| Coverage | 1996–2025, annual |
| Licence | US Government work, public domain |

Landing pages are JavaScript-rendered and return an empty shell to scripted
fetches. The `media/<id>/<name>.csv` URLs above were extracted from the rendered
HTML and are stable, but the `?v=` query parameter changes on republication —
omit it.

**Schema** (tidy long format):
`Commodity, Category, Item, Units, Size, Region, Country, Year, Value, Survey base year`

**Regions are per-commodity.** Verified against the published files:

| | Regions |
|---|---|
| Corn (7) | Eastern Uplands · Heartland · Northern Crescent · Northern Great Plains · Prairie Gateway · Southern Seaboard · U.S. total |
| Soybeans (8) | the above **plus Mississippi Portal** (754 rows) |

Do not hardcode one region list for both commodities. Iowa falls in
**Heartland**. There is no county resolution — this is the finest geographic
cut ERS publishes, and the model must not imply otherwise.

> **The forecast file has no regional breakdown.** All 306 rows of the
> 2026F–2027F file are `U.S. total`. There is no Heartland 2026F/2027F figure to
> read off. Any forward-looking regional number must be *derived* — e.g. by
> carrying the historical Heartland-to-U.S. ratio forward — and labelled as
> derived in `assumptions.md`. This is material: the model's forward economics
> cannot cite ERS directly at the region level.

**Categories:** Gross value of production · Operating costs · Allocated overhead
· Costs listed · Net value · Production practices · Supporting information.

### Verified figures — Heartland, $/planted acre

| Year | Corn net (full cost) | Corn over operating | Soy net (full cost) | Soy over operating |
|---|---|---|---|---|
| 2021 | +226.59 | 644.10 | +174.44 | 544.27 |
| 2022 | +318.02 | 764.54 | +130.64 | 524.96 |
| 2023 | +25.60 | 496.59 | +34.28 | 467.21 |
| 2024 | **−115.26** | 372.76 | **−121.20** | 325.76 |
| 2025 | **−108.05** | 381.28 | **−110.15** | 338.17 |

2025 Heartland corn detail: yield 214 bu/planted acre · price $3.92/bu ·
chemicals $49.23 · fertilizer $169.71 · seed $119.55 · repairs $47.04 ·
fuel/lube/electricity $25.59 · capital recovery of machinery $173.63 ·
opportunity cost of land $229.57.

Corn has posted a negative full-cost net value in **19 of 30 years**, so a
negative figure is not by itself unusual. The back-to-back 2024–25 depth is.

> **Modelling note.** `Chemicals` is *all* crop protection — herbicide,
> insecticide, fungicide — not herbicide alone. See & Spray addresses only the
> non-residual herbicide portion, so this line is an upper bound on the savings
> base and must be decomposed before use.
>
> Decomposition completed — see `assumptions.md`. Treating $49.23 as addressable
> overstates the savings base by **~3.9× for corn and ~2.8× for soybeans**, not
> the factor of two originally estimated here. Two-thirds of the overstatement
> comes from the residual/non-residual split, not the
> herbicide/insecticide/fungicide split.

---

## 2. USDA NASS — Quick Stats

County-level yield and price history for distribution fitting.

| | |
|---|---|
| API | `https://quickstats.nass.usda.gov/api/api_GET/` — **verified** (returns `{"error":["unauthorized"]}` without a key) |
| Key | Free, self-service: <https://quickstats.nass.usda.gov/api> |
| Cap | 50,000 records per request |
| Bulk fallback | `https://www.nass.usda.gov/datasets/qs.crops_YYYYMMDD.txt.gz` — **verified**, 1.13 GB gzipped, **no key required** |
| Licence | US Government work, public domain |

**Decision: use the keyed API.** Iowa × {corn, soybeans} × 99 counties × 20 years
× a handful of statistics is roughly 8,000 records — comfortably inside the
50k cap. The 1.13 GB bulk dump is the no-key fallback and the reproducibility
anchor if the API is unavailable; streaming-filtering it costs minutes, the API
costs seconds.

Operators available on query parameters: `__LE __LT __GT __GE __LIKE
__NOT_LIKE __NE`.

> **Yield is county-level; price is not.** NASS publishes `PRICE RECEIVED` at
> state and national level only — a county-level price query returns empty. The
> extractor therefore issues two queries: county yield, state price. The model
> must not imply county-resolution prices.
>
> Status: reported by the ETL implementation, **not independently confirmed** —
> no API key was available. Confirm on the first real run.

### Crop Progress — weekly, state level

| | |
|---|---|
| Series | `CORN - PROGRESS, MEASURED IN PCT PLANTED` · `SOYBEANS - PROGRESS, MEASURED IN PCT PLANTED` · `CORN, GRAIN - PROGRESS, MEASURED IN PCT HARVESTED` · `SOYBEANS - PROGRESS, MEASURED IN PCT HARVESTED` |
| Days suitable | `FIELDWORK - DAYS SUITABLE, MEASURED IN DAYS / WEEK`, `statisticcat_desc=DAYS SUITABLE` |
| Access | Same Quick Stats endpoint and key as the yield/price pull above — **verified 2026-08-16** |
| Coverage | Progress 2006–2026 (21 years); days suitable 2006-04-02 through 2026-08-09, 714 weekly observations |
| Geography | **State only.** NASS does not publish crop progress by county, so every window derived from it is a statewide dispersion and an upper bound on a single farm's window. |

Corn grain harvest is filed under `CORN, GRAIN`, not `CORN`. Querying the
obvious string returns an empty result rather than an error, so
`etl/crop_progress.py` names each `short_desc` explicitly and raises on an
empty series.

No progress series exists for spraying, tillage or fertilizer application.

---

## 3. Weather — Open-Meteo Historical Archive

| | |
|---|---|
| Endpoint | `https://archive-api.open-meteo.com/v1/archive` — **verified** |
| Key | None |
| Verified back to | 1980 (ERA5 reanalysis extends to 1940) |
| Resolution | Daily, by lat/lon; snaps to the nearest ~11 km grid cell |
| Licence | CC-BY 4.0, free for non-commercial use |

Verified call — Story County, Iowa centroid (42.03, −93.46), May 2024:
returned `temperature_2m_max`, `temperature_2m_min`, `precipitation_sum` with
unit selection and timezone handling. Requesting Fahrenheit/inches returns them
directly; omitting the unit parameters silently returns Celsius/mm, which is a
live footgun for a units-sensitive model.

**Chosen over PRISM and NOAA nClimGrid.** PRISM is the USDA's official
climatology at 800 m and is the literature standard, but using it means
downloading rasters and aggregating grid cells to county polygons. At county
resolution, feeding a yield model whose signal is dominated by a linear time
trend, that pipeline buys precision the model cannot exploit. Open-Meteo at
county centroids is one HTTP call. If the yield model ever turns out to be
weather-limited rather than trend-limited, PRISM is the documented upgrade.

---

## 4. See & Spray economics — University of Arkansas (UADA)

**Primary source, and the most important one in this project.**

Avent, Norsworthy, Nalley, Barber, Scott. *Opportunity Costs to Consider when
Adopting See & Spray.* University of Arkansas System Division of Agriculture,
FSA2225-PD-9-2025 (September 2025).
<https://www.uaex.uada.edu/publications/pdf/FSA2225.pdf> — **verified**, 4 pp.

### Machine values and speeds

| Configuration | Value | Working speed |
|---|---|---|
| New base sprayer | $650,000 | 18 mph |
| See & Spray **Premium** | $750,000 | 12 mph |
| See & Spray **Ultimate** | $900,000 | 15 mph |

Premium can be retrofitted to qualifying existing Deere sprayers for
**$25,000–$100,000**. Ultimate cannot be retrofitted.

The speed figures are a cost the naive model misses entirely: Premium runs at
**two-thirds** the field capacity of the base machine. Fewer acres per hour
means more machine hours, more labour, and a narrower spray window — real costs
that partially offset the chemical savings.

> **Premium is single-tank, and this is first-order.** It cannot spot-spray a
> foliar herbicide while broadcasting a residual in the same pass — Ultimate's
> dual tank is precisely what buys that capability. So only passes whose tank
> carries **no** residual product are addressable at all.
>
> This matters enormously in Iowa, where overlapping residuals in the
> post-emergence pass are standard waterhemp practice. A grower following that
> program has a near-zero addressable spend on Premium regardless of their total
> herbicide bill. Worked example in `assumptions.md` §4.1: a University of
> Nebraska program is 60% non-residual by chemistry, but two of its three tanks
> carry a residual, leaving Premium only the **$9.27 burndown — below the $11
> break-even on its own.**
>
> The consequence for the model: adopting Premium profitably may require the
> grower to *restructure their herbicide program* toward a broadcast PRE plus a
> clean foliar POST. That is a real agronomic decision with weed-resistance
> implications, not a free software toggle.

### Subscription

**$5/acre in-crop, $1/acre fallow**, billed on the area *not* sprayed. The fee
scales with the benefit, which means it compresses the upside rather than acting
as a fixed hurdle. A Deere "Unlimited" license at ~$28,000 one-time is reported
in trade press but is **not** in the UADA analysis — treat as unverified.

### Area actually treated (Deere commercial data, 1.26M acres covered / 524k sprayed)

| Crop | Mean | 50% range |
|---|---|---|
| Corn | 44.6% | 24–64% |
| Cotton | 46.9% | 29–64% |
| Soybean | 46.1% | 25–66% |
| Fallow | 44.9% | 22–67% |

So roughly 55% of the field goes unsprayed — consistent with Deere's own
"59% average herbicide savings in 2024" and "nearly 50% in 2025" claims.

### Return on investment (Table 1, $/acre, net of subscription and opportunity cost)

| Herbicide cost $/A | Premium — corn | Premium — soybean | Ultimate — corn | Ultimate — soybean |
|---|---|---|---|---|
| 5 | −3.07 | −3.07 | −5.84 | −5.84 |
| 10 | −0.30 | −0.40 | −3.07 | −3.17 |
| **11** | **+0.25** | **+0.16** | −2.52 | −2.61 |
| 15 | +2.49 | +2.32 | −0.28 | −0.45 |
| 20 | +5.24 | +4.96 | +2.47 | +2.19 |
| 30 | +10.74 | +10.52 | +7.97 | +7.75 |

**Premium breaks even around $11/acre of targeted herbicide cost. Ultimate needs
roughly $15–16/acre.** Below those thresholds the technology loses money per acre.

### Payback, per UADA, at $20/acre targeted herbicide

| | Acres to pay back |
|---|---|
| Premium | 13,400 – 20,400 |
| Ultimate | 53,300 – 117,000 |

> **This contradicts the project's original framing and is the finding the case
> study should lead with.** The initial sketch assumed a 2,400-acre Iowa
> corn/soy operation with a ~3.8-year payback. Against UADA's figures, 2,400
> acres/year against a 13,400–20,400 acre payback is **5.6 to 8.5 years** for
> Premium — and that is at $20/acre targeted herbicide, which is high for Iowa
> row crop. Arkansas carries heavy resistant-pigweed pressure and correspondingly
> higher herbicide spend; the Heartland does not.
>
> The honest model output for the demo farm is therefore likely **"this does not
> pay off at your acreage"** — and a decision tool whose headline answer is *no*
> is far more credible than one that validates the purchase. It also makes the
> break-even acreage and the herbicide-cost threshold the genuinely interesting
> outputs, rather than a foregone NPV.

> **Correction — the Arkansas-vs-Iowa discount was wrong.** An earlier revision
> of this file assumed UADA's figures should be discounted for Iowa because
> Arkansas carries heavier resistant-pigweed pressure. In *dollar* terms that is
> not supported. Verified directly from `soybeans.csv`, `Chemicals` $/planted
> acre, Mississippi Portal vs Heartland:
>
> | Year | Heartland | Mississippi Portal | Gap | ERS base survey |
> |---|---|---|---|---|
> | 2019 | 39.06 | 50.77 | +30.0% | 2018 |
> | 2021 | 38.07 | 50.22 | +31.9% | 2018 |
> | 2022 | 58.07 | 76.30 | +31.4% | 2018 |
> | **2023** | 65.95 | 67.27 | **+2.0%** | **2023** |
> | **2024** | 52.63 | 53.41 | **+1.5%** | **2023** |
> | **2025** | 52.61 | 53.36 | **+1.4%** | **2023** |
>
> The ~31% gap was an artefact of the stale 2018 base survey and vanished on
> re-basing. Mid-South growers do apply **more by mass** (roughly +43% by rate),
> but of cheaper, higher-rate chemistry. Only dollars drive ROI, so **UADA's
> $11/acre break-even transfers to Iowa better than assumed — do not discount
> it.** Soybeans only; ERS publishes no Mississippi Portal corn budget.

---

## 5. Machinery cost method — Iowa State University Extension

| Document | File |
|---|---|
| Estimating Farm Machinery Costs | AgDM A3-29 (`/agdm/crops/pdf/a3-29.pdf`) |
| Machinery cost calculator | `/agdm/crops/xls/a3-29machcostcalc.xlsx` |
| Iowa Farm Custom Rate Survey | AgDM A3-10 |
| Ownership vs. custom hire, self-propelled | AgDM A3-33 |

Base: `https://www.extension.iastate.edu`

**Not scriptable.** All four return HTTP 403 to `curl` regardless of
user-agent and headers — bot protection, not a bad URL. These are
**manual downloads**, and the retrieved copies must be dated in
`assumptions.md` since the figures are revised annually.

Reference point from the 2025 custom rate survey: self-propelled sprayer custom
rate **$10.00/acre**. Useful as an independent sanity check on the modelled
ownership + operating cost, and as the "hire it instead" alternative that any
honest equipment analysis has to price.

The underlying method is ASABE D497 / EP496 (depreciation, interest, repair
factors, field capacity), which is published and implementable directly. ISU's
spreadsheet is the cross-check, not the dependency.

---

## 6. John Deere Operations Center API

| | |
|---|---|
| Discovery | `https://signin.johndeere.com/oauth2/aus78tnlaysMraFhC1t7/.well-known/oauth-authorization-server` |
| Sandbox base | `https://sandboxapi.deere.com/platform` |
| Production base | `https://api.deere.com/platform` |
| Accept header | `application/vnd.deere.axiom.v3+json` — **required**; plain JSON is rejected |
| Scopes | `ag1 ag2 ag3 eq1 eq2 org1 org2 files offline_access` |
| Sandbox limits | 1 test org per app · max 5 org connections · 150,000 calls/month · 18 months maximum |

**Access status: connected and inventoried, 2026-08-12.** One organization (ID withheld),
connection established, 40 link rels advertised. Ten of thirteen probed
collections return HTTP 200; `assets`, `fieldOperations`, and `files` return 403.

**Every collection is empty — zero records.** No figure in this project is
sourced from Operations Center. Full result and reasoning:
[`docs/decisions/0001-deere-provider.md`](../../docs/decisions/0001-deere-provider.md).

**Three traps, all confirmed against the live sandbox** (details and tests:
`docs/decisions/0001-deere-provider.md`):

1. **An unauthorized org returns 200 with an empty array**, not 401/403. A
   `connections` rel means incomplete; a `manage_connection` rel means
   established. Read wrong, "not connected yet" looks like "this farm has no
   fields."
2. **The established rel is singular** — `manage_connection`. Deere's docs say
   `manage_connections`. Matching only the documented spelling classifies a live
   connection as unknown.
3. **Sandbox links carry production URIs.** Everything returned by
   `sandboxapi.deere.com` points at `api.deere.com`. Following HAL links
   verbatim walks from sandbox into production against a real organization.
   Treat link URIs as identifiers and re-base onto the configured host.

Corollary of (3): `machines` is advertised at
`/isg/equipment?organizationIds=…`, a different service from
`/platform/organizations/{id}/…`. A guessed path returns a 403 that is really a
wrong URL.

Source: Deere's own reference implementation,
<https://github.com/JohnDeere/OperationsCenterAPI-OAuth2-Python-Example>.
The published docs at developer.deere.com are JavaScript-rendered and return an
empty shell to scripted fetches.

---

## 7. Equipment specifications and MSRP

Deere public product pages and the Build & Price configurator. Manual capture,
each row carrying a retrieval date — configurator pricing changes without notice
and is not a stable reference.

The UADA machine values in §4 are the preferred figures for modelling: they are
peer-reviewed, dated, and already expressed as the base-versus-equipped
comparison the model needs.

---

## 8. Field capacity and agronomic windows — `operations.json`

`data/reference/operations.json` is a **compiled** reference, not a retrieved
one: ten Iowa corn/soybean field operations, hand-entered on 2026-08-13, each
row carrying its own `machine_source` and `window_source` string and a
confidence tag.

| Field | Provenance | Confidence |
|---|---|---|
| `width_ft`, `speed_mph`, `field_efficiency` | ASABE D497 typical values by machine class; the sprayer's 120 ft / 18 mph / 0.75 is UADA FSA2225 (§4) | `typical_published`, sprayer `sourced` |
| `window_days` | Agronomic reasoning stated per row | `author_estimate` — **every row** |
| `passes_per_farm_acre_per_year` | Per-row reasoning about the 50/50 corn-soybean rotation and pass count, stated in each row's `passes_source` | `author_estimate` — **every row** |
| `useful_life_years` | A uniform 10-year life, an author assumption applied to every row rather than sourced per machine, stated in each row's `life_source` | `author_estimate` — **every row** |
| `custom_rate_usd_per_acre`, `custom_rate_responses` | Joined from ISU A3-10 2026 at load time | sourced (§5) |
| `rated_annual_hours` | ISU A3-29 wearout hours (sourced) divided by the hand-entered, author-estimated `useful_life_years` — not itself fully sourced, since the divisor is an assumption, not a measurement | sourced input, `author_estimate` divisor |
| `salvage_fraction` | The A3-29 remaining-value equation (§5), evaluated at `age_years = useful_life_years` and `annual_hours = rated_annual_hours` — both carry the author-estimated life | sourced input, `author_estimate` life |
| `repair_factor_rc1`, `repair_factor_rc2` | The A3-29 machine-type row, joined at load time | sourced (§5) |
| `list_price_usd` | UADA FSA2225 for the sprayer; `null` for the other nine | dated manual |

The joins are strict: `etl/reference.py` raises `ReferenceDataError` unless each
row resolves to exactly one A3-10 rate and exactly one A3-29 machine type. A3-10
operation names are PDF-parsed fragments and two of them repeat across sections,
so a fuzzy match would mis-price an operation silently.

**A3-10 has no bare rental market for sprayers, planters or combines.** The
survey's Machinery Rental section lists combine heads, grain carts, augers, a
grain vacuum, a skid loader and two fertilizer applicators — and no
self-propelled sprayer, no planter, no combine. That absence is evidence, and
it is asserted in `tests/test_etl_reference.py` so a re-parse cannot erase it
unnoticed.

---

## 9. Corn planting-date yield response — Abendroth, Woli, Myers & Elmore (2017)

| Field | Value |
|---|---|
| Citation | Abendroth, L.J., K.P. Woli, A.J.W. Myers, and R.W. Elmore. 2017. Yield-Based Corn Planting Date Recommendation Windows for Iowa. *Crop, Forage & Turfgrass Management* 3(1):1–7. |
| DOI | `10.2134/cftm2017.02.0015` |
| Licence | CC BY-NC-ND |
| Publisher URL | `https://acsess.onlinelibrary.wiley.com/doi/10.2134/cftm2017.02.0015` — **403** to a scripted client, the same ASA-CSSA-SSSA/Wiley host that blocks the See & Spray economics literature search (§4) |
| Retrieved from | `https://pdfs.semanticscholar.org/ea04/240143615041bb7b47188be43d265a13639d.pdf` — **200**, verified to be the correct paper by its title, author list, and abstract text after `pdftotext` extraction |
| Retrieved | 2026-08-17 |
| Table used | Table 2 (fitted quadratic coefficients, per site-grouping and per site, and the published optimum day-of-year); Table 3 (98–100% and 95–100% planting windows) used only to check the transcription in `tests/test_timeliness.py`, not stored in the JSON |

**Deliberately not archived in this repository.** The three ISU PDFs already
in `data/reference/` (A1-20, A3-10, A3-29) are extension publications with no
stated redistribution restriction beyond attribution. This is a peer-reviewed
journal article under a CC BY-**NC**-**ND** licence — no derivatives, and this
repository is headed for public — so only the coefficients it publishes are
transcribed into `data/reference/planting_date_response.json`, with this
citation, not the PDF itself.

**What it is.** An 18-site-year randomized complete block field trial (3–4
reps) at six Iowa State University Research and Demonstration Farms (2006,
2007, 2009), five planting dates per site-year on a sliding calendar scale
targeting 1 April–1 June. Table 2 fits `yield = b0 + b1x + b2x²` per
site-grouping, where `x` is planting date transformed to
`(DOY − 120) / 40` (the paper's Statistical Analysis section) — not raw
day-of-year. `engine/timeliness.py`'s `PlantingDateCurve`/`fitted_yield`
implement that transform; `tests/test_timeliness.py` proves it against two
numbers the paper itself publishes: the vertex of the fitted curve reproduces
Table 2's published optimum day-of-year to the nearest day, for all three
site-groupings (107.54 → 108, 114.46 → 114, 117.30 → 117 — the fractional
remainder is the published coefficients' one-decimal-place rounding, not a
transformation error), and the 98–100% window Table 3 publishes sits within 1.5 percentage points of
exactly 98% relative yield on the reconstructed curve — the residual gap is
Table 2's coefficients being published to one decimal place, not a
transformation error. See `deliverables/appendix/assumptions.md` §11.7 for the
sourcing verdict on the other nine operation classes this same search
covered, the site-grouping choice, and what this does and does not change
about the landscape exhibit.

---

## Excluded, and why

| Source | Reason |
|---|---|
| Machine telemetry, service history, failure labels | Not public. Predictive maintenance is designed in `docs/architecture.md` and deliberately not modelled. |
| PRISM 800 m rasters | Precision the county-level model cannot exploit. Documented upgrade path. |
| Deere See & Spray savings calculator | Vendor marketing tool, method not disclosed. Useful as a comparison point, not as a source. |
| "Unlimited license $28,000" | Trade-press only, absent from the UADA analysis. Unverified. |

---

## 9. Combine ownership, custom-hire, and timing evidence — research gate

Evidence reviewed 2026-09-22 is recorded in
`.superpowers/sdd/market-evidence.md` and `.superpowers/sdd/timing-evidence.md`.
The local archived A3-10 PDF and A3-29 workbook are the reproducible inputs;
dealer and manufacturer links below are dated public observations, not completed
transactions or quotes.

### Cost classes and hire scope

| Source | Directly supported fact | Limit on use |
|---|---|---|
| ISU A3-29 machinery-cost-calculator `Data` sheet; [parsed local record](../../data/reference/isu_a3_29_machine_data.json) | `Combine SP unit`: RC1 **0.025**, RC2 **2.1**, wearout **3,000 h**, remaining-value intercept **1.1318**, age coefficient **0.1645**, hour coefficient **0.0079**. `Combine head`: RC1 **0.05**, RC2 **2.3**, wearout **2,000 h**, with the same three remaining-value coefficients. | The two rows are distinct. Apply the base row once to the combine and the head row separately to each corn and draper head, using each asset's own price proxy and crop hours. The generic head row is a transparent sensitivity, not model-specific repair, condition, or resale evidence. |
| ISU, [2026 A3-10 / FM 1698](https://www.extension.iastate.edu/agdm/crops/pdf/a3-10.pdf), revised March 2026; [parsed local rates](../../data/reference/isu_a3_10_2026_custom_rates.json) | Survey sent to 1,122 people in February; **205** responses and **4,698** rates. It says rates include fuel, operator labour, repairs, depreciation, interest, and other machinery costs unless noted; diesel assumption was $2.89/gal. | Statewide planning-guide evidence, not a local offer, completed contract, or timing commitment. |
| Same A3-10 harvest rows | Combine-only averages: corn **$46.05/ac** (median $45; $25–80; 119 responses) and soybean **$43.05/ac** (median $42; $24–70; 94 responses). | These are crop-specific combine-only rates. They do not establish grain-cart, hauling, drying, trucking, contractor scheduling, or draper-head ownership cost. |
| Same A3-10 harvest rows | The indented row following soybean combining is **“with draper head” $48.20/ac** (median $45.50; $24–80; 95 responses). | A soybean-combining-with-draper service-rate sensitivity only; it is not a draper-head rental or purchase price. Keep it separate from the $43.05 generic soybean combine-only baseline. |
| Same A3-10 harvest rows | Complete harvesting (combine, grain cart, haul to farm storage) averages **$82.00/ac** corn and **$77.40/ac** soybean. | A different service package. It cannot be added to combine-only rows. It is comparable only after adding matching owner-side cart and haul-to-storage costs, or after excluding those services from both alternatives. |

### Equipment configuration observations

| Configuration / source | Public observation | Evidence boundary |
|---|---|---|
| [Deere X9 brochure, p. 21](https://www.deere.com/assets/pdfs/region-4/products/harvesting/x-series-combines/4592750-x-series-combines.pdf) | Its front-end compatibility table marks X9 compatibility for C12F and RD40F. | Supports a technically compatible X9 1100 + C12F + RD40F configuration, not delivered options, adapters, or price. |
| [MachineFinder X9 1100](https://www.machinefinder.com/ww/en-US/machines/2024-john-deere-x9-1100-combine-10468480) and [Equipment Trader RD40F](https://www.equipmenttrader.com/listing/2024-John%2BDeere-RD40F-5038372772) | Direct public asks/listings: 2024 X9 1100, 816 h, **Header: No**, $584,000; used 2024 RD40F, 40 ft, $125,900. | Both are asks, not transaction prices, new-equipment quotes, bundles, or scenario inputs. The C&B dealer-homepage reference for a $159,500 C12F does not directly identify that item and is excluded from any sum. |
| [TractorZoom S780](https://tractorzoom.com/equipment/2020-john-deere-s780-63386702-0cdb-4e92-a608-c65c5dc4e32d) and [Heritage/MarketBook C12R](https://www.marketbook.bo/listado/para-la-venta/251716985/2020-john-deere-c12r-cabezales-para-cultivos-en-hilera) | Direct public listings identify a 2020 S780, serial 1H0S780SHLT811388, **Header: No**, and a 2020 C12R 12R30, serial 1H0C12RXEL0815011, $91,700. | No archived S780 capture supports a stable price or hours claim; live listing values are volatile. The C12R lacks hours/acres and repair/inspection history. The TractorHouse model-search reference for a $71,500 RD40F does not directly identify that item, so it is excluded from a used-package sum and compatibility claim. |

These observations deliberately distinguish an **ask/list price** from a quote,
documented sale, or negotiated transaction price. A listing marked `Header: No`
also excludes a head from its base-combine price; heads may therefore be counted
only as separately priced assets. There is no dated public price for a genuinely
new compatible three-asset configuration, and no public evidence here supports
new or used head condition, repair history, or terminal resale by model. No
three-asset public-price sum is source-supported while exact C12F and used-RD40F
item URLs are absent.

### Timing sources

| Source | What it supports | What it does not supply |
|---|---|---|
| ISU, [A3-25 Days Suitable for Fieldwork](https://www.extension.iastate.edu/AGDm/crops/pdf/a3-25.pdf), revised February 2025 | Iowa NASS 1964–2024 medians: Sep. 10–Oct. 28 statewide **38.4** suitable days; districts **36.0–38.7**. Published weekly statewide medians in that interval are 5.4–5.8 days; multiply by **0.84** where Sundays/holidays are not worked. | A crop-specific date window, forecast, operating hours/day, or outage allowance. Medians are not a low/high probability distribution. |
| USDA NASS, [Crop Progress terms](https://www.nass.usda.gov/Publications/National_Crop_Progress/terms_definitions.php) and [Iowa 2024 review](https://www.nass.usda.gov/Statistics_by_State/Iowa/Publications/Crop_Progress_%26_Condition/2024/IA-Annual-Crop-Progress-2024.pdf) | A suitable day allowed field work for a major portion of the day. In 2024, corn and soybean harvest both began the week ending Sep. 15; soybeans were 81% complete Oct. 13 and corn 68% Oct. 20. | A farm-level start/finish deadline, a conversion from suitable days to machine hours, or a claim that the crops can be sequenced without overlap. |
| ISU, [A3-28 Farm Machinery Selection](https://www.extension.iastate.edu/Agdm/crops/html/a3-28.html) and [A3-42 grain-system sizing tool](https://www.extension.iastate.edu/AGDM/crops/html/a3-42.html) | A3-28's worked example uses 12 h/day; A3-42 requires users to enter days/week and hours/day and considers headers, carts, labor, transport, and offload time. | A universal 12 h/day default, head-change time, crew availability, repair/downtime range, or capacity for this farm. |
| ISU, [A3-33 ownership versus custom hire](https://www.extension.iastate.edu/agdm/crops/pdf/a3-33.pdf) | Custom operators may be unavailable in the optimum period when weather and waiting farms intervene; schedule or priority should be agreed in advance. Specialized heads and cart/haul services may be separate or bundled. | A named contractor's availability, equipment, priority, or completion commitment. |

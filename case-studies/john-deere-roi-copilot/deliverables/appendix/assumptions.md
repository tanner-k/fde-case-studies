# Assumptions

Every modelled number, with its source, its status (**measured** or **estimated**),
and its uncertainty range. Estimates are labelled as estimates. No number here is
invented; where a figure could not be sourced, the reasoning behind the estimate is
shown in full so a reader can disagree with it explicitly.

Retrieval dates are the date the URL was actually fetched, not the publication date.
Both are given.

---

## 1. The question this file exists to answer

USDA ERS publishes a single `Chemicals` operating-cost line: **$49.23/planted acre**
for Heartland corn and **$52.61** for Heartland soybeans, 2025. That line is herbicide
*plus* insecticide *plus* fungicide.

See & Spray does not address all of it. It addresses only herbicide applied to
**emerged weeds** — burndown and post-emergence foliar products. Residual
(soil-applied, pre-emergence) herbicide is broadcast regardless, because its job is to
kill weeds that have not germinated yet and there is nothing on the ground for a camera
to see.

University of Arkansas (FSA2225, Sept 2025 — see `sources.md` §4) puts See & Spray
**Premium** break-even at roughly **$11/acre of targeted herbicide**. Below that the
technology loses money per acre. So the decomposition of that $49.23 is not a detail —
it is the number that decides the model's headline answer.

This file derives that decomposition in three steps:

```
ERS Chemicals total  ──×  herbicide share  ──×  addressable share  ──►  targeted $/acre
   (measured)             (measured, §3)       (estimated, §4)          (§5)
```

---

## 2. Method, and why it is built this way

Two families of source were available, and they disagree:

| | ERS Commodity Costs & Returns | University enterprise budgets |
|---|---|---|
| What it is | Survey of what farmers **actually spent** (ARMS) | A **recommended full program** priced at list |
| Granularity | One `Chemicals` line | Line-by-line, often product-by-product |
| Level, corn | $49.23/acre | $45–$62/acre herbicide **alone** |

Bottom-up totals from university budgets run **15–40% above** the ERS line (§6). That
gap is not an error in either source. ERS measures realised expenditure — farmers buy
on program discounts, use generics, cut rates, and skip passes. University budgets
specify a complete, agronomically defensible program at published prices.

**So the model uses ERS for the *level* and university budgets for the *proportions*.**
Anchoring the level on prescriptive budgets would inflate the savings base by a third
and bias the entire ROI toward "buy". This choice is the single most consequential
methodological decision in the case study.

---

## 3. Herbicide share of the `Chemicals` line — **measured**

The strongest evidence is a same-crop, same-year, national reconciliation between two
methodologically independent sources.

**Source A.** Singh, M. and Jhala, A.J. (2025). *Perspectives on the economics of
herbicide usage in corn and soybean production in the United States.* Weed Technology
39: e19. <https://doi.org/10.1017/wet.2025.19> — retrieved 2026-08-11.
Peer-reviewed. Method: USDA-NASS active-ingredient usage × average retail price from
2021–2023 Kansas State / Nebraska / North Dakota State extension price lists.
**Herbicide only. Excludes adjuvants and application cost.**

**Source B.** USDA ERS Commodity Costs & Returns, `Chemicals`, U.S. total, same year.
`https://www.ers.usda.gov/media/4962/corn.csv` and `.../4976/soybeans.csv` —
retrieved 2026-08-11.

| Crop | Year | Singh & Jhala herbicide | ERS `Chemicals`, U.S. | Herbicide share |
|---|---|---|---|---|
| Corn | 2021 | $88/ha = **$35.61/ac** | **$41.32/ac** | **86.2%** |
| Soybean | 2023 | $125/ha = **$50.59/ac** | **$61.12/ac** | **82.8%** |

Conversion: 1 ha = 2.47105 ac. Both ERS years are ERS **base survey years** for their
crop (`Base survey of 2021` for corn, `Base survey of 2023` for soybeans), so these are
directly surveyed values, not index-projected ones. That is the cleanest possible
comparison and it was available by luck rather than design.

**Corroboration — Iowa acres treated.** USDA NASS, *Iowa Ag News – Chemical Use,
Soybeans: Fall 2023*, released 2024-05-13
(<https://www.nass.usda.gov/Statistics_by_State/Iowa/Publications/Other_Surveys/2024/IA-Ag-Chem-Soybeans-05-24.pdf>,
retrieved 2026-08-11): herbicide active ingredients applied to **95%** of Iowa soybean
planted acres; **fungicide 33%**, **insecticide 29%**. Applying representative product
costs (fungicide ~$20–25/treated acre, insecticide ~$3–5/treated acre) gives a non-herbicide
load of roughly $7–9/acre against an ERS total of $52.61 — i.e. a herbicide share of
83–87%. Independent, Iowa-specific, and consistent with Source A.

| Parameter | Value | Range | Status |
|---|---|---|---|
| Herbicide share of `Chemicals`, corn | **0.85** | 0.78 – 0.90 | measured, reconciled |
| Herbicide share of `Chemicals`, soybean | **0.84** | 0.76 – 0.90 | measured, reconciled |

Range widened beyond the two point estimates because Sources A and B use different
price bases (list vs realised) and the two crops differ by 3.4 percentage points on a
sample of two.

### Resulting three-way decomposition, Heartland 2025 — $/planted acre

| Component | Corn | Soybean | Status |
|---|---|---|---|
| **Herbicide** | **$41.85** (38.40 – 44.31) | **$44.19** (39.98 – 47.35) | measured, §3 |
| Fungicide | ~$6.5 (3 – 10) | ~$7.0 (4 – 11) | **estimated** |
| Insecticide | ~$0.9 (0.3 – 2) | ~$1.4 (0.5 – 3) | **estimated** |
| **Total (= ERS)** | **$49.23** | **$52.61** | measured |

The fungicide/insecticide split is an **estimate**, and the weakest number in this
file. It is the residual after herbicide, apportioned using NASS acres-treated (33%
fungicide / 29% insecticide for Iowa soybeans) and the observation that fungicide costs
roughly five times as much per treated acre as insecticide. Supporting line items:
Ohio State 2026 budgets carry $22.50/acre fungicide on high-yield ground and $0 on
average ground; UNL 2026 soybean budgets carry $2.50–$3.89 fungicide and $1.01
insecticide at 10–20% of acres. **The model does not depend on this split** — See &
Spray addresses neither category — so it is reported for completeness and audit, not
used downstream.

---

## 4. Residual vs non-residual herbicide — **estimated**, and this is the crux

### 4.1 Why this is harder than it looks

No public source publishes "dollars of residual vs non-residual herbicide per acre for
Iowa." Three things make the number genuinely ambiguous:

1. **Timing ≠ chemistry.** A post-emergence *pass* routinely carries a residual
   *product* (overlapping residuals — Warrant, Zidua, Dual — are standard Iowa
   waterhemp practice). So "post-emergence spend" overstates spot-sprayable spend.
2. **Premixes straddle the line.** Warrant Ultra is acetochlor (residual) plus
   fomesafen (foliar) in one jug at one price.
3. **The machine constrains the program.** See & Spray **Premium is a single-tank,
   single-boom system**. It physically cannot spot-spray a foliar herbicide while
   broadcasting a residual in the same pass — that is what the dual-tank **Ultimate**
   adds. Sources: University of Wisconsin–Madison, Werle, R., *You upgraded to the John
   Deere See & Spray™ Premium precision system, now what?*, 2024-04-10,
   <https://wiscweeds.info/posts/2024see&spraypremium/> (retrieved 2026-08-11);
   corroborated by RDO Equipment and MachineFinder product documentation.

   **Consequence: for Premium, only passes containing no residual at all are
   addressable.** This is a hard constraint the naive "herbicide × 50% savings" model
   misses entirely, and it is where most of the addressable spend is lost.

Werle's recommended adaptation is to move all residual chemistry to a broadcast PRE
and run a clean foliar POST (his worked example: PRE = Authority First + Zidua
broadcast; POST = Liberty + Enlist One + clethodim, spot-sprayed). A grower who
restructures this way maximises addressable spend; one who keeps overlapping residuals
in the POST pass has almost none.

### 4.2 Evidence — post-emergence *pass* share of herbicide spend

**Purdue.** Stephens, M. (Carns), under Fiechter, C. *Indiana Herbicide Program Costs
Through the Lens of Geography.* Purdue Center for Commercial Agriculture, 2026-04-28.
<https://ag.purdue.edu/commercialag/home/resource/2026/04/indiana-herbicide-program-costs-through-the-lens-of-geography/>
— retrieved 2026-08-11. Authors' calculations from Purdue Agricultural Centers'
Enterprise Budgets 2026, **corn**. Values read from Figures 1 and 2 of the article.

| Purdue Ag Center | Pre share | Post share |
|---|---|---|
| PPAC (Valparaiso, N) | 45% | 55% |
| SWPAC (Vincennes, S) | 52% | 48% |
| NEPAC (Fort Wayne, N) | 47% | 53% |
| SEPAC (Columbus, S) | 62% | 38% |
| FPAC (Bedford, S) | 44% | 56% |
| DPAC (Muncie, C) | 49% | 51% |
| ACRE (Lafayette, C) | 63% | 37% |
| **Mean** | **51.7%** | **48.3%** |

Regional dollar totals from the same article (Figure 1): North $62/acre ($28 pre /
$34 post), Central $49 ($24/$25), South $57 ($33/$24).

**This is a post-*pass* share, not a non-residual share.** The article states plainly
that post-emergence products at these sites include **s-metolachlor** — a Group 15
residual. So 48.3% is an **upper bound** on the addressable fraction, not an estimate
of it.

### 4.3 Evidence — product-level programs, classified by chemistry

Four publicly-priced, product-level budgets. Costs are **materials only**; custom
application charges are excluded, matching ERS, where `Custom services` is a separate
line ($37.95/acre for Heartland corn 2025). All figures verified by recomputing rate ×
price. Retrieved 2026-08-11.

**a. UNL #016 — Corn, Dryland, Conventional Seed, Corn-Soybean Rotation, 2026**
(<https://cap.unl.edu/cropbudgets>; input prices surveyed Aug–Oct 2025)

| Pass | Product | $/ac | Class |
|---|---|---|---|
| PRE | Lumax EZ, 2.7 qt | 50.63 | residual |
| POST (50% of acres) | Laudis + MSO + UAN | 10.91 | foliar |
| **Total herbicide** | | **61.54** | **17.7% addressable** |

**b. UNL #059 — Soybeans, Dryland, Conv. Till after Corn (XtendFlex), 2026**

| Pass | Product | $/ac | Class |
|---|---|---|---|
| PRE | Zidua Pro, 5.25 oz | 24.90 | residual |
| POST | Glyphosate + AMS + Select Max + FlexStar GT | 30.84 | foliar |
| **Total herbicide** | | **55.74** | **55.3% addressable** |

**c. UNL #060 — Soybeans, Dryland, No-Till after Corn (Enlist E3), 2026**

| Pass | Product | $/ac | Class |
|---|---|---|---|
| Burndown | Glyphosate + 2,4-D Ester + AMS | 9.27 | foliar |
| PRE | Glyphosate + AMS + **Fierce MTZ** | 11.78 | mixed — tank contains residual |
| POST | Glyphosate + **Warrant Ultra** + Select Max + AMS | 36.47 | mixed — tank contains residual |
| **Total herbicide** | | **57.52** | **16.1% addressable as written** |

Budget (c) is the clearest illustration of the single-tank constraint. By chemistry,
~60% of its herbicide dollars are non-residual. But two of its three passes carry a
residual in the tank, so a Premium machine can only spot-spray the $9.27 burndown —
**16% of spend, and below the $11 break-even on its own.** Restructured per Werle
(residuals consolidated into PRE), addressable rises to roughly $19–20/acre.

**d. University of Missouri Extension, Southeast Missouri Crop Budget, 2021 Enlist
Soybean** (<https://extension.missouri.edu/media/wysiwyg/Extensiondata/CountyPages/Scott/CropBudgets/Soybeans-Enlist.pdf>):
explicit line items — Pre-Emerge $17.00, Post-Emerge 2 × $16.00 = $32.00, herbicide
total $49.00 → **65.3% post-pass**. Also Fungicide $15.00, Insecticide $5.00.
*Regional bias: SE Missouri is Delta, with Palmer amaranth pressure well above Iowa's.
Expect this to overstate the Iowa post share.*

### 4.4 The estimate

Addressable share ranges from 16% to 65% across four priced programs, and the spread is
driven by **program design, not geography**. This is a real property of the problem, not
noise to be averaged away: the same farm can move its own addressable share by 30
percentage points by choosing where to put its residuals.

| Parameter | Value | Range | Status |
|---|---|---|---|
| Addressable (non-residual, single-tank-compatible) share of herbicide spend, **corn** | **0.30** | 0.18 – 0.45 | **estimated** |
| Addressable share, **soybean** | **0.42** | 0.25 – 0.60 | **estimated** |

**Reasoning, shown so it can be argued with:**

- *Corn.* Purdue's Indiana corn post-*pass* share averages 48.3% (37–56%). Discounting
  for residual carried in the post tank — the Purdue text names s-metolachlor
  explicitly — takes the non-residual fraction to roughly 29%. UNL #016 gives 17.7%,
  but on conventional (non-GM) seed with no glyphosate in the POST, which understates a
  typical Iowa glyphosate/glufosinate-tolerant program. Centre **0.30**; floor at the
  UNL observation, ceiling below the undiscounted Purdue mean.
- *Soybean.* Soybean POST passes are richer than corn's — Enlist and XtendFlex systems
  carry expensive foliar chemistry (Liberty, Enlist One, FlexStar GT, clethodim).
  Observations: 55% (UNL #059), 65% (MO, Delta-biased high), 16% as-written / ~34%
  restructured (UNL #060). Centre **0.42**; range spans the restructure decision.
- **Uncertainty is roughly ±40% on the mode for both crops, and it is dominated by
  program design, not by measurement error.** Stated plainly: this is the least certain
  number in the model and the one that most deserves to be a user-facing slider rather
  than a constant.

**What would tighten this.** Iowa State's *Herbicide Guide for Iowa Corn and Soybean
Production* (WC 94) prices individual treatments and would give an Iowa-specific,
product-level split. It could not be retrieved — `extension.iastate.edu` serves an
Anubis proof-of-work bot challenge to automated clients (§7). It is a manual download,
and it is the highest-value single addition to this analysis.

---

## 5. Targeted herbicide spend — the model input

Heartland, 2025, $/planted acre. Derived as `ERS Chemicals × herbicide share ×
addressable share`.

| | Corn | Soybean | 50/50 rotation |
|---|---|---|---|
| ERS `Chemicals` (measured) | 49.23 | 52.61 | 50.92 |
| × herbicide share | 0.85 | 0.84 | — |
| = herbicide $/ac | 41.85 | 44.19 | 43.02 |
| × addressable share | 0.30 | 0.42 | — |
| **= targeted $/ac (mode)** | **$12.55** | **$18.56** | **$15.56** |
| low | $6.91 | $10.00 | $8.46 |
| high | $19.94 | $28.41 | $24.18 |

Machine-readable: `data/priors/crop_protection_split.json`.

### Against the UADA break-even

See & Spray **Premium** breaks even at ~**$11/acre** targeted herbicide; **Ultimate** at
~**$15–16/acre** (`sources.md` §4, UADA FSA2225 Table 1).

| | Corn | Soybean | 50/50 rotation |
|---|---|---|---|
| Mode vs Premium ($11) | **+$1.55, marginal** | +$7.56, clears | +$4.56, clears |
| Mode vs Ultimate ($15.50) | **−$2.95, below** | +$3.06, clears | ~breakeven |
| P(below Premium break-even) | **~40%** | ~10% | ~20% |

The low end of both ranges sits **below** the Premium break-even. Corn's mode sits
$1.55 above it — inside the estimate's own uncertainty, which means the honest
statement is *"for Iowa corn, this is a coin-flip, not a yes."*

---

## 6. Reconciliation against the ERS totals — a finding, not a fudge

Bottom-up sums of university budget chemical lines, against ERS Heartland 2025.
Materials only, application excluded.

| Budget | Herb | Fung | Insect | Total | vs ERS |
|---|---|---|---|---|---|
| **ERS Heartland corn 2025** | — | — | — | **$49.23** | — |
| Ohio State 2026 corn, avg yield | 45.00 | 0 | 0 | 45.00 | 91% |
| Ohio State 2026 corn, high yield | 45.00 | 22.50 | 0 | 67.50 | 137% |
| UNL #016 corn 2026 | 61.54 | 0 | 0.87 | 62.41 | 127% |
| Purdue Indiana corn 2026 (herbicide only) | 49–62 | — | — | 49–62 | 100–126% |
| **ERS Heartland soybean 2025** | — | — | — | **$52.61** | — |
| Ohio State 2026 soy, avg yield | 46.00 | 0 | 0 | 46.00 | 87% |
| Ohio State 2026 soy, high yield | 46.00 | 22.50 | 0 | 68.50 | 130% |
| UNL #059 soy 2026 | 55.74 | 3.89 | 1.01 | 60.64 | 115% |
| UNL #060 soy 2026 | 57.52 | 2.50 | 1.01 | 61.03 | 116% |

**Finding: prescriptive university budgets exceed the ERS survey line by 15–40%**, and
Purdue's Indiana *herbicide alone* meets or exceeds ERS's *all-chemicals* total. Ohio
State is the exception, landing 9–13% below ERS on average-yield ground — because it
carries no fungicide there.

This is a level disagreement, not a proportion disagreement, and it is why §2 anchors
the level on ERS. Reported rather than reconciled away.

Ohio State source: *2026 Corn / Soybean Production Budget*, updated 2026-05-27,
`https://farmoffice.osu.edu/sites/aglaw/files/site-library/farmmgtpdf/enterprisebudgets/corn-con2026%20May27.xlsx`
(and `soy-con2026%20May27.xlsx`) — retrieved 2026-08-11. Cross-check: Singh & Jhala
independently cite an Ohio State corn herbicide figure of $114/ha; the 2026 file gives
$45.00/ac = $111.2/ha. Agreement to 2.5% confirms the extraction.

Purdue's own state budget (ID-166-W, *2026 Purdue Crop Cost and Return Guide*, January
2026 estimates, published in PAER 2026-08,
<https://ag.purdue.edu/commercialag/home/wp-content/uploads/2026/03/PAER-2026-08.pdf>,
retrieved 2026-08-11) reports only an aggregate `Pesticides` line: **$110/ac** rotation
corn, **$115** continuous corn, **$70** rotation soybeans. That is 2.2× and 1.3× the ERS
Heartland figures respectively, and is **not used** — it is the most extreme case of the
prescriptive-budget bias described in §2.

---

## 7. Regional bias: Arkansas vs Iowa — the premise is weaker than assumed

The project's working assumption (`sources.md` §4) was that UADA's Arkansas break-even
overstates Iowa economics because Arkansas carries heavy resistant-pigweed pressure and
correspondingly higher herbicide spend. **The expenditure data only partly support
this.**

ERS soybean `Chemicals`, $/planted acre, Heartland vs Mississippi Portal (the ERS region
containing Arkansas). Retrieved 2026-08-11.

| Year | Heartland | Mississippi Portal | Gap |
|---|---|---|---|
| 2021 | 38.07 | 50.22 | +31.9% |
| 2022 | 58.07 | 76.30 | +31.4% |
| **2023 (base survey year)** | **65.95** | **67.27** | **+2.0%** |
| 2024 | 52.63 | 53.41 | +1.5% |
| 2025 | 52.61 | 53.36 | +1.4% |
| 5-year mean | 53.47 | 60.11 | +12.4% |

**Reading this correctly matters.** ERS re-bases its regional budgets on a survey year
and index-projects the others. The soybean series is `Base survey of 2023`. So 2023 is
the only directly-surveyed year in this window, and in it the Mid-South premium is
**+2.0%** — not the 2× the framing assumed. The large 2021–22 gaps are artefacts of the
previous (2018) base survey being carried forward, and were erased by the 2023 re-base.

**Direction of the correction: this makes UADA's break-even *more* transferable to Iowa,
not less.** The case study should stop discounting UADA's $11/acre as an
Arkansas-inflated figure.

**Counter-evidence, in physical terms.** Singh & Jhala report herbicide use *rates*:
Iowa corn 2.66 kg/ha, Iowa/Illinois soybean ~2.87–2.90 kg/ha, Mississippi soybean
4.15 kg/ha (+43% vs Iowa). So the Mid-South does apply substantially more active
ingredient — but at similar total cost, because the extra volume is cheap, high-rate
chemistry. Mass and dollars diverge, and only dollars drive this ROI.

**No corn comparison is possible.** ERS does not publish a corn budget for Mississippi
Portal. This section is soybean-only, and that limitation should not be papered over.

*Caveat.* This compares total `Chemicals`, not targeted herbicide. UADA's practice
context — three to four passes per season in the Mid-South — could still put a larger
*share* of Arkansas spend in the addressable post-emergence bucket than in Iowa, which
would mean the $11 break-even is reached on fewer Arkansas acres. That refinement is
unsourced and is **not** applied.

---

## 8. Parameter summary

| # | Parameter | Value | Range | Status | Section |
|---|---|---|---|---|---|
| 1 | ERS `Chemicals`, Heartland corn 2025 | 49.23 | — | measured | §1 |
| 2 | ERS `Chemicals`, Heartland soybean 2025 | 52.61 | — | measured | §1 |
| 3 | Herbicide share, corn | 0.85 | 0.78–0.90 | measured | §3 |
| 4 | Herbicide share, soybean | 0.84 | 0.76–0.90 | measured | §3 |
| 5 | Fungicide, corn / soybean | 6.5 / 7.0 | 3–10 / 4–11 | **estimated** | §3 |
| 6 | Insecticide, corn / soybean | 0.9 / 1.4 | 0.3–2 / 0.5–3 | **estimated** | §3 |
| 7 | Addressable share, corn | 0.30 | 0.18–0.45 | **estimated** | §4 |
| 8 | Addressable share, soybean | 0.42 | 0.25–0.60 | **estimated** | §4 |
| 9 | Targeted herbicide, corn | 12.55 | 6.91–19.94 | derived | §5 |
| 10 | Targeted herbicide, soybean | 18.56 | 10.00–28.41 | derived | §5 |
| 11 | Premium break-even | 11.00 | — | measured (UADA) | §5 |
| 12 | Ultimate break-even | 15.50 | 15–16 | measured (UADA) | §5 |

Parameters 7 and 8 carry the model. Parameters 5 and 6 carry nothing and are here only
so the decomposition closes against the ERS total.

---

## 9. Known gaps

| Gap | Effect | Fix |
|---|---|---|
| **Iowa State A1-20 and WC 94 not retrieved.** `extension.iastate.edu` serves an Anubis proof-of-work bot challenge to automated clients; HTTP 403 to `curl` and to server-side fetches. Not bypassed. | The only Iowa-specific figures used here are secondary: Singh & Jhala cite an ISU corn herbicide budget of $98/ha = **$39.66/ac** and an ISU herbicide-tolerant soybean budget of $180/ha = **$72.84/ac**. The corn figure sits within the §3 range ($38.40–44.31); the soybean figure is far above it and is **not used**. | Manual download of A1-20 and WC 94, dated on retrieval. Highest-value single addition. |
| No public source gives a residual/non-residual **dollar** split for Iowa. | §4 is an estimate at ±40%. | ISU WC 94 treatment pricing, or a dollar-weighted classification of NASS Iowa active-ingredient data against a retail price list. |
| Fungicide/insecticide split is inferred, not measured. | None — unused downstream. | NASS Quick Stats acres-treated × price, per crop. |
| No corn Arkansas-vs-Iowa comparison exists in ERS. | §7 is soybean-only. | None available in ERS; would need state budgets. |
| Purdue Figures 1 and 2 were read off charts, not tables. | Values carry ±1–2 pp / ±$1 reading error. | Request the underlying PAC enterprise budgets from Purdue. |

---

## 10. Corrections requested to `sources.md`

Not edited directly, per project convention. Three items:

1. **§4 note — "Arkansas carries heavy resistant-pigweed pressure and correspondingly
   higher herbicide spend; the Heartland does not."** Only partly supported. In the ERS
   2023 base survey year, Mississippi Portal soybean `Chemicals` exceeded Heartland by
   **2.0%**, not by a wide margin (§7). The physical use rate is +43%, but the
   expenditure gap is not. This *strengthens* the transferability of UADA's $11/acre
   break-even to Iowa.

2. **§1 modelling note — "Treating $49.23 as the addressable spend would overstate
   savings by roughly a factor of two."** The measured factor is larger: **~3.9×** for
   corn ($49.23 → $12.55) and **~2.8×** for soybeans ($52.61 → $18.56). Two-thirds of
   the overstatement comes from the residual/non-residual split, not from the
   herbicide/insecticide/fungicide split.

3. **§4 — the Premium/Ultimate difference is understated.** `sources.md` records the
   speed and price difference but not the **tank architecture**: Premium is single-tank
   and cannot spot-spray while broadcasting a residual; Ultimate is dual-tank and can.
   This is a first-order constraint on the savings base (§4.1), not a specification
   detail — for a grower who keeps overlapping residuals in the post pass, it takes
   Premium's addressable spend to near zero.

---

## 11. Landscape exhibit — window lengths and quadrant cuts

The three-panel landscape plot (`deliverables/figures/landscape-quadrants.png`,
built by `scripts/figures.py`) puts annual machine hours on x and agronomic
window length on y, sizes each point by ISU A3-10 custom-market depth, and
labels break-even acreage where a list price is sourced.

### 11.1 Four of ten window lengths are now measured; six remain author estimates

Through Phase 1, `window_days` in `data/reference/operations.json` was **not
sourced** for any row. Phase 2 replaces four of the ten: NASS Crop Progress
publishes weekly percent-complete for planting and harvest, and
`etl.reference.load_operations`'s `measured_windows` argument substitutes the
25th–75th percentile span (§11.2.1) for the estimate wherever an operation's
`nass_series_key` resolves against the panel.

| Operation | `nass_series_key` | Phase 1 estimate | Phase 2 measured (25–75) |
|---|---|---|---|
| Combine, corn head | `corn_harvested` | 30 d | 19.0 d |
| Combine, draper head | `soybean_harvested` | 14 d | 14.5 d |
| No-till planter | `corn_planted` | 21 d | 11.0 d |
| High-speed planter | `corn_planted` | 21 d | 11.0 d |

Both planters map to `corn_planted`, not to `soybean_planted`, deliberately:
a planter plants both crops, and corn is planted first and is the
timeliness-critical half of the rotation. Their `window_confidence` is now
`measured`, and `window_source` records the percentile pair, years observed,
the observed min–max range, and the median suitable-fieldwork days behind the
figure.

The remaining six keep an author estimate and `author_estimate` confidence,
because NASS publishes no crop-progress series for them at all: spraying,
tillage (field cultivating, vertical tillage, chisel plowing), and fertilizer
application (anhydrous, dry spreader) have no percent-complete survey to
measure — `nass_series_key` is `null` for all six.

**The self-propelled sprayer is one of the six.** It is both the exhibit's
flagship point and, at every farm size tested in Phase 1 and again in
Phase 2, the operation with the strongest market-depth agreement — genuinely
low-utilization and narrow-window all the way to 10,000 acres. Its 10-day
window is still the author's herbicide-label reasoning, not a measurement,
and NASS has no spraying progress series to measure it against. **Phase 2
measures four of ten windows, not ten**; that gap is structural — a limit of
what NASS's survey covers — not an oversight, and no source identified so far
closes it for the remaining six.

Machine geometry (`width_ft`, `speed_mph`, `field_efficiency`) is tagged
`typical_published` — ASABE D497 typical values for the machine class — except
the sprayer, which is `sourced` to UADA FSA2225 and matches the values already
used in `engine/models.py`.

### 11.2 The quadrant cuts are declared, not derived

| Cut | Value | Basis |
|---|---|---|
| Low utilization | ≤ 200 machine hours/year | Author-chosen; not derived. A round number at which the fixed ownership charge per acre is materially higher than the published per-acre custom rate. |
| Narrow window | ≤ 14 days | Two weeks. An operation that cannot slip a fortnight cannot be rescheduled around a service provider's queue. |
| Deep custom market | ≥ 70 A3-10 responses | Roughly a third of the survey's 205 respondents offering the service. |

**These were fixed before the plot was run and must not be tuned to improve the
agreement rate.** Market depth is an overlay used to validate the model (spec
§4); using it to choose the cuts would make the exhibit circular.

**The 200-hour cut is a judgment call, not a derived number, and an earlier
version of this table overstated its basis.** It previously read "half the
400 h/yr rated annual use this repository's ASABE cost basis assumes for a
self-propelled machine." That basis does not exist in this repository:
`400.0` appears nowhere except as an example annual-use value in four test
fixtures (`tests/test_machinery.py`, `test_precision.py`, `test_models.py`,
`test_engine_demo.py`), none of which cite a source document for it. Worse,
the ISU A3-29 join added on this branch (§8 of `sources.md`) derives the
self-propelled sprayer's own rated annual hours as 1,500 wearout hours / 10
years = **150 h/yr** — 2.7x below the figure the cut claimed to be half of.
The 200-hour cut therefore sits *above* the sprayer's own wearout-derived
annual use, not at half of some larger sourced figure. The value itself is
unchanged (200.0, per the global constraint against retuning thresholds): it
remains a round number, chosen before the plot was run, at which the fixed
ownership charge per acre is materially higher than the published per-acre
custom rate — an honest author estimate, not a citation.

#### 11.2.1 The window definition is also a declared choice

Measuring a window means picking two percentiles of the progress
distribution to call its start and end, and that choice is not free: measured
against Iowa's 2006–2026 crop-progress series, the same operation's window
differs by roughly a factor of three depending on which pair is used.

| Operation | 25–75 (primary) | 10–90 | 5–95 | Phase 1 estimate |
|---|---|---|---|---|
| Corn planted | 11 d | 25 d | 34 d (33.5) | 21 d |
| Soybean planted (unused — no operation maps to it) | 13 d | 28 d | 37 d | — |
| Corn harvested | 19 d (19.0) | 39 d | 52 d | 30 d |
| Soybean harvested | 14.5 d | 30 d | 39 d | 14 d |

Against the 14-day narrow-window cut, **25–75 puts corn planting on the
narrow side and 10–90 and 5–95 both put it on the wide side.** Choosing the
definition after seeing which one moves the gate would be exactly the kind
of tuning §11.2 already rules out for the quadrant cuts, so the primary was
fixed before any gate was run, on this reasoning:

- The axis exists to ask whether an operation's acres can route to a
  service provider. What actually binds a provider is the period when the
  operation runs *at scale* and every provider in the state is
  simultaneously busy — the middle of the distribution, not its tails.
- The 10–90 and 5–95 spans pull in early southern-Iowa fields and late
  replants, which widen the statewide span without widening any individual
  farm's window.
- Statewide dispersion is in any case an *upper* bound on a single farm's
  window, since it aggregates latitude, soil type and local weather. The
  narrowest defensible definition sits closest to the farm-level quantity
  the model actually wants.

**25–75 is the primary and drives the plotted point and the headline gate
(§11.6). 10–90 and 5–95 are computed and reported alongside it, not chosen
after the fact.** §11.6 reports what happens to the gate under all three —
and the three do not agree with each other.

### 11.3 Gate result (Phase 1 — superseded by §11.6)

**This section is the Phase 1 run, kept for the record of what motivated
Phase 2.** All ten `window_days` values below are author estimates; §11.1
replaces four of them with NASS measurements, and §11.6 re-runs this same
gate against the measured windows — that command now prints 5/8, 5/8, 2/8,
not the 4/8, 4/8, 2/8 shown here. Read this section as history, not as the
exhibit's current answer.

Actual run at the time, `uv run python case-studies/john-deere-roi-copilot/scripts/figures.py`,
against Phase 1's estimate-only `operations.json`:

```
500 acres
  market-depth agreement (n >= 70): 4/8 = 50%
  disagreeing: corn_combine, no_till_planter, high_speed_planter, anhydrous_toolbar

2,400 acres
  market-depth agreement (n >= 70): 4/8 = 50%
  disagreeing: corn_combine, no_till_planter, high_speed_planter, anhydrous_toolbar

10,000 acres
  market-depth agreement (n >= 70): 2/8 = 25%
  disagreeing: corn_combine, soybean_combine, no_till_planter, high_speed_planter, field_cultivator, anhydrous_toolbar
```

Agreement is weak at every farm size — a coin flip at 500 and 2,400 acres, and
worse than a coin flip at 10,000. **This does not confirm the thesis.** Eight
of the ten operations clear the 70-response deep-market bar; the model puts
only half of them, and at scale only a quarter of them, in the
low-utilization / narrow-window quadrant it predicts Iowa growers already
consolidated into custom hands.

Two operations — the self-propelled sprayer and vertical tillage — agree with
the model at every farm size tested; they are genuinely low-use and
narrow-window all the way to 10,000 acres. Two more — the draper-head combine
and the field cultivator — agree at 500 and 2,400 acres but flip to disagree
at 10,000 acres, and that flip is the utilization axis working exactly as
designed: both cross the 200-hour cut between 2,400 and 10,000 acres (combine
368 h/yr, cultivator 243 h/yr), which is the same "low-utilization machine at
2,400 acres becomes a high-utilization machine at 10,000" mechanic the module
docstring describes. That is not a model failure; it is the utilization side
of the cut doing its job.

The remaining four — the corn-head combine, the no-till planter, the
high-speed planter, and the anhydrous toolbar — disagree at **every** farm
size, including 500 acres where every other utilization number is at its
lowest. All four share the same cause: a wide estimated window (30, 21, 21 and
21 days respectively, against the 14-day cut), not high utilization — at 500
acres all four sit well under 30 hours/year. At the time this section was
written, every one of those window values was an `author_estimate`, not a
measurement — that was the reading gap this section left open, and §11.1
closed most of it: three of these four (corn-head combine, no-till planter,
high-speed planter) are now `measured`. Only the anhydrous toolbar is still
an `author_estimate` today, because NASS publishes no fertilizer-application
progress series to measure it against (§11.1, §11.6). What follows in this
paragraph is the reasoning as it stood before that measurement — see §11.6
for what the measurement actually showed.

At the time, that left two readings this exhibit could not distinguish
between: either Iowa growers do not in fact treat planting, anhydrous
application and corn harvest as un-reschedulable the way the thesis assumes,
or the estimated windows for those four operations were simply too generous
and the true agronomic window was tighter than 14 days. A model that is right
about utilization and uncertain about window length is not evidence the
thesis is wrong — but it is not evidence it is right, either, and 50%/50%/25%
agreement was too weak to build Phases 2–4 on without first replacing the
estimate with NASS Crop Progress days-suitable-for-fieldwork data, exactly as
§11.1 already proposes. That replacement happened next, in §11.6 — read there
for the result, not here.

### 11.4 Break-even is available for one machine only

Only the self-propelled sprayer has a sourced list price (UADA FSA2225,
$650,000, dated). Every other row carries `list_price_usd: null` and plots
without a break-even label. Deere Build & Price would supply the rest as dated
manual figures; per spec §6 that is needed for the deep dive, not for this
exhibit.

### 11.5 Unit of analysis: the operation, not the capital item

Every row in `operations.json` is one *operation* — one pass, one machine
class, one custom-rate lookup. Utilization economics, though, attach to the
*capital item*: the physical machine a farm actually owns and finances.
Where more than one row shares a capital item, or where a farm would use
only one of several rows, the per-row utilization the plot shows is not the
whole story on its own.

**The corn-head and draper-head combine rows share one physical combine**
(`a3_29_machine: "Combine SP unit"` on both). A farm does not own two
combines, one per head; it owns one self-propelled combine and swaps heads
between corn and soybean harvest. The combine's true annual utilization is
the *sum* of the two rows' hours, not either row read on its own.

At 2,400 acres: corn-head 134.7 h/yr + draper-head 88.4 h/yr = **223.1
h/yr**, above the 200-hour low-utilization cut. Read as one machine, the
combine sits outside the low-utilization half of the plane at the demo farm
size, where either row read alone sits inside it.

**Under Phase 1's author-estimated windows this changed the gate; measurement
made it moot.** With the draper-head row then estimated at a 14-day window it
sat inside the thesis quadrant, and merging the two rows moved it out, dropping
2,400-acre agreement from 4/8 to 3/8. The measured draper-head window is
**14.5 days** against the same 14-day cut, so that row now sits outside the
thesis quadrant on the window axis alone, however its hours are read. Merging
the two rows today moves it from low-use/wide-window to high-use/wide-window
and leaves the 2,400-acre agreement count unchanged at 5/8.

This is disclosure, not a data or threshold change — the two rows stay
separate and the quadrant cuts are not moved (Global Constraints); the
combine's true utilization is stated here so a reader is not misled by
seeing it plotted as two separately low-utilization machines. The paragraph
above must be re-checked whenever the harvest windows move: the draper-head
row clears the cut by half a day, so a small change in the measurement
restores the gate consequence this section used to carry.

**The seven implement rows** (no-till planter, high-speed planter, field
cultivator, vertical tillage, chisel plow, anhydrous applicator, dry
fertilizer spreader) **each imply a tractor pulling them.** None is
self-propelled. Read the same way as the combine, the farm's one tractor's
true annual utilization is the *sum* of every implement row's hours, not
any single row's. That tractor is not itself modelled in this dataset — no
`tractor` row, no tractor list price, no tractor A3-29 join — so its
combined hours are not computed here, but no single implement row's low
utilization should be read as the tractor's utilization.

**The two planter rows are alternatives, not complements.**
`no_till_planter` and `high_speed_planter` price two different ways to do
the same planting job — a farm buys one planter, not both. Unlike the two
combine heads, these two rows must *not* be summed; doing so would double
the same planting pass. Nothing in `operations.json` currently distinguishes
rows that share a capital item and should be summed (the two combine heads),
rows that are alternatives and should not be (the two planters), and rows
that imply an unmodelled shared capital item (the seven implements and their
tractor). That distinction lives only in this paragraph, not in the schema.

### 11.6 Phase 2 gate result

Actual run, `uv run python case-studies/john-deere-roi-copilot/scripts/figures.py`,
25–75 primary definition:

```
500 acres
  market-depth agreement (n >= 70): 5/8 = 62%
  disagreeing: corn_combine, soybean_combine, anhydrous_toolbar

2,400 acres
  market-depth agreement (n >= 70): 5/8 = 62%
  disagreeing: corn_combine, soybean_combine, anhydrous_toolbar

10,000 acres
  market-depth agreement (n >= 70): 2/8 = 25%
  disagreeing: corn_combine, soybean_combine, no_till_planter, high_speed_planter, field_cultivator, anhydrous_toolbar
```

10–90 sensitivity:

```
500 acres
  market-depth agreement (n >= 70): 3/8 = 38%
  disagreeing: corn_combine, soybean_combine, no_till_planter, high_speed_planter, anhydrous_toolbar

2,400 acres
  market-depth agreement (n >= 70): 3/8 = 38%
  disagreeing: corn_combine, soybean_combine, no_till_planter, high_speed_planter, anhydrous_toolbar

10,000 acres
  market-depth agreement (n >= 70): 2/8 = 25%
  disagreeing: corn_combine, soybean_combine, no_till_planter, high_speed_planter, field_cultivator, anhydrous_toolbar
```

5–95 sensitivity:

```
500 acres
  market-depth agreement (n >= 70): 3/8 = 38%
  disagreeing: corn_combine, soybean_combine, no_till_planter, high_speed_planter, anhydrous_toolbar

2,400 acres
  market-depth agreement (n >= 70): 3/8 = 38%
  disagreeing: corn_combine, soybean_combine, no_till_planter, high_speed_planter, anhydrous_toolbar

10,000 acres
  market-depth agreement (n >= 70): 2/8 = 25%
  disagreeing: corn_combine, soybean_combine, no_till_planter, high_speed_planter, field_cultivator, anhydrous_toolbar
```

**Under the primary definition, agreement rose at 500 and 2,400 acres — from
Phase 1's 4/8 = 50% to 5/8 = 62% — and stayed at 2/8 = 25% at 10,000 acres.
Under both sensitivity definitions, agreement at 500 and 2,400 acres *fell
below* even the Phase 1 estimate-based figure, to 3/8 = 38%. The 10,000-acre
result is identical — 2/8 = 25%, same six operations disagreeing — across all
three definitions.**

**Measurement reordered the quadrant, it did not just rescale it, and the
reordering runs in both directions:**

- **No-till planter and high-speed planter** (`corn_planted`): estimate 21 d
  → measured 11 d, a **10-day** move. At 500 and 2,400 acres both cross from
  `low_use_wide_window` to `low_use_narrow_window` — from disagreeing with
  the thesis to agreeing with it. At 10,000 acres both were already
  high-utilization, so the same 10-day move only relabels them
  `high_use_wide_window` → `high_use_narrow_window`; the gate outcome there
  (disagree) is unchanged because utilization, not window, decides it.
- **Draper-head combine** (`soybean_harvested`): estimate 14 d → measured
  14.5 d, a **half-day** move — but the estimate sat exactly on the 14-day
  cut, so half a day is enough to flip it from `low_use_narrow_window` to
  `low_use_wide_window` at 500 and 2,400 acres, from agreeing to
  disagreeing. At 10,000 acres it was already high-utilization; the same
  half-day move relabels it `high_use_narrow_window` → `high_use_wide_window`,
  again with no change to the (disagree) outcome. **This is the exhibit's
  most fragile result: the flip rests on half a day of measured window,
  against a bound (`crossing_date`'s `max_gap_days`) that itself excludes two
  of the twenty NASS-observed years for this series (§11.1's underlying
  `years_excluded`) as too gap-ridden to trust. A different, still-defensible
  choice of that bound could plausibly move the median back across 14 d.**
- **Corn-head combine** (`corn_harvested`): estimate 30 d → measured 19.0 d,
  an **11-day** move, the largest of the four — but 19.0 d is still above
  the 14-day cut, so it stays `..._wide_window` at every farm size and its
  agree/disagree status is unchanged. The measurement mattered for the
  number, not for the quadrant.
- Net effect at 500/2,400 acres under the primary definition: two
  operations join the agreeing set (both planters), one leaves it
  (draper-head combine), for a net of **+1**, taking agreement from 4/8 to
  5/8.

**The window axis is not robust to the percentile choice, and that is itself
a finding.** Both planters' flip to agreement depends entirely on 11 d being
picked over 25 d (10–90) or 33.5 d (5–95) — under either sensitivity
definition `corn_planted` stays above the 14-day cut and both planters
revert to disagreeing, which is why the sensitivity blocks fall to 3/8 = 38%,
*below* Phase 1's own 4/8 = 50%. The three definitions do not agree with
each other on whether measurement helped the thesis: the primary says yes
(50% → 62%), the sensitivity bands say no (50% → 38%). Per §11.2.1 the
primary was fixed before any gate was run specifically so this could not be
resolved by picking the flattering definition after the fact — but the
divergence itself means the 500/2,400-acre result is fragile to a modelling
choice that has no data-driven answer, not just to the underlying data.

**The 10,000-acre result is the one number that is robust:** 2/8 = 25% under
all three definitions, with the same six operations disagreeing every time.
At that scale, utilization dominates the quadrant assignment for enough
operations that the window-definition choice stops mattering to the gate,
even though it still moves individual operations' labelled quadrant
(no-till planter, high-speed planter, draper-head combine, as above).

**Anhydrous applicator disagrees at every farm size, under every
definition, unchanged from Phase 1** — it has no NASS series and keeps its
21-day author estimate throughout. It is now the single clearest remaining
case the exhibit cannot resolve: either Iowa growers do not treat fall
anhydrous application as un-reschedulable the way the thesis assumes, or
the 21-day estimate is too generous and no measurement exists in this
dataset to check it. That question is now sharper than in Phase 1 — three
of the four originally-estimated wide-window disagreements have since been
measured and two of them flipped — but it is still open, because NASS
publishes no fertilizer-application progress series.

### 11.7 Planting-date yield response — Iowa corn only, and why the `$/acre/day` axis stays deferred

`engine/timeliness.py`'s `PlantingDateCurve` and
`data/reference/planting_date_response.json` add the capability to price a
day of planting delay in dollars per acre, for Iowa corn. This section covers
what was searched for across all ten landscape-exhibit operations, why only
one cleared the bar, and what that means for the spec's `$/acre/day` y-axis.
**Neither the exhibit's axis nor `scripts/figures.py` changes in this phase**
— `window_days` (measured for four of ten operations, §11.1) stays the plot's
y-axis. This section documents a capability that exists, not one that is wired
into the figure yet.

#### 11.7.1 The sourcing verdict, operation by operation

Two rounds of sourcing (`.superpowers/sdd/task-4-sourcing.md`,
`.superpowers/sdd/task-4-sourcing-round2.md`) searched for a controlled-trial,
transcribable-as-data yield- or cost-response curve for every operation class
in the landscape exhibit that is not corn planting. None cleared the bar corn
planting did:

| Operation class | Curve available? | Why |
|---|---|---|
| Post-emergence herbicide | **Strong coefficients, but Ontario, not Iowa** | Soltani, Shropshire & Sikkema (2022) publish a fitted four-parameter log-logistic yield-loss model, separately for corn and soybean, with Table 1 parameter estimates directly transcribable — the same quality bar the corn curve clears. But the trial (17 site-years) ran at Ridgetown and Huron, Ontario, not in Iowa or the US Corn Belt, and no Iowa-specific equivalent of comparable quality was found. |
| Soybean harvest delay | **Real rate exists, publisher 403s, mirror dead** | Philbrook & Oplinger (1989) report a linear 0.2%/day field-loss rate from a four-year Wisconsin trial — a real, transcribable number — but the publisher blocks scripted access and the one alternate mirror found by search engines is a dead link. Content is strong; access is not confirmed. |
| Corn harvest delay | **Real multi-site data, nothing both fetchable and tabular** | Ohio State's C.O.R.N. newsletter and a Kentucky ASABE study both track corn harvest-delay loss, but the former reports only prose ranges tied to named calendar months (no table, no rate) and the latter is paywalled behind ASABE institutional access. |
| Fall anhydrous | **Wrong shape — a threshold, not a decay** | ISU's guidance is a soil-temperature threshold (apply once 4-inch soil temperature is below 50°F and falling) that gates *when the window opens*. There is no documented per-day yield or dollar penalty for waiting *longer* once the window is open — the opposite of the other operations' shape. See §11.7.3. |
| Tillage ×3 (field cultivator, vertical tillage, chisel plow) | **Confirmed absent — searched specifically** | No study treats "days late doing the tillage pass" as an independent yield-loss variable. Only system-choice (till vs. no-till) and cost-per-pass data exist. See §11.7.4. |
| Dry fertilizer | **Ambiguous, scope-dependent** | Fall-vs-spring broadcast P&K is a two-point comparison (not a day-rate) and leans low-penalty. N sidedress timing — a different operation, if that is what "dry fertilizer" in the exhibit means instead — shows a real, steep, late-season penalty. The two candidate readings point in opposite directions, and which one the exhibit's tenth row denotes was never disambiguated. |

Corn planting (Abendroth et al. 2017, §11.7.2 below) and soybean planting
(Kessler, Archontoulis & Licht 2020) were sourced in the first round, not the
second, and are not in the table above. Soybean planting was rejected for the
curve treatment: the per-site-year quadratic fits are noisy (R² 0.08–0.98
across 63 site-year-by-maturity-group models), there is no statewide or
multi-region aggregate model the way the corn paper provides one, and the
cleanest relative-yield numbers are prose statements tied to named calendar
periods ("late May," "mid-June") rather than a table.

**Three of ten operations having a searched-for, real, fetchable curve —
herbicide (Ontario), corn planting (Iowa), and arguably N-sidedress dry
fertilizer if that is the right reading — does not support switching the
exhibit's y-axis to `$/acre/day`.** Seven of ten operations have no usable
curve, a wrong-shaped one, or a curve for the wrong operation and the wrong
geography. The spec's `$/acre/day` axis upgrade is therefore **deferred, not
delivered**: `window_days` remains the axis, and the corn planting-date curve
this phase adds is a standalone capability, not a replacement for it.

#### 11.7.2 The corn curve is Iowa-specific, from a controlled trial, and the site-grouping is a modelling choice

Abendroth, Woli, Myers & Elmore (2017) is exactly the source the other nine
operations lack: an 18-site-year randomized complete block trial (3–4 reps)
at six Iowa State University Research and Demonstration Farms (2006, 2007,
2009), five planting dates per site-year, with a fitted quadratic
(`yield = b0 + b1x + b2x²`) and its coefficients published in Table 2 — not a
chart to read pixel positions off, and not a single-site or single-year
result. See `deliverables/appendix/sources.md` §9 for the full citation and
access note.

The paper does not publish one Iowa curve. It publishes **three**, for three
statistically distinct site-groupings — NC–NE, NW–C, SW–SE — because the six
research sites did not respond alike: "plant date is a stronger determining
factor for grain yield in the NC–NE and SW–SE site-groupings than in the
NW–C" (the paper's own Discussion). Choosing which grouping the exhibit's
planter-row annotation uses (a future step, not wired in this phase — §11.7.1
above) is therefore a modelling decision, not a free extraction from the
source:

| Grouping | Optimum DOY | 98–100% window | Curvature |
|---|---|---|---|
| NC–NE | 108 (18 April) | 102–120 DOY (12–30 April), 18 days | Steep — `b2 = -49.1` |
| NW–C | 114 (24 April) | 105–129 DOY (15 April–9 May), 24 days | Shallowest — `b2 = -26.7` |
| SW–SE | 117 (27 April) | 107–128 DOY (17 April–8 May), 21 days | Steepest — `b2 = -65.1` |

Two acceptance checks verify the transcription: the computed vertex (from b1/b2) 
matches the paper's published optimum DOY (primary proof), and the coefficients 
reproduce the published 98–100% window boundaries (corroborating evidence that 
confirms the transformation is correct). The second check is corroborating because 
it is measured against the rounding error baked into the paper's one-decimal-place 
coefficients, whereas the vertex check has only the transform's internal consistency 
at stake.

**This phase designates NC–NE as the grouping the exhibit will use when a
future phase wires the annotation in**, for two reasons: it has the earliest
optimum window, consistent with the module docstring's framing of corn
planting as the timeliness-critical half of the rotation (§11.1's
`nass_series_key` mapping already privileges corn planting over soybean on
exactly that basis); and it is one of the two most curvature-sensitive
groupings, so a day of delay costs the most there — the conservative choice
for an exhibit meant to make a timeliness argument. **Averaging the three
curves, or picking NW–C or SW–SE instead, would move the optimum date by up
to 9 days and the marginal cost of a day of delay by roughly a factor of
two** (`b2` ranges from -26.7 to -65.1, a 2.4x spread in curvature). No
statewide aggregate curve exists in the source; any single-grouping choice is
this repository's decision, stated here rather than left implicit in the
JSON.

#### 11.7.3 Fall anhydrous: a real constraint, the wrong shape for this axis

Fall anhydrous ammonia timing is genuinely well-documented agronomy — ISU's
guidance is specific and widely followed: apply only once 4-inch soil
temperature is below 50°F and trending colder, because nitrification
(ammonium → nitrate, the loss-vulnerable form) proceeds much faster above
50°F. In central Iowa that threshold is typically reached in the second week
of November.

That is a **threshold gating when the window opens**, structurally different
from every other operation this exhibit models. Every curve and every
measured window in this phase — corn planting's 98–100% span, the four NASS-
measured `window_days` in §11.1 — answers "how much does a day of delay cost
once the window is open." Fall anhydrous instead answers "when is it safe to
start," and the direction of the penalty runs the other way: applying *too
early* (above 50°F) is the documented risk, not applying late. No search in
either sourcing round found a documented per-day yield or dollar penalty for
waiting longer once the 50°F threshold has passed.

A complete timeliness model of fall anhydrous needs **two** things: a
window-start constraint (the soil-temperature threshold) and a per-day
delay-cost curve once the window is open. This phase — and the corn planting
curve generally — supplies only the second kind of quantity for any
operation, and no source found supplies it for anhydrous at all. Forcing
anhydrous onto the same `$/acre/day` axis as the operations that do have a
per-day curve would misrepresent what is actually known about it; §11.7.1
counts anhydrous among the seven operations without a usable curve for
exactly this reason, not as a search gap.

#### 11.7.4 Tillage: absence confirmed, and it supports the existing thesis

The second sourcing round searched specifically for a per-day-of-delay yield
penalty for primary or secondary tillage timing (field cultivator, vertical
tillage, chisel plow) and found none. What exists instead is: long-term
Corn Belt comparisons of tillage **system** choice (chisel-plow vs. no-till),
which report yield differences under 1.0 Mg/ha between systems, not a delay
curve within a system; and ISU Extension cost-per-pass figures ($7–10/acre
primary, $5–8/acre secondary), which price the operation but say nothing
about the cost of doing it late. The one timing-adjacent finding —
no-till and chisel-plow yields converge when corn planting slips from late
April to late May — is a *planting*-date interaction, already covered by the
Abendroth corn curve, not a tillage-timing effect in its own right.

**This absence is a finding, not a gap in the search, and it is the same
finding the exhibit's thesis already rests on.** §11.3 and §11.6 report that
the self-propelled sprayer and vertical tillage are the two operations that
agree with the low-utilization/narrow-window prediction at every farm size
tested — vertical tillage's wide `window_days` estimate (an `author_estimate`,
unmeasured, since NASS publishes no tillage progress series) is exactly what
a genuinely delay-tolerant operation should look like. A world in which
tillage timing carried a real per-day yield penalty is a world in which that
agreement would be suspicious; a world in which no study anywhere has found
one, despite searching for it specifically, is consistent with tillage being
exactly the kind of operation Iowa growers can leave to whenever custom
capacity is free — the reason those three operations do not need to
consolidate into custom hands the way narrow-window planting and harvest
operations do.

#### 11.7.5 Pricing the corn planting delay

The one operation with a curve (§11.7.2) can now be priced. `scripts/figures.py`
computes this at run time — `corn_planting_delay_cost_usd_per_acre_per_day` —
and reports it on the figure's caption (not as a point annotation; see
§11.7.6). Every input below is read from a file already committed to this
repository; none is invented.

| Input | Value | Source |
|---|---|---|
| Reference day | Day of year 131 (11 May, non-leap-year reading — the same convention §11.7.2's table uses for DOY 108) | `MeasuredWindow.median_closing_day_of_year` for `corn_planted`, primary (25–75) definition: the median, across the 21 years NASS has observed, of the day-of-year the 75th-percentile crossing falls on. This is the day the brief specifies — the last day the bulk of Iowa's corn is still going in, and a number the panel already produces rather than a picked date. |
| Curve | NC–NE site grouping | `data/reference/planting_date_response.json`, the grouping §11.7.2 designates for exactly this use. |
| Yield | 193 bu/acre | `data/reference/isu_a1_20_2026.json`, the continuous-corn / conventional-tillage budget (page 2), `yield_levels_bu_per_acre: [174, 193, 212]` — the medium of the three published tiers. |
| Price | $4.32/bu | `data/priors/yield_price.json`, `crops.CORN.price`: a fitted stationary lognormal, `price = exp(log_mean + log_sd·z)`. `exp(log_mean)` — `z = 0`, no shock — is the distribution's fitted central value, used here as a single point price rather than drawing a Monte Carlo sample for a caption sentence. |

**The yield tier is continuous-corn, not the 50/50 corn-soybean rotation the
rest of this model assumes (§11.1's `passes_per_farm_acre_per_year`, the
file-level `$comment` in `operations.json`), and that mismatch is forced, not
chosen.** `isu_a1_20_2026.json` carries four corn budget rows: one
continuous-corn and three corn-following-soybeans (different tillage
systems). Only the continuous-corn row has `yield_levels_bu_per_acre`
populated — all three corn-following-soybeans rows carry `null` for that
field. There is no rotation-consistent yield figure to use instead; the
continuous-corn tier is the only one this repository's committed data
supplies. Continuous corn also yields somewhat lower than corn following
soybeans in the agronomic literature (a rotation effect on top of the
planting-date effect this section prices), so $3.05/acre/day is not even
guaranteed to be biased in a knowable direction relative to a 50/50-rotation
figure that does not exist in the sourced data.

**Result: $3.05/acre/day, averaged over the 23.5 days elapsed since the
NC–NE optimum**, evaluated at day of year 131 (optimum day of year 107.5),
corresponding to an 8.6% yield-loss fraction on the fitted curve. Reproduce
with `uv run python case-studies/john-deere-roi-copilot/scripts/figures.py`,
first line of output.

**$3.05 is an average rate, not the marginal cost of the next day of
delay.** `delay_cost_usd_per_acre_per_day` divides the total loss accrued
since the optimum by the number of days elapsed — the right quantity for
"what has each day of this delay cost on average so far," and what the
figure caption states. It is not the slope of the loss curve at day 131,
which is the cost of *one more* day of delay from where planting already
stands. Because the fitted curve is concave (loss accelerates the further
planting slips), the marginal cost at day 131 is roughly double the average:
approximately $6.23/acre/day, against $3.05/acre/day averaged over the same
23.5 days. The two diverge further the longer the delay runs, since the
average keeps folding in the cheaper early days while the marginal cost keeps
climbing. Both quantities are computed from the same curve and the same
inputs above — the difference is average-over-elapsed-days versus
instantaneous-slope, not a different sourcing choice.

This is one point estimate under three modelling choices this phase makes
explicit rather than hides — the site grouping (§11.7.2: NW–C or SW–SE would
move it by roughly a factor of two), the yield tier (174 or 212 instead of
193 scales it linearly), and the price point (the distribution's spread is
real; $3.05 is its center, not a bound). It prices one operation, at one
reference day, under one set of choices — not a general-purpose $/acre/day
figure for the exhibit, which is exactly why §11.7.1 does not let three
sourced operations carry a ten-point axis.

#### 11.7.6 Where the number appears, and where it deliberately does not

The figure's caption gains one sentence stating this result and citing
Abendroth et al. (2017). **No point label changes.** Phase 1 shipped two
separate label-collision defects on this exhibit (`LABEL_OFFSETS` in
`scripts/figures.py` exists because of them); the two planter markers already
carry a break-even annotation candidate and sit in the plot's most crowded
region (§11.1's `window=11` cluster at the 25–75 definition). A fifth channel
on a plot that already carries four — x, y, point size, and one break-even
label — was not worth the risk for one number better stated once, in prose,
than twice, next to two points.

### 11.8 Phase 2 conclusion

The spec (§10) sets Phase 2's gate as one question: **do the penalties
reorder the quadrant, or only rescale it?**

**That question cannot be answered at this evidence level.** Answering it
requires a penalty-based ordering of the ten landscape-exhibit operations to
compare against the window-based ordering the plot already has. No such
ordering exists. §11.7.1 searched all ten operation classes for a
controlled-trial, transcribable delay-cost curve and found one that clears the
bar — corn planting — plus two marginal cases: post-emergence herbicide has
strong coefficients but from an Ontario trial, not Iowa, and dry fertilizer's
curve depends on a reading of the exhibit's tenth row that was never resolved.
Three of ten, on the most generous count, and only one (corn planting) is
actually priced anywhere in this repository (§11.7.5). A ranking needs all
ten placed, or at minimum enough of them placed that reordering is a
meaningful question rather than an artifact of which seven are missing.
Three does not clear that bar. This is not a negative result — it is not
"the penalties only rescale the quadrant" — because no penalty-based quadrant
was ever assembled to check that against. The honest status is that the gate
question is currently unanswerable, and the reason is a sourcing gap
documented operation-by-operation in §11.7.1, not a finding about the
thesis.

**What Phase 2 did establish, gathered in one place:**

- **Measurement, not pricing, is what this phase actually delivered.** Four of
  the ten `window_days` values are now measured from NASS Crop Progress
  (§11.1) rather than author-estimated; six remain estimates, including the
  self-propelled sprayer — the exhibit's flagship point and, at every farm
  size tested across both phases, the strongest single case for the thesis
  (§11.1, §11.6).
- **The gate moved, and the direction depends on which window definition is
  read.** Under the declared primary (25–75) definition, market-depth
  agreement rose to 5/8 = 62% at 500 and 2,400 acres, up from Phase 1's
  4/8 = 50%, and held at 2/8 = 25% at 10,000 acres. Under both wider
  sensitivity definitions (10–90, 5–95), agreement at 500 and 2,400 acres
  *fell* to 3/8 = 38% — below Phase 1's own estimate-based figure — while the
  10,000-acre result stayed 2/8 = 25% under every definition (§11.6). **The
  three definitions do not agree with each other.** The entire improvement at
  500/2,400 acres rests on both planter rows (`corn_planted`) crossing the
  14-day narrow-window cut, which happens only under 25–75: 11 measured days
  sits below the cut, 25 days (10–90) and 33.5 days (5–95) both sit above it.
- **What that means for the thesis, stated so a reader can disagree with it:**
  the exhibit's y-axis is not robust to a defensible, pre-declared change in
  how "window" is defined. That is a weakness of the axis — the same
  underlying NASS data, read through a different but equally defensible
  percentile pair, points the opposite way on whether measurement helped or
  hurt the thesis's agreement with revealed market behaviour. It is not
  evidence for the thesis (the primary definition's 62% does not prove
  narrow-window operations cluster with deep custom markets) and it is not
  evidence against it (the sensitivity bands' 38% does not disprove it
  either) — it is evidence that this particular axis, measured this
  particular way, is too sensitive to an unforced modelling choice to carry
  the gate's answer by itself. §11.2.1 fixed the primary before any gate ran
  specifically so this could not be resolved by picking the flattering
  definition after the fact; that discipline is what makes the disagreement
  visible instead of hidden.
- **What Phase 3 would need before relying on any of this:**
  - A penalty curve for enough more operations that a penalty-based ordering
    could be assembled at all — at minimum the two remaining candidates
    (§11.7.1's herbicide and dry-fertilizer entries) resolved to Iowa-specific
    sources or abandoned outright, since a mixed-geography or ambiguous-scope
    curve would make the ordering itself untrustworthy.
  - An independent way to choose between the three window definitions that
    does not reduce to picking whichever one the gate prefers — §11.2.1's
    reasoning for 25–75 is sound but untested against, for example, a
    farm-level (rather than statewide) crop-progress source, which does not
    exist in NASS's public data and would have to come from elsewhere.
  - A resolution, or an explicit decision to leave unresolved, for the two
    open cases already on record: fall anhydrous (§11.7.3, no per-day-delay
    source found in two sourcing rounds) and the self-propelled sprayer's
    estimated window (§11.1, the flagship point, still unmeasured).
  - If the segment-sizing work in Phase 3 leans on the landscape exhibit's
    quadrant placement for any operation, it should carry the sensitivity
    result forward explicitly rather than citing only the primary-definition
    62% — citing 62% alone, without the 38% it reverses to under an equally
    declared alternative, would be the kind of selective reporting §11.2 and
    §11.2.1 exist to rule out.

---

## 12. Dual-use combine research gate

This appendix does not assign a numeric ownership recommendation to a combine.
The evidence permits a transparent input-gap exhibit only. The detailed source
record is in `sources.md` §9 and the research ledgers are
`.superpowers/sdd/market-evidence.md` and `.superpowers/sdd/timing-evidence.md`.

### 12.1 Asset and cost-treatment rules

The ownership configuration has three separate assets: one self-propelled base
combine, one 12-row corn head, and one 40-ft draper head. A3-29 has separate
rows for `Combine SP unit` and `Combine head`: the base's RC1/RC2/wearout values
are 0.025/2.1/3,000 h, while each head's are 0.05/2.3/2,000 h. Apply the base
row once and the head row once for each head. Do not assign the base-combine
coefficient to both heads, and do not treat the generic head row as a
machine-specific repair, inspection, or resale record.

All observed equipment values are public **asking/list prices**. They are not
quotes, documented sales, transaction prices, bundled packages, or delivered
costs. The 2024 X9 1100 listing explicitly says `Header: No`, as does the used
2020 S780 listing. Each observed base price therefore excludes a head, so a
separately priced head can be included once but never inferred as bundled.

The published X9 front-end table supports the X9 1100 + C12F + RD40F equipment
family. It does not establish a delivered new configuration or its price. Direct
item URLs support an X9 base ask and a new-style RD40F ask, but the C&B C12F
reference is a dealer homepage, not an item URL; no new three-asset sum is
source-supported. Direct URLs also support the S780 base and C12R head asks, but
the TractorHouse RD40F reference is a model-search page, not an item URL; no used
three-asset sum is source-supported. No archived S780 capture supports a stable
price or hours claim because live listing values are volatile; the C12R lacks
hours/acres and condition/repair evidence. These omissions fail the
used-condition gate; do not create a purchase valuation from partial asks.

### 12.2 Hire-rate display and matched scope

For a 1,200-acre corn and 1,200-acre soybean workload, the A3-10 generic
combine-only averages are $46.05/ac and $43.05/ac, respectively. Their
arithmetic annual display is **$106,920**. It is a survey sensitivity for
combine-only service, not a contractor quote or a head-specific rate. The
separate $48.20/ac soybean-with-draper survey row may be displayed only as a
draper-service sensitivity; it is not a draper purchase or rental value and
must remain separate from the $43.05/ac generic baseline.

Grain cart, haul to farm storage, trucking, drying, destination, fuel, and
operator scope are unknown for a prospective hire. A3-10's complete-harvest
rates are a different package and cannot be added to the combining-only rows.
For any comparison, either document and include the same owner-side services
or exclude those services from both sides.

### 12.3 Timing inputs and hard unknowns

Weather can be entered as a source-labelled descriptive input only after the
farm's Iowa reporting district and dated crop windows are known. A3-25 provides
median suitable days, and NASS defines a suitable day without assigning hours.
The 12 h/day value in A3-28 is a worked-example sensitivity, not a default.
The 2024 NASS record shows statewide corn and soybean harvest overlap; allocate
any shared-combine overlap once rather than presuming sequential windows.

Use this structure once farm inputs exist:

```
crop available hours = suitable days in its dated interval
                     × selected hours per workable day
                     − allocated outage, head-change, and other lost hours
```

Actual crop windows, hours/day, crew and grain-handling availability,
head-change duration, repair/outage history, and a contractor schedule are all
unknown. A3-33 specifically warns that a custom operator may not be available
in the optimum period; it requires an agreed schedule or priority. Therefore
mark `hire_both` timing **unknown** until a written commitment covers both
crops, acreage/fields, equipment and heads, requested dates or priority,
weather/cancellation terms, and the cart/haul/drying scope. Mark owned-combine
timing **unknown** until dated crop windows and a farm labor-hours/day basis are
provided. Do not monetize lateness or impute a contractor advantage.

### 12.4 Inputs required before a comparable recommendation

1. A dated written dealer quote or public configuration/list price for the
   exact new base, C12F, RD40F, feeder/adapter, freight, warranty, taxes, and
   purchase basis.
2. For the used package, head serials, prior acres/hours, inspection or repair
   history, and exact compatibility hardware with the identified S780. A single
   dealer package is required before calling its price bundled.
3. A defensible terminal-resale and repair range for each head. The A3-29
   generic `Combine head` row may support a clearly labelled sensitivity after
   price and starting use are known; it does not close this condition gate.
4. A dated farm window, district, shift/crew plan, grain-handling plan,
   head-change observations, and machine-specific outage evidence.
5. A written custom-harvest scope and scheduling commitment with matching
   owner-side services.

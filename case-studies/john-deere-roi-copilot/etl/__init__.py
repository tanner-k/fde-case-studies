"""Offline data acquisition for the Deere ROI copilot.

Three extractors, each emitting tidy parquet into `data/raw/`:

| Module | Source | Key needed |
|---|---|---|
| `ers` | USDA ERS commodity costs and returns | no |
| `nass` | USDA NASS Quick Stats yield and price | `NASS_API_KEY` |
| `weather` | Open-Meteo historical archive | no |
| `reference` | Archived ISU A3-10 / A3-29 / operations JSON | no — local files |

Nothing here runs at request time. The API container does not install these
dependencies — they live in the `etl` optional extra for exactly that reason.
"""

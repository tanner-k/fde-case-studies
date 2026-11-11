# ADR 0001 — `DeereProvider` is a real client against an empty organization

**Date:** 2026-08-12
**Status:** Accepted
**Onigiri:** JDRC-7

---

## Context

The case study's central claim is that it builds the decision layer Deere could
put on top of Operations Center data. Whether that claim reads as *"integrated
with"* or *"designed for"* depends on what the granted credentials actually
return — which is knowable only by calling the API, not by reading the docs.

`scripts/deere_spike.py` authenticates via authorization-code OAuth, enumerates
organizations, and probes every collection the organization advertises. It was
run three times against `https://sandboxapi.deere.com/platform`; the raw output
lives in `data/raw/deere-spike/` (gitignored — it describes a real account).

## What the API actually returned

One organization (ID withheld, type `customer`), connection
**established**, advertising **40 link rels**.

| Endpoint | Status | Records |
|---|---|---|
| `clients` | 200 | 0 |
| `farms` | 200 | 0 |
| `fields` | 200 | 0 |
| `boundaries` | 200 | 0 |
| `equipment?organizationIds=` | 200 | 0 |
| `operators` | 200 | 0 |
| `chemicals` | 200 | 0 |
| `tankMixes` | 200 | 0 |
| `varieties` | 200 | 0 |
| `fertilizers` | 200 | 0 |
| `assets` | **403** | — |
| `fieldOperations` | **403** | — |
| `files` | **403** | — |

Ten of thirteen endpoints authorize and return well-formed empty collections.
Three remain forbidden despite `ag1 ag2 ag3 eq1 eq2 org1 org2 files` being
requested and consented — Deere gates individual *activities* inside the
Connections dialog separately from OAuth scopes, and at least
`VIEW_OPERATORS`-style activities were observed being enforced that way.

**The organization contains no data.** No clients, no farms, no fields, no
equipment. This is the expected state of an Operations Center account that has
never had a machine connected or field work recorded.

## Decision

1. **`DeereProvider` ships as a real client**, not a stub. Authentication,
   organization discovery, link traversal, and collection reads are implemented
   and exercised against the live sandbox.
2. **The demo runs on `DemoProvider`.** With zero records available, no
   published figure can be sourced from Operations Center.
3. **The case study claims exactly this and no more:** authenticated against the
   live API, mapped its schema, demonstrated on synthetic data because the
   connected organization holds none.

`FarmDataProvider` keeps the same shape either way, which is the point — the
seam is real, and swapping the implementation is a configuration change rather
than a rewrite.

## Three traps found, and why they matter beyond this project

Each of these is invisible from the documentation and cost a round trip to find.
They are the substance of the integration work, and are pinned by tests in
`tests/test_deere_spike.py`.

### 1. An unauthorized org returns 200 with an empty array

Before the connection is established, collections return HTTP **200** and
`{"values": []}`, not 401 or 403. A client reads that as *"this farm has no
fields"* when it means *"you are not connected yet."* The distinction lives in
the organization's HAL links: a `connections` rel means incomplete, a
`manage_connection` rel means established.

This is the single most dangerous behaviour in the API. Silent, plausible, wrong.

### 2. The established-state rel is singular

Deere's documentation says `manage_connections`. The live sandbox sends
`manage_connection`. Matching only the documented spelling classified a fully
established connection as `unknown` — the same outcome as not checking at all.
Both spellings are now accepted.

### 3. Sandbox links carry production URIs

Every link returned by `sandboxapi.deere.com` points at **`api.deere.com`**.
Following them as HAL intends walks a client from sandbox into production
against a real organization. Link URIs are therefore treated as identifiers, and
every request is re-based onto the configured host (`rebase()`); non-API hosts
such as the connections dialog are deliberately left alone.

A secondary consequence: `machines` is advertised at
`/isg/equipment?organizationIds=…`, a different service from
`/platform/organizations/{id}/…`. The spike originally probed a guessed path and
reported a 403 that was really a wrong URL. Probing the org's *advertised* rels
rather than constructed paths corrected it to 200.

## Consequences

**Good.** The integration is genuine and its failure modes are documented and
tested. The three traps above are more convincing evidence of real API work than
a screenshot of populated data would be.

**Limiting.** No figure in the deliverables can be sourced from Operations
Center. Every headline number comes from USDA ERS, USDA NASS, Open-Meteo, or the
UADA analysis — which the appendices already require.

**Open.** Whether `assets`, `fieldOperations`, and `files` are grantable through
additional Connections activities is untested. Resolving it is low value while
the org is empty: `fieldOperations` is the endpoint that would carry applied and
harvested totals, and it would return zero rows regardless. Revisit if real
operational data ever lands in the account.

## Alternatives rejected

| Option | Why not |
|---|---|
| Populate the sandbox with fabricated field operations | Manufactures the exact evidence the project promises not to fake. |
| Describe the integration without building it | The three traps above are only findable by calling the API, and they are the most interesting output of this work. |
| Wait for an organization with real data | Requires a cooperating farm business. Unbounded, and not required for the decision layer to be demonstrable. |

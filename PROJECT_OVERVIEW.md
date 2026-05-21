# Project Overview — tax-harvest

A personal CLI for an Indian retail investor to identify which mutual fund units to
redeem each financial year so that booked Long-Term Capital Gain (LTCG) stays inside
the ₹1.25 lakh Section 112A exemption.

This document is the engineering walkthrough — what was built, how the pieces fit
together, and why. For installation and usage, see `README.md`.

---

## Table of contents

1. [Goal in one paragraph](#goal-in-one-paragraph)
2. [End-to-end data flow](#end-to-end-data-flow)
3. [Module map](#module-map)
4. [Tax-rule cheat sheet (codified)](#tax-rule-cheat-sheet-codified)
5. [Key design decisions](#key-design-decisions)
6. [Edge cases covered](#edge-cases-covered)
7. [Configuration surface](#configuration-surface)
8. [Output artifacts](#output-artifacts)
9. [Test coverage](#test-coverage)
10. [What is intentionally out of scope](#what-is-intentionally-out-of-scope)

---

## Goal in one paragraph

The Indian Income Tax Act, Section 112A, exempts the first ₹1.25 lakh of LTCG on
listed equity (and equity mutual funds) each financial year. Realised gains above that
limit are taxed at 12.5% (post Budget 2024). "Tax harvesting" means redeeming and
immediately reinvesting just enough units each year that the booked gain lands at the
exemption — this resets your cost basis higher each year and permanently saves the
12.5% you would otherwise have paid on those gains later. The tool reads a CAS
(Consolidated Account Statement) PDF, replays every transaction to know exactly which
units you own and what they cost, then produces a ranked list of redemptions that
together hit the exemption without overshooting.

---

## End-to-end data flow

```
            ┌──────────────┐
            │  CAS PDF     │ password-protected; CAMS / KFintech / MF Central
            └──────┬───────┘
                   │  parser.py  (casparser + normalization)
                   ▼
            ┌──────────────┐
            │  CASData     │  schemes[], NRI/joint flags, statement period
            └──────┬───────┘
                   │  classifier.py + overrides
                   ▼
            ┌──────────────┐
            │  Scheme[]    │  tagged with SchemeCategory + is_suspended
            └──────┬───────┘
                   │  lots.py    (FIFO replay)
                   ▼
            ┌──────────────┐
            │  Lot[] per   │  surviving units, cost/unit, purchase date
            │  scheme      │
            └──────┬───────┘
                   │  lots.evaluate_lots()
                   │  ↑ nav.py  (today's NAV from AMFI)
                   │  ↑ fmv_2018.py  (Sec 112A grandfathering)
                   ▼
            ┌──────────────┐
            │ LotEvaluation│  per-lot: gain, holding days, locked?, excluded?
            │      []      │
            └──────┬───────┘
                   │  harvest.py (greedy fill) + loss_harvest.py
                   ▼
            ┌──────────────┐
            │  HarvestPlan │  PlanLines, budget remaining, warnings,
            │              │  loss candidates, grandfathered lots
            └──────┬───────┘
                   │  report.py
                   ▼
            ┌──────────────┐
            │ Rich console │
            │  + JSON file │
            └──────────────┘
```

Each stage is a pure function of its inputs — easy to unit-test, easy to swap.

---

## Module map

```
tax_harvest/
├── main.py            CLI: argparse, getpass for PDF password, glue
├── models.py          Pydantic v2 models — single source of truth for shapes
├── parser.py          casparser wrapper + NRI/joint heuristics + txn-type mapping
├── classifier.py      Name-regex → SchemeCategory; override loader; suspended list
├── lots.py            FIFO replay; lock-in / exit-load / LTCG eligibility / grandfathering
├── nav.py             AMFI NAVAll.txt fetch + 24h cache + ISIN/code/name lookup
├── fmv_2018.py        AMFI 31-Jan-2018 snapshot for Sec 112A pre-2018 cost uplift
├── harvest.py         Greedy gain-per-unit-desc fill; marginal-lot fractional cut
├── loss_harvest.py    STCL vs LTCL candidate identification
├── report.py          Rich console tables + timestamped JSON report writer
├── data/
│   ├── category_overrides.json   Packaged ISIN → SchemeCategory overrides
│   └── suspended_schemes.json    Packaged wound-up scheme list (empty by default)
└── tests/             62 pytest tests across 6 files
```

### Module responsibilities (one-liners)

| Module | Responsibility |
| --- | --- |
| `main.py` | Parse CLI args, prompt for password, orchestrate the pipeline, render output, return exit code |
| `models.py` | `TxnType`, `SchemeCategory` enums; `Transaction`, `Scheme`, `Lot`, `LotEvaluation`, `PlanLine`, `HarvestPlan`, `CASData` Pydantic models |
| `parser.py` | Delegate PDF parsing to `casparser`; map every variant of "purchase / SIP / switch-in / redemption / dividend / bonus" to a normalized `TxnType`; mask PAN/email; heuristically flag NRI & joint holdings |
| `classifier.py` | Priority-ordered regex rules over scheme name; ISIN-keyed override merging; suspended-scheme list loader; per-lot Sec 50AA refinement |
| `lots.py` | Chronological transaction replay into FIFO `Lot` deque per `(folio, scheme)`; per-lot lock-in (ELSS 3yr / solution 5yr / FMP-close-ended), exit-load, LTCG-eligibility, grandfathering, suspended-status checks |
| `nav.py` | Pull AMFI's pipe-delimited NAVAll feed, cache 24h, build ISIN/code/normalized-name lookup tables, fuzzy prefix-match as last resort |
| `fmv_2018.py` | Pull the 31-Jan-2018 historical snapshot from AMFI's DownloadNAVHistoryReport endpoint; cache permanently; implement `max(actual, min(FMV, sale_NAV))` |
| `harvest.py` | Sort harvestable lots by gain-per-unit desc; accumulate until effective budget filled; truncate marginal lot to 4-decimal units to land on budget exactly; aggregate multi-lot scheme touches into one redemption line |
| `loss_harvest.py` | Filter non-positive gains; tag STCL (≤365d for equity / always for Sec 50AA debt) vs LTCL |
| `report.py` | Render Rich-formatted console panels & tables (redemption plan, warnings, grandfathered lots, loss candidates, excluded lots); write timestamped JSON to `./reports/` (cwd-relative, gitignored) |

---

## Tax-rule cheat sheet (codified)

These rules are implemented inside `classifier.py` (categorisation) and `lots.py`
(eligibility / lock-in / grandfathering). They reflect the law as understood at
build time; users should reconfirm with a CA before transacting.

### Section 112A — Equity LTCG (post Budget 2024)

- Applies to equity-oriented funds (≥65% domestic equity), ELSS, aggressive
  hybrid, arbitrage.
- Holding period for LTCG: **strictly greater than 12 months** (we use `> 365 days`).
- First **₹1.25 lakh** of LTCG per FY is exempt.
- Excess taxed at **12.5%** without indexation.
- **Grandfathering** for lots acquired on/before 31-Jan-2018:
  `effective_COA = max(actual_COA, min(FMV_31_Jan_2018, sale_value))`.

### Section 50AA — Specified Mutual Funds (debt post 1-Apr-2023)

- Units of debt-oriented schemes acquired **on or after 1-Apr-2023**: always
  short-term, taxed at slab rate regardless of holding period.
- We apply this **per lot**, not per scheme — a single debt scheme can have
  some lots in this bucket and some in pre-Apr-2023 LTCG bucket.

### Debt-oriented (pre 1-Apr-2023 acquisitions)

- LTCG after **> 24 months** (Budget 2024 lowered this from 36 months).
- Taxed at **12.5% without indexation** (Budget 2024 removed indexation).

### Lock-ins (enforced per lot, not per scheme)

| Scheme type | Lock-in | Notes |
| --- | --- | --- |
| ELSS | 3 years | Each SIP installment has its own clock |
| Solution-oriented (Retirement / Children's Gift) | 5 years OR goal age | Goal age can't be derived from CAS — flagged |
| FMP / close-ended | till maturity | Excluded outright |

### Exit-load

- Default: 1% if equity-like lot is younger than 365 days (configurable via
  `--equity-exit-load-days`).
- For LTCG harvesting the lot must already be >12 months, so this rarely binds —
  it's kept as a defensive check.

---

## Key design decisions

### Decision 1 — FIFO at the `(folio, scheme)` level

Indian capital gains rules require FIFO depletion. We key the queue on
`(folio, isin or scheme_name)` because the same investor can hold the same scheme
across multiple folios (different cost-basis chains), and a single scheme can have
both regular and direct plan ISINs (different NAVs, treated separately).

### Decision 2 — Greedy by gain-per-unit, not by total gain

Sorting harvestable lots by **gain-per-unit descending** maximises the basis reset
per unit redeemed. Redeeming a lot with a high gain/unit moves more cost basis
forward into the future for the same ₹125,000 budget. The marginal lot is
fractionally truncated to land exactly on the budget (units floored to 4 decimal
places, the precision at which AMCs actually transact).

### Decision 3 — Per-lot category refinement for Sec 50AA

`classify_lot_for_tax(scheme_category, purchase_date)` lives in `classifier.py`. A
scheme is one category, but its lots may straddle the 1-Apr-2023 cutoff — so the
effective category is computed lot-by-lot inside `evaluate_lots`. This keeps the
high-level scheme classification simple while honouring the statute's per-acquisition
rule.

### Decision 4 — Exclusion-with-reason instead of silent filtering

Every lot we don't recommend gets a string `excluded_reason` — "ELSS 3-yr lock-in
(unlocks 2028-11-01)", "Debt unit acquired on/after 1-Apr-2023 — Sec 50AA...", etc.
The user sees both the plan *and* what we excluded and why, which builds trust and
helps catch classification mistakes.

### Decision 5 — Pydantic models as the contract between modules

Every cross-module value is a Pydantic model (`Transaction`, `Scheme`, `Lot`,
`LotEvaluation`, `PlanLine`, `HarvestPlan`, `CASData`). This gives free
validation, free JSON serialisation for the report, and a single place to grep for
the shape of any data.

### Decision 6 — Heuristic detection + manual override for fuzzy signals

NRI status, joint holdings, and scheme classification all have heuristics + a CLI
override (`--nri`, `--joint-holdings`, `--overrides`). The heuristic catches the
common case; the override is there because no heuristic is 100%.

### Decision 7 — Cache everything, fetch lazily

- AMFI daily NAV: 24h cache (NAV moves daily).
- AMFI 31-Jan-2018 snapshot: permanent cache (historical NAVs don't change).
- All cached under `./cache/` (cwd-relative, gitignored) so multiple runs in the
  same day cost zero network calls.

---

## Edge cases covered

| Case | Where handled | Test |
| --- | --- | --- |
| SIP folio with hundreds of installments | `lots.build_lots` (linear FIFO) | covered by harvest tests |
| Switch-out and switch-in across schemes | `parser._TYPE_KEYWORDS` + UNIT_CREATING / UNIT_DEPLETING sets | `test_switch_in_creates_lot_and_switch_out_depletes` |
| Same scheme across multiple folios | Scheme keyed on `(folio, isin or name)` | implicit in plan tests |
| Dividend reinvest (IDCW-R) creates new lot | `UNIT_CREATING_TYPES` includes `DIVIDEND_REINVEST` | `test_dividend_reinvest_creates_lot_at_reinvest_nav` |
| Bonus units (zero cost basis) | `build_lots` sets `cost=0` for `TxnType.BONUS` | `test_bonus_units_have_zero_cost_basis` |
| Demat-held units possibly missing | `Scheme.is_demat` flag + warning | warning surfaced in `main.py` |
| NRI status | Heuristic regex over investor metadata; `--nri` flag | `test_parser_detects_nri_from_investor_address` |
| Joint holdings | Heuristic regex; `--joint-holdings` flag | `test_parser_detects_joint_holding_from_folio_text` |
| Already-realised LTCG this FY | `--already-realized` subtracts from budget | `test_already_realized_ltcg_shrinks_budget` |
| Carry-forward LTCL | `--carry-forward-loss` adds to budget | `test_carry_forward_loss_expands_budget` |
| Suspended / wound-up schemes | `Scheme.is_suspended` + `data/suspended_schemes.json` + `--suspended` | `test_suspended_lot_excluded_even_when_nav_present` |
| Direct vs Regular plan | Different ISINs treated as separate schemes | implicit |
| Pre-2018 equity grandfathering | `fmv_2018.py` + `lots._apply_grandfathering` | `test_grandfathering_*` (5 tests) |
| Redemption history exceeds units (CAS partial) | `build_lots` clamps `to_deplete` against queue, doesn't crash | `test_redemption_exceeding_holdings_does_not_crash` |
| Unknown scheme category | Excluded with "manual verification required" | `test_unknown_scheme_excluded_with_warning_message` |
| Missing NAV on AMFI feed | Excluded with hint at suspended/wound-up or wrong ISIN | `test_missing_nav_alone_excludes_with_verification_hint` |
| Marginal lot overshoot | Fractional unit cut floored to 4dp | `test_marginal_lot_truncated_to_exact_budget` |
| Multiple harvested lots in same scheme | Aggregated into one PlanLine | `test_aggregates_multiple_lots_of_same_scheme_into_one_line` |

---

## Configuration surface

### CLI flags

| Flag | Default | Purpose |
| --- | --- | --- |
| `cas_pdf` (positional) | required | Path to the CAS PDF |
| `--fy` | derived from today | FY label, e.g. `2026-27` |
| `--password` | prompt | CAS PDF password (prompt is recommended) |
| `--already-realized` | 0 | LTCG already booked this FY |
| `--carry-forward-loss` | 0 | LT capital losses carried forward |
| `--no-cache` | off | Force AMFI NAV refresh |
| `--no-report` | off | Skip writing JSON report |
| `--nri` | off | Assert NRI status |
| `--joint-holdings` | off | Assert joint-holding presence |
| `--overrides FILE` | none | User ISIN → category override file |
| `--suspended FILE` | none | User suspended-ISIN file |
| `--equity-exit-load-days N` | 365 | Equity exit-load assumption window |
| `--no-grandfathering` | off | Skip Sec 112A grandfathering |
| `--refresh-fmv` | off | Re-fetch the 31-Jan-2018 FMV snapshot |

### Files & directories

- `./cache/nav_cache.txt` — daily AMFI NAV snapshot (24h TTL)
- `./cache/fmv_jan_2018.txt` — 31-Jan-2018 NAV snapshot (permanent)
- `./reports/harvest_plan_<FY>_<timestamp>.json` — timestamped reports (cwd-relative, gitignored)
- `tax_harvest/data/category_overrides.json` — packaged classifier overrides
- `tax_harvest/data/suspended_schemes.json` — packaged suspended list

### Override file format

```json
{
  "overrides": {
    "INF000A": "equity",
    "INF000B": "debt_post_apr_2023"
  }
}
```

Valid category strings: `equity`, `elss`, `equity_hybrid_aggressive`, `arbitrage`,
`debt_pre_apr_2023`, `debt_post_apr_2023`, `hybrid_conservative`, `international`,
`gold`, `solution_oriented`, `close_ended`, `fmp`.

---

## Output artifacts

The console output renders four sections (each suppressed if empty):

1. **Header panel** — FY label, exemption limit, already-realised, carry-forward,
   effective budget.
2. **Recommended Redemptions table** — scheme, folio, AMC, units, NAV, cost basis
   being redeemed, estimated LTCG. Sorted by harvested gain desc.
3. **Summary row** — total LTCG harvested, budget remaining.
4. **Warnings panel** — NAV snapshot date, NRI/joint flags, per-scheme caveats
   (international, gold, demat, unknown category, suspended).
5. **Sec 112A Grandfathering Applied table** — only shown if any lot was uplifted;
   includes actual vs effective cost so the user can verify.
6. **Loss-Harvesting Candidates table** — STCL vs LTCL with notes.
7. **Excluded Lots table** — top 30 by would-be gain, with reason text.
8. **Disclaimer** — printed at the end of every run.

The JSON report mirrors the structured plan (`HarvestPlan.model_dump()`) plus the
loss-candidate list.

---

## Test coverage

62 tests total, ~0.2s wall time, split across:

| File | Tests | Focus |
| --- | --- | --- |
| `test_lots.py` | 9 | FIFO depletion, bonus zero-cost, switch in/out, dividend reinvest, ELSS lock-in, Sec 50AA debt, pre-Apr-2023 debt LTCG eligibility, equity <1yr exclusion, unknown scheme handling, over-redemption robustness |
| `test_harvest.py` | 9 | Plan fills budget without exceeding, `--already-realized` shrinks budget, `--carry-forward-loss` expands budget, gain-per-unit ordering, empty input, locked lot exclusion, loss lots not harvested, marginal-lot truncation, multi-lot aggregation |
| `test_classifier.py` | 18 | Name-heuristic across 15 representative schemes, unknown returns UNKNOWN, debt pre/post Apr-2023 refinement, per-lot Sec 50AA bucketing |
| `test_nav.py` | 4 | AMFI text parser, ISIN/code lookups, unmatched-list tracking |
| `test_grandfathering.py` | 8 | Cost formula (3 algebraic cases), pre-2018 application, post-2018 skip, debt skip, FMV-disabled, FMV-missing |
| `test_overrides_and_extras.py` | 14 | Override semantics, file loading + validation, suspended-lot exclusion, NRI/joint heuristic detection (positive + negative), configurable exit-load window |

```
python -m pytest tax_harvest/tests
```

---

## What is intentionally out of scope

These were explicit non-goals in the original spec and have not been built:

- No web UI, no server, no database, no auth.
- No multi-user support.
- No automated redemption execution — the tool tells you what to do; you do it
  on your AMC's portal or via your broker.
- No tax-filing integration — output is informational only.
- No PII storage or upload. The CAS PDF, password, and all derived data stay on
  local disk under `./cache/` and `./reports/` (both gitignored).
- No surcharge / cess / TDS computation. The 12.5% headline rate above ₹1.25L
  is not modelled because harvesting *up to* the exemption produces zero tax.
- No grandfathering for listed equity shares held directly (the tool is
  mutual-fund only).

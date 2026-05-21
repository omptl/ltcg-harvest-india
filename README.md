# tax-harvest

Personal CLI tool for an Indian retail investor to identify which mutual fund units
to redeem each financial year to harvest LTCG up to the ₹1.25 lakh exemption under
Section 112A.

Single-user, runs locally, no server, no PII leaves the machine.

## Install

```
python -m pip install -e .
```

Python 3.11+ required.

## Use

```
tax-harvest path/to/cas.pdf
```

You will be prompted for the CAS PDF password (typically PAN + DOB in DDMMYYYY).
The password is never persisted.

Common options:

```
tax-harvest cas.pdf \
  --fy 2026-27 \
  --already-realized 30000 \
  --carry-forward-loss 15000 \
  --no-cache
```

| Flag | Default | Purpose |
| --- | --- | --- |
| `--fy LABEL` | derived from today | Indian FY label like `2026-27` |
| `--already-realized AMT` | 0 | LTCG already booked this FY — shrinks budget |
| `--carry-forward-loss AMT` | 0 | LT capital loss carried forward — grows budget |
| `--no-cache` | off | Force refresh of AMFI NAV file |
| `--no-report` | off | Skip writing the JSON report file |
| `--password PWD` | prompt | Provide password non-interactively (not recommended) |
| `--nri` | off | Assert NRI status (in addition to auto-detection) |
| `--joint-holdings` | off | Assert joint-holding presence |
| `--overrides FILE` | none | JSON file: `{ISIN: category}` overrides for classifier |
| `--suspended FILE` | none | JSON file: additional suspended/wound-up ISIN list |
| `--equity-exit-load-days N` | 365 | Days under which equity exit load is assumed |
| `--no-grandfathering` | off | Skip Sec 112A pre-2018 cost uplift |
| `--refresh-fmv` | off | Re-fetch the 31-Jan-2018 FMV snapshot |

JSON reports are written under `~/.tax_harvest/reports/`. The AMFI NAV cache
lives at `~/.tax_harvest/nav_cache.txt` (refreshed every 24h). The Sec 112A
31-Jan-2018 FMV snapshot is cached permanently at `~/.tax_harvest/fmv_jan_2018.txt`.

## What it does

1. Parses your CAS PDF via [`casparser`](https://pypi.org/project/casparser/) —
   handles CAMS, KFintech, and MF Central statements. Heuristically detects
   NRI status and joint-holding mode and emits warnings.
2. Classifies each scheme (equity / ELSS / arbitrage / aggressive hybrid /
   debt-pre-Apr-2023 / debt-post-Apr-2023 / international / gold / etc).
   An ISIN-keyed overrides file (`--overrides`) wins over name heuristics.
3. Builds per `(folio, scheme)` FIFO lot queues from your transaction history.
   Bonus units carry zero cost basis; switch-ins create new lots at their NAV;
   dividend reinvestments create new lots at the reinvestment NAV.
4. Fetches today's NAV from the AMFI feed for each scheme, plus the 31-Jan-2018
   FMV snapshot for Sec 112A grandfathering on pre-2018 equity lots.
5. For each lot, evaluates: LTCG eligibility, ELSS per-lot 3-year lock-in,
   solution-oriented 5-year lock-in, FMP / close-ended status, Section 50AA
   applicability for debt units acquired on/after 1-Apr-2023, exit-load window
   (configurable via `--equity-exit-load-days`), and suspended/wound-up status.
6. Sec 112A grandfathering: for equity lots acquired on or before 31-Jan-2018,
   effective cost = `max(actual, min(FMV_31_Jan_2018, sale_NAV))`. The plan
   shows actual vs effective cost per affected lot.
7. Greedy harvest: sort eligible lots by gain-per-unit descending, fill until
   the effective LTCG budget is exhausted, fractional-truncating the marginal
   lot to land exactly on budget.
8. Surfaces a secondary table of loss-harvesting candidates (STCL vs LTCL).

## What it explicitly does not do

- No web UI, no server, no database, no auth, no multi-user support.
- No automated redemption execution.
- No tax filing integration.
- No PII storage or upload. The CAS PDF stays on your local disk.

## Caveats & manual checks

The tool prints warnings for everything it can't be fully sure about:

- International / global / FoF schemes — post-Budget-2024/2025 treatment depends
  on the underlying allocation.
- Gold / silver schemes — separate post-Budget-2024 rules; verify per fund.
- Solution-oriented schemes (retirement / children's gift) — also need a
  goal-age check that isn't in the CAS.
- Demat-held units may not appear in CAS at all.
- NRI status detection is heuristic — pass `--nri` if your CAS doesn't surface it.
- Joint-holding detection is heuristic — pass `--joint-holdings` if missed.
- Pre-31-Jan-2018 equity lots have grandfathering applied automatically when the
  FMV snapshot is fetchable; verify each effective cost in the report.
- The suspended-schemes list ships empty; populate `tax_harvest/data/suspended_schemes.json`
  or use `--suspended` if you hold any wound-up funds. NAV-miss on the AMFI feed
  also flags a scheme as unverified.

This tool is for personal analysis only. Verify with a CA before transacting,
and remember that the NAV at execution will differ from the NAV at analysis.

### Definition of Done — what you still need to verify

The automated tests cover algorithm correctness against synthetic data. The
following items from the original spec require running against your real
CAS PDF:

1. Reads your real CAS PDF without error.
2. Correctly identifies your LTCG-eligible lots — spot-check a few against
   CAMS / KFintech online statements.
3. Outputs a redemption plan that, if executed, produces LTCG close to ₹1.25L —
   verify the total in the bottom-right of the plan.
4. Passes a manual cross-check against your CAMS statement (unit counts,
   purchase dates, cost basis).

Run with `--no-report` first if you don't want a JSON dump while testing.

## Project layout

```
tax_harvest/
├── main.py          # CLI entry point
├── parser.py        # CAS parsing wrapper around casparser
├── classifier.py    # Scheme tax-category classification + override loader
├── lots.py          # FIFO lot construction + lock-in / exit-load / grandfathering
├── nav.py           # AMFI NAV fetch + cache
├── fmv_2018.py      # 31-Jan-2018 FMV snapshot for Sec 112A grandfathering
├── harvest.py       # Greedy harvesting algorithm
├── loss_harvest.py  # Loss-harvest candidate identification
├── report.py        # Rich tables + JSON report writer
├── models.py        # Pydantic data models
├── data/
│   ├── category_overrides.json   # ISIN -> SchemeCategory override map
│   └── suspended_schemes.json    # known wound-up scheme list
└── tests/
```

## Tests

```
python -m pytest tax_harvest/tests
```

62 tests cover FIFO replay, lock-in enforcement, Section 50AA per-lot bucketing,
budget arithmetic with carry-forward losses and prior realizations, scheme
classification + overrides, AMFI NAV parsing, loss categorization, Sec 112A
grandfathering math, suspended-scheme exclusion, and NRI / joint-holding
heuristic detection.

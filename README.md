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
| `--stocks-ltcg AMT` | none | Flat stocks LTCG (₹) booked this FY — shrinks budget |
| `--stocks-ledger FILE` | none | Per-trade CSV of stock sells — see "Stocks vs MF" section |

Two reports are written under `./reports/` (relative to the directory you run
`tax-harvest` from — gitignored at the repo root):

- `harvest_plan_<FY>_<timestamp>.json` — full structured output for tooling.
- `harvest_summary_<FY>_<timestamp>.md` — one-page Markdown summary you can
  open in any editor or GitHub viewer; this is the artifact a non-developer
  should read.

The AMFI NAV cache
lives at `./cache/nav_cache.txt` (refreshed every 24h). The Sec 112A
31-Jan-2018 FMV snapshot is cached permanently at `./cache/fmv_jan_2018.txt`.
Both paths are relative to the directory you run `tax-harvest` from and are
gitignored at the repo root.

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

## Stocks vs mutual funds — the ₹1.25 L exemption is shared

The Sec 112A ₹1,25,000 annual exemption is **aggregate** across:

1. Listed equity shares (STT-paid on both buy + sell)
2. Equity-oriented mutual fund units (STT-paid on redemption) — *what this tool sees*
3. Equity business-trust units (REITs / InvITs)

You do **not** get a separate ₹1.25 L for stocks and another ₹1.25 L for MFs.

If you also book LTCG on direct equity this FY, fold that into the budget so
the MF redemption plan shrinks to fit the remaining headroom. Two options:

**Easy** — pass the LTCG total from your broker's tax P&L as a flat number:

```
tax-harvest cas.pdf --stocks-ltcg 40000
```

**Auditable** — pass a per-trade CSV; the tool filters by FY (on `sell_date`),
keeps only LTCG-eligible rows (held > 365 days) with positive gain, sums them,
and folds the result into the budget:

```
tax-harvest cas.pdf --stocks-ledger stocks.csv
```

The CSV must have these columns (header required, order flexible):

| Column | Format | Notes |
| --- | --- | --- |
| `isin` | string | e.g. `INE002A01018`. Used for traceability. |
| `symbol` | string | e.g. `TCS`. |
| `buy_date` | date | `YYYY-MM-DD`, `DD-MM-YYYY`, `DD/MM/YYYY`, or `DD-Mon-YYYY`. |
| `sell_date` | date | same formats. Leave blank for open positions (ignored). |
| `quantity` | number | shares sold in this row. |
| `buy_value` | ₹ | total acquisition cost for this lot. |
| `sell_value` | ₹ | total proceeds for this lot. |

Example minimal `stocks.csv`:

```csv
isin,symbol,buy_date,sell_date,quantity,buy_value,sell_value
INE002A01018,TCS,2024-01-15,2026-04-22,10,32000,42000
INE001A01036,RELIANCE,2023-06-01,2026-09-12,5,12000,15500
```

Both flags can be combined — they sum. The Markdown summary will break the
budget down so you can audit where each rupee of shrinkage came from.

This tool only sees mutual fund folios from your CAS — direct demat equity
holdings are out of scope as a recommendation source (the tool never suggests
stock buys or sells). The stocks input only affects the **budget**, not the plan.

## What it explicitly does not do

- No web UI, no server, no database, no auth, no multi-user support.
- No automated redemption execution.
- No tax filing integration.
- No coverage of direct equity shares (see note above — combine via `--already-realized`).
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

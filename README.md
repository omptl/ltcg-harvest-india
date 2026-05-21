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

JSON reports are written under `~/.tax_harvest/reports/`. The AMFI NAV cache
lives at `~/.tax_harvest/nav_cache.txt` and is refreshed if older than 24h.

## What it does

1. Parses your CAS PDF via [`casparser`](https://pypi.org/project/casparser/) —
   handles CAMS, KFintech, and MF Central statements.
2. Classifies each scheme (equity / ELSS / arbitrage / aggressive hybrid /
   debt-pre-Apr-2023 / debt-post-Apr-2023 / international / gold / etc).
3. Builds per `(folio, scheme)` FIFO lot queues from your transaction history.
   Bonus units carry zero cost basis; switch-ins create new lots at their NAV;
   dividend reinvestments create new lots at the reinvestment NAV.
4. Fetches today's NAV from the AMFI feed for each scheme.
5. For each lot, evaluates: LTCG eligibility, ELSS per-lot 3-year lock-in,
   solution-oriented 5-year lock-in, FMP / close-ended status, Section 50AA
   applicability for debt units acquired on/after 1-Apr-2023, exit-load window.
6. Greedy harvest: sort eligible lots by gain-per-unit descending, fill until
   the effective LTCG budget is exhausted, fractional-truncating the marginal
   lot to land exactly on budget.
7. Surfaces a secondary table of loss-harvesting candidates (STCL vs LTCL).

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
- NRI status, joint holdings, and pre-31-Jan-2018 equity grandfathering need
  manual confirmation.

This tool is for personal analysis only. Verify with a CA before transacting,
and remember that the NAV at execution will differ from the NAV at analysis.

## Project layout

```
tax_harvest/
├── main.py          # CLI entry point
├── parser.py        # CAS parsing wrapper around casparser
├── classifier.py    # Scheme tax-category classification
├── lots.py          # FIFO lot construction + lock-in / exit-load logic
├── nav.py           # AMFI NAV fetch + cache
├── harvest.py       # Greedy harvesting algorithm
├── loss_harvest.py  # Loss-harvest candidate identification
├── report.py        # Rich tables + JSON report writer
├── models.py        # Pydantic data models
└── tests/
```

## Tests

```
python -m pytest tax_harvest/tests
```

41 tests cover FIFO replay, lock-in enforcement, Section 50AA per-lot bucketing,
budget arithmetic with carry-forward losses and prior realizations, scheme
classification, AMFI NAV parsing, and loss categorization.

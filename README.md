# LTCG Harvest India — Section 112A mutual fund tax planner

Free, open-source tool for Indian retail mutual fund investors to identify
which units to redeem each financial year so booked long-term capital gains
land inside the ₹1,25,000 **Section 112A** exemption. Saves the 12.5% LTCG
tax that would otherwise apply later.

Two surfaces — same engine, same outputs:
- **In-browser** (no install): https://omptl.github.io/ltcg-harvest-india/
- **CLI** (`tax-harvest`): for local use or driving from an AI coding agent.

Single-user, runs locally, no server, no PII leaves the machine. MIT licensed.

---

## How it works (30-second version)

LTCG Harvest India parses your **Consolidated Account Statement (CAS) PDF**
from MF Central / CAMS / KFintech, replays every buy / SIP / switch /
dividend reinvest / redemption in chronological order, builds a per-folio
FIFO lot queue, fetches today's NAV from AMFI, then runs a greedy harvest
algorithm to pick the units to redeem that maximise booked LTCG without
overshooting the **₹1.25 lakh Sec 112A exemption** for the current Indian
financial year. It applies Sec 112A grandfathering for pre-31-Jan-2018 lots,
Sec 50AA for post-1-Apr-2023 debt units (per-lot, not per-scheme), and
nets stocks LTCG/LTCL (Sec 112A bucket is shared across listed equity).
Output is a one-page Markdown plan saying "sell N units of scheme X"
plus a JSON dump. The browser build runs the same Python engine via
Pyodide — same arithmetic, zero data upload.

---

## Three ways to use it

### A. In your browser (nothing to install on your machine — recommended for most users)

**https://omptl.github.io/ltcg-harvest-india/**

- Your CAS PDF, password, and broker P&L are processed **in your browser**
  via WebAssembly Python (Pyodide). Nothing is uploaded, logged, or sent
  to any server.
- Same engine as the CLI — produces identical plans for the same inputs
  (verified by a Playwright end-to-end test in `scripts/e2e_web_test.py`).
- Open the URL → fill the form → done. No Python, no pip, no command line.
  The page downloads a WebAssembly Python runtime (~15 MB the first time:
  Pyodide + ISIN database + NAV snapshot) and runs it sandboxed inside
  your browser tab; the browser cache holds it for subsequent visits, so
  later runs are instant. All of that happens inside the tab — nothing
  touches your operating system, PATH, or filesystem.
- AMFI NAV is mirrored daily by a GitHub Actions cron (the upstream feed
  blocks cross-origin browser fetch).
- Limitation: handles CAMS / KFintech / MF Central CAS PDFs. NSDL/CDSL
  demat-only CAS is out of scope for the browser build (the SQLite ISIN
  database casparser uses for demat CAS does not fit in the browser bundle).
  Use Path C below for those.

### B. Drive it via your AI coding agent (for forking + extending)

If you've just forked this repo and you have Claude Code, Codex, Cursor,
Copilot Chat, Aider, Windsurf, or any other agentic coding tool, the fastest
path is to let the agent handle everything — input gathering, install, run,
result interpretation.

1. Open this repo in your coding tool.
2. Paste the prompt from [`prompts/harvest-runner.md`](prompts/harvest-runner.md)
   into the chat.
3. Answer the questions the agent asks (CAS path, password, optional broker
   tax-P&L, safety buffer).
4. The agent installs the project, runs the tool, and walks you through the
   one-page Markdown summary at `reports/harvest_summary_*.md`.

Inside **Claude Code** specifically, you can also invoke the dedicated
subagent directly:

```
/agent harvest-runner
```

The agent is briefed via [`AGENTS.md`](AGENTS.md) (cross-tool) and
[`CLAUDE.md`](CLAUDE.md) (Claude-specific extras). Both files load
automatically in tools that support those conventions.

### C. Drive it yourself (CLI, no agent)

```
python -m pip install -e .[dev]
python -m pytest tax_harvest/tests             # sanity check — expect 92+ passes
tax-harvest path/to/cas.pdf                    # prompts for password
```

Python 3.11+ required. On Windows, prefix runs with `PYTHONIOENCODING=utf-8`
so the Rich console can render `₹`.

A worked invocation that uses every lever:

```
PYTHONIOENCODING=utf-8 tax-harvest path/to/cas.pdf \
  --stocks-ledger path/to/stocks.csv \
  --safety-buffer-pct 1.5 \
  --fy 2026-27
```

---

## Inputs you'll need

### 1. CAS PDF (required)

Download a **Detailed** Consolidated Account Statement covering the longest
available period (pre-2018 lots matter for Sec 112A grandfathering).

| Source | Coverage |
| --- | --- |
| [MF Central](https://www.mfcentral.com) | CAMS + KFintech + NSDL/CDSL demat (broadest) |
| [CAMSonline](https://www.camsonline.com) | CAMS + KFintech AMCs only |

Email delivery takes ~10–30 minutes. The PDF is password-protected;
password is usually your PAN in uppercase, or PAN + DOB in `DDMMYYYY` format
(the delivery email tells you which).

### 2. Stocks tax-P&L (optional, materially affects the result)

The Sec 112A ₹1.25 L exemption is **aggregate** across listed shares,
equity MFs, and equity business trusts — you don't get a separate ₹1.25 L
for each. The tool reads only your MFs from the CAS, so you need to tell it
how much stock-side LTCG / LTCL you've already booked in this FY (if any).

Three input shapes — pick whichever matches what your broker gave you:

```
--stocks-ltcg 26000 --stocks-ltcl 32000    # flat numbers; both positive
--stocks-ledger path/to/stocks.csv         # per-trade CSV (auditable)
```

Combine the flags — they sum. See "Stocks CSV schema" below.

Note: current-FY long-term **losses** are set off against current-FY
long-term gains **before** the ₹1.25 L exemption kicks in. So a
loss-heavy stock year actually **expands** the MF harvest budget. The
tool nets LTCG and LTCL for you; just pass both.

### 3. Safety buffer (recommended: 1.5%)

```
--safety-buffer-pct 1.5
```

Indian MFs are end-of-day priced. The NAV you transact at is declared
**after** market close that day, not at the moment you place the order.
Mid-cap funds can swing ±1–2% intraday. A 1.5% buffer guarantees the
booked LTCG stays under the ₹1.25 L exemption even if NAV ticks up
between plan time and execution.

Trade-off: ~₹1,900 of exemption goes unused unless you follow up with a
top-up redemption tomorrow against the now-known NAV.

---

## Stocks CSV schema

Header required. Column order flexible. Save as UTF-8 CSV.

| Column | Format | Notes |
| --- | --- | --- |
| `isin` | string | e.g. `INE002A01018`. Used for traceability. |
| `symbol` | string | e.g. `TCS`. |
| `buy_date` | date | `YYYY-MM-DD`, `DD-MM-YYYY`, `DD/MM/YYYY`, or `DD-Mon-YYYY` |
| `sell_date` | date | Same formats. Leave blank for open positions (ignored). |
| `quantity` | number | shares sold in this row. |
| `buy_value` | ₹ | total acquisition cost for this lot. |
| `sell_value` | ₹ | total proceeds for this lot. |

Minimal example:

```csv
isin,symbol,buy_date,sell_date,quantity,buy_value,sell_value
INE002A01018,TCS,2024-01-15,2026-04-22,10,32000,42000
INE001A01036,RELIANCE,2023-06-01,2026-09-12,5,12000,15500
```

Converting from broker exports:
- **Zerodha Console** (Tax P&L Excel): `Tradewise Exits` sheet, `Equity - Long Term`
  section. Map `Symbol → symbol`, `ISIN → isin`, `Entry Date → buy_date`,
  `Exit Date → sell_date`, `Quantity → quantity`, `Buy Value → buy_value`,
  `Sell Value → sell_value`.
- **Other brokers**: same idea, different sheet names. If you're using the
  agent-driven flow above, the agent will do this transformation for you.

The tool filters by FY (on `sell_date`), keeps only LTCG-eligible rows
(holding > 365 days), separates gains and losses, sums each, nets them,
folds the result into the budget.

---

## Outputs

Written to `./reports/` (cwd-relative, gitignored):

- **`harvest_summary_<FY>_<ts>.md`** — one-page Markdown summary. **Read this.**
- `harvest_plan_<FY>_<ts>.json` — full structured plan for tooling.

The Markdown summary has:

1. **🟢 / 🟡 Redemption window** — should you act now or wait until tomorrow?
   Based on current IST time vs the 3 PM cut-off.
2. **Budget breakdown** — exemption, prior MF LTCG, stocks LTCG/LTCL, net
   stocks position, carry-forward, safety buffer, effective budget.
3. **What to sell** — per-scheme: units, NAV, cost basis, estimated LTCG.
4. **How to execute** — order placement, post-settlement reinvestment.
5. **Spot-check checklist** — what to verify on your AMC portal before
   clicking Sell.
6. **Stocks LTCG / LTCL detail** (if you provided a ledger).
7. **Loss-harvesting candidates** (top 10).
8. **Warnings** — international / gold / unclassified / suspended schemes
   to verify manually.

Caches live in `./cache/`:
- `nav_cache.txt` — AMFI daily NAV (24h TTL; `--no-cache` to bust).
- `fmv_jan_2018.txt` — historical FMV snapshot (permanent; `--refresh-fmv` to bust).

---

## CLI flag reference

| Flag | Default | Purpose |
| --- | --- | --- |
| `cas_pdf` (positional) | required | Path to the CAS PDF |
| `--password PWD` | prompt | CAS PDF password (omit to be prompted; recommended) |
| `--fy LABEL` | derived from today | Indian FY label, e.g. `2026-27` |
| `--stocks-ltcg AMT` | none | Flat stocks LTCG (₹, positive) booked this FY |
| `--stocks-ltcl AMT` | none | Flat stocks LTCL (₹, positive number for losses) — nets off LTCG; can expand budget |
| `--stocks-ledger FILE` | none | Per-trade CSV — see "Stocks CSV schema" |
| `--safety-buffer-pct N` | 0 | Shave N% off budget — absorbs NAV swing. Typical 1.0–2.0. |
| `--already-realized AMT` | 0 | MF LTCG already booked this FY (separate from stocks) |
| `--carry-forward-loss AMT` | 0 | LTCL from PRIOR FYs being applied now |
| `--nri` / `--joint-holdings` | off | Override heuristics if your CAS doesn't surface these |
| `--overrides FILE` | none | JSON `{ISIN: category}` for misclassified schemes |
| `--suspended FILE` | none | JSON list of additional suspended/wound-up ISINs |
| `--equity-exit-load-days N` | 365 | Days under which equity exit load is assumed |
| `--no-grandfathering` | off | Skip Sec 112A pre-2018 cost uplift |
| `--refresh-fmv` | off | Re-fetch the 31-Jan-2018 FMV snapshot |
| `--no-cache` | off | Force AMFI NAV refresh |
| `--no-report` | off | Skip writing JSON + Markdown to `reports/` |

---

## What it does NOT do

- No web UI, no server, no database, no auth, no multi-user.
- No automated redemption execution — it tells you what to do; you do it.
- No tax-filing integration.
- No coverage of direct equity recommendations (read-only on stocks).
- No PII storage or upload.
- No surcharge / cess / TDS computation. The plan harvests *up to* the
  exemption → zero tax in the current FY by construction.

---

## Caveats (the tool prints warnings for these)

- **International / global FoFs** — post-Budget-2024/2025 treatment depends
  on underlying allocation. Verify per fund.
- **Gold / silver schemes** — separate post-Budget-2024 rules. Verify per fund.
- **Solution-oriented schemes** (retirement / children's gift) — also need
  a goal-age check that isn't in the CAS.
- **Demat-held units** may not appear in CAS at all. Cross-check.
- **NRI / joint-holding** detection is heuristic; pass `--nri` /
  `--joint-holdings` if your CAS doesn't surface these.
- **Pre-31-Jan-2018 equity lots** get grandfathering applied automatically
  when the FMV snapshot loads; verify each effective cost in the report.
- **Suspended schemes** — packaged list ships empty; populate
  `tax_harvest/data/suspended_schemes.json` or use `--suspended` if you
  hold any wound-up funds.
- **NAV at execution differs from NAV at analysis** — Indian MFs are
  end-of-day priced. The safety buffer absorbs typical intraday swing.
- **Public-holiday calendar is not modelled** — the timing advisory uses
  "next weekday" not "next trading day". Verify against NSE / AMC calendar
  if your run lands near Diwali / Republic Day / etc.

This tool is for personal analysis only. **Verify with a CA before
transacting.**

---

## Definition of Done — what you still need to verify against your real CAS

Regardless of which path you used (browser / agent / CLI):

1. Reads your CAS PDF without error.
2. Correctly identifies your LTCG-eligible lots — spot-check a few against
   CAMS / KFintech / MF Central online statements.
3. Outputs a redemption plan that, if executed, produces LTCG close to the
   effective budget (top-right of the Markdown summary).
4. Unit counts, purchase dates, and cost basis in the action table
   reconcile with your AMC portal.
5. Booked stock LTCG/LTCL (if any) is reflected in the Budget table's
   "Net stocks position" row.
6. NAV snapshot date in the warnings panel is recent (≤ 1 trading day).
   If it's older, the GitHub Actions NAV mirror has lagged — for the
   browser build wait for the next cron; for the CLI rerun with
   `--no-cache`.

CLI users: pass `--no-report` if you don't want a JSON + Markdown dump
while testing.

---

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
├── stocks.py        # Stocks ledger / flat-input adjustment (LTCG/LTCL netting)
├── timing.py        # IST cut-off advisory + NAV staleness
├── report.py        # Rich tables + JSON + Markdown writers
├── models.py        # Pydantic data models
├── data/
│   ├── category_overrides.json   # ISIN → SchemeCategory overrides
│   └── suspended_schemes.json    # known wound-up scheme list
└── tests/                         # 92+ tests, ~1s

web/
├── index.html       # In-browser UI (Pyodide-driven)
├── spike.html       # Day-1 compatibility test, kept as regression
└── data/
    ├── nav_cache.txt              # AMFI NAV mirror, refreshed by GH cron
    ├── fmv_jan_2018.txt           # 31-Jan-2018 historical FMV snapshot
    ├── isin_db.json               # Slim scheme DB (sidesteps rapidfuzz in browser)
    └── tax_harvest-*.whl          # Engine wheel, installed via micropip

scripts/
└── e2e_web_test.py  # Playwright headless drive that verifies the browser
                     # build's output matches the CLI's output, lot for lot.

.github/workflows/
├── mirror-nav.yml   # Daily cron: refresh nav_cache.txt + rebuild wheel.
└── deploy-pages.yml # Publish web/ to https://omptl.github.io/ltcg-harvest-india/
```

Architecture deep-dive (data flow, design decisions, tax-rule cheat sheet,
edge-case-to-test map) lives in [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md).
Agent-driving guide lives in [`AGENTS.md`](AGENTS.md).

# AGENTS.md

Canonical guide for any AI coding agent (Claude Code, Codex, Cursor, Copilot
Chat, Aider, Windsurf, etc.) driving this repo for an end user. If you are
that agent, read this file end-to-end before touching anything else.

---

## What this project is

`tax-harvest` is a personal CLI for an Indian retail mutual-fund investor.
Each financial year (FY = Apr 1 → Mar 31) the Income Tax Act, Sec 112A
exempts the first ₹1,25,000 of long-term capital gains on listed equity +
equity MFs + equity business trusts. "Tax harvesting" means redeeming and
immediately reinvesting just enough units that booked LTCG lands at the
exemption — resets cost basis higher, permanently saves the 12.5% tax that
would otherwise apply later.

Input: a CAS PDF (Consolidated Account Statement from CAMS / KFintech /
MF Central) + optionally a stocks tax-P&L from the user's broker.

Output: a one-page Markdown summary (`reports/harvest_summary_*.md`) saying
"sell these units of these schemes" + a JSON dump for tooling.

The tool runs entirely locally. No network calls except AMFI NAV feed (public).
No PII leaves the machine. Personal data is gitignored.

---

## Your job, as the agent

Drive the user through input gathering → install → run → result interpretation.
Do NOT recommend tax strategies the tool didn't compute. Do NOT modify tax-rule
constants without going through the `tax-rule-change` checklist (see
`.claude/skills/tax-rule-change/SKILL.md` if you are in Claude Code).

Conversational flow:

1. **Greet + confirm goal**. "I see you want a Sec 112A LTCG harvest plan
   for the current FY." Confirm current FY (e.g. `2026-27` if it's
   May 2026; the tool auto-derives it).
2. **Gather inputs** (ask one at a time, do not batch):
   - Path to CAS PDF.
   - CAS PDF password (usually `PAN` in uppercase, or `PAN + DOB DDMMYYYY`).
     Never persist this. Pass via `--password` only for this single
     subprocess call; do not log it.
   - Optional: path to broker tax-P&L (Zerodha Console Excel, Groww CSV,
     etc.) for FY 2026-27 onward. If user has it, convert to canonical CSV
     (see §"Canonical stocks CSV" below) and pass via `--stocks-ledger`.
     If they only have a number, use `--stocks-ltcg` and `--stocks-ltcl`.
   - Safety buffer percentage (default 1.5 unless user says otherwise).
3. **Install** (only if not done):
   - Check Python 3.11+ exists (`python --version`).
   - If `venv` module missing (some stripped Python installs lack it),
     install `virtualenv` via `pip install --user virtualenv` and use that.
   - Create `.venv`, install editable: `.venv/Scripts/python.exe -m pip
     install -e ".[dev]"` (Windows) or `.venv/bin/pip install -e ".[dev]"`
     (Unix).
   - Run the test suite as sanity: `python -m pytest tax_harvest/tests`.
     Should be 92+ tests passing in ~1s.
4. **Run the tool** with `PYTHONIOENCODING=utf-8` set in the environment on
   Windows (rich panel renders `₹` glyph which crashes legacy cp1252
   consoles otherwise).
5. **Read the Markdown summary** (`reports/harvest_summary_<FY>_<ts>.md`)
   back to the user. Walk them through: the Redemption-window advisory
   (green/amber), the budget breakdown, the per-scheme units to sell, the
   spot-check items, and any warnings.
6. **Answer follow-ups** using the tool's outputs as ground truth. If
   asked about something not in the report, say so — don't invent.

---

## Install

```
python -m pip install --user virtualenv  # only if `python -m venv` fails
python -m virtualenv .venv               # or `python -m venv .venv`
.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows
.venv/bin/pip install -e ".[dev]"                       # Unix
```

Confirm with:

```
.venv/Scripts/tax-harvest.exe --help   # Windows
.venv/bin/tax-harvest --help            # Unix
python -m pytest tax_harvest/tests -q   # 92 tests, ~1s
```

---

## Run

Minimal:

```
PYTHONIOENCODING=utf-8 .venv/Scripts/tax-harvest.exe \
    path/to/cas.pdf
```

With stocks ledger + safety buffer (the recommended invocation):

```
PYTHONIOENCODING=utf-8 .venv/Scripts/tax-harvest.exe \
    path/to/cas.pdf \
    --stocks-ledger path/to/stocks.csv \
    --safety-buffer-pct 1.5
```

If the user hasn't passed `--password`, the tool prompts interactively.

---

## Inputs the user provides

### 1. CAS PDF (required)

Sources:
- **MF Central** (`https://www.mfcentral.com`) — broadest coverage (CAMS + KFin + NSDL/CDSL demat).
- **CAMSonline** (`https://www.camsonline.com`) — CAMS + KFin AMCs only.

Settings to choose at download time:
- Statement type: **Detailed** (NOT summary — tool needs full transaction history).
- Period: earliest possible to today (pre-2018 lots matter for grandfathering).
- Delivery: email. Arrives in 10–30 min as a password-protected PDF.

Password: usually PAN in uppercase, or PAN + DOB in `DDMMYYYY` format.

### 2. Stocks tax-P&L (optional, but materially affects the result)

The Sec 112A ₹1.25 L exemption is **aggregate** across listed shares,
equity MFs, and equity business trusts. Stock LTCG already booked in the
current FY shrinks the MF harvest budget; stock LTCL **expands** it
(current-FY LTCL sets off current-FY LTCG before the exemption applies).

Two ways the user can provide it:

**A. Flat numbers** (easy):
```
--stocks-ltcg 26000 --stocks-ltcl 32000
```
(Both numbers positive. Read off the broker's tax P&L total — Zerodha
Console → Reports → Tax P&L → Equity → Long Term row.)

**B. Per-trade CSV** (auditable):
```
--stocks-ledger stocks.csv
```

### 3. Safety buffer (recommended)

```
--safety-buffer-pct 1.5
```

Shaves 1.5% off the budget before harvesting so a 1.5% adverse intraday
NAV move (typical mid-cap fund) cannot push booked LTCG over the
exemption. Single-pass alternative to a two-pass top-up redemption.

---

## Canonical stocks CSV

Required columns (header row; column order flexible):

```csv
isin,symbol,buy_date,sell_date,quantity,buy_value,sell_value
INE002A01018,TCS,2024-01-15,2026-04-22,10,32000,42000
INE001A01036,RELIANCE,2023-06-01,2026-09-12,5,12000,15500
```

Date formats accepted: `YYYY-MM-DD`, `DD-MM-YYYY`, `DD/MM/YYYY`, `DD-Mon-YYYY`.
Blank `sell_date` → treated as an open position and ignored.

The tool filters by FY on `sell_date`, keeps only LTCG-eligible rows
(holding > 365d), separates gains and losses, sums each, nets them,
folds into the budget.

### Converting a broker export

Zerodha "Tax P&L" Excel (Tradewise Exits sheet, "Equity - Long Term"
section): map `Symbol → symbol`, `ISIN → isin`, `Entry Date → buy_date`,
`Exit Date → sell_date`, `Quantity → quantity`, `Buy Value → buy_value`,
`Sell Value → sell_value`. Other brokers: same idea, different sheet names.

When the user shares an Excel file, write a one-off Python script using
`openpyxl` to extract the long-term rows and emit canonical CSV. Save the
script under `scripts/` if it's reusable, otherwise inline it.

---

## Levers (CLI flags worth knowing)

| Flag | Use |
| --- | --- |
| `--fy 2026-27` | Override FY. Defaults to current. |
| `--already-realized AMT` | MF LTCG already booked this FY (not the same as stocks). |
| `--carry-forward-loss AMT` | LTCL from PRIOR FYs being applied now. |
| `--stocks-ltcg AMT` / `--stocks-ltcl AMT` | Flat numbers from broker P&L. Both positive. |
| `--stocks-ledger FILE` | Per-trade canonical CSV. Combines with flat flags. |
| `--safety-buffer-pct N` | Shave N% off budget. 1.0–2.0 typical. |
| `--no-cache` | Force AMFI NAV refresh (use after a crashed prior run, or for fresh prices). |
| `--no-report` | Skip writing JSON + Markdown to `reports/`. |
| `--nri` / `--joint-holdings` | Override heuristics if your CAS doesn't surface NRI / joint status. |
| `--overrides FILE` | JSON `{ISIN: category}` for misclassified schemes. |
| `--suspended FILE` | JSON list of additional suspended/wound-up ISINs. |
| `--no-grandfathering` | Skip Sec 112A pre-2018 cost uplift (don't normally use). |
| `--refresh-fmv` | Re-fetch the 31-Jan-2018 FMV snapshot. |

---

## Outputs

- `reports/harvest_summary_<FY>_<ts>.md` — one-page Markdown, the artifact
  the user should read.
- `reports/harvest_plan_<FY>_<ts>.json` — full structured plan for tooling.
- `cache/nav_cache.txt` — AMFI daily NAV (24h TTL).
- `cache/fmv_jan_2018.txt` — historical FMV snapshot (permanent).

All cwd-relative, all gitignored at repo root.

---

## Failure modes you may hit

| Symptom | Cause | Fix |
| --- | --- | --- |
| `No module named venv` | Stripped Python install missing `venv` + `ensurepip` | `pip install --user virtualenv` then `python -m virtualenv .venv` |
| `UnicodeEncodeError: 'charmap'` on Windows | Legacy cp1252 console can't render `₹` | Set `PYTHONIOENCODING=utf-8` before running |
| Plan empty + every lot "NAV unavailable" | NAV cache is 0 bytes from a prior crashed run | `rm cache/nav_cache.txt` and rerun with `--no-cache` |
| "Snapshot dated 25-Mar-2025" but it's actually 2026 | (Fixed in this repo's nav.py) Old AMFI feeds had mixed dates from interval funds | Pull latest main; `--no-cache` to force refresh |
| `'CASData' object has no attribute 'get'` | (Fixed) Old casparser version mismatch | Pull latest main |
| Lots-locked / lots in lock-in dominate excluded list | Real — ELSS 3-yr / solution-oriented 5-yr / FMP locks. Surface in the excluded-lots table, not actionable. | n/a |
| User holds direct equity (stocks) but tool says "0 stocks LTCG" | Tool doesn't read demat — user must supply via `--stocks-ltcg` / `--stocks-ltcl` / `--stocks-ledger` | Ask user for broker tax P&L |

---

## Invariants (don't break)

These are the load-bearing design rules. If a change forces you to violate
one of them, stop and ask the user first.

- **FIFO key is `(folio, isin or scheme_name)`.** Don't collapse across folios
  or across direct vs regular plans.
- **Sec 50AA is per-lot, not per-scheme.** `classify_lot_for_tax` straddles
  the 1-Apr-2023 cutoff inside `evaluate_lots`. Keep the per-lot refinement.
- **Greedy harvest sorts by gain-per-unit descending; marginal lot is
  fractionally truncated to 4 decimal places.** That's the AMC precision.
- **Excluded lots carry a human-readable `excluded_reason` string.** Never
  silent-filter; always say why.
- **Pydantic models in `models.py` are the cross-module contract.** Don't
  thread ad-hoc dicts across stages.
- **Sec 112A exemption is shared with listed equity LTCG.** The
  `--stocks-*` flags are how the user folds that in. Don't suggest stock
  buys or sells — read-only on stocks.
- **Indian MFs are end-of-day priced.** Plan NAV is yesterday; transaction
  NAV is today (or next biz day after 3 PM IST cutoff). The timing
  advisory + safety buffer exist to make this honest.
- **Tax rule changes require a 3-file update**: rule code in
  `classifier.py`/`lots.py` + cheat sheet in `PROJECT_OVERVIEW.md` + test
  in `tax_harvest/tests/`. Skipping any drifts the codified rules from
  the docs.

---

## Where to look for more

- `PROJECT_OVERVIEW.md` — engineering walkthrough: end-to-end data flow,
  module responsibilities, codified tax rules (Sec 112A, Sec 50AA,
  lock-ins, grandfathering), design decisions, edge-case-to-test map.
  Read this before any non-trivial code change.
- `CLAUDE.md` — Claude-Code-specific extras (this file imports it).
- `.claude/skills/tax-rule-change/SKILL.md` — checklist for tax rule
  updates.
- `.claude/agents/tax-rule-auditor.md` — read-only audit subagent that
  cross-checks the cheat sheet against the codified constants.
- `README.md` — end-user quickstart with the paste-prompt for kicking
  off this exact flow.

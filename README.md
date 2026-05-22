# LTCG Harvest India

> Section 112A long-term capital gains harvesting calculator for Indian
> retail mutual fund investors. **Free, open source, runs entirely on
> your machine or in your browser tab.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Live site](https://img.shields.io/badge/live-omptl.github.io%2Fltcg--harvest--india-brightgreen)](https://omptl.github.io/ltcg-harvest-india/)
[![Tests](https://img.shields.io/badge/tests-92%20passing-brightgreen)](tax_harvest/tests/)

Each financial year, the Indian Income Tax Act, **Section 112A**, exempts
the first **₹1,25,000** of long-term capital gains on listed equity, equity
mutual funds, and equity business trusts. Realising gains *up to* that
limit and immediately reinvesting resets your cost basis higher — saving
the 12.5% tax that would otherwise apply on those gains later. This tool
picks the exact units of which mutual fund schemes to redeem so booked
LTCG lands at the exemption, without overshooting.

---

## Try it

### 🌐 In your browser — nothing to install

**→ https://omptl.github.io/ltcg-harvest-india/**

Upload your CAS PDF + optional broker tax-P&L → get a one-page redemption
plan. Your data never leaves the tab — the Python engine runs sandboxed
in WebAssembly. First visit downloads ~15 MB (cached after).

### 💻 As a Python CLI

```bash
pip install -e .[dev]
tax-harvest path/to/cas.pdf --stocks-ltcg 26000 --safety-buffer-pct 1.5
```

Requires Python 3.11+. On Windows prefix with `PYTHONIOENCODING=utf-8`
so Rich can render `₹`. See [CLI reference](#cli-reference) below.

### 🤖 Via your AI coding agent (forks + extensions)

Open this repo in Claude Code / Cursor / Codex / Copilot Chat / Aider /
Windsurf → paste [`prompts/harvest-runner.md`](prompts/harvest-runner.md)
into the chat → answer 4 questions. Agent handles install, run, result
walkthrough.

Inside Claude Code: `/agent harvest-runner`.

---

## What you need

| Input | Required? | How to get it |
|---|---|---|
| **CAS PDF** | yes | [MF Central](https://www.mfcentral.com) (broadest) or [CAMSonline](https://www.camsonline.com). Pick **Detailed**, longest period available. Arrives by email in ~10–30 min. |
| **PDF password** | yes | Usually your PAN in uppercase, or PAN + DOB `DDMMYYYY`. The delivery email says which. |
| **Broker tax-P&L** | optional | Zerodha Console "Tax P&L" Excel, or any CSV in the canonical schema (see below). |

The Sec 112A ₹1.25 L exemption is **shared** with listed equity LTCG —
not separate buckets. If you've booked stock gains/losses this FY, fold
them in via `--stocks-ltcg` / `--stocks-ltcl` (or `--stocks-ledger` for a
per-trade CSV). Current-FY long-term losses set off against gains
**before** the exemption — so a loss-heavy stock year actually *expands*
the MF harvest budget.

### Stocks CSV schema

```csv
isin,symbol,buy_date,sell_date,quantity,buy_value,sell_value
INE002A01018,TCS,2024-01-15,2026-04-22,10,32000,42000
```

Dates: `YYYY-MM-DD` / `DD-MM-YYYY` / `DD/MM/YYYY` / `DD-Mon-YYYY`. Blank
`sell_date` = open position, ignored. The web build accepts the Zerodha
xlsx directly — no conversion needed.

---

## What you get

A one-page Markdown summary at `reports/harvest_summary_<FY>_<ts>.md`
(plus a structured JSON dump beside it). Sections:

1. **🟢 / 🟡 Redemption window** — should you act now or rerun tomorrow?
   Based on current IST time vs the 3 PM AMC cut-off.
2. **Budget breakdown** — exemption, MF prior gains, stocks net position,
   safety buffer, effective budget.
3. **What to sell** — per-scheme: units, NAV, cost basis, estimated LTCG.
4. **How to execute** — order placement + post-settlement reinvestment.
5. **Spot-check checklist** — verify on your AMC portal before clicking Sell.
6. **Warnings** — international / gold / unclassified / suspended schemes
   worth manual review.

---

## Verify before you sell

Regardless of which path you used:

- **Unit counts + folio numbers** in the action table match your AMC portal.
- **NAV snapshot date** in the warnings panel is recent (≤ 1 trading day).
  If stale, the GitHub Actions NAV mirror lagged — wait for the next cron
  (browser) or rerun with `--no-cache` (CLI).
- **Booked stock LTCG/LTCL** (if any) shows up in the Budget table's
  "Net stocks position" row.

NAV at execution will differ from plan NAV by ±1–2% (Indian MFs are
end-of-day priced — see the [redemption window section][howitworks]).
The default 1.5% safety buffer absorbs this. Always verify with a CA
before transacting.

[howitworks]: PROJECT_OVERVIEW.md#timing-and-the-end-of-day-nav

---

## CLI reference

`tax-harvest --help` shows the full list. The high-leverage flags:

```
tax-harvest CAS_PDF [options]

  --stocks-ltcg AMT          Stocks LTCG booked this FY (₹, positive)
  --stocks-ltcl AMT          Stocks LTCL booked this FY (₹, positive)
  --stocks-ledger FILE       Per-trade CSV (canonical schema)
  --safety-buffer-pct N      Shave N% off budget (typical 1.0–2.0)
  --fy 2026-27               Override FY (auto-derived from today)
  --already-realized AMT     MF LTCG already booked this FY
  --carry-forward-loss AMT   LTCL from PRIOR FYs being applied now
  --no-cache                 Force AMFI NAV refresh
  --no-report                Skip writing reports/
```

Less common flags: `--nri`, `--joint-holdings`, `--overrides`,
`--suspended`, `--equity-exit-load-days`, `--no-grandfathering`,
`--refresh-fmv`. Documented in `--help`.

---

## Limitations

<details>
<summary>The tool prints warnings for these — review every run</summary>

- **International / gold / silver / FoF schemes** — post-Budget-2024
  treatment depends on the underlying allocation. Verify per fund.
- **Solution-oriented schemes** (retirement / children's gift) — also
  need a goal-age check that isn't in the CAS.
- **Demat-held units** may not appear in CAS at all. Cross-check.
- **NRI / joint-holding** detection is heuristic; pass `--nri` /
  `--joint-holdings` if your CAS doesn't surface these.
- **Pre-31-Jan-2018 equity lots** get grandfathering applied
  automatically; verify each effective cost in the report.
- **Suspended schemes** — packaged list ships empty; populate
  `tax_harvest/data/suspended_schemes.json` or `--suspended` if you hold
  any wound-up funds.
- **Public holidays not modelled** — timing advisory uses "next weekday"
  not "next trading day". Verify near Diwali / Republic Day / etc.
- **Browser build: CAMS / KFin / MF-Central CAS only.** NSDL/CDSL
  demat-only CAS needs the full SQLite ISIN DB that won't fit in the
  bundle — use the CLI for those.

</details>

### Explicit non-goals

No server, no database, no user accounts. No automated redemption
execution. No tax-filing integration. No surcharge / cess / TDS
computation (the plan harvests *up to* the exemption → zero tax in the
current FY by construction). No recommendations on direct equity / F&O
/ derivatives.

---

## How it works

CLI / browser parse your CAS via [casparser](https://pypi.org/project/casparser/),
build per-folio FIFO lot queues from your full transaction history,
fetch today's NAV from [AMFI](https://www.amfiindia.com/spages/NAVAll.txt),
apply Sec 112A grandfathering (pre-31-Jan-2018 lots) and Sec 50AA
(per-lot, not per-scheme, for debt acquired post-1-Apr-2023), net any
stocks LTCG/LTCL into the budget, then run a greedy harvest sorted by
gain-per-unit (the marginal lot is fractionally truncated to 4 decimal
places to land on budget exactly). Output is rendered as Rich console
tables + Markdown + JSON.

Architecture deep-dive — data flow, design decisions, tax-rule cheat
sheet, edge-case-to-test map — lives in
[`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md). Agent-driving guide in
[`AGENTS.md`](AGENTS.md).

---

## Contributing

PRs welcome — bug fixes, broker adapters, tax-rule updates (with the
3-file rule), UI polish. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for
dev setup + the must-read tax-rule change process.

## License

[MIT](LICENSE). Not investment, tax, or legal advice — the author is
not a SEBI-registered investment adviser or a Chartered Accountant.

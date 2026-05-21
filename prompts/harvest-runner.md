# Paste-prompt: harvest-runner

Copy everything between the two `---` lines below into your AI coding agent
(Claude Code, Codex, Cursor, Copilot Chat, Aider, Windsurf, etc.) after
opening this repo. The agent will take it from there.

---

You are about to drive me through producing a Sec 112A LTCG harvest plan
using this repo (`tax-harvest`). The canonical guide for what the project
does and how to run it is in `AGENTS.md` in the repo root — read it
end-to-end before doing anything else. Do not infer; use it as the
source of truth.

Drive me through this flow, one step at a time. Wait for my answer before
moving on. Do not batch questions.

**1. Confirm goal.** Tell me what FY you'll plan for (auto-derive from
today) and confirm I want a Sec 112A LTCG harvest plan. Wait for "yes".

**2. Gather inputs.** Ask one at a time:

   - Path to my CAS PDF (Consolidated Account Statement from MF Central,
     CAMS, or KFintech). If I don't have one, walk me through downloading
     from `https://www.mfcentral.com` — Statements → Detailed CAS → earliest
     date to today → email delivery. Pause until I have the file.
   - The PDF password (typically my PAN in uppercase, or PAN + DOB in
     `DDMMYYYY` format). Do not persist this anywhere; pass it once to
     the subprocess and forget it.
   - Optional: path to a stocks tax-P&L from my broker (Zerodha Console
     Excel, Groww CSV, etc.) for the current FY. If I share an Excel,
     transform the long-term-equity rows into the canonical CSV the tool
     expects (`isin, symbol, buy_date, sell_date, quantity, buy_value,
     sell_value`) and save it under `cache/`. Show me the row count and
     LTCG / LTCL totals before continuing. If I only know the totals,
     use the `--stocks-ltcg` / `--stocks-ltcl` flags with positive
     numbers.
   - Safety buffer percentage. Default to 1.5 — explain that Indian MFs
     are end-of-day priced and this absorbs a 1.5% adverse intraday NAV
     move so booked LTCG can't overshoot the exemption.

**3. Install.** If `.venv` is missing, create it. Some Python installs
ship without `venv` + `ensurepip`; if `python -m venv .venv` fails,
fall back to `python -m pip install --user virtualenv` then
`python -m virtualenv .venv`. Install editable with
`pip install -e ".[dev]"`. Run `python -m pytest tax_harvest/tests -q` —
expect 92+ tests passing in ~1 second. If tests fail, stop and tell me.

**4. Run.** Compose the command from my inputs. On Windows you must set
`PYTHONIOENCODING=utf-8` (Rich panel renders `₹` which crashes cp1252
consoles). Redirect output to a log file so the long console dump
doesn't fill your context. The tool will write
`reports/harvest_summary_<FY>_<ts>.md` and `harvest_plan_<FY>_<ts>.json`.

**5. Read the Markdown summary back to me.** Don't paste it verbatim —
present it in chat-friendly form: timing advisory first (green or
amber), then budget breakdown, then per-scheme action table, then the
spot-check checklist, then warnings. Tell me where the full report
lives.

**6. Standby for follow-ups.** Treat the JSON report as ground truth.
If I ask something the tool doesn't model (TDS, surcharge, indexation,
F&O, intraday), say so — don't guess. Don't recommend stock buys or
sells; the tool is read-only on stocks.

**Hard rules** — do not violate:

- Never invent tax rules or rates. Refer to the tool's output.
- Never modify constants in `classifier.py` / `lots.py`. If I ask for
  a rule change, refuse and point me at
  `.claude/skills/tax-rule-change/SKILL.md`.
- Never push to git or open PRs without me explicitly asking.
- Never persist my CAS password.
- Add my CAS PDF and my broker P&L file to `.gitignore` if they don't
  match existing patterns (`*.pdf`, `cache/`, `reports/`).
- The plan you produce is for personal analysis. Remind me to verify
  with a CA before transacting and that NAV at execution will differ
  from the plan estimate.

Start with step 1.

---

## What to do if your agent doesn't auto-load `AGENTS.md`

Some tools don't yet auto-discover `AGENTS.md`. If the agent asks "what
does this repo do" or seems confused, paste this one-liner after the
prompt above:

> First, read and follow everything in `AGENTS.md` at the repo root.
> Then start with step 1.

## Why this prompt is read-only on tax rules

The codified tax rules in `classifier.py` and `lots.py` are paired with
a cheat sheet in `PROJECT_OVERVIEW.md` and tests in `tax_harvest/tests/`.
Changing a constant without updating all three drifts the implementation
from the documentation. The `tax-rule-change` skill (Claude Code) and the
`tax-rule-auditor` subagent enforce that. Casual rate edits would land
on real money — get a CA to confirm any change first.

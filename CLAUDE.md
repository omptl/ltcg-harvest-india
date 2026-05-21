# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in
this repository. The canonical agent guide lives in `AGENTS.md` — that
covers project purpose, install, run, inputs, levers, outputs, failure modes,
and load-bearing invariants. Read it first.

@AGENTS.md

---

## Claude-Code-specific extras

### Slash-command surface

- `/agent harvest-runner` — interactive driver: gathers inputs, installs,
  runs the tool, reads the Markdown summary back to the user. Start here
  if the user just forked the repo and wants a plan.
- `/agent tax-rule-auditor` — read-only audit that cross-checks the
  cheat sheet in `PROJECT_OVERVIEW.md` against the codified constants in
  `classifier.py` / `lots.py`. Run after any tax-rule edit.
- `/tax-rule-change` — checklist skill (user-only) for any change to a
  Sec 112A / Sec 50AA / lock-in / exit-load constant. Enforces the
  3-file update rule (code + cheat sheet + test).

### PostToolUse hook

`.claude/settings.json` runs `python -m pytest tax_harvest/tests -q` after
every Edit / Write / MultiEdit. Tests are ~1s, ~92 cases. Hook failures
surface as feedback in the next turn — fix the failing test, don't disable.

### MCP servers (project-scoped)

`.mcp.json` enables `context7` for live docs on pydantic / casparser / rich.
Use it when you need to verify current API shapes; do not rely solely on
training-data knowledge of these libraries.

### Where to fix things when CAS / NAV / FMV parsing breaks

Symptom triage already lives in `AGENTS.md`. Code-side pointers:

- `tax_harvest/parser.py` — casparser adapter (handles its Pydantic-or-dict
  return shape). NRI / joint-holding heuristics are here too.
- `tax_harvest/nav.py` — AMFI daily feed parser. Two column layouts handled
  separately: `from_text` (daily 6-col) and `from_historical_text` (FMV
  8-col with Repurchase/Sale).
- `tax_harvest/fmv_2018.py` — 31-Jan-2018 snapshot loader. Uses
  `from_historical_text`.
- `tax_harvest/report.py` — JSON + Markdown writers. Per-lot dumps strip
  `scheme.transactions` to keep the JSON small.
- `tax_harvest/main.py` — pipeline orchestrator + CLI argument surface.

For tax-rule semantics, always read `PROJECT_OVERVIEW.md` §"Tax-rule cheat
sheet" — that is the spec the codified rules implement.

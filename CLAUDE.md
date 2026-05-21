# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Authoritative references

- `README.md` — install / usage / CLI flag table / caveats.
- `PROJECT_OVERVIEW.md` — full engineering walkthrough: end-to-end data flow diagram,
  module responsibilities, codified tax rules (Sec 112A, Sec 50AA, lock-ins,
  grandfathering), design decisions, edge-case-to-test map. Read this before any
  non-trivial change.

Keep both files in sync with code changes — they're the project's documentation.

## Commands

```
python -m pip install -e .[dev]      # install w/ pytest
python -m pytest tax_harvest/tests   # full suite (~0.2s, 62 tests)
python -m pytest tax_harvest/tests/test_harvest.py::test_marginal_lot_truncated_to_exact_budget
tax-harvest path/to/cas.pdf          # entry point = tax_harvest.main:cli
```

There is no separate lint / typecheck step configured.

## Architecture invariants

The pipeline is a chain of pure stages, each consuming Pydantic models from the
previous one. Order matters:

```
parser.parse_cas  →  classifier (overrides + suspended list applied inside parser)
                  →  lots.build_lots (FIFO per (folio, isin or scheme_name))
                  →  lots.evaluate_lots (+ nav.load_nav_index, fmv_2018.load_fmv_index)
                  →  harvest.build_plan  +  loss_harvest.find_loss_candidates
                  →  report.render_plan / write_json_report
```

When adding a feature, identify which stage owns it and keep the stage boundaries
clean — do not reach across stages or duplicate logic.

### Things that look like they could move but should not

- **FIFO key is `(folio, isin or scheme_name)`** — same scheme across folios = separate
  cost-basis chains; regular vs direct plan ISINs = separate schemes. Do not collapse.
- **Sec 50AA bucketing is per-lot, not per-scheme** (`classifier.classify_lot_for_tax`
  called inside `lots.evaluate_lots`). A single debt scheme can straddle the 1-Apr-2023
  cutoff — keep the per-lot refinement.
- **Greedy harvest sorts by gain-per-unit descending** (not total gain). The marginal
  lot is fractionally truncated to **4 decimal places** to land on the ₹1.25L budget
  exactly — 4dp matches AMC transaction precision. Don't change either.
- **Excluded lots carry a human-readable `excluded_reason` string** (e.g. "ELSS 3-yr
  lock-in (unlocks 2028-11-01)"). New exclusion paths must populate this; never
  silent-filter.
- **Pydantic models in `models.py` are the cross-module contract.** New cross-stage
  fields go on the model, not in ad-hoc dicts / tuples.
- **Heuristic + explicit override pairing** for fuzzy signals (NRI, joint holdings,
  scheme category, suspended). When adding similar signals, follow the same pattern —
  ship the heuristic with an escape hatch.

### Caches & on-disk state

- `./cache/nav_cache.txt` — AMFI daily NAV, 24h TTL (`--no-cache` to bust).
- `./cache/fmv_jan_2018.txt` — 31-Jan-2018 snapshot, permanent
  (`--refresh-fmv` to bust). Historical NAVs don't change.
- `./reports/harvest_plan_<FY>_<timestamp>.json` — full structured output, cwd-relative, gitignored.
- `./reports/harvest_summary_<FY>_<timestamp>.md` — one-page human-readable summary written alongside.
- Both controlled by `--no-report` (skips both).
- `tax_harvest/data/{category_overrides,suspended_schemes}.json` — packaged data;
  user-supplied files via `--overrides` / `--suspended` merge on top.

## Scope

Personal single-user CLI. No web UI, no server, no DB, no auth, no automated
redemption, no tax-filing integration, no PII upload. Don't add any of these — they
were explicit non-goals.

**The ₹1.25 L Sec 112A exemption is shared with listed equity LTCG.** The tool
only reads CAS (mutual funds + bonds), not direct equity demat holdings. If the
user has also booked / will book stock LTCG this FY, they must pass that amount
via `--already-realized` so the MF plan shrinks correspondingly. The Markdown
summary surfaces this as a callout — keep it there.

Tax rules reflect law as of build time (post-Budget-2024). When updating a rule,
update both `classifier.py` / `lots.py` and the "Tax-rule cheat sheet" section of
`PROJECT_OVERVIEW.md`, and add/adjust a test under `tax_harvest/tests/`.

---
name: tax-rule-change
description: Walk through the 3-file update required when changing any Indian MF tax rule (Sec 112A, Sec 50AA, lock-ins, exit-load, grandfathering). Ensures the rule code, the codified cheat sheet, and the test suite stay in sync.
disable-model-invocation: true
---

# tax-rule-change

Use whenever a tax rule changes (Budget update, CBDT clarification, fixing a misread).
Skipping any step here causes silent drift between code and docs — the failure mode
is shipping a plan that quotes the wrong rate / cutoff / holding period.

## Required updates (do all three, in order)

### 1. Rule code

Locate the rule in one of:

- `tax_harvest/classifier.py` — scheme categorisation + per-lot Sec 50AA refinement
  (`classify_lot_for_tax`).
- `tax_harvest/lots.py` — holding-period thresholds, lock-in windows, exit-load
  default, grandfathering formula (`_apply_grandfathering`), LTCG eligibility.

Grep for the existing constant before editing — e.g. `grep -n "365" tax_harvest/lots.py`,
`grep -n "1,?25,?000\|125000\|1_25_000" tax_harvest/`, `grep -n "2023.*4.*1\|apr.*2023" tax_harvest/`.

Change the constant or branch in one place. Do not duplicate the value.

### 2. Cheat-sheet row in `PROJECT_OVERVIEW.md`

Open `PROJECT_OVERVIEW.md` and update the matching row under
**§ Tax-rule cheat sheet (codified)**. Sections to keep accurate:

- Section 112A — Equity LTCG (holding period, exemption, rate, grandfathering formula)
- Section 50AA — Specified Mutual Funds (acquisition cutoff date, treatment)
- Debt-oriented (pre-1-Apr-2023) — holding period, rate, indexation
- Lock-ins table — ELSS / solution-oriented / FMP / close-ended
- Exit-load — default window

If the change adds a new rule, add a new row + a new test case (step 3).

### 3. Test under `tax_harvest/tests/`

Add or update the test in the matching file:

| Rule area | Test file |
| --- | --- |
| Sec 112A holding / exemption / rate | `test_harvest.py` |
| Sec 112A grandfathering formula | `test_grandfathering.py` |
| Sec 50AA per-lot bucketing | `test_classifier.py`, `test_lots.py` |
| Lock-ins (ELSS / solution / FMP) | `test_lots.py` |
| Exit-load window | `test_overrides_and_extras.py` |
| Scheme classification regex | `test_classifier.py` |

Run the suite:

```
python -m pytest tax_harvest/tests
```

All 62+ tests must pass. If a test was asserting the **old** rule, update both the
expected value and a comment in the test referencing the rule source.

## Cross-check before committing

- `git diff` shows changes across **at least 2 of 3**: rule code, cheat sheet, test.
  If only one file changed, you missed a sync point — go back.
- Run `tax-rule-auditor` subagent for an independent read.

## Commit message convention

Lead with the statute / Budget reference so future-you can find it:

```
fix(112A): correct LTCG exemption to ₹1.25L (Budget 2024)
```

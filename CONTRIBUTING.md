# Contributing

Thanks for looking. Quick guide before opening an issue or PR.

## Scope

This is a **personal-use** open-source tool. PRs welcome for:

- Bug fixes (parsing, classification, arithmetic).
- Broker tax-P&L adapter additions (see `web/index.html` → `HEADER_MAP`).
- Tax-rule updates after a Budget / CBDT clarification (see strict
  process below — these touch real money).
- Web UI polish (accessibility, mobile layout, error copy).

PRs probably out of scope:

- Server-side processing, user accounts, multi-tenancy. The single-user
  local model is load-bearing for the no-SEBI-no-DPDP legal posture.
- Recommendations on direct equity / F&O / derivatives. The tool is
  read-only on stocks by design.
- Tax-filing automation / e-filing integration.

## Dev setup

```bash
python -m pip install -e .[dev]
python -m pytest tax_harvest/tests    # ~1s, 92+ cases
```

Python 3.11+. On Windows, set `PYTHONIOENCODING=utf-8` before running the
CLI so Rich can render `₹`.

For the web build:

```bash
cd web && python -m http.server 8000
# Then open http://localhost:8000/
```

End-to-end test (drives the local web build with a real CAS via
Playwright — set the env vars in `.env.example` first):

```bash
python scripts/e2e_web_test.py
```

## Tax-rule changes — read this before touching `classifier.py` or `lots.py`

Every codified tax rule is paired with a **cheat-sheet row in
`PROJECT_OVERVIEW.md`** AND a **test in `tax_harvest/tests/`**. Changing
the constant without updating the doc and the test silently drifts the
implementation from the spec. The rule is enforced by:

- `.claude/skills/tax-rule-change/SKILL.md` — checklist for Claude Code users.
- `.claude/agents/tax-rule-auditor.md` — read-only audit subagent.

If you're not using Claude Code, follow the same 3-file rule manually:
**code + cheat sheet + test**, in one PR.

## Sensitive data

**Never commit** real CAS PDFs, broker statements, passwords, PANs, or
client IDs. The `.gitignore` blocks `*.pdf`, `*.xlsx`, `*.xls`, `.env`,
`taxpnl*`, `*.secret` and the `cache/` + `reports/` directories. Use
env vars (`LTCGH_*` — see `.env.example`) for the e2e test fixture.

If you accidentally commit a secret: rotate it immediately, then
`git filter-repo --replace-text` to scrub history, force-push, and
file a GitHub Support ticket to expedite the cached-blob garbage
collection.

## Issue triage

When filing a bug:

- Mask any PAN / folio / client ID before pasting output.
- Include the version (`git rev-parse --short HEAD`).
- Note which path (browser / CLI / agent) and your OS.
- For browser bugs: open DevTools → Console, paste relevant errors.

## Commit style

Conventional Commits when reasonable (`fix:`, `feat:`, `docs:`, `chore:`,
`security:`). Subject ≤ 60 chars. Body explains the *why*, not the
*what* (the diff already shows what). Sign-off / coauthor not required.

## License

MIT. Contributions are accepted under the same license.

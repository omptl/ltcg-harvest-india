"""End-to-end test of the web UI using Playwright.

All sensitive inputs (CAS path, CAS password, broker tax-P&L) are read from
environment variables — never hard-coded. Set them in a local .env file
(gitignored) or export them in your shell before running.

Required env vars:
    LTCGH_CAS_PATH        absolute path to your CAS PDF
    LTCGH_CAS_PASSWORD    CAS PDF password (typically PAN uppercase, or PAN+DOB)

Optional:
    LTCGH_STOCKS_LEDGER   absolute path to a broker tax-P&L CSV or xlsx
    LTCGH_WEB_URL         override the URL under test (default localhost:8000)
    LTCGH_SHOT_PATH       where to save the verification screenshot

Run:
    python -m http.server 8000 -d web/    # in another shell
    .venv/Scripts/python.exe scripts/e2e_web_test.py
"""

import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

CAS_PATH = os.environ.get("LTCGH_CAS_PATH")
CAS_PASSWORD = os.environ.get("LTCGH_CAS_PASSWORD")
STOCKS_LEDGER = os.environ.get("LTCGH_STOCKS_LEDGER")  # optional
URL = os.environ.get("LTCGH_WEB_URL", "http://localhost:8000/index.html")
SHOT = os.environ.get("LTCGH_SHOT_PATH", "C:/tmp/web_e2e.png")


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    print("\nSet the required env vars first (see docstring at top of this file).",
          file=sys.stderr)
    return 2


async def main() -> int:
    if not CAS_PATH or not CAS_PASSWORD:
        return _fail("LTCGH_CAS_PATH and LTCGH_CAS_PASSWORD must be set.")
    if not Path(CAS_PATH).exists():
        return _fail(f"CAS file not found at {CAS_PATH}")
    if STOCKS_LEDGER and not Path(STOCKS_LEDGER).exists():
        return _fail(f"LTCGH_STOCKS_LEDGER points at a missing file: {STOCKS_LEDGER}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 1600})
        page = await ctx.new_page()

        page.on("console", lambda msg: print(f"[console:{msg.type}] {msg.text}"))
        page.on("pageerror", lambda exc: print(f"[pageerror] {exc}"))

        print("-> Navigating...")
        await page.goto(URL, wait_until="domcontentloaded")

        print("-> Waiting for engine ready (up to 180s)...")
        await page.wait_for_selector("#enginestatus:has-text('Engine ready')", timeout=180_000)
        print("OK: Engine ready")

        print("-> Filling form...")
        await page.set_input_files("#cas", CAS_PATH)
        await page.fill("#pwd", CAS_PASSWORD)
        if STOCKS_LEDGER:
            await page.set_input_files("#ledger", STOCKS_LEDGER)
        await page.fill("#buffer", "1.5")
        print("OK: Form filled")

        print("-> Clicking Compute...")
        await page.click("#compute")

        print("-> Waiting for report (up to 120s)...")
        await page.wait_for_selector("#report:not([style*='display:none'])", timeout=120_000)
        await page.wait_for_selector("#status.ok", timeout=120_000)
        print("OK: Report rendered")

        report_text = await page.inner_text("#report")
        status_text = await page.inner_text("#status")

        print(f"\n-> Status panel: {status_text!r}")
        print(f"\n-> Report length: {len(report_text)} chars")
        print(f"\n=== FIRST 60 LINES OF REPORT ===")
        for line in report_text.split("\n")[:60]:
            print(line)

        await page.screenshot(path=SHOT, full_page=True)
        print(f"\nOK: Screenshot saved to {SHOT}")

        # Lightweight sanity (no hard-coded portfolio numbers — those are
        # personal to the test fixture and would themselves leak intent).
        # The structural assertions catch UI regressions without committing
        # what any user's plan should look like.
        structural = [
            "FY ",                       # title format
            "Effective budget",          # budget block rendered
            "What to sell",              # action table heading
            "Spot-check before",         # checklist heading
            "Safety buffer",             # buffer row present
        ]
        missing = [s for s in structural if s not in report_text]
        if missing:
            print(f"\nFAIL: Missing expected substrings: {missing}")
            await browser.close()
            return 1
        print("\nOK: All structural assertions passed")

        await browser.close()
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

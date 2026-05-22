"""End-to-end test of the web UI using Playwright.

Drives the local web/index.html with a real CAS PDF + Zerodha tax-P&L,
verifies the rendered plan matches the CLI output (₹1,31,046 ± buffer).
"""

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

CAS_PATH = r"C:/Users/ompatel.j/Downloads/CAS_01012011-22052026_***REDACTED***_22052026125947128.pdf"
CAS_PASSWORD = "***REDACTED-PASSWORD***"
STOCKS_CSV = r"C:/Projects/prod/MFHarvest/cache/stocks_ledger_fy2627.csv"
URL = "http://localhost:8000/index.html"
SHOT = r"C:/tmp/web_e2e.png"


async def main() -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 1600})
        page = await ctx.new_page()

        # Capture console for debug
        page.on("console", lambda msg: print(f"[console:{msg.type}] {msg.text}"))
        page.on("pageerror", lambda exc: print(f"[pageerror] {exc}"))

        print("→ Navigating…")
        await page.goto(URL, wait_until="domcontentloaded")

        print("→ Waiting for engine ready (up to 180s)…")
        await page.wait_for_selector("#enginestatus:has-text('Engine ready')", timeout=180_000)
        print("✓ Engine ready")

        print("→ Filling form…")
        await page.set_input_files("#cas", CAS_PATH)
        await page.fill("#pwd", CAS_PASSWORD)
        await page.set_input_files("#ledger", STOCKS_CSV)
        await page.fill("#buffer", "1.5")
        print("✓ Form filled")

        print("→ Clicking Compute…")
        await page.click("#compute")

        print("→ Waiting for report (up to 120s)…")
        await page.wait_for_selector("#report:not([style*='display:none'])", timeout=120_000)
        await page.wait_for_selector("#status.ok", timeout=120_000)
        print("✓ Report rendered")

        # Grab the report markdown body as text
        report_text = await page.inner_text("#report")
        status_text = await page.inner_text("#status")

        print(f"\n→ Status panel: {status_text!r}")
        print(f"\n→ Report length: {len(report_text)} chars")
        print(f"\n=== FIRST 60 LINES OF REPORT ===")
        for line in report_text.split("\n")[:60]:
            print(line)

        # Save screenshot
        await page.screenshot(path=SHOT, full_page=True)
        print(f"\n✓ Screenshot saved: {SHOT}")

        # Sanity-check the expected numbers (CLI output with same inputs +
        # 1.5% safety buffer: Nippon 58.3870 + HDFC 664.9045 = ₹1,29,080.75).
        expected_substrings = [
            "FY 2026-27",
            "129,080.75",      # post-buffer total LTCG booked
            "58.3870",         # Nippon Mid Cap units to redeem
            "664.9045",        # HDFC Mid Cap units to redeem
            "Stocks LTCG",
            "Safety buffer",
            "GREEN",           # weekday morning → green window
        ]
        misses = [s for s in expected_substrings if s not in report_text]
        if misses:
            print(f"\n✗ Missing expected substrings: {misses}")
            await browser.close()
            return 1
        print("\n✓ All expected substrings present")

        await browser.close()
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

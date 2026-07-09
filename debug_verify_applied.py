"""Debug script: Verify if jobs were actually applied on LinkedIn by checking application status."""

import asyncio
import json
import os

from playwright.async_api import async_playwright

# The 3 jobs that were reported as "Applied"
JOBS_TO_VERIFY = [
    {
        "title": "Cloud Engineer @ NIKSUN",
        "url": "https://www.linkedin.com/jobs/view/4436839981/",
    },
    {
        "title": "Azure DevOps Engineer @ InovarTech",
        "url": "https://www.linkedin.com/jobs/view/4437025386/",
    },
    {
        "title": "Platform Engineer @ Crossing Hurdles (from earlier run)",
        "url": "https://www.linkedin.com/jobs/view/4377671299/",
    },
]

RESULTS_FILE = os.path.join(os.path.dirname(__file__), "debug_verify_applied_results.json")


async def check_job_applied(page, job: dict) -> dict:
    """Navigate to a job URL and check if we already applied."""
    result = {
        "title": job["title"],
        "url": job["url"],
        "applied": False,
        "easy_apply_button_text": "",
        "applied_indicators": [],
        "page_signals": [],
    }

    try:
        await page.goto(job["url"], timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(4)

        # Check 1: Easy Apply button text — if it says "Applied" or is disabled, we applied
        try:
            easy_apply_btns = page.locator("button.jobs-apply-button")
            count = await easy_apply_btns.count()
            for i in range(count):
                btn = easy_apply_btns.nth(i)
                if await btn.is_visible(timeout=1000):
                    text = (await btn.inner_text()).strip()
                    result["easy_apply_button_text"] = text
                    if "applied" in text.lower():
                        result["applied"] = True
                        result["applied_indicators"].append(f"Easy Apply button says: '{text}'")
        except Exception as e:
            result["page_signals"].append(f"Easy Apply button check error: {e}")

        # Check 2: Look for "Applied" badge/indicator anywhere on the page
        try:
            applied_indicators = [
                "span:has-text('Applied')",
                "div:has-text('Applied')",
                "li-icon[type='applied']",
                ".jobs-unified-top-card__applied-date",
                "[class*='applied']",
            ]
            for sel in applied_indicators:
                try:
                    loc = page.locator(sel).first
                    if await loc.is_visible(timeout=500):
                        text = (await loc.inner_text()).strip()[:100]
                        result["applied"] = True
                        result["applied_indicators"].append(f"Found '{sel}': {text}")
                except Exception:
                    pass
        except Exception:
            pass

        # Check 3: Check page text for application date
        try:
            page_text = await page.evaluate("""() => {
                const body = document.body?.innerText || '';
                const lines = body.split('\\n').filter(l => l.trim());
                const applied_lines = lines.filter(l => 
                    l.toLowerCase().includes('applied') || 
                    l.toLowerCase().includes('application submitted') ||
                    l.toLowerCase().includes('your application')
                );
                return applied_lines.slice(0, 5).join(' | ');
            }""")
            if page_text:
                result["page_signals"].append(f"Applied-related text: {page_text[:200]}")
                if "applied" in page_text.lower():
                    result["applied"] = True
        except Exception:
            pass

        # Check 4: Screenshot the button area for visual confirmation
        try:
            btn_text = await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const applyBtns = btns.filter(b => {
                    const t = b.textContent?.toLowerCase() || '';
                    return t.includes('apply') || t.includes('applied');
                });
                return applyBtns.map(b => ({
                    text: b.textContent?.trim()?.substring(0, 100),
                    disabled: b.disabled,
                    className: b.className?.substring(0, 100),
                }));
            }""")
            result["page_signals"].append(f"Apply buttons found: {json.dumps(btn_text)}")
        except Exception:
            pass

    except Exception as e:
        result["page_signals"].append(f"Navigation error: {e}")

    return result


async def main():
    print(f"\n{'='*70}")
    print(f"  VERIFY: Did LinkedIn jobs actually get applied?")
    print(f"{'='*70}\n")

    pw = await async_playwright().start()
    user_data_dir = os.path.join(os.path.dirname(__file__), "browser_data_linkedin")

    context = await pw.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=False,
        viewport={"width": 1280, "height": 800},
        args=["--disable-blink-features=AutomationControlled"],
    )

    page = context.pages[0] if context.pages else await context.new_page()
    results = []

    for i, job in enumerate(JOBS_TO_VERIFY, 1):
        print(f"\n[{i}/{len(JOBS_TO_VERIFY)}] Checking: {job['title']}")
        print(f"  URL: {job['url']}")

        result = await check_job_applied(page, job)
        results.append(result)

        status = "APPLIED" if result["applied"] else "NOT APPLIED"
        print(f"  Status: {status}")
        if result["easy_apply_button_text"]:
            print(f"  Easy Apply button: '{result['easy_apply_button_text']}'")
        for indicator in result["applied_indicators"]:
            print(f"  Indicator: {indicator}")
        for signal in result["page_signals"]:
            print(f"  Signal: {signal}")

    # Summary
    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    applied_count = sum(1 for r in results if r["applied"])
    print(f"  Total checked: {len(results)}")
    print(f"  Actually applied: {applied_count}")
    print(f"  Not applied: {len(results) - applied_count}")
    for r in results:
        status = "APPLIED" if r["applied"] else "NOT APPLIED"
        print(f"    [{status}] {r['title']}")

    # Save results
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to: {RESULTS_FILE}")

    await context.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())

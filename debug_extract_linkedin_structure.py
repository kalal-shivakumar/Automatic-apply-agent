import argparse
import asyncio
import json
import os
from datetime import datetime, timezone

from playwright.async_api import async_playwright

BASE_DIR = os.path.dirname(__file__)
LINKEDIN_BROWSER_DATA_DIR = os.path.join(BASE_DIR, "browser_data_linkedin")
DEFAULT_URL = "https://www.linkedin.com/jobs/search/?keywords=DevOps%20Engineer&location=Hyderabad"
OUTPUT_PATH = os.path.join(BASE_DIR, "debug_extract_linkedin_structure_results.json")


async def extract_linkedin_structure(url: str):
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=LINKEDIN_BROWSER_DATA_DIR,
            headless=False,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)
        except Exception:
            # Retry once with a lighter navigation path.
            await page.goto("https://www.linkedin.com/", wait_until="domcontentloaded", timeout=90000)
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2.5)

        for y in [500, 1200, 2000, 2800]:
            await page.evaluate(f"window.scrollTo(0, {y})")
            await asyncio.sleep(0.6)

        payload = await page.evaluate(
            r"""() => {
                const count = (sel) => document.querySelectorAll(sel).length;
                const toText = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim();
                const countButtonsByText = (needle) => {
                    const lowNeedle = String(needle || '').toLowerCase();
                    const all = Array.from(document.querySelectorAll('button'));
                    return all.filter((btn) => toText(btn).toLowerCase().includes(lowNeedle)).length;
                };

                const jobCards = Array.from(document.querySelectorAll(
                    'li:has(a[href*="/jobs/view/"]), .jobs-search-results__list-item, .job-search-card'
                )).slice(0, 20).map((card, idx) => {
                    const link = card.querySelector('a[href*="/jobs/view/"]');
                    const title = card.querySelector('.job-card-list__title, a[href*="/jobs/view/"]');
                    const company = card.querySelector('.job-card-container__company-name, .artdeco-entity-lockup__subtitle, h4 a');
                    const location = card.querySelector('.job-card-container__metadata-item, .job-search-card__location');
                    return {
                        index: idx,
                        title: toText(title),
                        company: toText(company),
                        location: toText(location),
                        href: link ? link.href : '',
                        className: card.className || '',
                    };
                });

                const buttons = Array.from(document.querySelectorAll('button')).slice(0, 80)
                    .map((b) => ({
                        text: toText(b).slice(0, 140),
                        ariaLabel: b.getAttribute('aria-label') || '',
                        className: b.className || '',
                        disabled: !!b.disabled,
                    }))
                    .filter((b) => b.text || b.ariaLabel);

                const forms = Array.from(document.querySelectorAll('form')).slice(0, 20).map((form, idx) => ({
                    index: idx,
                    className: form.className || '',
                    textPreview: toText(form).slice(0, 220),
                    inputCount: form.querySelectorAll('input').length,
                    selectCount: form.querySelectorAll('select').length,
                    textareaCount: form.querySelectorAll('textarea').length,
                    radioCount: form.querySelectorAll('input[type="radio"]').length,
                }));

                return {
                    url: location.href,
                    title: document.title,
                    selector_counts: {
                        job_cards: count('li:has(a[href*="/jobs/view/"]), .jobs-search-results__list-item, .job-search-card'),
                        easy_apply_buttons: countButtonsByText('easy apply'),
                        apply_buttons: countButtonsByText('apply'),
                        forms: count('form'),
                        text_inputs: count('input[type="text"]'),
                        select_inputs: count('select'),
                        textareas: count('textarea'),
                        radio_inputs: count('input[type="radio"]'),
                    },
                    job_cards: jobCards,
                    buttons: buttons,
                    forms: forms,
                };
            }"""
        )

        data = payload or {}
        selector_counts = data.get("selector_counts") or {}
        page_url = str(data.get("url") or "")
        title = str(data.get("title") or "")
        authwall_detected = "authwall" in page_url.lower() or "sign up" in title.lower()

        button_texts = [
            ((b.get("text") or "") + " " + (b.get("ariaLabel") or "")).strip().lower()
            for b in (data.get("buttons") or [])
        ]

        has_search_results = int(selector_counts.get("job_cards", 0) or 0) > 0
        has_forms = int(selector_counts.get("forms", 0) or 0) > 0
        has_inputs = (
            int(selector_counts.get("text_inputs", 0) or 0) > 0
            or int(selector_counts.get("select_inputs", 0) or 0) > 0
            or int(selector_counts.get("textareas", 0) or 0) > 0
            or int(selector_counts.get("radio_inputs", 0) or 0) > 0
        )
        has_easy_apply = int(selector_counts.get("easy_apply_buttons", 0) or 0) > 0
        has_submit_or_next = any(
            any(tok in text for tok in ["submit application", "review", "next", "continue"])
            for text in button_texts
        )

        automation_readiness = {
            "linkedin_login": {
                "resolved": not authwall_detected,
                "details": "LinkedIn login looks valid" if not authwall_detected else "Authwall detected. Login is required before automation.",
            },
            "job_search": {
                "resolved": has_search_results and not authwall_detected,
                "details": f"Detected {selector_counts.get('job_cards', 0)} job cards",
            },
            "fields_detection": {
                "resolved": has_forms and has_inputs and not authwall_detected,
                "details": (
                    f"forms={selector_counts.get('forms', 0)}, text_inputs={selector_counts.get('text_inputs', 0)}, "
                    f"selects={selector_counts.get('select_inputs', 0)}, textareas={selector_counts.get('textareas', 0)}, "
                    f"radios={selector_counts.get('radio_inputs', 0)}"
                ),
            },
            "field_answering_strategy": {
                "resolved": has_inputs and not authwall_detected,
                "details": "AI can map question text/labels to profile answers for text/select/radio fields.",
            },
            "job_submission": {
                "resolved": (has_easy_apply or has_submit_or_next) and not authwall_detected,
                "details": (
                    "Easy Apply / submit controls detected"
                    if (has_easy_apply or has_submit_or_next)
                    else "Submit controls not detected in current page snapshot"
                ),
            },
        }

        result = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "seed_url": url,
            "data": data,
            "automation_readiness": automation_readiness,
            "notes": [
                "If selector counts are 0, login may be required or LinkedIn served anti-bot interstitial.",
                "Re-run after manual login in the same browser profile directory.",
            ],
        }

        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"Saved LinkedIn structure debug to: {OUTPUT_PATH}")
        print("You can keep the opened browser for manual selector inspection, then close it.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract LinkedIn jobs page structure for selector debugging")
    parser.add_argument("--url", default=DEFAULT_URL, help="LinkedIn jobs page URL")
    args = parser.parse_args()
    asyncio.run(extract_linkedin_structure(args.url))

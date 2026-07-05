"""
One-job deep investigation: open a LinkedIn job page, dump all button details,
click Apply, and dump whatever appears (modal fields, redirects, etc.)
"""
import asyncio
import json
import os
from playwright.async_api import async_playwright

def _clean(v):
    return " ".join(str(v or "").split()).strip()


BASE_DIR = os.path.dirname(__file__)
LINKEDIN_BROWSER_DATA_DIR = os.path.join(BASE_DIR, "browser_data_linkedin")
OUTPUT_PATH = os.path.join(BASE_DIR, "debug_investigate_job_result.json")


async def investigate(user_data_dir: str):
    async with async_playwright() as p:
        context = await asyncio.wait_for(
            p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                viewport={"width": 1400, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            ),
            timeout=60,
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # Step 1: Open search and grab first few job URLs
        search_url = "https://www.linkedin.com/jobs/search/?keywords=DevOps+Engineer&location=Hyderabad&f_LF=f_AL"
        print(f"[invest] loading search with Easy Apply filter: {search_url}")
        await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(2.5)

        current_url = page.url
        print(f"[invest] current URL: {current_url}")

        # Check login
        is_logged_in = await page.locator(
            'a[href*="/feed"], a[href*="/mynetwork"], button[aria-label*="Me"], img.global-nav__me-photo'
        ).first.is_visible(timeout=2000)
        print(f"[invest] logged in: {is_logged_in}")

        if not is_logged_in:
            print("[invest] NOT logged in - please log in manually, then press Enter in terminal...")
            input()

        # Scroll to load jobs
        for y in [400, 900, 1500]:
            await page.evaluate(f"window.scrollTo(0, {y})")
            await asyncio.sleep(0.5)

        # Grab job cards from search
        job_cards = await page.evaluate("""
            () => {
                const cards = document.querySelectorAll('li a[href*="/jobs/view/"]');
                const seen = new Set();
                const out = [];
                cards.forEach(a => {
                    const url = a.href.split('?')[0];
                    if (!url || seen.has(url)) return;
                    seen.add(url);
                    out.push({ url: a.href, title: (a.textContent || '').replace(/\\s+/g,' ').trim().slice(0,80) });
                });
                return out.slice(0, 5);
            }
        """)
        print(f"[invest] found {len(job_cards)} job cards in search results")
        for i, j in enumerate(job_cards):
            print(f"  [{i}] {j['title']} => {j['url'][:80]}")

        if not job_cards:
            print("[invest] No job cards found. Saving current page HTML for diagnosis.")
            html = await page.content()
            with open("debug_investigate_page.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("[invest] saved debug_investigate_page.html")
            await context.close()
            return

        report = {"search_url": search_url, "logged_in": is_logged_in, "job_cards_found": len(job_cards), "jobs_investigated": []}

        # Step 2: Click each job CARD in the search panel (not navigate to URL)
        # LinkedIn's new UI only shows Easy Apply button in the search split-pane detail view
        job_list_items = page.locator('li:has(a[href*="/jobs/view/"])')
        li_count = await job_list_items.count()
        print(f"[invest] found {li_count} list items with job links")

        for idx in range(min(li_count, 3)):
            li = job_list_items.nth(idx)
            job_link = li.locator('a[href*="/jobs/view/"]').first
            job_url = await job_link.get_attribute("href") or ""
            job_title = _clean(await job_link.inner_text())
            print(f"\n[invest] === clicking card [{idx}]: {job_title[:60]} ===")

            # Click the card to load detail in right panel
            try:
                await li.click()
            except Exception:
                try:
                    await job_link.click()
                except Exception:
                    pass

            # Wait for right panel to load (watch for job-detail container or apply button)
            await asyncio.sleep(1.0)
            try:
                await page.wait_for_selector(
                    '.jobs-search__job-details, .jobs-details__main-content, .job-view-layout, .jobs-unified-top-card',
                    timeout=8000
                )
            except Exception:
                pass
            await asyncio.sleep(1.5)

            # Query buttons ONLY inside the job detail right panel
            btns = await page.evaluate("""
                () => {
                    const containers = [
                        '.jobs-search__job-details--container',
                        '.jobs-details__main-content',
                        '.job-view-layout',
                        '.jobs-unified-top-card',
                        '.jobs-s-apply',
                        'main',
                    ];
                    let container = null;
                    for (const sel of containers) {
                        const el = document.querySelector(sel);
                        if (el) { container = el; break; }
                    }
                    const scope = container || document;
                    return Array.from(scope.querySelectorAll('button')).map(b => ({
                        text: b.textContent.replace(/\\s+/g,' ').trim(),
                        aria: b.getAttribute('aria-label') || '',
                        cls: b.className || '',
                        visible: b.offsetParent !== null,
                        disabled: b.disabled,
                    })).filter(b => b.text);
                }
            """)
            print(f"[invest] detail-panel buttons ({len(btns)}):")
            for b in btns:
                v = "VIS" if b["visible"] else "hid"
                d = "DIS" if b["disabled"] else "ena"
                print(f"  [{v}][{d}] '{b['text'][:40]}' | aria='{b['aria'][:40]}'")

            # Look for any Apply-like button IN the detail panel only (exclude filter pill buttons)
            apply_btn_info = await page.evaluate("""
                () => {
                    const containers = [
                        '.jobs-search__job-details--container',
                        '.jobs-details__main-content',
                        '.job-view-layout',
                        '.jobs-unified-top-card',
                        '.jobs-s-apply',
                        'main',
                    ];
                    let container = null;
                    for (const sel of containers) {
                        const el = document.querySelector(sel);
                        if (el) { container = el; break; }
                    }
                    const scope = container || document;
                    const btns = Array.from(scope.querySelectorAll('button'));
                    for (const b of btns) {
                        const t = (b.textContent || '').replace(/\\s+/g,' ').trim().toLowerCase();
                        const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                        const cls = b.className || '';
                        // Exclude search filter pills
                        if (cls.includes('search-reusables__filter-pill-button')) continue;
                        if (cls.includes('artdeco-pill--choice')) continue;
                        if (t.includes('easy apply') || (t === 'apply') || aria.includes('easy apply')) {
                            return {
                                text: b.textContent.replace(/\\s+/g,' ').trim(),
                                aria: b.getAttribute('aria-label') || '',
                                cls: cls,
                                disabled: b.disabled,
                                visible: b.offsetParent !== null,
                            };
                        }
                    }
                    return null;
                }
            """)
            print(f"[invest] apply-like button: {apply_btn_info}")

            job_entry = {
                "title": job_title,
                "url": job_url,
                "all_buttons": btns,
                "apply_btn": apply_btn_info,
                "modal_opened": False,
                "modal_fields": [],
                "modal_buttons": [],
            }

            # Step 3: Click Apply if visible and enabled
            if apply_btn_info and apply_btn_info.get("visible") and not apply_btn_info.get("disabled"):
                print("[invest] clicking Easy Apply button in detail panel...")
                try:
                    # Click by aria-label or text, scoped to avoid filter buttons
                    aria_txt = apply_btn_info.get("aria", "")
                    btn_txt = apply_btn_info.get("text", "")
                    if aria_txt:
                        apply_locator = page.locator(f"button[aria-label='{aria_txt}']").first
                    else:
                        apply_locator = page.locator("button").filter(has_text=btn_txt).nth(1)  # skip filter pill
                    await apply_locator.click(timeout=5000)
                    await asyncio.sleep(2.0)

                    after_url = page.url
                    print(f"[invest] URL after click: {after_url}")
                    job_entry["url_after_apply_click"] = after_url

                    # Check if modal opened
                    modal_visible = await page.locator('[role="dialog"], .jobs-easy-apply-modal').first.is_visible(timeout=2000)
                    print(f"[invest] modal visible: {modal_visible}")
                    job_entry["modal_opened"] = modal_visible

                    if modal_visible:
                        # Dump modal fields
                        fields = await page.evaluate("""
                            () => {
                                const modal = document.querySelector('[role="dialog"], .jobs-easy-apply-modal') || document.body;
                                return {
                                    text: modal.innerText.replace(/\\s+/g,' ').trim().slice(0,400),
                                    inputs: Array.from(modal.querySelectorAll('input,select,textarea')).map(el => ({
                                        type: el.tagName + '[' + (el.type||'') + ']',
                                        label: el.getAttribute('aria-label') || el.getAttribute('name') || el.placeholder || '',
                                    })),
                                    btns: Array.from(modal.querySelectorAll('button')).map(b => b.textContent.replace(/\\s+/g,' ').trim()).filter(Boolean),
                                };
                            }
                        """)
                        print(f"[invest] modal text snippet: {fields['text'][:200]}")
                        print(f"[invest] modal inputs: {fields['inputs'][:10]}")
                        print(f"[invest] modal buttons: {fields['btns'][:10]}")
                        job_entry["modal_fields"] = fields["inputs"]
                        job_entry["modal_buttons"] = fields["btns"]
                    else:
                        print("[invest] no modal - likely external apply redirect")
                except Exception as e:
                    print(f"[invest] click error: {e}")
                    job_entry["click_error"] = str(e)

                # Close modal if open
                for sel in ["button[aria-label='Dismiss']", "button:has-text('Discard')", "button:has-text('Cancel')"]:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible(timeout=500):
                            await btn.click()
                            await asyncio.sleep(0.4)
                            break
                    except Exception:
                        pass
            else:
                print("[invest] no clickable apply button found on this job page")

            report["jobs_investigated"].append(job_entry)

        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n[invest] report saved: {OUTPUT_PATH}")

        await context.close()


if __name__ == "__main__":
    asyncio.run(investigate(LINKEDIN_BROWSER_DATA_DIR))

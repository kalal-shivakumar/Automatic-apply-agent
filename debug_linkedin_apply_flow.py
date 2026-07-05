import argparse
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote_plus

from playwright.async_api import async_playwright

from ai_answerer import QuestionAnswerer
from config import Config

BASE_DIR = os.path.dirname(__file__)
LINKEDIN_BROWSER_DATA_DIR = os.path.join(BASE_DIR, "browser_data_linkedin")
OUTPUT_PATH = os.path.join(BASE_DIR, "debug_linkedin_apply_flow_results.json")
STORAGE_STATE_PATH = os.path.join(BASE_DIR, "linkedin_storage_state.json")
SCREENSHOT_DIR = os.path.join(BASE_DIR, "debug_screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def _clean(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _extract_number_tokens(text: str) -> list[float]:
    vals = []
    for token in re.findall(r"\d+(?:\.\d+)?", (text or "").replace(",", "")):
        try:
            vals.append(float(token))
        except Exception:
            continue
    return vals


def _parse_salary_range_lpa(salary_text: str) -> tuple[float | None, float | None]:
    txt = (salary_text or "").strip().lower()
    if not txt:
        return (None, None)
    nums = _extract_number_tokens(txt)
    if not nums:
        return (None, None)
    if any(n > 100 for n in nums):
        nums = [round(n / 100000.0, 2) for n in nums]
    if len(nums) == 1:
        return (nums[0], nums[0])
    return (min(nums), max(nums))


async def _collect_jobs_from_search(page):
    jobs = await page.evaluate(
        """() => {
            const items = [];
            const cards = document.querySelectorAll('li:has(a[href*="/jobs/view/"]), .jobs-search-results__list-item, .job-search-card');
            cards.forEach((card) => {
                const link = card.querySelector('a[href*="/jobs/view/"]');
                const title = card.querySelector('.job-card-list__title, a[href*="/jobs/view/"]');
                const company = card.querySelector('.job-card-container__company-name, .artdeco-entity-lockup__subtitle, h4 a');
                const location = card.querySelector('.job-card-container__metadata-item, .job-search-card__location');
                if (!link || !link.href) return;
                items.push({
                    url: link.href,
                    title: (title?.textContent || '').trim(),
                    company: (company?.textContent || '').trim(),
                    location: (location?.textContent || '').trim(),
                });
            });
            return items;
        }"""
    )
    return jobs or []


async def _extract_job_context(page):
    full_jd = await page.evaluate(
        r"""() => {
            const sels = [
                '.jobs-description-content__text',
                '.jobs-box__html-content',
                '.jobs-description',
                '[class*="jobs-description"]'
            ];
            let best = '';
            for (const s of sels) {
                const el = document.querySelector(s);
                const t = (el?.innerText || '').trim();
                if (t.length > best.length) best = t;
            }
            if (!best) {
                const blocks = Array.from(document.querySelectorAll('section, article, div'));
                for (const b of blocks) {
                    const t = (b.innerText || '').trim();
                    const lc = t.toLowerCase();
                    if (t.length < 250 || t.length > 25000) continue;
                    if (!lc.includes('responsibilities') && !lc.includes('requirements') && !lc.includes('job description')) continue;
                    if (t.length > best.length) best = t;
                }
            }

            const allText = (document.body?.innerText || '').replace(/\s+/g, ' ');
            const salaryMatch = allText.match(/(₹|INR)\s?[\d,.]+\s?(LPA|Lakhs?|per year|\/yr|\/year)?\s?(to|-)?\s?(₹|INR)?\s?[\d,.]*/i);
            const expMatch = allText.match(/\b\d+\s*(?:-|to)?\s*\d*\s*(?:years?|yrs?)\b/i);

            return {
                jd: best || '',
                salary: salaryMatch ? salaryMatch[0] : '',
                experience: expMatch ? expMatch[0] : '',
                structure: {
                    forms: document.querySelectorAll('form').length,
                    text_inputs: document.querySelectorAll('input[type="text"], input[type="number"], input[type="email"]').length,
                    textareas: document.querySelectorAll('textarea').length,
                    selects: document.querySelectorAll('select').length,
                    radios: document.querySelectorAll('input[type="radio"]').length,
                    buttons: document.querySelectorAll('button').length,
                }
            };
        }"""
    )
    return full_jd or {"jd": "", "salary": "", "experience": "", "structure": {}}


async def _extract_modal_fields(page):
    return await page.evaluate(
        r"""() => {
            const modal = document.querySelector('[role="dialog"], .jobs-easy-apply-modal') || document;
            const out = [];

            const add = (kind, question, options=[]) => {
                const q = (question || '').replace(/\s+/g, ' ').trim();
                if (!q) return;
                out.push({kind, question: q, options});
            };

            modal.querySelectorAll('input[type="text"], input[type="number"], input[type="email"]').forEach((el) => {
                add('text', el.getAttribute('aria-label') || el.getAttribute('name') || el.id || el.placeholder || 'Text field', []);
            });

            modal.querySelectorAll('textarea').forEach((el) => {
                add('textarea', el.getAttribute('aria-label') || el.getAttribute('name') || el.id || el.placeholder || 'Textarea field', []);
            });

            modal.querySelectorAll('select').forEach((el) => {
                const opts = Array.from(el.querySelectorAll('option')).map(o => (o.textContent || '').trim()).filter(Boolean);
                add('select', el.getAttribute('aria-label') || el.getAttribute('name') || el.id || 'Dropdown field', opts);
            });

            modal.querySelectorAll('fieldset').forEach((fs) => {
                const legend = (fs.querySelector('legend')?.textContent || '').trim();
                const opts = Array.from(fs.querySelectorAll('label')).map(l => (l.textContent || '').trim()).filter(Boolean);
                if (legend || opts.length) add('radio', legend || 'Radio field', opts);
            });

            const btns = Array.from(modal.querySelectorAll('button'))
                .map((b) => (b.textContent || '').replace(/\s+/g, ' ').trim())
                .filter(Boolean)
                .slice(0, 80);

            return { fields: out, buttons: btns };
        }"""
    )


async def _dismiss_post_apply_popup(page):
    """Dismiss all post-apply popups: Open to Work, resume-to-profile, etc."""
    dismiss_selectors = [
        "button:has-text('No thanks')",
        "button:has-text('Not now')",
        "button:has-text('Dismiss')",
        "button[aria-label='Dismiss']",
        "button:has-text('Skip')",
        "button:has-text('Close')",
    ]
    # Try up to 3 rounds (stacked popups)
    for _ in range(3):
        dismissed = False
        for selector in dismiss_selectors:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=700):
                    await btn.click()
                    await asyncio.sleep(0.6)
                    dismissed = True
                    break
            except Exception:
                continue
        if not dismissed:
            break


async def _fill_easy_apply_fields(page, ai, job_result):
    answers = []
    _step = [0]

    async def _safe_ai_answer(question: str, options=None, default: str = "") -> str:
        try:
            # Guard against occasional long/hung model responses.
            ans = await asyncio.wait_for(
                asyncio.to_thread(ai.answer_question, question, options),
                timeout=10.0,
            )
            return _clean(ans)
        except Exception:
            return default

    # Find ALL inputs and textareas with explicit timeout handling
    try:
        # Use explicit timeout in locator operation
        text_fields = page.locator("[role='dialog'] input, [role='dialog'] textarea")
        # Try to count fields with a short timeout
        try:
            text_count = await asyncio.wait_for(
                asyncio.create_task(text_fields.count()),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            print(f"[debug] _fill_easy_apply_fields: timeout on field count, page may be transitioning")
            return answers
    except Exception as e:
        print(f"[debug] _fill_easy_apply_fields: error in field detection: {str(e)[:60]}")
        return answers
    
    if text_count == 0:
        print(f"[debug] _fill_easy_apply_fields: no fields found on this page")
        return answers
        
    print(f"[debug] _fill_easy_apply_fields: found {text_count} total input/textarea fields")
    for i in range(min(text_count, 30)):
        field = text_fields.nth(i)
        try:
            if not await field.is_visible(timeout=200):
                continue
            current = ""
            try:
                current = (await field.input_value()).strip()
            except Exception:
                pass
            field_type = await field.get_attribute("type") or "text"
            field_id = await field.get_attribute("id") or ""
            field_name = await field.get_attribute("name") or ""
            field_placeholder = await field.get_attribute("placeholder") or ""
            field_aria = await field.get_attribute("aria-label") or ""
            
            # Build question label from all available attributes
            q = field_aria or field_name or field_placeholder or field_id or "Field"
            # Also check for associated <label> element
            if field_id:
                try:
                    q = _clean(await page.locator(f"label[for='{field_id}']").first.inner_text())
                except Exception:
                    pass
            q = _clean(q)
            
            q_lower = q.lower()
            # Determine if field should be numeric at all
            should_be_numeric = field_type == "number" or any(
                k in q_lower
                for k in [
                    "exp",
                    "ctc",
                    "salary",
                    "years",
                    "cost",
                    "kubernetes",
                    "docker",
                    "aws",
                    "azure",
                    "gcp",
                    "cloud",
                    "python",
                    "bash",
                    "go",
                    "devops",
                    "sre",
                    "notice",
                    "period",
                ]
            )
            integer_required = any(
                k in q_lower for k in ["whole number", "integer", "between 0 and 99"]
            ) or (
                "year" in q_lower
                and not any(k in q_lower for k in ["ctc", "salary", "notice", "period", "annual"])
            )
            
            # For number/decimal fields: only refill if empty or <= 0
            if should_be_numeric:
                try:
                    if current and float(current) > 0:
                        print(f"[debug] skipping field {q[:30]} - already has value: {current}")
                        continue
                except Exception:
                    pass
            else:
                if current:
                    print(f"[debug] skipping field {q[:30]} - already has value: {current}")
                    continue
            
            print(f"[debug] fill[{_step[0]}] type={field_type} numeric={should_be_numeric} int_required={integer_required} q='{q[:60]}'")
            _step[0] += 1
            
            ans = await _safe_ai_answer(q, None, default="")
            
            # For number/decimal fields, extract ONLY the numeric part and format as decimal
            if should_be_numeric:
                import re as _re
                nums = _re.findall(r"\d+(?:\.\d+)?", ans)
                if nums:
                    val = float(nums[0])
                    if integer_required:
                        ans = str(max(0, min(99, int(round(val)))))
                    else:
                        # Format with .1 decimal place minimum
                        ans = str(val) if "." in str(val) else f"{val:.1f}"
                else:
                    # Sensible defaults based on question
                    if any(k in q_lower for k in ["total", "experience", "exp"]):
                        ans = "10" if integer_required else "10.0"
                    elif any(k in q_lower for k in ["kubernetes", "docker", "aws", "azure", "gcp", "cloud", "python", "bash", "go", "devops", "sre"]):
                        ans = "8" if integer_required else "8.0"
                    elif any(k in q_lower for k in ["ctc", "salary", "cost"]):
                        if "current" in q_lower:
                            ans = "25.0"
                        else:
                            ans = "35.0"
                    elif "notice" in q_lower or "period" in q_lower:
                        ans = "30.0"  # days
                    else:
                        ans = "5" if integer_required else "5.0"
            else:
                # Normalize common structured text fields that often fail validation.
                if "linkedin" in q_lower and ("url" in q_lower or "profile" in q_lower):
                    ans = "https://www.linkedin.com/in/shivakumar-kalal"
                elif "current company" in q_lower:
                    ans = "Confidential"
                elif "current job title" in q_lower:
                    ans = "DevOps Engineer"
                elif "city" in q_lower or "location" in q_lower:
                    ans = "Hyderabad"
                elif "what has attracted" in q_lower or "why" in q_lower:
                    ans = "Role matches my DevOps and cloud automation experience."

                # Keep free-text concise and plain to reduce validation errors.
                if len(ans) > 140:
                    ans = ans[:140].strip()
            
            print(f"[debug]   => '{ans}'")
            await field.fill(ans)
            if should_be_numeric:
                kind = "integer" if integer_required else "decimal"
            else:
                kind = "text"
            answers.append({"kind": kind, "question": q, "ai_answer": ans})
        except Exception as e:
            print(f"[debug] fill error: {str(e)[:60]}")
            continue

    select_fields = page.locator("[role='dialog'] select")
    try:
        select_count = await asyncio.wait_for(asyncio.create_task(select_fields.count()), timeout=2.0)
    except (asyncio.TimeoutError, Exception):
        select_count = 0
    for i in range(min(select_count, 20)):
        sel = select_fields.nth(i)
        try:
            if not await sel.is_visible(timeout=200):
                continue
            # Check if already has a valid selection
            current_val = await sel.input_value()
            q = (await sel.get_attribute("aria-label") or await sel.get_attribute("name") or "Dropdown field")
            options = [o.strip() for o in await sel.locator("option").all_inner_texts() if _clean(o)]
            if not options:
                continue
            # Filter out placeholder options
            real_options = [o for o in options if o.lower() not in ("select an option", "select", "", "--")]
            if not real_options:
                continue
            # Skip if already has valid (non-placeholder) selection
            if current_val and current_val.strip() and current_val.strip().lower() not in ("select an option", "select", ""):
                continue
            ans = await _safe_ai_answer(q, real_options, default=real_options[0] if real_options else "")
            chosen = None
            for opt in real_options:
                if opt.lower() == ans.lower():
                    chosen = opt
                    break
            if not chosen:
                for opt in real_options:
                    if ans.lower() in opt.lower() or opt.lower() in ans.lower():
                        chosen = opt
                        break
            # Fallback: prefer 'Yes' for Yes/No questions, else first option
            if not chosen:
                yes_opts = [o for o in real_options if o.lower() == "yes"]
                chosen = yes_opts[0] if yes_opts else real_options[0]
            if chosen:
                await sel.select_option(label=chosen)
                answers.append({"kind": "select", "question": _clean(q), "ai_answer": chosen, "options": real_options[:10]})
        except Exception:
            continue

    fieldsets = page.locator("[role='dialog'] fieldset")
    try:
        fs_count = await asyncio.wait_for(asyncio.create_task(fieldsets.count()), timeout=2.0)
    except (asyncio.TimeoutError, Exception):
        fs_count = 0
    for i in range(min(fs_count, 15)):
        fs = fieldsets.nth(i)
        try:
            if not await fs.is_visible(timeout=200):
                continue
            q = _clean(await fs.locator("legend").first.inner_text()) if await fs.locator("legend").count() else "Radio question"
            labels = fs.locator("label")
            l_count = await labels.count()
            opts = []
            for j in range(l_count):
                txt = _clean(await labels.nth(j).inner_text())
                if txt:
                    opts.append(txt)
            if not opts:
                continue
            ans = await _safe_ai_answer(q, opts, default=(opts[0] if opts else ""))
            picked = None
            for j in range(l_count):
                txt = _clean(await labels.nth(j).inner_text())
                if txt.lower() == ans.lower() or ans.lower() in txt.lower() or txt.lower() in ans.lower():
                    await labels.nth(j).click()
                    picked = txt
                    break
            if picked:
                answers.append({"kind": "radio", "question": q, "ai_answer": picked, "options": opts[:10]})
        except Exception:
            continue

    job_result.setdefault("ai_answers", []).extend(answers)


async def _try_submit_easy_apply_with_fill(page, ai, job_result):
    """Multi-step submit loop: fill fields on every screen, click Next/Submit, detect success."""
    _shot_idx = [0]

    async def _screenshot(label: str):
        try:
            ts = datetime.now(timezone.utc).strftime("%H%M%S")
            name = f"{ts}_{_shot_idx[0]:02d}_{label}.png"
            _shot_idx[0] += 1
            await page.screenshot(path=os.path.join(SCREENSHOT_DIR, name), full_page=False)
        except Exception:
            pass

    for step in range(25):
        await asyncio.sleep(1.2)

        # Fill any newly appeared fields on this step
        try:
            await asyncio.wait_for(_fill_easy_apply_fields(page, ai, job_result), timeout=20.0)
        except asyncio.TimeoutError:
            print(f"[debug] _fill_easy_apply_fields timed out on step {step}; continuing")
        await asyncio.sleep(0.5)

        # Check success FIRST before any button clicks
        success_texts = [
            "application was sent",
            "application submitted",
            "you're all set",
            "successfully applied",
        ]
        try:
            dlg = page.locator('[role="dialog"]').first
            page_text = _clean(await dlg.inner_text()).lower()
        except Exception:
            page_text = ""
        if any(s in page_text for s in success_texts):
            await _screenshot("success")
            await _dismiss_post_apply_popup(page)
            return True, "success_marker_detected"

        # Scroll to bottom of modal to reveal Submit button if hidden
        try:
            await page.evaluate("""
                () => {
                    const dlg = document.querySelector('[role="dialog"]');
                    if (dlg) dlg.scrollTop = dlg.scrollHeight;
                }
            """)
            await asyncio.sleep(0.3)
        except Exception:
            pass

        # Take screenshot to record current state
        await _screenshot(f"step{step:02d}")

        # Check for validation errors - if present, log and break to avoid infinite loop
        try:
            err_text = await page.locator('[role="dialog"] .artdeco-inline-feedback--error, [role="dialog"] .fb-error-container').first.inner_text()
            if err_text:
                print(f"[debug] validation error on step {step}: {_clean(err_text)[:80]}")
        except Exception:
            pass

        # Click Submit application first, then Review, then Next
        clicked = False
        submitted_now = False
        for selector in [
            "button:has-text('Submit application')",
            "button:has-text('Review')",
            "button:has-text('Next')",
            "button:has-text('Continue')",
        ]:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=600) and await btn.is_enabled(timeout=600):
                    print(f"[debug] clicking step button: {selector} (step {step})")
                    if "Submit" in selector:
                        submitted_now = True
                    await btn.click()
                    clicked = True
                    # Wait for page transition after clicking Next/Review/Continue
                    if not submitted_now:
                        await asyncio.sleep(3.0)  # Extended wait for page to fully load
                    break
            except Exception:
                continue

        # Fallback: LinkedIn sometimes renders primary nav button without matching inner text
        if not clicked:
            for selector in [
                "[role='dialog'] footer button.artdeco-button--primary",
                "[role='dialog'] button.artdeco-button--primary",
                "[role='dialog'] button[aria-label*='next' i]",
                "[role='dialog'] button[aria-label*='review' i]",
                "[role='dialog'] button[aria-label*='submit' i]",
            ]:
                try:
                    btn = page.locator(selector).first
                    if await btn.is_visible(timeout=600) and await btn.is_enabled(timeout=600):
                        btn_text = _clean(await btn.inner_text()).lower()
                        btn_aria = _clean(await btn.get_attribute("aria-label") or "").lower()
                        print(f"[debug] clicking fallback button: {selector} text='{btn_text[:30]}' aria='{btn_aria[:40]}' (step {step})")
                        if "submit" in btn_text or "submit" in btn_aria:
                            submitted_now = True
                        await btn.click()
                        clicked = True
                        if not submitted_now:
                            await asyncio.sleep(3.0)
                        break
                except Exception:
                    continue

        if not clicked:
            await _screenshot("no_button_found")
            print(f"[debug] no navigation button found on step {step}, stopping")
            break

        # After Submit, wait longer for success confirmation
        if submitted_now:
            await asyncio.sleep(2.5)
            try:
                dlg = page.locator('[role="dialog"]').first
                page_text = _clean(await dlg.inner_text()).lower()
            except Exception:
                page_text = ""
            if any(s in page_text for s in success_texts):
                await _screenshot("success_after_submit")
                await _dismiss_post_apply_popup(page)
                return True, "success_after_submit"
            # Check if modal closed (navigated away) = also success
            try:
                modal_gone = not await page.locator('[role="dialog"]').first.is_visible(timeout=1500)
                if modal_gone:
                    await _dismiss_post_apply_popup(page)
                    return True, "modal_closed_after_submit"
            except Exception:
                pass

    return False, "submit_not_reached"


async def _try_submit_easy_apply(page):
    for step in range(20):
        await asyncio.sleep(1.2)

        # Check success markers (including LinkedIn's new wording)
        success_texts = [
            "application was sent",
            "application submitted",
            "you're all set",
            "successfully applied",
        ]
        try:
            page_text = _clean(await page.locator('[role="dialog"]').first.inner_text())
        except Exception:
            try:
                page_text = _clean(await page.locator("body").inner_text())
            except Exception:
                page_text = ""
        page_text_lower = page_text.lower()
        if any(s in page_text_lower for s in success_texts):
            # Dismiss post-apply popup (Open to Work, etc.)
            await _dismiss_post_apply_popup(page)
            return True, "success_marker_detected"

        # Fill any new fields that appeared on this step
        # (handled externally before each Next click)

        # Click Next / Review / Submit
        clicked = False
        for selector in [
            "button:has-text('Submit application')",
            "button:has-text('Review')",
            "button:has-text('Next')",
            "button:has-text('Continue')",
        ]:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=500) and await btn.is_enabled(timeout=500):
                    await btn.click()
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            # No button found - modal might have closed or something unexpected
            break

    return False, "submit_not_reached"


async def _close_easy_apply_modal(page):
    for selector in [
        "button[aria-label='Dismiss']",
        "button:has-text('Discard')",
        "button:has-text('Cancel')",
        "button:has-text('No thanks')",
    ]:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=300):
                await btn.click()
                await asyncio.sleep(0.4)
                # If Discard confirmation appears, confirm it
                try:
                    discard_confirm = page.locator("button:has-text('Discard')").first
                    if await discard_confirm.is_visible(timeout=800):
                        await discard_confirm.click()
                        await asyncio.sleep(0.3)
                except Exception:
                    pass
                return
        except Exception:
            continue


async def _wait_for_manual_login(page, timeout_seconds: int = 300) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        try:
            authwall = await page.evaluate(
                """() => {
                    const u = location.href.toLowerCase();
                    return u.includes('authwall') || u.includes('/login') || u.includes('/checkpoint');
                }"""
            )
            logged_in = await page.locator('a[href*="/feed"], a[href*="/mynetwork"], button[aria-label*="Me"], img.global-nav__me-photo').first.is_visible(timeout=800)
            if logged_in and not authwall:
                return True
        except Exception:
            pass
        await asyncio.sleep(2.0)
    return False


def _write_partial_result(payload: dict):
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _build_search_urls(base_url: str, keywords: list[str], locations: list[str], max_pages: int) -> list[str]:
    urls = []
    for kw in keywords:
        for loc in locations:
            for p in range(max_pages):
                start = p * 25
                # f_LF=f_AL = Easy Apply filter
                urls.append(
                    "https://www.linkedin.com/jobs/search/"
                    f"?keywords={quote_plus(kw)}&location={quote_plus(loc)}&f_LF=f_AL&f_TPR=r604800&start={start}"
                )
    if base_url and base_url not in urls:
        urls.insert(0, base_url)
    return urls


async def _click_job_card_and_wait(page, li_element, prev_job_url: str = ""):
    """Click a job card to load the detail right panel. Wait for URL change if prev known."""
    try:
        await li_element.click()
    except Exception:
        try:
            link = li_element.locator('a[href*="/jobs/view/"]').first
            await link.click()
        except Exception:
            pass
    await asyncio.sleep(1.0)
    # Wait for the currentJobId in URL to change (ensures new job loaded)
    if prev_job_url:
        try:
            prev_id = prev_job_url.split("/jobs/view/")[-1].split("/")[0].split("?")[0]
            for _ in range(10):
                cur = page.url
                if prev_id not in cur:
                    break
                await asyncio.sleep(0.5)
        except Exception:
            pass
    try:
        await page.wait_for_selector(
            '.jobs-search__job-details, .jobs-details__main-content, .job-view-layout, .jobs-unified-top-card',
            timeout=8000,
        )
    except Exception:
        pass
    await asyncio.sleep(1.2)


async def _get_detail_panel_context(page):
    """Extract JD, salary, experience from the right detail panel."""
    return await page.evaluate(
        r"""() => {
            const containers = [
                '.jobs-search__job-details--container',
                '.jobs-details__main-content',
                '.job-view-layout',
                'main',
            ];
            let panel = null;
            for (const sel of containers) {
                const el = document.querySelector(sel);
                if (el) { panel = el; break; }
            }
            const scope = panel || document;
            const jdSels = [
                '.jobs-description-content__text',
                '.jobs-box__html-content',
                '.jobs-description',
                '[class*="jobs-description"]',
            ];
            let jd = '';
            for (const s of jdSels) {
                const el = scope.querySelector(s);
                const t = (el?.innerText || '').trim();
                if (t.length > jd.length) jd = t;
            }
            const allText = (scope.innerText || '').replace(/\s+/g, ' ');
            const salaryMatch = allText.match(/(₹|INR|\$)\s?[\d,.]+\s?(LPA|Lakhs?|per year|\/yr|\/year|\/hr)?\s?(to|-)?\s?(₹|INR|\$)?\s?[\d,.]*/i);
            const expMatch = allText.match(/\b\d+\s*(?:-|to)?\s*\d*\s*(?:years?|yrs?)\b/i);
            const structure = {
                forms: scope.querySelectorAll('form').length,
                text_inputs: scope.querySelectorAll('input[type="text"],input[type="number"],input[type="email"]').length,
                textareas: scope.querySelectorAll('textarea').length,
                selects: scope.querySelectorAll('select').length,
                buttons: scope.querySelectorAll('button').length,
            };
            return {
                jd: jd || allText.slice(0, 8000),
                salary: salaryMatch ? salaryMatch[0] : '',
                experience: expMatch ? expMatch[0] : '',
                structure,
            };
        }"""
    )


async def _find_easy_apply_btn(page):
    """Find the Easy Apply button in the right detail panel, excluding search filter pills."""
    # Try aria-label selector first (most specific)
    try:
        btn = page.locator("button[aria-label*='Easy Apply to']").first
        if await btn.is_visible(timeout=2000):
            return btn
    except Exception:
        pass
    # Try class-based
    try:
        btn = page.locator("button.jobs-apply-button").first
        if await btn.is_visible(timeout=1500):
            return btn
    except Exception:
        pass
    # Scan all buttons in detail panel, skip filter pills
    try:
        result = await page.evaluate(
            """() => {
                const containers = ['.jobs-search__job-details--container','.jobs-details__main-content','.job-view-layout','main'];
                let panel = null;
                for (const sel of containers) { const el = document.querySelector(sel); if (el) { panel = el; break; } }
                const scope = panel || document;
                for (const b of scope.querySelectorAll('button')) {
                    const cls = b.className || '';
                    if (cls.includes('artdeco-pill--choice') || cls.includes('search-reusables__filter-pill-button')) continue;
                    const t = (b.textContent || '').replace(/\\s+/g,' ').trim().toLowerCase();
                    const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    if (t === 'easy apply' || aria.includes('easy apply to')) {
                        return { aria: b.getAttribute('aria-label') || '', text: b.textContent.replace(/\\s+/g,' ').trim() };
                    }
                }
                return null;
            }"""
        )
        if result:
            if result.get("aria"):
                btn = page.locator(f"button[aria-label='{result['aria']}']").first
            else:
                btn = page.locator("button.jobs-apply-button").first
            if await btn.is_visible(timeout=1000):
                return btn
    except Exception:
        pass
    return None


async def run_inspection(base_url: str, target_applies: int, min_score: int, user_data_dir: str):
    ai = QuestionAnswerer()
    results = []
    search_log = []
    seen_urls = set()
    applied_count = 0
    inspected_count = 0

    keywords = [
        "DevOps Engineer",
        "Site Reliability Engineer",
        "Platform Engineer",
        "Cloud Infrastructure Engineer",
        "Azure DevOps Engineer",
    ]
    locations = ["Hyderabad", "Bangalore", "Pune", "Chennai"]
    search_urls = _build_search_urls(base_url, keywords, locations, max_pages=3)

    final = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "ok": False,
        "message": "Started LinkedIn debug verification.",
        "steps": {
            "1_login_successful": False,
            "2_search_and_jd_score": False,
            "3_job_page_structure": False,
            "4_fields_and_values": False,
            "5_apply_popup_fields": False,
            "6_apply_submit_verified": False,
        },
        "target_applies": target_applies,
        "applied_count": 0,
        "inspected_count": 0,
        "search_urls": search_urls,
        "search_log": search_log,
        "jobs": results,
    }
    _write_partial_result(final)

    async with async_playwright() as p:
        print(f"[debug] launching Chromium with profile: {user_data_dir}")
        context = await asyncio.wait_for(p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        ), timeout=60)
        page = context.pages[0] if context.pages else await context.new_page()

        print("[debug] step1 login verification")
        await page.goto(search_urls[0], wait_until="domcontentloaded", timeout=90000)
        await asyncio.sleep(2.0)

        authwall = await page.evaluate(
            """() => {
                const u = location.href.toLowerCase();
                return u.includes('authwall') || u.includes('/login') || u.includes('/checkpoint');
            }"""
        )
        logged_in_now = False
        try:
            logged_in_now = await page.locator('a[href*="/feed"], a[href*="/mynetwork"], button[aria-label*="Me"], img.global-nav__me-photo').first.is_visible(timeout=1500)
        except Exception:
            logged_in_now = False

        if logged_in_now:
            authwall = False

        if authwall:
            print("[debug] authwall detected. Please log in manually in the opened browser window...")
            login_ok = await _wait_for_manual_login(page, timeout_seconds=300)
            if not login_ok:
                final = {
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "ok": False,
                    "message": "LinkedIn login failed (authwall detected).",
                    "steps": {
                        "1_login_successful": False,
                        "2_search_and_jd_score": False,
                        "3_job_page_structure": False,
                        "4_fields_and_values": False,
                        "5_apply_popup_fields": False,
                        "6_apply_submit_verified": False,
                    },
                    "target_applies": target_applies,
                    "applied_count": 0,
                    "inspected_count": 0,
                    "search_urls": search_urls,
                    "search_log": [],
                    "jobs": [],
                }
                with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                    json.dump(final, f, ensure_ascii=False, indent=2)
                print(f"Saved: {OUTPUT_PATH}")
                return

            try:
                await context.storage_state(path=STORAGE_STATE_PATH)
                print(f"[debug] saved storage state: {STORAGE_STATE_PATH}")
            except Exception as exc:
                print(f"[debug] storage state save warning: {exc}")

        final["steps"]["1_login_successful"] = True
        final["captured_at"] = datetime.now(timezone.utc).isoformat()
        final["message"] = "Login verified. Continuing search and apply verification."
        _write_partial_result(final)

        for surl in search_urls:
            if applied_count >= target_applies:
                break

            print(f"[debug] step2 search URL: {surl}")
            await page.goto(surl, wait_until="domcontentloaded", timeout=90000)
            await asyncio.sleep(1.5)
            # Scroll to load all job cards
            for y in [500, 1200, 2000]:
                await page.evaluate(f"window.scrollTo(0, {y})")
                await asyncio.sleep(0.4)
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)

            # Collect job card list items from search left panel
            job_cards_raw = await page.evaluate("""
                () => {
                    const seen = new Set();
                    const out = [];
                    document.querySelectorAll('li a[href*="/jobs/view/"]').forEach(a => {
                        const url = a.href.split('?')[0];
                        if (!url || seen.has(url)) return;
                        seen.add(url);
                        out.push({ url: a.href, base_url: url });
                    });
                    return out;
                }
            """)
            search_log.append({"url": surl, "jobs_found": len(job_cards_raw)})
            final["search_log"] = search_log
            _write_partial_result(final)

            # Get list item elements for clicking
            li_elements = page.locator('li:has(a[href*="/jobs/view/"])')
            li_count = await li_elements.count()
            print(f"[debug]   found {li_count} job cards")

            for li_idx in range(li_count):
                if applied_count >= target_applies:
                    break

                li = li_elements.nth(li_idx)
                try:
                    job_link = li.locator('a[href*="/jobs/view/"]').first
                    job_url = await job_link.get_attribute("href") or ""
                    job_base_url = job_url.split("?")[0]
                except Exception:
                    continue

                if not job_base_url or job_base_url in seen_urls:
                    continue
                seen_urls.add(job_base_url)
                inspected_count += 1

                # Get title/company from card before clicking
                raw_title = _clean(await li.locator('a[href*="/jobs/view/"]').first.inner_text())

                job_result = {
                    "title": raw_title,
                    "company": "",
                    "location": "",
                    "url": job_url,
                    "search_url": surl,
                    "status": "inspected",
                    "ai_answers": [],
                }

                try:
                    print(f"[debug] clicking card: {raw_title[:60]}")
                    # Pass previous URL so panel-update check works
                    prev_url = page.url
                    await _click_job_card_and_wait(page, li, prev_url)

                    # Extract JD from right panel
                    ctx = await _get_detail_panel_context(page)
                    jd = _clean(ctx.get("jd", ""))[:9000]
                    salary_txt = _clean(ctx.get("salary", ""))
                    exp_txt = _clean(ctx.get("experience", ""))
                    structure = ctx.get("structure", {})

                    job_result["job_structure"] = structure
                    job_result["salary_detected"] = salary_txt
                    job_result["experience_detected"] = exp_txt
                    final["steps"]["3_job_page_structure"] = True

                    if not jd:
                        job_result["status"] = "skipped_missing_jd"
                        results.append(job_result)
                        continue

                    # Try to get company from page title or panel header
                    try:
                        company_txt = await page.locator(
                            '.jobs-unified-top-card__company-name, .job-details-jobs-unified-top-card__company-name'
                        ).first.inner_text()
                        job_result["company"] = _clean(company_txt)
                    except Exception:
                        pass

                    score, reason = ai.match_job_score(
                        job_title=job_result["title"],
                        company=job_result["company"],
                        location=job_result["location"],
                        salary=salary_txt,
                        experience=exp_txt,
                        skills=jd[:600],
                        full_description=jd,
                    )
                    job_result["match_score"] = score
                    job_result["match_reason"] = _clean(reason)
                    print(f"[debug] score={score}")
                    final["steps"]["2_search_and_jd_score"] = True

                    # Salary gate
                    min_expected, _ = _parse_salary_range_lpa(str(getattr(Config, "YOUR_EXPECTED_CTC", "") or ""))
                    _, job_salary_max = _parse_salary_range_lpa(salary_txt)
                    if salary_txt and min_expected is not None and job_salary_max is not None and job_salary_max < min_expected:
                        job_result["status"] = "skipped_salary_below_min"
                        results.append(job_result)
                        continue

                    if score < min_score:
                        job_result["status"] = "skipped_low_score"
                        results.append(job_result)
                        continue

                    # Find Easy Apply button in right panel
                    easy_btn = await _find_easy_apply_btn(page)
                    if easy_btn is None:
                        job_result["status"] = "skipped_no_easy_apply"
                        results.append(job_result)
                        continue

                    btn_aria = _clean(await easy_btn.get_attribute("aria-label") or "")
                    btn_txt = _clean(await easy_btn.inner_text()).lower()
                    print(f"[debug] easy apply btn: '{btn_aria[:50]}'")

                    if not await easy_btn.is_enabled(timeout=1500):
                        job_result["status"] = "skipped_easy_apply_disabled"
                        results.append(job_result)
                        continue

                    await easy_btn.click()
                    await asyncio.sleep(1.5)

                    # Initial field fill
                    modal = await _extract_modal_fields(page)
                    job_result["apply_popup_fields"] = modal.get("fields", [])
                    job_result["apply_popup_buttons"] = (modal.get("buttons", []) or [])[:30]
                    print(f"[debug] step5 fields extracted={len(job_result['apply_popup_fields'])}")
                    if job_result["apply_popup_fields"]:
                        final["steps"]["4_fields_and_values"] = True
                        final["steps"]["5_apply_popup_fields"] = True

                    try:
                        await asyncio.wait_for(_fill_easy_apply_fields(page, ai, job_result), timeout=20.0)
                    except asyncio.TimeoutError:
                        print("[debug] initial _fill_easy_apply_fields timed out; continuing to submit loop")

                    # Submit loop: fill fields on each step, then click Next/Submit
                    try:
                        submitted, submit_note = await asyncio.wait_for(
                            _try_submit_easy_apply_with_fill(page, ai, job_result),
                            timeout=180.0,
                        )
                    except asyncio.TimeoutError:
                        submitted, submit_note = False, "apply_loop_timeout"
                    job_result["submit_verification"] = submit_note

                    if submitted:
                        applied_count += 1
                        job_result["status"] = "applied_verified"
                        print(f"[debug] step6 apply verified count={applied_count}")
                        final["steps"]["6_apply_submit_verified"] = True
                    else:
                        job_result["status"] = "apply_incomplete"
                        await _close_easy_apply_modal(page)

                    results.append(job_result)
                except asyncio.CancelledError:
                    job_result["status"] = "cancelled"
                    results.append(job_result)
                    final["ok"] = applied_count >= 1
                    final["message"] = "Run interrupted; partial verification results saved."
                    final["applied_count"] = applied_count
                    final["inspected_count"] = inspected_count
                    _write_partial_result(final)
                    print(f"Saved (partial): {OUTPUT_PATH}")
                    return
                except Exception as exc:
                    job_result["status"] = "error"
                    job_result["error"] = _clean(str(exc))
                    try:
                        await _close_easy_apply_modal(page)
                    except Exception:
                        pass
                    results.append(job_result)

                final["applied_count"] = applied_count
                final["inspected_count"] = inspected_count
                _write_partial_result(final)

        final = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "ok": applied_count >= min(1, target_applies),
            "message": (
                f"Completed LinkedIn debug verification. Applied verified: {applied_count}. "
                f"Target: {target_applies}."
            ),
            "steps": {
                "1_login_successful": True,
                "2_search_and_jd_score": any("match_score" in j for j in results),
                "3_job_page_structure": any("job_structure" in j for j in results),
                "4_fields_and_values": any((j.get("apply_popup_fields") or []) for j in results),
                "5_apply_popup_fields": any((j.get("apply_popup_fields") or []) for j in results),
                "6_apply_submit_verified": any(j.get("status") == "applied_verified" for j in results),
            },
            "target_applies": target_applies,
            "applied_count": applied_count,
            "inspected_count": inspected_count,
            "search_urls": search_urls,
            "search_log": search_log,
            "jobs": results,
        }

        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(final, f, ensure_ascii=False, indent=2)

        print(f"Saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify LinkedIn end-to-end apply flow with AI answers")
    parser.add_argument(
        "--url",
        default="https://www.linkedin.com/jobs/search/?keywords=DevOps%20Engineer&location=Hyderabad",
        help="LinkedIn jobs search URL",
    )
    parser.add_argument("--target-applies", type=int, default=10, help="How many verified applications to attempt")
    parser.add_argument("--min-score", type=int, default=60, help="Minimum AI match score for apply")
    parser.add_argument("--user-data-dir", default=LINKEDIN_BROWSER_DATA_DIR, help="Playwright persistent profile directory")
    args = parser.parse_args()
    asyncio.run(run_inspection(args.url, args.target_applies, args.min_score, args.user_data_dir))

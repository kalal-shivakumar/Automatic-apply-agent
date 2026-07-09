"""
Debug script: Collect 10 LinkedIn Easy Apply URLs, navigate to each,
dynamically extract ALL form fields, fill them with AI answers, click through steps,
submit, and verify if the job shows as "Applied".

This script is standalone — it uses the LinkedIn browser profile directly.
"""

import asyncio
import json
import logging
import os
import re
import sys
from urllib.parse import quote_plus

from playwright.async_api import async_playwright

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(__file__))
from ai_answerer import QuestionAnswerer
from config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Fix Windows console encoding
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

RESULTS_FILE = os.path.join(os.path.dirname(__file__), "debug_linkedin_apply_10_results.json")


async def collect_easy_apply_urls(page, count=10) -> list[dict]:
    """Search LinkedIn and collect job URLs that have Easy Apply."""
    jobs = []
    keywords_list = [
        ("DevOps Engineer", "hyderabad"),
        ("Azure DevOps Engineer", "hyderabad"),
        ("Cloud Engineer", "hyderabad"),
        ("DevOps Engineer", "bangalore"),
        ("Platform Engineer", "hyderabad"),
    ]

    for keywords, location in keywords_list:
        if len(jobs) >= count:
            break
        for page_no in range(1, 4):
            if len(jobs) >= count:
                break
            start = (page_no - 1) * 25
            # f_AL=true = Easy Apply only, f_TPR=r86400 = last 24 hours
            url = f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(keywords)}&location={quote_plus(location)}&f_TPR=r86400&f_AL=true&start={start}"
            logger.info(f"Searching: {keywords} in {location} (page {page_no})")
            try:
                await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                await asyncio.sleep(3)
                # Scroll to load cards
                for y in [500, 1000, 1500]:
                    await page.evaluate(f"window.scrollTo(0, {y})")
                    await asyncio.sleep(0.5)

                cards = await page.evaluate("""() => {
                    const out = [];
                    document.querySelectorAll('a[href*="/jobs/view/"]').forEach(a => {
                        const href = a.href;
                        const title = a.textContent?.trim()?.substring(0, 100) || '';
                        if (href && !out.some(j => j.url === href)) {
                            out.push({ url: href.split('?')[0], title });
                        }
                    });
                    return out;
                }""")

                for card in cards:
                    if len(jobs) >= count:
                        break
                    if card["url"] not in [j["url"] for j in jobs]:
                        jobs.append(card)
                        logger.info(f"  [{len(jobs)}/{count}] {card['title'][:60]} - {card['url']}")
            except Exception as e:
                logger.warning(f"Search error: {e}")

    return jobs[:count]


async def extract_modal_fields(page) -> dict:
    """Extract ALL visible form fields from the Easy Apply modal using JavaScript."""
    return await page.evaluate(r"""() => {
        const modal = document.querySelector('div.artdeco-modal, div[role="dialog"]');
        if (!modal) return { error: 'No modal found', fields: [], buttons: [], modal_text: '' };

        const fields = [];
        const buttons = [];

        // All inputs (text, number, tel, email, etc.)
        modal.querySelectorAll('input').forEach(el => {
            if (el.type === 'hidden') return;
            if (!el.offsetHeight) return; // not visible
            const label = el.id ? document.querySelector(`label[for="${el.id}"]`)?.textContent?.trim() : '';
            fields.push({
                type: 'input',
                inputType: el.type || 'text',
                name: el.name,
                id: el.id,
                value: el.value,
                label: label || el.getAttribute('aria-label') || el.placeholder || '',
                required: el.required,
                checked: el.checked,
            });
        });

        // All selects
        modal.querySelectorAll('select').forEach(el => {
            if (!el.offsetHeight) return;
            const label = el.id ? document.querySelector(`label[for="${el.id}"]`)?.textContent?.trim() : '';
            const opts = Array.from(el.options).map(o => ({ text: o.text.trim(), value: o.value, selected: o.selected }));
            fields.push({
                type: 'select',
                id: el.id,
                label: label || el.getAttribute('aria-label') || '',
                options: opts.slice(0, 20),
                currentValue: el.value,
                currentText: el.options[el.selectedIndex]?.text?.trim() || '',
                required: el.required,
            });
        });

        // All textareas
        modal.querySelectorAll('textarea').forEach(el => {
            if (!el.offsetHeight) return;
            const label = el.id ? document.querySelector(`label[for="${el.id}"]`)?.textContent?.trim() : '';
            fields.push({
                type: 'textarea',
                id: el.id,
                value: el.value,
                label: label || el.getAttribute('aria-label') || el.placeholder || '',
                required: el.required,
            });
        });

        // All visible buttons
        modal.querySelectorAll('button').forEach(el => {
            if (!el.offsetHeight) return;
            buttons.push({
                text: el.textContent?.trim()?.substring(0, 80),
                ariaLabel: el.getAttribute('aria-label'),
                disabled: el.disabled,
                type: el.type,
                class: el.className?.substring(0, 100),
                isPrimary: el.classList.contains('artdeco-button--primary'),
            });
        });

        return {
            error: null,
            fields,
            buttons,
            modal_text: modal.innerText?.substring(0, 1000) || '',
            progress: modal.querySelector('.jobs-easy-apply-modal__progress-bar, [role="progressbar"]')?.getAttribute('aria-valuenow') || '',
        };
    }""")


async def fill_field(page, field: dict, ai: QuestionAnswerer) -> str:
    """Fill a single field using AI answer. Returns what was done."""
    ftype = field["type"]
    fid = field.get("id", "")
    label = field.get("label", "")

    if not fid:
        return f"SKIP (no id): {label}"

    if ftype == "input":
        input_type = field.get("inputType", "text")
        if input_type in ("radio", "checkbox"):
            return f"SKIP radio/checkbox via fill_field"
        current = field.get("value", "").strip()
        if current:
            return f"ALREADY FILLED: '{current[:30]}'"
        if not label:
            return f"SKIP (no label)"

        answer = ai.answer_question(label, None)
        try:
            await page.locator(f"#{fid}").fill(str(answer))
            return f"FILLED '{label}' -> '{answer}'"
        except Exception as e:
            return f"ERROR filling '{label}': {e}"

    elif ftype == "select":
        options = field.get("options", [])
        current_text = field.get("currentText", "")
        if current_text and "Select" not in current_text:
            return f"ALREADY SELECTED: '{current_text}'"

        # Special cases
        opt_texts = [o["text"] for o in options if o["text"]]
        email_opt = next((o for o in opt_texts if "@" in o), None)
        if email_opt:
            try:
                await page.locator(f"#{fid}").select_option(label=email_opt)
                return f"SELECTED email: '{email_opt}'"
            except Exception as e:
                return f"ERROR selecting email: {e}"

        india_opt = next((o for o in opt_texts if "India" in o), None)
        if india_opt:
            try:
                await page.locator(f"#{fid}").select_option(label=india_opt)
                return f"SELECTED country: '{india_opt}'"
            except Exception as e:
                return f"ERROR selecting country: {e}"

        # AI answer for other selects
        if label and len(opt_texts) > 1:
            answer = ai.answer_question(label, opt_texts)
            chosen = next((o for o in opt_texts if o.lower() == str(answer).strip().lower()), None)
            if chosen:
                try:
                    await page.locator(f"#{fid}").select_option(label=chosen)
                    return f"AI SELECTED '{label}' -> '{chosen}'"
                except Exception as e:
                    return f"ERROR AI select: {e}"
            else:
                # Select first non-default option
                non_default = [o for o in opt_texts if "Select" not in o and o]
                if non_default:
                    try:
                        await page.locator(f"#{fid}").select_option(label=non_default[0])
                        return f"DEFAULT SELECTED '{label}' -> '{non_default[0]}'"
                    except Exception as e:
                        return f"ERROR default select: {e}"

        return f"SKIP select (no action needed)"

    elif ftype == "textarea":
        current = field.get("value", "").strip()
        if current:
            return f"ALREADY FILLED textarea: '{current[:30]}'"
        if not label:
            return f"SKIP textarea (no label)"
        answer = ai.answer_question(label, None)
        try:
            await page.locator(f"#{fid}").fill(str(answer))
            return f"FILLED textarea '{label}' -> '{str(answer)[:50]}'"
        except Exception as e:
            return f"ERROR textarea: {e}"

    return f"UNKNOWN type: {ftype}"


async def handle_radio_buttons(page, ai: QuestionAnswerer) -> list[str]:
    """Handle radio button groups via JavaScript evaluation."""
    actions = []
    radio_groups = await page.evaluate(r"""() => {
        const modal = document.querySelector('div.artdeco-modal, div[role="dialog"]');
        if (!modal) return [];
        const groups = {};
        modal.querySelectorAll('input[type="radio"]').forEach(r => {
            if (!r.offsetHeight) return;
            const name = r.name;
            if (!groups[name]) groups[name] = { name, options: [], anyChecked: false };
            const label = r.id ? document.querySelector(`label[for="${r.id}"]`)?.textContent?.trim() : r.value;
            groups[name].options.push({ id: r.id, value: r.value, label: label || r.value, checked: r.checked });
            if (r.checked) groups[name].anyChecked = true;
        });
        // Get group question from parent fieldset legend or nearby span
        Object.values(groups).forEach(g => {
            const firstRadio = document.getElementById(g.options[0]?.id);
            if (firstRadio) {
                const fieldset = firstRadio.closest('fieldset');
                const legend = fieldset?.querySelector('legend, span')?.textContent?.trim();
                g.question = legend || g.name;
            }
        });
        return Object.values(groups);
    }""")

    for group in radio_groups:
        if group.get("anyChecked"):
            actions.append(f"RADIO '{group.get('question','')}' already answered")
            continue
        options = [o["label"] for o in group.get("options", [])]
        question = group.get("question", group.get("name", ""))
        if not options or not question:
            continue

        answer = ai.answer_question(question, options)
        chosen_id = None
        for opt in group.get("options", []):
            if opt["label"].lower() == str(answer).strip().lower():
                chosen_id = opt["id"]
                break
        if not chosen_id and group["options"]:
            chosen_id = group["options"][0]["id"]  # default to first

        if chosen_id:
            try:
                await page.locator(f"[id='{chosen_id}']").click()
                actions.append(f"RADIO '{question}' -> '{answer}'")
            except Exception:
                # Fallback: click via JavaScript for IDs with special characters
                try:
                    await page.evaluate(f"document.getElementById('{chosen_id}')?.click()")
                    actions.append(f"RADIO JS '{question}' -> '{answer}'")
                except Exception as e2:
                    actions.append(f"RADIO ERROR '{question}': {e2}")

    return actions


async def apply_to_single_job(page, job: dict, ai: QuestionAnswerer) -> dict:
    """Apply to a single job. Returns detailed result."""
    result = {
        "url": job["url"],
        "title": job.get("title", ""),
        "steps": [],
        "applied": False,
        "error": None,
    }

    job_id_match = re.search(r'/jobs/view/(\d+)', job["url"])
    if not job_id_match:
        result["error"] = "Could not extract job ID from URL"
        return result

    apply_url = f"https://www.linkedin.com/jobs/view/{job_id_match.group(1)}/apply/"

    try:
        # Navigate to apply URL
        logger.info(f"Navigating to: {apply_url}")
        await page.goto(apply_url, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        # Check if modal appeared
        modal = page.locator("div.artdeco-modal, div[role='dialog']")
        if not await modal.first.is_visible(timeout=5000):
            result["error"] = "Modal did not appear"
            return result

        logger.info("Modal visible, starting form fill loop...")

        # Process up to 8 steps
        prev_field_sig = ""
        stuck_count = 0
        for step in range(1, 9):
            await asyncio.sleep(2)
            step_data = {"step": step, "fields_found": 0, "actions": [], "button_clicked": ""}

            # Extract all fields
            modal_data = await extract_modal_fields(page)
            if modal_data.get("error"):
                step_data["actions"].append(f"Modal error: {modal_data['error']}")
                result["steps"].append(step_data)
                break

            # Detect if stuck on same step
            field_sig = str([(f.get("label","")[:20], f.get("value","")[:10]) for f in modal_data.get("fields",[])])
            if field_sig == prev_field_sig:
                stuck_count += 1
                if stuck_count >= 2:
                    logger.info(f"  STUCK: Same fields {stuck_count} times, skipping job")
                    step_data["actions"].append("STUCK - same fields repeated")
                    result["steps"].append(step_data)
                    break
            else:
                stuck_count = 0
            prev_field_sig = field_sig

            progress = modal_data.get("progress", "?")
            fields = modal_data.get("fields", [])
            buttons = modal_data.get("buttons", [])
            step_data["fields_found"] = len(fields)
            step_data["progress"] = progress

            logger.info(f"  Step {step}: {len(fields)} fields, progress={progress}%")
            print(f"\n  --- Step {step} (progress: {progress}%) ---")
            print(f"  Fields: {len(fields)}")
            for f in fields:
                print(f"    {f['type']}: label='{f.get('label','')[:40]}' value='{str(f.get('value',''))[:20]}' id={f.get('id','')[:30]}")

            # Fill all fields
            for field in fields:
                action = await fill_field(page, field, ai)
                step_data["actions"].append(action)
                if "FILLED" in action or "SELECTED" in action:
                    logger.info(f"    {action}")
                    print(f"    >> {action}")

            # Handle radio buttons
            radio_actions = await handle_radio_buttons(page, ai)
            step_data["actions"].extend(radio_actions)
            for ra in radio_actions:
                if "RADIO" in ra and "already" not in ra.lower():
                    logger.info(f"    {ra}")
                    print(f"    >> {ra}")

            await asyncio.sleep(1)

            # Dismiss any typeahead/autocomplete dropdowns by clicking outside them
            try:
                typeahead = page.locator("div.search-typeahead-v2__hit, div.basic-typeahead__triggered-content").first
                if await typeahead.is_visible(timeout=300):
                    # Click on the modal body to dismiss typeahead instead of Escape
                    await page.locator("div.artdeco-modal__content").first.click(position={"x": 5, "y": 5})
                    await asyncio.sleep(0.5)
            except Exception:
                pass

            # Handle "Save this application?" dialog if it appeared
            async def dismiss_save_dialog():
                """Dismiss the 'Save this application?' dialog by clicking Discard via JS."""
                try:
                    has_dialog = await page.evaluate("""() => {
                        const overlay = document.querySelector('[data-test-modal-id="data-test-easy-apply-discard-confirmation"]');
                        if (overlay && overlay.offsetHeight > 0) {
                            const discardBtn = overlay.querySelector('button[data-control-name="discard_application_confirm_btn"], button[data-test-dialog-secondary-btn]');
                            const saveBtn = overlay.querySelector('button[data-control-name="save_application_confirm_btn"], button[data-test-dialog-primary-btn]');
                            if (saveBtn) { saveBtn.click(); return 'saved'; }
                            if (discardBtn) { discardBtn.click(); return 'discarded'; }
                            // Try any button with "Save" text
                            const btns = Array.from(overlay.querySelectorAll('button'));
                            const save = btns.find(b => b.textContent?.trim() === 'Save');
                            if (save) { save.click(); return 'saved_fallback'; }
                            return 'no_button';
                        }
                        return 'no_dialog';
                    }""")
                    if has_dialog and has_dialog != 'no_dialog':
                        logger.info(f"  [DIALOG] Handled save dialog: {has_dialog}")
                        await asyncio.sleep(1)
                        return True
                except Exception:
                    pass
                return False

            await dismiss_save_dialog()

            # Click progression button (Next > Review > Submit)
            next_btn = page.locator("div.artdeco-modal button[aria-label='Continue to next step'], div[role='dialog'] button[aria-label='Continue to next step']").first
            review_btn = page.locator("div.artdeco-modal button[aria-label='Review your application'], div[role='dialog'] button[aria-label='Review your application']").first
            submit_btn = page.locator("div.artdeco-modal button[aria-label='Submit application'], div[role='dialog'] button[aria-label='Submit application']").first

            # Fallback text-based (primary class only)
            next_fb = page.locator("div.artdeco-modal button.artdeco-button--primary:has-text('Next'), div[role='dialog'] button.artdeco-button--primary:has-text('Next')").first
            review_fb = page.locator("div.artdeco-modal button.artdeco-button--primary:has-text('Review'), div[role='dialog'] button.artdeco-button--primary:has-text('Review')").first
            submit_fb = page.locator("div.artdeco-modal button.artdeco-button--primary:has-text('Submit'), div[role='dialog'] button.artdeco-button--primary:has-text('Submit')").first

            clicked = None
            try:
                if await next_btn.is_visible(timeout=500):
                    try:
                        await next_btn.click(timeout=5000)
                    except Exception:
                        await dismiss_save_dialog()
                        await page.evaluate("document.querySelector('button[aria-label=\"Continue to next step\"]')?.click()")
                    clicked = "Next (aria-label)"
                elif await next_fb.is_visible(timeout=300):
                    try:
                        await next_fb.click(timeout=5000)
                    except Exception:
                        await dismiss_save_dialog()
                        await page.evaluate("document.querySelector('button[aria-label=\"Continue to next step\"]')?.click()")
                    clicked = "Next (fallback)"
                elif await review_btn.is_visible(timeout=300):
                    try:
                        await review_btn.click(timeout=5000)
                    except Exception:
                        await dismiss_save_dialog()
                        await page.evaluate("document.querySelector('button[aria-label=\"Review your application\"]')?.click()")
                    clicked = "Review (aria-label)"
                elif await review_fb.is_visible(timeout=300):
                    try:
                        await review_fb.click(timeout=5000)
                    except Exception:
                        await dismiss_save_dialog()
                    clicked = "Review (fallback)"
                elif await submit_btn.is_visible(timeout=300):
                    try:
                        await submit_btn.click(timeout=5000)
                    except Exception:
                        await dismiss_save_dialog()
                        await page.evaluate("document.querySelector('button[aria-label=\"Submit application\"]')?.click()")
                    clicked = "Submit (aria-label)"
                elif await submit_fb.is_visible(timeout=300):
                    await submit_fb.click()
                    clicked = "Submit (fallback)"
            except Exception as e:
                clicked = f"ERROR: {e}"

            step_data["button_clicked"] = clicked or "None found"
            logger.info(f"  Clicked: {clicked}")
            print(f"  -> Button: {clicked}")

            result["steps"].append(step_data)

            if not clicked or "None" in str(clicked):
                logger.info("  No button found, stopping")
                break

            # If we clicked Submit, check for success
            if clicked and "Submit" in clicked:
                await asyncio.sleep(3)
                # Check if modal closed
                try:
                    if not await modal.first.is_visible(timeout=2000):
                        result["applied"] = True
                        logger.info("  >>> MODAL CLOSED AFTER SUBMIT - SUCCESS!")
                        print("  >>> MODAL CLOSED AFTER SUBMIT - SUCCESS!")
                        break
                except Exception:
                    pass
                # Check for success text
                for marker in ["text=/application submitted/i", "text=/your application was sent/i"]:
                    try:
                        if await page.locator(marker).first.is_visible(timeout=1000):
                            result["applied"] = True
                            logger.info("  >>> SUCCESS TEXT DETECTED!")
                            print("  >>> SUCCESS TEXT DETECTED!")
                            break
                    except Exception:
                        pass
                if result["applied"]:
                    break

            # Check if progress changed (form actually advanced)
            await asyncio.sleep(1)
            new_modal = await extract_modal_fields(page)
            new_progress = new_modal.get("progress", progress)
            if new_progress != progress and new_progress != "?":
                logger.info(f"  Progress changed: {progress}% -> {new_progress}%")
                print(f"  Progress: {progress}% -> {new_progress}%")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Error: {e}")

    # Close any open modal/dialog before next job
    try:
        for dismiss_sel in [
            "div.artdeco-modal button[aria-label='Dismiss']",
            "div[role='dialog'] button[aria-label='Dismiss']",
            "button:has-text('Discard')",
            "button:has-text('Cancel')",
        ]:
            try:
                btn = page.locator(dismiss_sel).first
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    await asyncio.sleep(1)
                    break
            except Exception:
                continue
    except Exception:
        pass

    # Verify by going back to job page
    if result.get("applied") or len(result.get("steps", [])) > 0:
        try:
            await page.goto(job["url"], timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(3)
            btn_text = await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const applyBtn = btns.find(b => b.textContent?.toLowerCase()?.includes('appl'));
                return applyBtn?.textContent?.trim() || '';
            }""")
            result["verify_button_text"] = btn_text
            if "applied" in btn_text.lower():
                result["applied"] = True
                logger.info(f"  VERIFIED: Button says '{btn_text}'")
            else:
                logger.info(f"  NOT VERIFIED: Button says '{btn_text}'")
        except Exception:
            pass

    return result


async def main():
    print(f"\n{'='*70}")
    print(f"  LinkedIn Easy Apply: 10-Job Debug Script")
    print(f"{'='*70}\n")

    # Load config
    from dotenv import load_dotenv
    load_dotenv(override=True)

    # Load resume profile and apply to Config so AI answerer has correct context
    profile_path = os.path.join(os.path.dirname(__file__), "resume_profile.json")
    if os.path.exists(profile_path):
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
        Config.YOUR_NAME = str(profile.get("full_name", "") or "")
        Config.YOUR_PHONE = str(profile.get("phone", "") or "")
        Config.YOUR_EXPERIENCE = str(profile.get("overall_experience_years", "") or "")
        Config.YOUR_SKILLS = ", ".join(profile.get("skills", []))
        Config.CANDIDATE_LEVEL = str(profile.get("candidate_level", "Fresher") or "Fresher")
        min_lpa = str(profile.get("salary_min_lpa", "") or "")
        max_lpa = str(profile.get("salary_max_lpa", "") or "")
        Config.YOUR_EXPECTED_CTC = f"{min_lpa}-{max_lpa} LPA" if min_lpa and max_lpa else ""
        Config.YOUR_NOTICE_PERIOD = str(profile.get("notice_period", "") or "")
        Config.JOB_LOCATION = str(profile.get("preferred_location", "") or "Hyderabad")
        Config.EXPERIENCE_YEARS = Config.YOUR_EXPERIENCE
        print(f"  Profile loaded: {Config.YOUR_NAME}, Exp: {Config.YOUR_EXPERIENCE}, Phone: {Config.YOUR_PHONE}")
        print(f"  Level: {Config.CANDIDATE_LEVEL}, Skills: {Config.YOUR_SKILLS[:80]}...")
    else:
        print("  WARNING: resume_profile.json not found!")

    pw = await async_playwright().start()
    user_data_dir = os.path.join(os.path.dirname(__file__), "browser_data_linkedin")

    context = await pw.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=False,
        viewport={"width": 1280, "height": 800},
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.pages[0] if context.pages else await context.new_page()

    # Initialize AI
    ai = QuestionAnswerer()

    # Step 1: Collect URLs
    print("\n[PHASE 1] Collecting Easy Apply job URLs...")
    jobs = await collect_easy_apply_urls(page, count=10)
    print(f"\nCollected {len(jobs)} job URLs:")
    for i, j in enumerate(jobs, 1):
        print(f"  {i}. {j['title'][:60]} - {j['url']}")

    # Step 2: Apply to each
    print(f"\n[PHASE 2] Applying to {len(jobs)} jobs...\n")
    all_results = []
    applied_count = 0

    for i, job in enumerate(jobs, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{len(jobs)}] {job.get('title','')[:60]}")
        print(f"URL: {job['url']}")
        print(f"{'='*60}")

        result = await apply_to_single_job(page, job, ai)
        all_results.append(result)

        if result["applied"]:
            applied_count += 1
            print(f"\n  RESULT: APPLIED (Total: {applied_count})")
        elif result.get("error"):
            print(f"\n  RESULT: ERROR - {result['error']}")
        else:
            print(f"\n  RESULT: NOT APPLIED")

        # Save intermediate results after each job
        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)

        await asyncio.sleep(2)

    # Summary
    print(f"\n\n{'='*70}")
    print(f"  FINAL SUMMARY")
    print(f"{'='*70}")
    print(f"  Total jobs attempted: {len(all_results)}")
    print(f"  Successfully applied: {applied_count}")
    print(f"  Failed: {len(all_results) - applied_count}")
    for r in all_results:
        status = "APPLIED" if r["applied"] else f"FAILED ({(r.get('error') or 'unknown')[:40]})"
        steps = len(r.get("steps", []))
        print(f"    [{status}] {r.get('title','')[:50]} ({steps} steps)")

    # Save results
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to: {RESULTS_FILE}")

    try:
        await context.close()
    except Exception:
        pass
    try:
        await pw.stop()
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())

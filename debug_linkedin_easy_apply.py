"""Debug script: Navigate to a LinkedIn Easy Apply URL, extract ALL form fields and buttons.
Dumps the full DOM structure of the Easy Apply modal at each step."""

import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright

TARGET_URL = (
    "https://www.linkedin.com/jobs/view/4437025386/apply/"
    "?companyName=InovarTech"
    "&refId=lSDBztEQXTAaPHoBe1gb5Q%3D%3D"
    "&trackingId=XKC9xrC3QjLDlBl51LgZGA%3D%3D"
    "&applicantTrackingSystemName=LinkedIn"
)

RESULTS_FILE = os.path.join(os.path.dirname(__file__), "debug_linkedin_easy_apply_results.json")


async def extract_all_fields(page, step_name: str) -> dict:
    """Extract every interactive element visible on the page."""
    data = await page.evaluate(r"""() => {
        const result = {
            step: '',
            modals: [],
            forms: [],
            text_inputs: [],
            number_inputs: [],
            textareas: [],
            selects: [],
            radios: [],
            checkboxes: [],
            fieldsets: [],
            buttons: [],
            labels: [],
            divs_with_role: [],
            file_inputs: [],
            page_text_snippet: '',
        };

        // Check for modals / dialogs
        document.querySelectorAll('div.artdeco-modal, div.jobs-easy-apply-modal, div[role="dialog"], div[class*="easy-apply"]').forEach(m => {
            result.modals.push({
                tag: m.tagName,
                class: m.className?.substring(0, 200),
                role: m.getAttribute('role'),
                visible: m.offsetHeight > 0,
                childCount: m.children.length,
            });
        });

        // Forms
        document.querySelectorAll('form').forEach(f => {
            result.forms.push({
                id: f.id,
                class: f.className?.substring(0, 150),
                action: f.action,
                inputCount: f.querySelectorAll('input, select, textarea').length,
            });
        });

        // Text inputs
        document.querySelectorAll('input[type="text"], input:not([type])').forEach(el => {
            result.text_inputs.push({
                name: el.name,
                id: el.id,
                ariaLabel: el.getAttribute('aria-label'),
                placeholder: el.placeholder,
                value: el.value?.substring(0, 100),
                visible: el.offsetHeight > 0,
                required: el.required,
                class: el.className?.substring(0, 100),
                parentClass: el.parentElement?.className?.substring(0, 100),
            });
        });

        // Number inputs
        document.querySelectorAll('input[type="number"]').forEach(el => {
            result.number_inputs.push({
                name: el.name,
                id: el.id,
                ariaLabel: el.getAttribute('aria-label'),
                value: el.value,
                visible: el.offsetHeight > 0,
                class: el.className?.substring(0, 100),
            });
        });

        // Textareas
        document.querySelectorAll('textarea').forEach(el => {
            result.textareas.push({
                name: el.name,
                id: el.id,
                ariaLabel: el.getAttribute('aria-label'),
                placeholder: el.placeholder,
                value: el.value?.substring(0, 100),
                visible: el.offsetHeight > 0,
                class: el.className?.substring(0, 100),
            });
        });

        // Selects
        document.querySelectorAll('select').forEach(el => {
            const opts = Array.from(el.options).map(o => o.text.trim()).filter(Boolean);
            result.selects.push({
                name: el.name,
                id: el.id,
                ariaLabel: el.getAttribute('aria-label'),
                options: opts.slice(0, 15),
                selectedValue: el.value,
                visible: el.offsetHeight > 0,
                class: el.className?.substring(0, 100),
            });
        });

        // Radio buttons
        document.querySelectorAll('input[type="radio"]').forEach(el => {
            const label = el.id ? document.querySelector(`label[for="${el.id}"]`) : null;
            result.radios.push({
                name: el.name,
                id: el.id,
                value: el.value,
                checked: el.checked,
                labelText: label?.textContent?.trim()?.substring(0, 100) || '',
                visible: el.offsetHeight > 0,
                ariaLabel: el.getAttribute('aria-label'),
            });
        });

        // Checkboxes
        document.querySelectorAll('input[type="checkbox"]').forEach(el => {
            const label = el.id ? document.querySelector(`label[for="${el.id}"]`) : null;
            result.checkboxes.push({
                name: el.name,
                id: el.id,
                checked: el.checked,
                labelText: label?.textContent?.trim()?.substring(0, 100) || '',
                visible: el.offsetHeight > 0,
            });
        });

        // Fieldsets
        document.querySelectorAll('fieldset').forEach(el => {
            const legend = el.querySelector('legend');
            result.fieldsets.push({
                legend: legend?.textContent?.trim()?.substring(0, 100) || '',
                inputCount: el.querySelectorAll('input').length,
                visible: el.offsetHeight > 0,
                class: el.className?.substring(0, 100),
            });
        });

        // Divs with role=group (LinkedIn uses these instead of fieldsets)
        document.querySelectorAll('div[role="group"]').forEach(el => {
            const label = el.querySelector('span, label, legend');
            result.divs_with_role.push({
                role: el.getAttribute('role'),
                labelText: label?.textContent?.trim()?.substring(0, 100) || '',
                inputCount: el.querySelectorAll('input').length,
                visible: el.offsetHeight > 0,
                class: el.className?.substring(0, 150),
            });
        });

        // File inputs
        document.querySelectorAll('input[type="file"]').forEach(el => {
            result.file_inputs.push({
                name: el.name,
                id: el.id,
                accept: el.accept,
                visible: el.offsetHeight > 0,
            });
        });

        // Buttons
        document.querySelectorAll('button').forEach(el => {
            if (!el.textContent?.trim()) return;
            result.buttons.push({
                text: el.textContent.trim().substring(0, 100),
                ariaLabel: el.getAttribute('aria-label'),
                disabled: el.disabled,
                visible: el.offsetHeight > 0,
                type: el.type,
                class: el.className?.substring(0, 100),
            });
        });

        // Labels
        document.querySelectorAll('label').forEach(el => {
            if (!el.textContent?.trim()) return;
            result.labels.push({
                text: el.textContent.trim().substring(0, 100),
                for: el.getAttribute('for'),
                visible: el.offsetHeight > 0,
                class: el.className?.substring(0, 100),
            });
        });

        // Page text snippet (modal area)
        const modal = document.querySelector('div.artdeco-modal, div[role="dialog"]');
        if (modal) {
            result.page_text_snippet = modal.innerText?.substring(0, 2000) || '';
        }

        return result;
    }""")

    data["step"] = step_name
    return data


async def main():
    print(f"\n{'='*70}")
    print(f"  DEBUG: LinkedIn Easy Apply Field Extraction")
    print(f"  URL: {TARGET_URL[:80]}...")
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

    all_steps = []

    try:
        # Step 1: Navigate to the apply URL
        print("[1] Navigating to apply URL...")
        await page.goto(TARGET_URL, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(5)  # Wait for modal to render

        # Extract fields at initial state
        step1 = await extract_all_fields(page, "initial_page_load")
        all_steps.append(step1)

        print(f"  Modals found: {len(step1['modals'])}")
        print(f"  Forms: {len(step1['forms'])}")
        print(f"  Text inputs: {len(step1['text_inputs'])} (visible: {sum(1 for f in step1['text_inputs'] if f['visible'])})")
        print(f"  Number inputs: {len(step1['number_inputs'])}")
        print(f"  Textareas: {len(step1['textareas'])}")
        print(f"  Selects: {len(step1['selects'])}")
        print(f"  Radios: {len(step1['radios'])}")
        print(f"  Checkboxes: {len(step1['checkboxes'])}")
        print(f"  Fieldsets: {len(step1['fieldsets'])}")
        print(f"  Divs with role=group: {len(step1['divs_with_role'])}")
        print(f"  File inputs: {len(step1['file_inputs'])}")
        print(f"  Buttons: {len(step1['buttons'])}")
        print(f"  Labels: {len(step1['labels'])}")

        # Print visible buttons
        print(f"\n  VISIBLE BUTTONS:")
        for b in step1["buttons"]:
            if b["visible"]:
                print(f"    [{b['text'][:60]}] disabled={b['disabled']} class={b['class'][:50] if b['class'] else ''}")

        # Print visible text inputs
        print(f"\n  VISIBLE TEXT INPUTS:")
        for f in step1["text_inputs"]:
            if f["visible"]:
                print(f"    name={f['name']} aria-label='{f['ariaLabel']}' value='{f['value'][:30]}' required={f['required']}")

        # Print visible selects
        print(f"\n  VISIBLE SELECTS:")
        for s in step1["selects"]:
            if s["visible"]:
                print(f"    name={s['name']} aria-label='{s['ariaLabel']}' options={s['options'][:5]}")

        # Print visible radios
        print(f"\n  VISIBLE RADIOS:")
        for r in step1["radios"]:
            if r["visible"]:
                print(f"    name={r['name']} value={r['value']} label='{r['labelText']}' checked={r['checked']}")

        # Print visible labels
        print(f"\n  VISIBLE LABELS:")
        for l in step1["labels"]:
            if l["visible"]:
                print(f"    '{l['text'][:80]}' for={l['for']}")

        # Print divs with role=group
        print(f"\n  DIVS WITH ROLE=GROUP:")
        for d in step1["divs_with_role"]:
            if d["visible"]:
                print(f"    label='{d['labelText']}' inputs={d['inputCount']} class={d['class'][:60]}")

        # Print modal text snippet
        if step1["page_text_snippet"]:
            print(f"\n  MODAL TEXT (first 500 chars):")
            print(f"    {step1['page_text_snippet'][:500]}")

        # Step 2-5: Click Next/Review/Submit and extract fields at each step
        for step_num in range(2, 7):
            print(f"\n{'='*50}")
            print(f"[{step_num}] Clicking progression button...")

            # Try Submit > Review > Next
            clicked = None
            for btn_text in ["Submit application", "Review", "Next"]:
                try:
                    btn = page.locator(f"div.artdeco-modal button:has-text('{btn_text}'), div[role='dialog'] button:has-text('{btn_text}')").first
                    if await btn.is_visible(timeout=1500):
                        await btn.click()
                        clicked = btn_text
                        print(f"  Clicked: '{btn_text}'")
                        break
                except Exception:
                    continue

            if not clicked:
                # Try any button in modal
                try:
                    btn = page.locator("div.artdeco-modal button, div[role='dialog'] button").first
                    if await btn.is_visible(timeout=1000):
                        btn_text_val = (await btn.inner_text()).strip()
                        print(f"  Fallback click: '{btn_text_val}'")
                except Exception:
                    pass

                print("  No progression button found, stopping.")
                break

            await asyncio.sleep(3)  # Wait for next step to render

            step_data = await extract_all_fields(page, f"after_click_{clicked.replace(' ', '_')}_{step_num}")
            all_steps.append(step_data)

            vis_inputs = sum(1 for f in step_data["text_inputs"] if f["visible"])
            vis_selects = sum(1 for s in step_data["selects"] if s["visible"])
            vis_radios = sum(1 for r in step_data["radios"] if r["visible"])
            vis_labels = sum(1 for l in step_data["labels"] if l["visible"])

            print(f"  Text inputs: {vis_inputs} | Selects: {vis_selects} | Radios: {vis_radios} | Labels: {vis_labels}")

            # Print visible buttons
            print(f"  BUTTONS:")
            for b in step_data["buttons"]:
                if b["visible"]:
                    print(f"    [{b['text'][:60]}] disabled={b['disabled']}")

            # Print visible inputs
            if vis_inputs:
                print(f"  TEXT INPUTS:")
                for f in step_data["text_inputs"]:
                    if f["visible"]:
                        print(f"    name={f['name']} aria='{f['ariaLabel']}' value='{f['value'][:30]}' placeholder='{f['placeholder'][:30]}'")

            if vis_selects:
                print(f"  SELECTS:")
                for s in step_data["selects"]:
                    if s["visible"]:
                        print(f"    aria='{s['ariaLabel']}' opts={s['options'][:5]}")

            if vis_radios:
                print(f"  RADIOS:")
                for r in step_data["radios"]:
                    if r["visible"]:
                        print(f"    name={r['name']} label='{r['labelText']}' checked={r['checked']}")

            # Print modal text
            if step_data["page_text_snippet"]:
                print(f"  MODAL TEXT (first 300 chars):")
                print(f"    {step_data['page_text_snippet'][:300]}")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

    # Save results
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_steps, f, indent=2, ensure_ascii=False)
    print(f"\n\nResults saved to: {RESULTS_FILE}")

    # Don't close browser so user can inspect
    print("\nBrowser left open for inspection. Press Ctrl+C to close.")
    try:
        await asyncio.sleep(300)
    except KeyboardInterrupt:
        pass

    await context.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import logging
import sys
from browser import NaukriBrowser

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])

JOB_URL = "https://www.naukri.com/job-listings-devops-engineer-3-qikrecruit-bengaluru-6-to-11-years-210426019310?src=simJobDeskACP"


async def main():
    print("=== Debug: Deep Drawer Inspection ===\n")
    browser = NaukriBrowser()

    try:
        await browser.launch()
        await browser.wait_for_login()
        page = browser.page

        print(f"Opening: {JOB_URL}\n")
        await page.goto(JOB_URL)
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(3)
        await page.evaluate("window.scrollTo(0, 300)")
        await asyncio.sleep(1)

        # Force click apply
        locator = page.locator('button:has-text("Apply")').first
        btn_text = (await locator.inner_text()).strip()
        print(f"Button text: '{btn_text}'")
        print("Clicking Apply...\n")
        await locator.click()
        await asyncio.sleep(4)

        # PAUSE
        input(">>> PAUSED: Verify popup is open. Press ENTER...")

        # Dump the full HTML of the Drawer
        print("\n\n=== DRAWER INNER HTML ===")
        drawer = page.locator('[class*="Drawer"]').first
        if await drawer.is_visible(timeout=3000):
            html = await drawer.evaluate("el => el.innerHTML")
            print(html[:3000])
        else:
            print("Drawer not visible!")

        # Check for contenteditable elements
        print("\n\n=== CONTENTEDITABLE ELEMENTS ===")
        editables = await page.evaluate("""() => {
            const els = document.querySelectorAll('[contenteditable="true"], [contenteditable=""]');
            return Array.from(els).map(el => ({
                tag: el.tagName,
                class: el.className?.substring?.(0, 100) || '',
                text: el.textContent?.substring(0, 100) || '',
                html: el.outerHTML?.substring(0, 200) || '',
            }));
        }""")
        for el in editables:
            print(f"  <{el['tag']} class='{el['class']}'> text='{el['text']}'")
            print(f"    HTML: {el['html']}")

        # Check for ALL inputs/textareas including hidden ones inside drawer
        print("\n\n=== ALL INPUTS IN DRAWER (including hidden) ===")
        drawer_inputs = await page.evaluate("""() => {
            const drawer = document.querySelector('[class*="Drawer"]') || document.querySelector('[class*="chatbot"]');
            if (!drawer) return [];
            const els = drawer.querySelectorAll('input, textarea, select, [contenteditable], [role="textbox"]');
            return Array.from(els).map(el => ({
                tag: el.tagName,
                type: el.type || '',
                name: el.name || '',
                class: el.className?.substring?.(0, 100) || '',
                placeholder: el.placeholder || '',
                contenteditable: el.contentEditable || '',
                role: el.getAttribute('role') || '',
                display: getComputedStyle(el).display,
                visibility: getComputedStyle(el).visibility,
                html: el.outerHTML?.substring(0, 300) || '',
            }));
        }""")
        print(f"  Found {len(drawer_inputs)} elements:")
        for el in drawer_inputs:
            print(f"\n  <{el['tag']} type='{el['type']}' name='{el['name']}' "
                  f"placeholder='{el['placeholder']}' role='{el['role']}' "
                  f"contenteditable='{el['contenteditable']}' "
                  f"display='{el['display']}' visibility='{el['visibility']}'>")
            print(f"    class: {el['class']}")
            print(f"    HTML: {el['html']}")

        # Check for buttons in the drawer
        print("\n\n=== BUTTONS IN DRAWER ===")
        drawer_btns = await page.evaluate("""() => {
            const drawer = document.querySelector('[class*="Drawer"]') || document.querySelector('[class*="chatbot"]');
            if (!drawer) return [];
            const btns = drawer.querySelectorAll('button, [role="button"], a[class*="btn"]');
            return Array.from(btns).map(el => ({
                tag: el.tagName,
                text: el.textContent?.trim()?.substring(0, 80) || '',
                class: el.className?.substring?.(0, 100) || '',
                disabled: el.disabled || false,
            }));
        }""")
        for btn in drawer_btns:
            print(f"  <{btn['tag']}> text='{btn['text']}' disabled={btn['disabled']}")
            print(f"    class: {btn['class']}")

        print("\n\n=== DONE ===")
        input("\n>>> Press ENTER to close...")

    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        try:
            await browser.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass

import asyncio
import logging
import sys
from browser import NaukriBrowser
from naukri_agent import JobApplicant

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

JOB_URL = "https://www.naukri.com/job-listings-devops-engineer-3-qikrecruit-bengaluru-6-to-11-years-210426019310?src=simJobDeskACP"


async def main():
    print("=== Test: Apply with Questions ===\n")
    browser = NaukriBrowser()

    try:
        await browser.launch()
        await browser.wait_for_login()
        page = browser.page
        applicant = JobApplicant(page)

        job = {
            "title": "DevOps Engineer",
            "company": "Qikrecruit",
            "url": JOB_URL,
            "location": "Bengaluru",
            "salary": "N/A",
        }

        print(f"Applying to: {job['title']} @ {job['company']}")
        print(f"URL: {JOB_URL}")
        print("-" * 60)

        # Navigate and click apply (bypass already-applied check for testing)
        await page.goto(JOB_URL)
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(3)
        await page.evaluate("window.scrollTo(0, 300)")
        await asyncio.sleep(1)

        locator = page.locator('button:has-text("Apply")').first
        btn_text = (await locator.inner_text()).strip()
        print(f"Button: '{btn_text}'")
        print("Clicking Apply...")
        await locator.click()
        await asyncio.sleep(4)

        print("\n--- Handling Application Flow ---")
        await applicant._handle_application_flow()

        if applicant.applied_jobs:
            print("\n✓ Application completed!")
        else:
            print("\nApplication flow ended (may need more iterations)")

        print("\nKeeping browser open for 15 seconds...")
        await asyncio.sleep(15)

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

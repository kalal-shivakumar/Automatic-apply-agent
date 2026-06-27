"""Apply to a specific job, answer all questions, verify each step."""
import asyncio
import logging
import sys
import random
from browser import NaukriBrowser
from naukri_agent import JobApplicant, human_delay
from ai_answerer import QuestionAnswerer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

JOB_URL = "https://www.naukri.com/job-listings-microsoft-ai-azure-architect-hucon-solutions-noida-bengaluru-15-to-22-years-170126004317?src=simJobDeskACP"


async def verify_answer_submitted(page, answer_text: str) -> bool:
    """Check if our answer appears in the chatbot as a user message."""
    try:
        user_msgs = page.locator('li.userItem .userMsg span')
        count = await user_msgs.count()
        if count > 0:
            last_msg = await user_msgs.last.text_content()
            if last_msg and answer_text.lower()[:20] in last_msg.strip().lower():
                return True
    except Exception:
        pass
    return False


async def main():
    print("=" * 70)
    print("  APPLY TO SPECIFIC JOB WITH Q&A VERIFICATION")
    print("=" * 70)
    print(f"\nJob URL: {JOB_URL[:80]}...")

    browser = NaukriBrowser()
    try:
        await browser.launch()
        await browser.wait_for_login()
        page = browser.page
        applicant = JobApplicant(page)

        job = {
            "title": "Microsoft AI Azure Architect",
            "company": "Hucon Solutions",
            "url": JOB_URL,
            "location": "Noida/Bengaluru",
            "salary": "N/A",
        }

        print(f"\nApplying to: {job['title']} @ {job['company']}")
        print("-" * 70)

        # Navigate to job
        await page.goto(JOB_URL)
        await page.wait_for_load_state("networkidle")
        await human_delay(2.0, 4.0)
        await page.evaluate("window.scrollTo(0, 300)")
        await human_delay(1.0, 2.0)

        # Extract full JD and score the match
        full_jd = await applicant._extract_full_jd()
        page_details = await applicant._extract_job_details_from_page()
        combined_skills = page_details.get("page_skills", "")

        if full_jd:
            print(f"\n  Full JD extracted: {len(full_jd)} chars")
            print(f"  JD preview: {full_jd[:300]}...")
        else:
            print("  WARNING: Could not extract full JD from page")

        # Score match
        ai = QuestionAnswerer()
        match_score, match_reason = ai.match_job_score(
            job_title=job["title"],
            company=job["company"],
            location=job.get("location", ""),
            salary=job.get("salary", ""),
            experience="",
            skills=combined_skills,
            full_description=full_jd,
        )
        print(f"\n  Match Score: {match_score}% — {match_reason}")

        if match_score < 60:
            print(f"  ✗ Skipping (below 60% threshold)")
            return
        print(f"  ✓ Good match — proceeding to apply")

        # Find and check Apply button
        apply_btn = page.locator('button:has-text("Apply")').first
        try:
            visible = await apply_btn.is_visible(timeout=3000)
        except Exception:
            visible = False

        if not visible:
            print("ERROR: No Apply button found!")
            return

        btn_text = (await apply_btn.inner_text()).strip()
        print(f"Apply button: '{btn_text}'")

        if btn_text.lower().endswith("applied"):
            print("Job shows as applied — trying to re-open chatbot anyway...")
            try:
                await apply_btn.click(force=True)
                await human_delay(3.0, 5.0)
            except Exception:
                print("Could not click Apply button.")
                return
        else:
            try:
                enabled = await apply_btn.is_enabled(timeout=1000)
                if not enabled:
                    print("Apply button is disabled!")
                    return
            except Exception:
                pass

            # Click Apply
            print("\nClicking Apply...")
            await human_delay(0.5, 1.5)
            await apply_btn.click()
            await human_delay(3.0, 5.0)

        # Check if page redirected (external apply)
        if "job-listings" not in page.url:
            print(f"Redirected to: {page.url[:80]}")
            print("This is an external apply job.")
            return

        # Check for Cancel/Proceed modal and dismiss it
        try:
            cancel_btn = page.locator('button:has-text("Cancel")').first
            if await cancel_btn.is_visible(timeout=2000):
                print("Found Cancel/Proceed modal — clicking Cancel to dismiss...")
                await cancel_btn.click()
                await human_delay(1.0, 2.0)
        except Exception:
            pass

        # Now handle the Q&A flow with detailed verification
        print("\n--- ANSWERING QUESTIONS ---\n")
        questions_answered = 0
        max_iterations = 30

        for iteration in range(max_iterations):
            await human_delay(1.5, 3.0)

            # Check for success
            for success_text in ["applied successfully", "Application Submitted",
                                 "Successfully Applied"]:
                success = page.locator(f'text="{success_text}"')
                try:
                    if await success.count() > 0 and await success.first.is_visible(timeout=500):
                        print(f"\n{'='*70}")
                        print(f"  ✓ APPLICATION SUBMITTED SUCCESSFULLY!")
                        print(f"  Questions answered: {questions_answered}")
                        print(f"{'='*70}")
                        applicant.applied_jobs.append({
                            "title": job["title"],
                            "company": job["company"],
                            "location": job.get("location", ""),
                            "salary": job.get("salary", ""),
                            "status": "Applied",
                        })
                        return
                except Exception:
                    pass

            # Try chatbot step
            handled = await applicant._handle_chatbot_step()
            if handled:
                questions_answered += 1
                print(f"  [✓ Q{questions_answered} answered]")
                continue

            # Try form step
            handled = await applicant._handle_form_step()
            if handled:
                questions_answered += 1
                print(f"  [✓ Form Q{questions_answered} answered]")
                continue

            # Try action button
            handled = await applicant._click_action_button()
            if handled:
                continue

            # Nothing to interact with - check if chatbot is still open
            chatbot = page.locator('.chatbot_Drawer, [class*="chatbot"]')
            try:
                if await chatbot.count() > 0 and await chatbot.first.is_visible(timeout=500):
                    # Chatbot is open but no question detected - might be loading
                    if iteration < max_iterations - 1:
                        continue
            except Exception:
                pass

            # Really nothing left
            break

        # Final check
        print(f"\n--- FINAL STATUS ---")
        print(f"Questions answered: {questions_answered}")

        # Check if we got through
        for success_text in ["applied successfully", "Application Submitted",
                             "Successfully Applied", "Thank you"]:
            try:
                el = page.locator(f'text="{success_text}"')
                if await el.count() > 0:
                    print(f"✓ Found success text: '{success_text}'")
                    return
            except Exception:
                pass

        # Check if chatbot is still showing
        try:
            chatbot = page.locator('.chatbot_Drawer')
            if await chatbot.count() > 0 and await chatbot.first.is_visible(timeout=500):
                print("⚠ Chatbot still open - may need more answers")
                # Dump remaining question
                bot_msgs = page.locator('li.botItem .botMsg span')
                count = await bot_msgs.count()
                if count > 0:
                    last_q = await bot_msgs.last.text_content()
                    print(f"  Last question: {last_q}")
            else:
                print("✓ Chatbot closed (likely applied)")
        except Exception:
            pass

        print(f"\nApplied jobs: {applicant.applied_jobs}")

        await human_delay(3.0, 5.0)

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

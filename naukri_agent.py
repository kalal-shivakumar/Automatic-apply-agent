import asyncio
import logging
import json
import random
from playwright.async_api import Page, Response
from config import Config
from ai_answerer import QuestionAnswerer

logger = logging.getLogger(__name__)


async def human_delay(min_s: float = 1.0, max_s: float = 3.0):
    """Random delay to mimic human behavior and avoid bot detection."""
    delay = random.uniform(min_s, max_s)
    await asyncio.sleep(delay)


class JobSearcher:
    """Searches for jobs using Naukri's internal API (intercepted via browser)."""

    def __init__(self, page: Page):
        self.page = page
        self.job_data = None

    async def search_jobs(self, page_no: int = 1, keywords: str = None,
                          location: str = None) -> list[dict]:
        """Search for jobs and capture API response with job details."""
        self.job_data = None

        async def capture_response(response: Response):
            if "jobapi/v3/search" in response.url and response.status == 200:
                try:
                    body = await response.json()
                    if "jobDetails" in body:
                        self.job_data = body
                except Exception:
                    pass

        self.page.on("response", capture_response)

        kw = keywords or Config.JOB_KEYWORDS
        loc = (location or Config.JOB_LOCATION).lower()
        experience = Config.EXPERIENCE_YEARS

        # Use Naukri's keyword search URL format
        keyword_slug = kw.replace(" ", "-").lower()
        url = (
            f"https://www.naukri.com/{keyword_slug}-jobs-in-{loc}"
            f"?k={kw.replace(' ', '%20')}&experience={experience}"
            f"&jobAge=1"  # Posted in last 1 day only
        )
        if page_no > 1:
            url += f"&pageNo={page_no}"

        logger.info(f"Searching: {url}")
        await self.page.goto(url)
        await self.page.wait_for_load_state("networkidle")
        await human_delay(3.0, 6.0)

        # Scroll to trigger lazy loading
        for i in range(3):
            await self.page.evaluate(f"window.scrollTo(0, {(i + 1) * 600})")
            await human_delay(0.8, 2.0)

        self.page.remove_listener("response", capture_response)

        if not self.job_data:
            logger.warning("No job API response captured")
            return []

        jobs = []
        for jd in self.job_data.get("jobDetails", []):
            job = {
                "title": jd.get("title", ""),
                "company": jd.get("companyName", ""),
                "jobId": jd.get("jobId", ""),
                "url": "https://www.naukri.com" + jd.get("jdURL", ""),
                "description": jd.get("jobDescription", ""),
                "skills": jd.get("tagsAndSkills", ""),
                "experience": "",
                "salary": "",
                "location": "",
            }
            for ph in jd.get("placeholders", []):
                if ph["type"] == "experience":
                    job["experience"] = ph["label"]
                elif ph["type"] == "salary":
                    job["salary"] = ph["label"]
                elif ph["type"] == "location":
                    job["location"] = ph["label"]
            jobs.append(job)

        total = self.job_data.get("noOfJobs", 0)
        logger.info(f"Found {len(jobs)} jobs on page {page_no} (total: {total})")
        return jobs


class JobApplicant:
    """Applies to jobs on Naukri.com with AI-powered questionnaire answering."""

    def __init__(self, page: Page):
        self.page = page
        self.ai = QuestionAnswerer()
        self.applied_jobs = []
        self._last_question = None
        self._stuck_count = 0
        self.last_match_score = 0
        self.last_match_reason = ""
        self.last_skip_reason = ""

    async def _extract_full_jd(self) -> str:
        """Extract the complete job description from the current job page."""
        try:
            # Scroll down to ensure lazy-loaded content is rendered
            for scroll_y in [500, 1000, 1500, 2000]:
                await self.page.evaluate(f"window.scrollTo(0, {scroll_y})")
                await human_delay(0.3, 0.6)
            # Scroll back to top
            await self.page.evaluate("window.scrollTo(0, 0)")
            await human_delay(0.5, 1.0)

            # Method 1: Try structured data (JSON-LD) — most reliable, contains full JD
            try:
                jd_text = await self.page.evaluate("""() => {
                    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                    for (const s of scripts) {
                        try {
                            const data = JSON.parse(s.textContent);
                            if (data.description) return data.description;
                            if (data['@graph']) {
                                for (const item of data['@graph']) {
                                    if (item.description) return item.description;
                                }
                            }
                        } catch(e) {}
                    }
                    return '';
                }""")
                if jd_text and len(jd_text.strip()) > 100:
                    # Strip HTML tags if present
                    import re
                    clean = re.sub(r'<[^>]+>', ' ', jd_text)
                    clean = re.sub(r'\s+', ' ', clean).strip()
                    logger.info(f"JD extracted from JSON-LD: {len(clean)} chars")
                    return clean
            except Exception:
                pass

            # Method 2: Try Naukri-specific selectors (CSS module class patterns)
            jd_selectors = [
                'section[class*="job-desc"]',
                'div[class*="job-desc"]',
                'section[class*="JDC"]',
                'div[class*="JDC"]',
                'div[class*="dang-inner-html"]',
                'div[class*="jobDesc"]',
                'div[class*="job_desc"]',
                '#job_description',
                '.job-description',
                'div[class*="styles_JDC"]',
                'section[class*="styles_job-desc"]',
                'div[class*="jd-desc"]',
                'div[class*="other-details"]',
            ]
            for sel in jd_selectors:
                try:
                    el = self.page.locator(sel).first
                    if await el.is_visible(timeout=800):
                        text = await el.inner_text()
                        if text and len(text.strip()) > 50:
                            logger.info(f"JD extracted via '{sel}': {len(text.strip())} chars")
                            return text.strip()
                except Exception:
                    continue

            # Method 3: JavaScript — find the largest text block that looks like a JD
            try:
                jd_text = await self.page.evaluate("""() => {
                    // Find all sections/divs that might contain JD text
                    const candidates = document.querySelectorAll('section, div, article');
                    let best = '';
                    let bestLen = 0;
                    for (const el of candidates) {
                        const text = el.innerText || '';
                        // JD blocks typically contain keywords like 'experience', 'skills', 'requirements'
                        const lc = text.toLowerCase();
                        const hasJDKeywords = (
                            (lc.includes('experience') || lc.includes('requirement') || 
                             lc.includes('responsibilities') || lc.includes('qualification') ||
                             lc.includes('job description') || lc.includes('role') ||
                             lc.includes('skills')) &&
                            text.length > 200 && text.length < 15000
                        );
                        if (hasJDKeywords && text.length > bestLen) {
                            // Avoid nav/header/footer blocks
                            const tag = el.tagName.toLowerCase();
                            const cls = (el.className || '').toLowerCase();
                            if (cls.includes('nav') || cls.includes('header') || cls.includes('footer') ||
                                cls.includes('chatbot') || cls.includes('sidebar') || cls.includes('recommend')) {
                                continue;
                            }
                            best = text;
                            bestLen = text.length;
                        }
                    }
                    return best;
                }""")
                if jd_text and len(jd_text.strip()) > 100:
                    logger.info(f"JD extracted via JS heuristic: {len(jd_text.strip())} chars")
                    return jd_text.strip()[:6000]
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"JD extraction error: {e}")
        return ""

    async def _extract_job_details_from_page(self) -> dict:
        """Extract additional job details (skills, salary, experience) from the page."""
        details = {"page_skills": "", "page_salary": "", "page_experience": "", "page_location": ""}
        try:
            # Extract key-value highlights from the job page
            highlight_text = await self.page.evaluate("""() => {
                const result = {};
                // Look for highlight items
                const items = document.querySelectorAll('[class*="highlight"] li, [class*="detail"] li, [class*="info"] li');
                items.forEach(item => {
                    result[item.className || 'info'] = item.textContent.trim();
                });
                // Look for key skills section
                const skillEls = document.querySelectorAll('[class*="skill"] a, [class*="skill"] span, [class*="tag"] a, [class*="tag"] span, [class*="chip"]');
                const skills = [];
                skillEls.forEach(el => {
                    const t = el.textContent.trim();
                    if (t && t.length < 50) skills.push(t);
                });
                result.skills = [...new Set(skills)].join(', ');
                return JSON.stringify(result);
            }""")
            import json as _json
            parsed = _json.loads(highlight_text)
            details["page_skills"] = parsed.get("skills", "")
        except Exception:
            pass
        return details

    async def apply_to_job(self, job: dict, min_match_pct: int = 60) -> bool:
        """Open a job page, extract full JD, check match, then apply."""
        self._last_question = None
        self._stuck_count = 0
        self.last_match_score = 0
        self.last_match_reason = ""
        self.last_skip_reason = ""
        try:
            logger.info(f"Opening: {job['title']} at {job['company']}")

            await self.page.goto(job["url"])
            await self.page.wait_for_load_state("networkidle")
            await human_delay(2.0, 5.0)

            # Scroll down to load full page content
            await self.page.evaluate("window.scrollTo(0, 300)")
            await human_delay(1.0, 2.5)

            # Extract full job description from the page
            full_jd = await self._extract_full_jd()
            page_details = await self._extract_job_details_from_page()

            # Combine API description with page-scraped JD
            combined_jd = full_jd or job.get("description", "")
            combined_skills = job.get("skills", "")
            if page_details.get("page_skills"):
                combined_skills += ", " + page_details["page_skills"]

            # Score the job match
            match_score, match_reason = self.ai.match_job_score(
                job_title=job.get("title", ""),
                company=job.get("company", ""),
                location=job.get("location", ""),
                salary=job.get("salary", ""),
                experience=job.get("experience", ""),
                skills=combined_skills,
                full_description=combined_jd,
            )

            print(f"  Match Score: {match_score}% — {match_reason}")
            logger.info(f"Match: {match_score}% for {job['title']} @ {job['company']} — {match_reason}")

            self.last_match_score = match_score
            self.last_match_reason = match_reason

            if match_score < min_match_pct:
                print(f"  ✗ Skipping (below {min_match_pct}% threshold)")
                logger.info(f"Skipped: {job['title']} @ {job['company']} ({match_score}% < {min_match_pct}%)")
                self.last_skip_reason = "low_score"
                return False

            print(f"  ✓ Good match — proceeding to apply")

            # Find the apply button using Playwright locators
            apply_btn = None
            for selector in [
                'button:has-text("Apply")',
                'button:has-text("Easy Apply")',
                'button:has-text("Apply on company site")',
                'button[class*="apply"]',
                '#apply-button',
            ]:
                try:
                    locator = self.page.locator(selector).first
                    if await locator.is_visible(timeout=2000):
                        btn_text = (await locator.inner_text()).strip().lower()
                        # Parse the primary button text (first line) vs counter sub-text
                        # e.g. "Apply\n520 applied" → primary="apply", sub="520 applied"
                        # vs "Applied" → primary="applied" (actually already applied)
                        lines = [l.strip() for l in btn_text.split('\n') if l.strip()]
                        primary_text = lines[0] if lines else btn_text
                        # Only skip if the PRIMARY text is "applied" (not a sub-counter)
                        is_already_applied = (
                            primary_text == "applied" or
                            "already applied" in btn_text
                        )
                        if is_already_applied:
                            logger.info(f"Already applied to this job (button: '{btn_text}')")
                            self.last_skip_reason = "already_applied"
                            return False
                        # Skip disabled buttons to avoid 30s timeout
                        if not await locator.is_enabled(timeout=1000):
                            logger.info("Apply button is disabled, skipping")
                            self.last_skip_reason = "button_disabled"
                            return False
                        apply_btn = locator
                        break
                except Exception:
                    continue

            if not apply_btn:
                logger.info("No apply button found, skipping")
                self.last_skip_reason = "no_button"
                return False

            # Click apply
            await human_delay(0.5, 1.5)
            await apply_btn.click()
            await human_delay(2.5, 5.0)

            # Handle chatbot/questionnaire if it appears
            await self._handle_application_flow()

            self.applied_jobs.append({
                "title": job["title"],
                "company": job["company"],
                "location": job.get("location", ""),
                "salary": job.get("salary", ""),
                "status": "Applied",
            })
            logger.info(f"Applied! Total: {len(self.applied_jobs)}")
            return True

        except Exception as e:
            logger.error(f"Error applying: {e}")
            return False

    async def _handle_application_flow(self):
        """Handle the entire application flow including questionnaires."""
        for iteration in range(25):
            await human_delay(1.5, 3.5)

            # Check if application was successful
            try:
                for success_text in ["applied successfully", "Application Submitted",
                                     "Successfully Applied"]:
                    success = self.page.locator(f'text="{success_text}"')
                    if await success.count() > 0 and await success.first.is_visible(timeout=500):
                        print("  ✓ Application submitted successfully!")
                        logger.info("Application submitted successfully!")
                        return
            except Exception:
                pass

            # Handle chatbot questions
            if await self._handle_chatbot_step():
                continue

            # Handle form questions
            if await self._handle_form_step():
                continue

            # Try to click submit/continue
            if await self._click_action_button():
                continue

            # Nothing to interact with
            break

    async def _handle_chatbot_step(self) -> bool:
        """Handle one chatbot question step.
        
        Naukri chatbot structure (from DOM inspection):
        - Container: div.chatbot_Drawer
        - Bot messages: li.botItem > div.botMsg.msg > div > span
        - User messages: li.userItem > div.userMsg.msg > span
        - Text input: div[contenteditable="true"].textArea
        - Save button: div.sendMsg (NOT a <button>!)
        - Radio inputs: input[type="radio"] with adjacent labels
        """
        try:
            # Get the LAST bot question from the chatbot
            # Naukri chatbot uses: li.botItem .botMsg span
            question_text = None

            # Method 1: Direct selector for Naukri's chatbot bot messages
            bot_msgs = self.page.locator('li.botItem .botMsg span, li.botItem .botMsg div > span')
            bot_count = await bot_msgs.count()
            if bot_count > 0:
                # Get the last bot message
                last_msg = await bot_msgs.last.text_content()
                if last_msg and last_msg.strip():
                    text = last_msg.strip()
                    # Skip intro/greeting messages
                    if ('thank you for showing interest' not in text.lower() and
                        'kindly answer' not in text.lower() and
                        len(text) > 5):
                        question_text = text

            # Method 2: Fallback to broader chatbot selectors
            if not question_text:
                for sel in ['[class*="chatbot"] [class*="msg"]', '[class*="chatbot"]',
                            '[class*="Chatbot"]', '[class*="quest"]']:
                    try:
                        els = self.page.locator(sel)
                        if await els.count() > 0:
                            text = await els.last.inner_text()
                            if text and text.strip():
                                lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
                                skip_words = {'save', 'send', 'submit', 'skip', 'cancel',
                                              'proceed', 'skip this question'}
                                filtered = []
                                for line in lines:
                                    if line.lower() in skip_words:
                                        continue
                                    if 'thank you for showing interest' in line.lower():
                                        continue
                                    if 'kindly answer' in line.lower():
                                        continue
                                    if 'quick apply' in line.lower():
                                        continue
                                    filtered.append(line)
                                if filtered:
                                    question_text = ' '.join(filtered[-3:])  # Last 3 lines max
                                    break
                    except Exception:
                        continue

            if not question_text:
                return False

            # Stuck detection: if same question appears 3+ times, skip it
            if question_text == self._last_question:
                self._stuck_count += 1
                if self._stuck_count >= 3:
                    logger.warning(f"Stuck on question (3x): {question_text[:60]}")
                    # Try clicking Skip if available
                    try:
                        skip = self.page.locator('text="Skip this question"').first
                        if await skip.is_visible(timeout=1000):
                            await skip.click()
                            logger.info("Clicked 'Skip this question'")
                            await human_delay(1.0, 2.0)
                            self._stuck_count = 0
                            return True
                    except Exception:
                        pass
                    self._stuck_count = 0
                    return False
            else:
                self._last_question = question_text
                self._stuck_count = 0

            print(f"  \n  ┌─ QUESTION: {question_text.strip()[:120]}")
            logger.info(f"Chatbot Q: {question_text.strip()[:80]}")

            # PRIORITY 1: Contenteditable text input (Naukri's actual input)
            for sel in ['div[contenteditable="true"].textArea',
                        'div[contenteditable="true"][data-placeholder*="message"]',
                        '[id*="InputBox"][contenteditable="true"]',
                        'div[contenteditable="true"][data-placeholder]']:
                try:
                    inp = self.page.locator(sel).first
                    if await inp.is_visible(timeout=1500):
                        answer = self.ai.answer_question(question_text.strip())
                        print(f"  └─ AI ANSWER: {answer}")
                        logger.info(f"AI typed: {answer}")

                        await inp.click()
                        await human_delay(0.3, 0.8)
                        await self.page.keyboard.press("Control+a")
                        await self.page.keyboard.press("Backspace")
                        await self.page.keyboard.type(answer, delay=random.randint(25, 60))
                        await human_delay(0.5, 1.5)

                        # Click Save (div.sendMsg) or press Enter
                        await self._click_save_button()
                        return True
                except Exception:
                    continue

            # PRIORITY 2: Regular input/textarea
            for sel in ['[class*="chatbot"] input[type="text"]',
                        '[class*="chatbot"] textarea',
                        '.chatbot_Drawer input[type="text"]',
                        '.chatbot_Drawer textarea']:
                try:
                    inp = self.page.locator(sel).first
                    if await inp.is_visible(timeout=1000):
                        answer = self.ai.answer_question(question_text.strip())
                        print(f"  └─ AI ANSWER: {answer}")
                        logger.info(f"AI typed: {answer}")
                        await inp.fill(answer)
                        await self._click_save_button()
                        return True
                except Exception:
                    continue

            # PRIORITY 3: Radio buttons inside chatbot drawer
            radio_handled = False
            try:
                for container_sel in ['.chatbot_Drawer', '[class*="chatbot"]',
                                      '[class*="Drawer"]']:
                    radios = self.page.locator(f'{container_sel} input[type="radio"]')
                    radio_count = await radios.count()
                    if radio_count == 0:
                        continue

                    # Collect options from labels
                    labels = self.page.locator(
                        f'{container_sel} input[type="radio"] + label, '
                        f'{container_sel} input[type="radio"] ~ label, '
                        f'{container_sel} label:has(input[type="radio"])'
                    )
                    opts = []
                    label_count = await labels.count()
                    if label_count > 0:
                        for i in range(label_count):
                            t = await labels.nth(i).text_content()
                            if t and t.strip():
                                opts.append(t.strip())
                    if not opts:
                        for i in range(radio_count):
                            parent_text = await radios.nth(i).evaluate(
                                "el => el.parentElement?.textContent?.trim() || ''")
                            if parent_text:
                                opts.append(parent_text)

                    if not opts:
                        continue

                    print(f"  │  Radio options: {opts}")
                    answer = self.ai.answer_question(question_text.strip(), opts)
                    print(f"  └─ AI ANSWER: {answer}")
                    logger.info(f"AI picked radio: {answer}")

                    # Click matching label
                    clicked = False
                    for i in range(label_count):
                        t = (await labels.nth(i).text_content() or "").strip()
                        if t.lower() == answer.lower():
                            await labels.nth(i).click()
                            clicked = True
                            break
                    if not clicked:
                        for i in range(label_count):
                            t = (await labels.nth(i).text_content() or "").strip()
                            if answer.lower() in t.lower():
                                await labels.nth(i).click()
                                clicked = True
                                break
                    if not clicked:
                        # Click the radio input directly with force
                        await radios.first.click(force=True)

                    await human_delay(0.5, 1.5)
                    # Click Save (div.sendMsg) after selecting radio
                    await self._click_save_button()
                    radio_handled = True
                    break
            except Exception as e:
                logger.debug(f"Radio error: {e}")

            if radio_handled:
                return True

            # PRIORITY 3.5: Checkboxes inside chatbot (e.g., city selection)
            checkbox_handled = False
            try:
                for container_sel in ['.chatbot_Drawer', '[class*="chatbot"]', '[class*="Drawer"]']:
                    checkboxes = self.page.locator(f'{container_sel} input[type="checkbox"]')
                    cb_count = await checkboxes.count()
                    if cb_count == 0:
                        continue

                    # Collect options from labels
                    opts = []
                    label_elements = []
                    for i in range(cb_count):
                        cb = checkboxes.nth(i)
                        # Try to find associated label element
                        label_text = await cb.evaluate("""el => {
                            if (el.id) {
                                const label = document.querySelector('label[for="' + el.id + '"]');
                                if (label) return label.textContent.trim();
                            }
                            const nextLabel = el.nextElementSibling;
                            if (nextLabel && nextLabel.tagName === 'LABEL') return nextLabel.textContent.trim();
                            const parentLabel = el.closest('label');
                            if (parentLabel) return parentLabel.textContent.trim();
                            return el.parentElement?.textContent?.trim() || '';
                        }""")
                        if label_text and label_text.lower() != 'skip this question':
                            opts.append(label_text)
                            label_elements.append(i)

                    if not opts:
                        continue

                    print(f"  │  Checkbox options: {opts}")
                    answer = self.ai.answer_question(question_text.strip(), opts)
                    print(f"  └─ AI ANSWER: {answer}")
                    logger.info(f"AI picked checkbox: {answer}")

                    # Click the matching checkbox - try label first, then input
                    clicked = False
                    for idx in label_elements:
                        cb = checkboxes.nth(idx)
                        label_text = await cb.evaluate("""el => {
                            if (el.id) {
                                const label = document.querySelector('label[for="' + el.id + '"]');
                                if (label) return label.textContent.trim();
                            }
                            const nextLabel = el.nextElementSibling;
                            if (nextLabel && nextLabel.tagName === 'LABEL') return nextLabel.textContent.trim();
                            const parentLabel = el.closest('label');
                            if (parentLabel) return parentLabel.textContent.trim();
                            return el.parentElement?.textContent?.trim() || '';
                        }""")
                        if label_text and answer.lower() in label_text.lower():
                            # Try clicking the label element first (more reliable)
                            try:
                                label_el = await cb.evaluate_handle("""el => {
                                    if (el.id) {
                                        const label = document.querySelector('label[for="' + el.id + '"]');
                                        if (label) return label;
                                    }
                                    const nextLabel = el.nextElementSibling;
                                    if (nextLabel && nextLabel.tagName === 'LABEL') return nextLabel;
                                    const parentLabel = el.closest('label');
                                    if (parentLabel) return parentLabel;
                                    return el.parentElement;
                                }""")
                                await label_el.click()
                                clicked = True
                                logger.info(f"Clicked checkbox label: {label_text}")
                            except Exception:
                                # Fallback: click the parent element or checkbox itself
                                try:
                                    parent = cb.locator('..')
                                    await parent.click()
                                    clicked = True
                                    logger.info(f"Clicked checkbox parent: {label_text}")
                                except Exception:
                                    await cb.click(force=True)
                                    clicked = True
                                    logger.info(f"Force-clicked checkbox: {label_text}")
                            break

                    if not clicked and label_elements:
                        # Click the first real option
                        cb = checkboxes.nth(label_elements[0])
                        try:
                            parent = cb.locator('..')
                            await parent.click()
                        except Exception:
                            await cb.click(force=True)
                        logger.info("Checked first checkbox (fallback)")

                    await human_delay(0.5, 1.5)
                    await self._click_save_button()
                    checkbox_handled = True
                    break
            except Exception as e:
                logger.warning(f"Checkbox error: {e}")

            if checkbox_handled:
                return True

            if checkbox_handled:
                return True

            # PRIORITY 4: Select/dropdown inside chatbot
            try:
                for container_sel in ['.chatbot_Drawer', '[class*="chatbot"]']:
                    selects = self.page.locator(f'{container_sel} select')
                    if await selects.count() > 0:
                        select = selects.first
                        opts = await select.locator('option').all_text_contents()
                        opts = [o.strip() for o in opts if o.strip() and o.strip() != 'Select']
                        if opts:
                            print(f"  │  Dropdown options: {opts}")
                            answer = self.ai.answer_question(question_text.strip(), opts)
                            print(f"  └─ AI ANSWER: {answer}")
                            logger.info(f"AI picked dropdown: {answer}")
                            try:
                                await select.select_option(label=answer)
                            except Exception:
                                # Try partial match
                                for opt in opts:
                                    if answer.lower() in opt.lower():
                                        await select.select_option(label=opt)
                                        break
                            await human_delay(0.5, 1.5)
                            await self._click_save_button()
                            return True
            except Exception:
                pass

            # PRIORITY 5: Clickable option elements (role="option", class*="choice")
            try:
                for container_sel in ['.chatbot_Drawer', '[class*="chatbot"]', '[class*="Drawer"]']:
                    clickables = self.page.locator(
                        f'{container_sel} [class*="option"], '
                        f'{container_sel} [class*="choice"], '
                        f'{container_sel} [role="option"], '
                        f'{container_sel} [role="radio"]'
                    )
                    click_count = await clickables.count()
                    if click_count > 0:
                        opts = []
                        for i in range(click_count):
                            t = (await clickables.nth(i).text_content() or "").strip()
                            if t and len(t) < 100:
                                opts.append(t)
                        if opts:
                            print(f"  │  Choice options: {opts}")
                            answer = self.ai.answer_question(question_text.strip(), opts)
                            print(f"  └─ AI ANSWER: {answer}")
                            for i in range(click_count):
                                t = (await clickables.nth(i).text_content() or "").strip()
                                if t.lower() == answer.lower():
                                    await clickables.nth(i).click()
                                    await human_delay(0.5, 1.5)
                                    return True
                            await clickables.first.click()
                            await human_delay(0.5, 1.5)
                            return True
            except Exception:
                pass

            # PRIORITY 6: Quick reply buttons
            nav_words = {'save', 'send', 'submit', 'cancel', 'proceed',
                         'skip', 'skip this question', 'quick apply',
                         'quick applyapplied', 'applied'}
            for sel in ['[class*="quickReply"] button', '[class*="chip"]']:
                try:
                    option_els = self.page.locator(sel)
                    count = await option_els.count()
                    if count > 0:
                        options = []
                        for i in range(count):
                            text = (await option_els.nth(i).text_content() or "").strip()
                            if text and text.lower() not in nav_words:
                                options.append(text)
                        if options:
                            print(f"  │  Quick reply: {options}")
                            answer = self.ai.answer_question(question_text.strip(), options)
                            print(f"  └─ AI ANSWER: {answer}")
                            for i in range(count):
                                text = (await option_els.nth(i).text_content() or "").strip()
                                if text.lower() == answer.lower():
                                    await option_els.nth(i).click()
                                    return True
                            await option_els.first.click()
                            return True
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"Chatbot error: {e}")

        return False

    async def _click_save_button(self):
        """Click the Save/Send button in the chatbot to proceed to next question.
        
        Naukri's chatbot uses <div class="sendMsg">Save</div> — NOT a <button>.
        """
        # Priority 1: The actual Naukri chatbot Save button (div.sendMsg)
        for sel in ['div.sendMsg', '.sendMsg', '[class*="sendMsg"]']:
            try:
                btn = self.page.locator(sel).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    logger.info("Clicked div.sendMsg (Save)")
                    await human_delay(1.0, 2.5)
                    return True
            except Exception:
                continue

        # Priority 2: Standard button elements with save/send/next text
        for btn_sel in [
            'button:has-text("Save")', 'button:has-text("Send")',
            'button:has-text("Next")', 'button:has-text("Submit")',
            'button:has-text("Proceed")', 'button:has-text("Continue")',
        ]:
            try:
                btn = self.page.locator(btn_sel).first
                if await btn.is_visible(timeout=800):
                    btn_text = (await btn.text_content() or "").strip().lower()
                    if btn_text in ('cancel', 'quick apply', 'quick applyapplied'):
                        continue
                    await btn.click()
                    logger.info(f"Clicked button: {btn_text}")
                    await human_delay(1.0, 2.5)
                    return True
            except Exception:
                continue

        # Priority 3: Any element with exact "Save" or "Send" text inside chatbot
        for container_sel in ['.chatbot_Drawer', '[class*="chatbot"]', '[class*="Drawer"]']:
            try:
                container = self.page.locator(container_sel).first
                if not await container.is_visible(timeout=500):
                    continue
                for text in ['Save', 'Send', 'Next', 'Submit']:
                    el = container.locator(f'text="{text}"').first
                    try:
                        if await el.is_visible(timeout=500):
                            await el.click()
                            logger.info(f"Clicked '{text}' in chatbot")
                            await human_delay(1.0, 2.5)
                            return True
                    except Exception:
                        continue
            except Exception:
                continue

        # Fallback: Enter key
        logger.info("No save button found, pressing Enter")
        await self.page.keyboard.press("Enter")
        await human_delay(1.0, 2.0)
        return False

    async def _handle_form_step(self) -> bool:
        """Handle form-style questions."""
        try:
            form_selectors = [
                '[class*="form"] label',
                '[class*="question"] label',
                'form label',
                '[class*="field"] label',
            ]

            handled_any = False
            for sel in form_selectors:
                try:
                    labels = self.page.locator(sel)
                    count = await labels.count()
                    if count == 0:
                        continue

                    for i in range(min(count, 10)):
                        label = labels.nth(i)
                        q_text = await label.text_content()
                        if not q_text or not q_text.strip():
                            continue

                        parent = label.locator('..')

                        # Select dropdown
                        select = parent.locator('select')
                        if await select.count() > 0:
                            opts = await select.first.locator('option').all_text_contents()
                            opts = [o.strip() for o in opts if o.strip()]
                            if opts:
                                answer = self.ai.answer_question(q_text.strip(), opts)
                                print(f"  \n  ┌─ QUESTION: {q_text.strip()[:120]}")
                                print(f"  │  Options: {opts}")
                                print(f"  └─ AI ANSWER: {answer}")
                                logger.info(f"Form select: {q_text.strip()[:50]} -> {answer}")
                                await select.first.select_option(label=answer)
                                handled_any = True
                            continue

                        # Text input
                        inp = parent.locator('input[type="text"], input[type="number"], textarea')
                        if await inp.count() > 0:
                            current = await inp.first.input_value()
                            if not current.strip():
                                answer = self.ai.answer_question(q_text.strip())
                                print(f"  \n  ┌─ QUESTION: {q_text.strip()[:120]}")
                                print(f"  └─ AI ANSWER: {answer}")
                                logger.info(f"Form input: {q_text.strip()[:50]} -> {answer}")
                                await inp.first.fill(answer)
                                handled_any = True
                            continue

                        # Radio buttons
                        radios = parent.locator('input[type="radio"]')
                        if await radios.count() > 0:
                            radio_labels = parent.locator('input[type="radio"] + label, input[type="radio"] ~ label')
                            opts = await radio_labels.all_text_contents()
                            opts = [o.strip() for o in opts if o.strip()]
                            if opts:
                                answer = self.ai.answer_question(q_text.strip(), opts)
                                print(f"  \n  ┌─ QUESTION: {q_text.strip()[:120]}")
                                print(f"  │  Options: {opts}")
                                print(f"  └─ AI ANSWER: {answer}")
                                logger.info(f"Form radio: {q_text.strip()[:50]} -> {answer}")
                                for j in range(await radio_labels.count()):
                                    text = await radio_labels.nth(j).text_content()
                                    if text and text.strip().lower() == answer.lower():
                                        await radio_labels.nth(j).click()
                                        handled_any = True
                                        break

                except Exception:
                    continue

            return handled_any

        except Exception as e:
            logger.debug(f"Form error: {e}")
            return False

    async def _click_action_button(self) -> bool:
        """Find and click submit/continue/next buttons."""
        for selector in [
            'button:has-text("Submit")',
            'button:has-text("Apply")',
            'button:has-text("Continue")',
            'button:has-text("Next")',
            'button:has-text("Confirm")',
            'button[type="submit"]',
            'input[type="submit"]',
        ]:
            try:
                btn = self.page.locator(selector).first
                if await btn.is_visible(timeout=1000):
                    text = await btn.text_content()
                    if text and any(skip in text.lower() for skip in ["login", "register", "sign"]):
                        continue
                    await btn.click()
                    logger.info(f"Clicked: {text.strip() if text else selector}")
                    await human_delay(1.5, 3.5)
                    return True
            except Exception:
                continue
        return False

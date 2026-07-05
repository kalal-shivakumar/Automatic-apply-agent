import asyncio
import logging
import random
import re
from urllib.parse import quote_plus

from playwright.async_api import Page

from ai_answerer import QuestionAnswerer
from config import Config

logger = logging.getLogger(__name__)


async def linkedin_human_delay(min_s: float = 0.8, max_s: float = 2.5):
    await asyncio.sleep(random.uniform(min_s, max_s))


class LinkedInJobSearcher:
    """Searches jobs on LinkedIn Jobs pages and extracts cards from DOM."""

    def __init__(self, page: Page):
        self.page = page

    async def search_jobs(self, page_no: int = 1, keywords: str | None = None, location: str | None = None) -> list[dict]:
        kw = (keywords or Config.JOB_KEYWORDS or "DevOps Engineer").strip()
        loc = (location or Config.JOB_LOCATION or "Hyderabad").strip()
        start = max(page_no - 1, 0) * 25
        url = (
            "https://www.linkedin.com/jobs/search/"
            f"?keywords={quote_plus(kw)}&location={quote_plus(loc)}&f_TPR=r604800&start={start}"
        )

        logger.info(f"LinkedIn search: {url}")
        await self.page.goto(url)
        await self.page.wait_for_load_state("domcontentloaded")
        await linkedin_human_delay(1.8, 3.2)

        for y in [500, 1000, 1500, 2000]:
            await self.page.evaluate(f"window.scrollTo(0, {y})")
            await linkedin_human_delay(0.4, 0.8)

        jobs = await self.page.evaluate(
            """() => {
                const out = [];
                const cards = document.querySelectorAll(
                    'li:has(a[href*="/jobs/view/"]), .jobs-search-results__list-item, .job-search-card'
                );
                cards.forEach((card) => {
                    const titleEl = card.querySelector('a.job-card-list__title, a[href*="/jobs/view/"]');
                    const companyEl = card.querySelector('.job-card-container__company-name, .artdeco-entity-lockup__subtitle, h4 a');
                    const locEl = card.querySelector('.job-card-container__metadata-item, .job-search-card__location');
                    const expSalaryEl = card.querySelector('.job-card-container__metadata-wrapper, .job-card-container__metadata-item--workplace-type');
                    const href = titleEl ? titleEl.href : '';
                    if (!href) return;
                    out.push({
                        title: (titleEl?.textContent || '').trim(),
                        company: (companyEl?.textContent || '').trim(),
                        location: (locEl?.textContent || '').trim(),
                        url: href,
                        experience: '',
                        salary: '',
                        skills: '',
                        meta: (expSalaryEl?.textContent || '').trim(),
                    });
                });
                return out;
            }"""
        )

        cleaned = []
        seen = set()
        for j in jobs or []:
            url_key = str(j.get("url", "")).split("?")[0]
            if not url_key or url_key in seen:
                continue
            seen.add(url_key)
            cleaned.append(
                {
                    "title": j.get("title", ""),
                    "company": j.get("company", ""),
                    "location": j.get("location", ""),
                    "url": j.get("url", ""),
                    "experience": j.get("experience", ""),
                    "salary": j.get("salary", ""),
                    "skills": j.get("skills", ""),
                    "description": "",
                }
            )

        logger.info(f"LinkedIn cards extracted: {len(cleaned)}")
        return cleaned


class LinkedInJobApplicant:
    """Applies to LinkedIn jobs with Easy Apply and AI answers."""

    def __init__(self, page: Page):
        self.page = page
        self.ai = QuestionAnswerer()
        self.applied_jobs = []
        self.last_match_score = 0
        self.last_match_reason = ""
        self.last_skip_reason = ""
        self.last_full_jd = ""
        self.last_qa_pairs = []

    def _record_qa(self, question: str, answer: str):
        q = (question or "").strip()
        a = (answer or "").strip()
        if q and a:
            self.last_qa_pairs.append({"question": q, "answer": a})

    @staticmethod
    def _extract_number_tokens(text: str) -> list[float]:
        vals = []
        for token in re.findall(r"\d+(?:\.\d+)?", (text or "").replace(",", "")):
            try:
                vals.append(float(token))
            except Exception:
                continue
        return vals

    def _parse_salary_range_lpa(self, salary_text: str) -> tuple[float | None, float | None]:
        txt = (salary_text or "").strip().lower()
        if not txt:
            return (None, None)
        nums = self._extract_number_tokens(txt)
        if not nums:
            return (None, None)
        if any(n > 100 for n in nums):
            nums = [round(n / 100000.0, 2) for n in nums]
        if len(nums) == 1:
            return (nums[0], nums[0])
        return (min(nums), max(nums))

    def _parse_experience_range_years(self, exp_text: str) -> tuple[float | None, float | None]:
        nums = self._extract_number_tokens(exp_text or "")
        if not nums:
            return (None, None)
        if len(nums) == 1:
            return (nums[0], nums[0])
        return (min(nums), max(nums))

    def _candidate_min_salary_lpa(self) -> float | None:
        min_sal, _ = self._parse_salary_range_lpa(getattr(Config, "YOUR_EXPECTED_CTC", ""))
        return min_sal

    def _candidate_experience_years(self) -> float | None:
        min_exp, _ = self._parse_experience_range_years(getattr(Config, "YOUR_EXPERIENCE", ""))
        return min_exp

    def _is_experience_match(self, job_exp_text: str) -> bool:
        candidate = self._candidate_experience_years()
        job_min, job_max = self._parse_experience_range_years(job_exp_text)
        if candidate is None or job_min is None:
            return False
        if job_max is None:
            return candidate >= job_min
        return job_min <= candidate <= job_max

    async def _extract_full_jd(self) -> str:
        txt = ""
        selectors = [
            ".jobs-description-content__text",
            ".jobs-box__html-content",
            ".jobs-description",
            "[class*='jobs-description']",
        ]
        for sel in selectors:
            try:
                el = self.page.locator(sel).first
                if await el.is_visible(timeout=1000):
                    val = (await el.inner_text()).strip()
                    if len(val) > len(txt):
                        txt = val
            except Exception:
                continue
        if txt:
            return txt[:8000]

        try:
            val = await self.page.evaluate(
                """() => {
                    const blocks = Array.from(document.querySelectorAll('section, div, article'));
                    let best = '';
                    for (const b of blocks) {
                        const t = (b.innerText || '').trim();
                        const lc = t.toLowerCase();
                        if (t.length < 250 || t.length > 20000) continue;
                        if (!lc.includes('job description') && !lc.includes('responsibilities') && !lc.includes('requirements')) continue;
                        if (t.length > best.length) best = t;
                    }
                    return best;
                }"""
            )
            return (val or "")[:8000]
        except Exception:
            return ""

    async def _extract_details(self, job: dict) -> dict:
        details = {
            "salary": str(job.get("salary", "") or "").strip(),
            "experience": str(job.get("experience", "") or "").strip(),
            "skills": str(job.get("skills", "") or "").strip(),
            "location": str(job.get("location", "") or "").strip(),
        }
        try:
            panel = await self.page.evaluate(
                """() => {
                    const text = (document.body?.innerText || '').replace(/\s+/g, ' ');
                    const salaryMatch = text.match(/(₹|INR)\s?[\d,.]+\s?(LPA|Lakhs?|per year|\/yr|\/year)?\s?(to|-)?\s?(₹|INR)?\s?[\d,.]*/i);
                    const expMatch = text.match(/\b\d+\s*(?:-|to)?\s*\d*\s*(?:years?|yrs?)\b/i);
                    return {
                        salary: salaryMatch ? salaryMatch[0] : '',
                        experience: expMatch ? expMatch[0] : '',
                    };
                }"""
            )
            if panel.get("salary") and not details["salary"]:
                details["salary"] = panel.get("salary")
            if panel.get("experience") and not details["experience"]:
                details["experience"] = panel.get("experience")
        except Exception:
            pass
        return details

    async def _click_first_visible(self, selectors: list[str], timeout_ms: int = 1200) -> bool:
        for sel in selectors:
            try:
                loc = self.page.locator(sel).first
                if await loc.is_visible(timeout=timeout_ms):
                    await loc.click()
                    return True
            except Exception:
                continue
        return False

    async def _fill_text_questions(self):
        fields = self.page.locator(
            "form input[type='text'], form input[type='number'], form textarea"
        )
        count = await fields.count()
        for i in range(min(count, 20)):
            try:
                field = fields.nth(i)
                if not await field.is_visible(timeout=300):
                    continue
                current = (await field.input_value()).strip()
                if current:
                    continue
                label = (
                    await field.get_attribute("aria-label")
                    or await field.get_attribute("name")
                    or ""
                )
                if not label:
                    continue
                answer = self.ai.answer_question(label, None)
                await field.fill(str(answer))
                self._record_qa(label, str(answer))
            except Exception:
                continue

    async def _select_dropdown_questions(self):
        selects = self.page.locator("form select")
        count = await selects.count()
        for i in range(min(count, 20)):
            try:
                sel = selects.nth(i)
                if not await sel.is_visible(timeout=300):
                    continue
                options = await sel.locator("option").all_inner_texts()
                cleaned = [o.strip() for o in options if o and o.strip()]
                if len(cleaned) <= 1:
                    continue
                question = (await sel.get_attribute("aria-label") or "Select one option").strip()
                answer = self.ai.answer_question(question, cleaned)
                chosen = None
                for opt in cleaned:
                    if opt.lower() == str(answer).strip().lower():
                        chosen = opt
                        break
                if chosen:
                    await sel.select_option(label=chosen)
                    self._record_qa(question, chosen)
            except Exception:
                continue

    async def _answer_visible_questions(self):
        await self._fill_text_questions()
        await self._select_dropdown_questions()

    async def _handle_easy_apply_flow(self) -> bool:
        for _ in range(10):
            await linkedin_human_delay(1.0, 2.0)

            success_markers = [
                "text=/application submitted/i",
                "text=/you.re all set/i",
                "text=/applied/i",
            ]
            for marker in success_markers:
                try:
                    loc = self.page.locator(marker).first
                    if await loc.is_visible(timeout=500):
                        return True
                except Exception:
                    continue

            await self._answer_visible_questions()

            # Prefer submit/review/next progression.
            clicked = await self._click_first_visible(
                [
                    "button:has-text('Submit application')",
                    "button:has-text('Review')",
                    "button:has-text('Next')",
                ],
                timeout_ms=900,
            )
            if not clicked:
                break

        return False

    async def apply_to_job(self, job: dict, min_match_pct: int = 60) -> bool:
        self.last_match_score = 0
        self.last_match_reason = ""
        self.last_skip_reason = ""
        self.last_full_jd = ""
        self.last_qa_pairs = []

        try:
            await self.page.goto(job["url"])
            await self.page.wait_for_load_state("domcontentloaded")
            await linkedin_human_delay(1.5, 3.0)

            full_jd = await self._extract_full_jd()
            self.last_full_jd = full_jd
            details = await self._extract_details(job)

            if not full_jd.strip():
                self.last_skip_reason = "missing_jd"
                self.last_match_reason = "No LinkedIn job description extracted"
                return False

            salary_txt = details.get("salary", "")
            exp_txt = details.get("experience", "")
            candidate_min_salary = self._candidate_min_salary_lpa()
            _, job_salary_max = self._parse_salary_range_lpa(salary_txt)

            if salary_txt and candidate_min_salary is not None and job_salary_max is not None:
                if job_salary_max < candidate_min_salary:
                    self.last_skip_reason = "salary_below_min"
                    self.last_match_reason = (
                        f"Salary mismatch: job max {job_salary_max} LPA < expected {candidate_min_salary} LPA"
                    )
                    return False

            if not salary_txt:
                if not self._is_experience_match(exp_txt):
                    self.last_skip_reason = "salary_missing_experience_mismatch"
                    self.last_match_reason = "Salary missing and experience mismatch"
                    return False

            skills_text = details.get("skills") or full_jd[:400]
            match_score, match_reason = self.ai.match_job_score(
                job_title=job.get("title", ""),
                company=job.get("company", ""),
                location=details.get("location") or job.get("location", ""),
                salary=salary_txt,
                experience=exp_txt,
                skills=skills_text,
                full_description=full_jd,
            )
            self.last_match_score = match_score
            self.last_match_reason = match_reason

            if match_score < min_match_pct:
                self.last_skip_reason = "low_score"
                return False

            easy_apply = self.page.locator("button:has-text('Easy Apply')").first
            if not await easy_apply.is_visible(timeout=2000):
                self.last_skip_reason = "no_easy_apply"
                self.last_match_reason = "Easy Apply button not available"
                return False

            btn_text = (await easy_apply.inner_text()).strip().lower()
            if "applied" in btn_text:
                self.last_skip_reason = "already_applied"
                self.last_match_reason = "Already applied"
                return False

            if not await easy_apply.is_enabled(timeout=1200):
                self.last_skip_reason = "button_disabled"
                return False

            await easy_apply.click()
            await linkedin_human_delay(1.0, 2.5)

            submitted = await self._handle_easy_apply_flow()
            if not submitted:
                self.last_skip_reason = "submit_not_reached"
                self.last_match_reason = "Could not complete Easy Apply flow"
                # Close dialog so next job can continue.
                await self._click_first_visible(
                    [
                        "button[aria-label='Dismiss']",
                        "button:has-text('Discard')",
                        "button:has-text('Cancel')",
                    ],
                    timeout_ms=700,
                )
                return False

            self.applied_jobs.append(
                {
                    "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "location": job.get("location", ""),
                    "salary": salary_txt,
                    "status": "Applied",
                }
            )
            return True

        except Exception as exc:
            logger.error(f"LinkedIn apply error: {exc}")
            self.last_skip_reason = "error"
            self.last_match_reason = str(exc)
            return False

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
        await self.page.goto(url, timeout=60000, wait_until="domcontentloaded")
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

    async def _get_field_label(self, field) -> str:
        """Get the label text for a form field using multiple strategies."""
        # Strategy 1: aria-label attribute
        label = await field.get_attribute("aria-label")
        if label and label != "None":
            return label.strip()

        # Strategy 2: Find label via field's id + label[for=id]
        field_id = await field.get_attribute("id")
        if field_id:
            try:
                label_el = self.page.locator(f"label[for='{field_id}']").first
                if await label_el.count() > 0:
                    label_text = (await label_el.inner_text()).strip()
                    if label_text:
                        return label_text
            except Exception:
                pass

        # Strategy 3: Parent container's label/span
        try:
            parent = field.locator("xpath=..")
            label_el = parent.locator("label, span.fb-dash-form-element__label").first
            if await label_el.count() > 0:
                label_text = (await label_el.inner_text()).strip()
                if label_text:
                    return label_text
        except Exception:
            pass

        # Strategy 4: name or placeholder
        name = await field.get_attribute("name")
        if name:
            return name
        placeholder = await field.get_attribute("placeholder")
        if placeholder:
            return placeholder

        return ""

    async def _fill_text_questions(self):
        fields = self.page.locator(
            ":is(div.artdeco-modal, div[role='dialog']) input[type='text'], "
            ":is(div.artdeco-modal, div[role='dialog']) input[type='number'], "
            ":is(div.artdeco-modal, div[role='dialog']) textarea, "
            "div.jobs-easy-apply-modal input[type='text'], div.jobs-easy-apply-modal input[type='number'], "
            "div.jobs-easy-apply-modal textarea, "
            "form input[type='text'], form input[type='number'], form textarea"
        )
        count = await fields.count()
        logger.info(f"  [FIELDS] Found {count} text/number/textarea fields")
        for i in range(min(count, 20)):
            try:
                field = fields.nth(i)
                if not await field.is_visible(timeout=300):
                    continue
                current = (await field.input_value()).strip()
                if current:
                    logger.info(f"  [FIELD {i}] Already filled: '{current[:50]}'")
                    continue
                label = await self._get_field_label(field)
                if not label:
                    logger.info(f"  [FIELD {i}] No label found, skipping")
                    continue
                logger.info(f"  [FIELD {i}] Question: '{label}'")
                print(f"    Q: {label}")
                answer = self.ai.answer_question(label, None)
                logger.info(f"  [FIELD {i}] AI Answer: '{answer}'")
                print(f"    A: {answer}")
                await field.fill(str(answer))
                self._record_qa(label, str(answer))
            except Exception as e:
                logger.warning(f"  [FIELD {i}] Error: {e}")
                continue

    async def _select_dropdown_questions(self):
        selects = self.page.locator(
            ":is(div.artdeco-modal, div[role='dialog']) select, "
            "div.jobs-easy-apply-modal select, form select"
        )
        count = await selects.count()
        logger.info(f"  [DROPDOWNS] Found {count} select fields")
        for i in range(min(count, 20)):
            try:
                sel = selects.nth(i)
                if not await sel.is_visible(timeout=300):
                    continue
                options = await sel.locator("option").all_inner_texts()
                cleaned = [o.strip() for o in options if o and o.strip()]
                if len(cleaned) <= 1:
                    continue
                # Check if already selected (not on default "Select an option")
                current_val = await sel.input_value()
                if current_val and current_val != "Select an option" and current_val != "":
                    sel_text = await sel.locator(f"option[value='{current_val}']").first.inner_text()
                    if sel_text.strip() and sel_text.strip() != "Select an option":
                        logger.info(f"  [DROPDOWN {i}] Already selected: '{sel_text.strip()[:50]}'")
                        continue

                question = await self._get_field_label(sel)
                if not question:
                    question = "Select one option"
                logger.info(f"  [DROPDOWN {i}] Question: '{question}' | Options: {cleaned[:8]}")
                print(f"    Q: {question} | Options: {cleaned[:8]}")
                answer = self.ai.answer_question(question, cleaned)
                chosen = None
                for opt in cleaned:
                    if opt.lower() == str(answer).strip().lower():
                        chosen = opt
                        break
                if chosen:
                    await sel.select_option(label=chosen)
                    self._record_qa(question, chosen)
                    logger.info(f"  [DROPDOWN {i}] AI Selected: '{chosen}'")
                    print(f"    A: {chosen}")
                else:
                    logger.info(f"  [DROPDOWN {i}] AI answered '{answer}' but no match in options")
                    print(f"    A: {answer} (no match in options)")
            except Exception as e:
                logger.warning(f"  [DROPDOWN {i}] Error: {e}")
                continue

    async def _answer_visible_questions(self):
        # First, handle LinkedIn's standard contact info fields (email, phone)
        await self._prefill_contact_info()
        await self._fill_text_questions()
        await self._select_dropdown_questions()

    async def _prefill_contact_info(self):
        """Pre-fill LinkedIn's standard contact info step (email select, phone country, phone number)."""
        try:
            selects = self.page.locator(":is(div.artdeco-modal, div[role='dialog']) select")
            sel_count = await selects.count()
            logger.info(f"  [PREFILL] Found {sel_count} selects in modal")
            for i in range(sel_count):
                sel = selects.nth(i)
                if not await sel.is_visible(timeout=200):
                    continue
                options = await sel.locator("option").all_inner_texts()
                cleaned = [o.strip() for o in options if o and o.strip()]

                # Email dropdown: has an email-like option — always force-select it
                email_opt = next((o for o in cleaned if "@" in o), None)
                if email_opt:
                    await sel.select_option(label=email_opt)
                    logger.info(f"  [PREFILL] Force-selected email: {email_opt}")
                    print(f"    [PREFILL] Email: {email_opt}")
                    continue

                # Phone country code: has "India (+91)" — always force-select it
                india_opt = next((o for o in cleaned if "India" in o), None)
                if india_opt:
                    await sel.select_option(label=india_opt)
                    logger.info(f"  [PREFILL] Force-selected country: {india_opt}")
                    print(f"    [PREFILL] Country: {india_opt}")
                    continue

            # Fill phone number if empty
            phone = getattr(Config, "YOUR_PHONE", "").replace("+91", "").replace(" ", "").strip()
            if phone:
                inputs = self.page.locator(":is(div.artdeco-modal, div[role='dialog']) input[type='text']")
                inp_count = await inputs.count()
                for i in range(inp_count):
                    inp = inputs.nth(i)
                    if not await inp.is_visible(timeout=200):
                        continue
                    # Check label for phone/mobile
                    inp_id = await inp.get_attribute("id") or ""
                    label_text = ""
                    if inp_id:
                        try:
                            lbl = self.page.locator(f"label[for='{inp_id}']").first
                            if await lbl.count() > 0:
                                label_text = (await lbl.inner_text()).strip().lower()
                        except Exception:
                            pass
                    if "phone" in label_text or "mobile" in label_text:
                        await inp.fill(phone)
                        logger.info(f"  [PREFILL] Filled phone: {phone}")
                        print(f"    [PREFILL] Phone: {phone}")
                        break
                    # Fallback: if this is the only required empty text input in the modal
                    current = (await inp.input_value()).strip()
                    required = await inp.get_attribute("required")
                    if not current and required is not None:
                        await inp.fill(phone)
                        logger.info(f"  [PREFILL] Filled required empty input with phone: {phone}")
                        print(f"    [PREFILL] Phone (required field): {phone}")
                        break
        except Exception as e:
            logger.warning(f"  [PREFILL] Error: {e}")

    async def _answer_radio_questions(self):
        """Handle radio button groups in LinkedIn Easy Apply forms."""
        fieldsets = self.page.locator(
            "fieldset, :is(div.artdeco-modal, div[role='dialog']) div[role='group'], "
            "div.jobs-easy-apply-modal div[role='group'], "
            "div.fb-dash-form-element"
        )
        count = await fieldsets.count()
        logger.info(f"  [RADIOS] Found {count} fieldsets")
        for i in range(min(count, 10)):
            try:
                fs = fieldsets.nth(i)
                if not await fs.is_visible(timeout=300):
                    continue
                legend = fs.locator("legend, span.fb-dash-form-element__label")
                question = ""
                if await legend.count() > 0:
                    question = (await legend.first.inner_text()).strip()
                if not question:
                    continue

                radios = fs.locator("input[type='radio']")
                radio_count = await radios.count()
                if radio_count == 0:
                    continue

                # Check if any radio is already selected
                already_selected = False
                for ri in range(radio_count):
                    if await radios.nth(ri).is_checked():
                        already_selected = True
                        break
                if already_selected:
                    continue

                # Get label texts for each radio
                labels = []
                for ri in range(radio_count):
                    radio = radios.nth(ri)
                    radio_id = await radio.get_attribute("id") or ""
                    label_el = fs.locator(f"label[for='{radio_id}']")
                    if await label_el.count() > 0:
                        labels.append((await label_el.first.inner_text()).strip())
                    else:
                        labels.append(await radio.get_attribute("value") or f"Option {ri+1}")

                logger.info(f"  [RADIO {i}] Question: '{question}' | Options: {labels}")
                print(f"    Q (radio): {question} | Options: {labels}")
                answer = self.ai.answer_question(question, labels)
                chosen_idx = None
                for ri, lbl in enumerate(labels):
                    if lbl.lower() == str(answer).strip().lower():
                        chosen_idx = ri
                        break
                if chosen_idx is not None:
                    await radios.nth(chosen_idx).click()
                    self._record_qa(question, labels[chosen_idx])
                    logger.info(f"  [RADIO {i}] AI Selected: '{labels[chosen_idx]}'")
                    print(f"    A (radio): {labels[chosen_idx]}")
                else:
                    # Default to first option if no exact match
                    await radios.first.click()
                    self._record_qa(question, labels[0] if labels else str(answer))
                    logger.info(f"  [RADIO {i}] No exact match for '{answer}', selected first: '{labels[0] if labels else 'N/A'}'")
                    print(f"    A (radio): {labels[0] if labels else answer} (defaulted)")
            except Exception as e:
                logger.warning(f"  [RADIO {i}] Error: {e}")
                continue

    async def _extract_modal_fields_js(self) -> dict:
        """Extract all visible form fields from Easy Apply modal using JavaScript."""
        return await self.page.evaluate(r"""() => {
            const modal = document.querySelector('div.artdeco-modal, div[role="dialog"]');
            if (!modal) return { error: 'No modal', fields: [], buttons: [] };
            const fields = [];
            modal.querySelectorAll('input').forEach(el => {
                if (el.type === 'hidden' || !el.offsetHeight) return;
                const label = el.id ? document.querySelector(`label[for="${el.id}"]`)?.textContent?.trim() : '';
                fields.push({ type: 'input', inputType: el.type || 'text', id: el.id, value: el.value,
                    label: label || el.getAttribute('aria-label') || el.placeholder || '', required: el.required });
            });
            modal.querySelectorAll('select').forEach(el => {
                if (!el.offsetHeight) return;
                const label = el.id ? document.querySelector(`label[for="${el.id}"]`)?.textContent?.trim() : '';
                const opts = Array.from(el.options).map(o => ({ text: o.text.trim(), value: o.value }));
                fields.push({ type: 'select', id: el.id, label: label || '', options: opts.slice(0, 20),
                    currentText: el.options[el.selectedIndex]?.text?.trim() || '' });
            });
            modal.querySelectorAll('textarea').forEach(el => {
                if (!el.offsetHeight) return;
                const label = el.id ? document.querySelector(`label[for="${el.id}"]`)?.textContent?.trim() : '';
                fields.push({ type: 'textarea', id: el.id, value: el.value, label: label || '' });
            });
            return { error: null, fields };
        }""")

    async def _fill_modal_fields_js(self, fields: list) -> list[str]:
        """Fill modal fields using AI answers. Returns list of actions taken."""
        actions = []
        for field in fields:
            ftype = field.get("type", "")
            fid = field.get("id", "")
            label = field.get("label", "")
            if not fid:
                continue

            if ftype == "input":
                if field.get("inputType") in ("radio", "checkbox"):
                    continue
                current = (field.get("value") or "").strip()
                if current:
                    continue
                if not label:
                    continue
                answer = self.ai.answer_question(label, None)
                try:
                    await self.page.locator(f"#{fid}").fill(str(answer))
                    self._record_qa(label, str(answer))
                    actions.append(f"FILLED '{label[:40]}' -> '{answer}'")
                    logger.info(f"    FILLED '{label[:40]}' -> '{answer}'")
                except Exception:
                    pass

            elif ftype == "select":
                current_text = field.get("currentText", "")
                if current_text and "Select" not in current_text:
                    continue
                opt_texts = [o["text"] for o in field.get("options", []) if o.get("text")]
                email_opt = next((o for o in opt_texts if "@" in o), None)
                if email_opt:
                    try:
                        await self.page.locator(f"#{fid}").select_option(label=email_opt)
                        actions.append(f"SELECTED email: '{email_opt}'")
                    except Exception:
                        pass
                    continue
                india_opt = next((o for o in opt_texts if "India" in o), None)
                if india_opt:
                    try:
                        await self.page.locator(f"#{fid}").select_option(label=india_opt)
                        actions.append(f"SELECTED country: '{india_opt}'")
                    except Exception:
                        pass
                    continue
                if label and len(opt_texts) > 1:
                    answer = self.ai.answer_question(label, opt_texts)
                    chosen = next((o for o in opt_texts if o.lower() == str(answer).strip().lower()), None)
                    if not chosen:
                        chosen = next((o for o in opt_texts if "Select" not in o and o), None)
                    if chosen:
                        try:
                            await self.page.locator(f"#{fid}").select_option(label=chosen)
                            self._record_qa(label, chosen)
                            actions.append(f"AI SELECTED '{label[:40]}' -> '{chosen}'")
                            logger.info(f"    AI SELECTED '{label[:40]}' -> '{chosen}'")
                        except Exception:
                            pass

            elif ftype == "textarea":
                current = (field.get("value") or "").strip()
                if current or not label:
                    continue
                answer = self.ai.answer_question(label, None)
                try:
                    await self.page.locator(f"#{fid}").fill(str(answer))
                    self._record_qa(label, str(answer))
                    actions.append(f"FILLED textarea '{label[:40]}'")
                except Exception:
                    pass
        return actions

    async def _handle_radio_buttons_js(self) -> list[str]:
        """Handle radio button groups via JavaScript."""
        actions = []
        groups = await self.page.evaluate(r"""() => {
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
            Object.values(groups).forEach(g => {
                const firstRadio = document.getElementById(g.options[0]?.id);
                if (firstRadio) {
                    const fieldset = firstRadio.closest('fieldset');
                    g.question = fieldset?.querySelector('legend, span')?.textContent?.trim() || g.name;
                }
            });
            return Object.values(groups);
        }""")
        for group in groups:
            if group.get("anyChecked"):
                continue
            options = [o["label"] for o in group.get("options", [])]
            question = group.get("question", "")
            if not options or not question:
                continue
            answer = self.ai.answer_question(question, options)
            chosen_id = None
            for opt in group.get("options", []):
                if opt["label"].lower() == str(answer).strip().lower():
                    chosen_id = opt["id"]
                    break
            if not chosen_id and group["options"]:
                chosen_id = group["options"][0]["id"]
            if chosen_id:
                try:
                    await self.page.evaluate(f"document.getElementById('{chosen_id}')?.click()")
                    self._record_qa(question, str(answer))
                    actions.append(f"RADIO '{question[:40]}' -> '{answer}'")
                    logger.info(f"    RADIO '{question[:40]}' -> '{answer}'")
                except Exception:
                    pass
        return actions

    async def _dismiss_save_dialog(self):
        """Dismiss 'Save this application?' dialog via JS."""
        try:
            await self.page.evaluate(r"""() => {
                const overlay = document.querySelector('[data-test-modal-id="data-test-easy-apply-discard-confirmation"]');
                if (overlay && overlay.offsetHeight > 0) {
                    const saveBtn = overlay.querySelector('button[data-control-name="save_application_confirm_btn"], button[data-test-dialog-primary-btn]');
                    if (saveBtn) { saveBtn.click(); return; }
                    const btns = Array.from(overlay.querySelectorAll('button'));
                    const save = btns.find(b => b.textContent?.trim() === 'Save');
                    if (save) save.click();
                }
            }""")
        except Exception:
            pass

    async def _handle_easy_apply_flow(self) -> bool:
        prev_field_sig = ""
        stuck_count = 0
        for step in range(8):
            await linkedin_human_delay(1.5, 2.5)
            logger.info(f"  [EASY APPLY] Step {step + 1}/8")

            # Check if modal still open
            try:
                modal = self.page.locator("div.artdeco-modal, div[role='dialog']").first
                if not await modal.is_visible(timeout=1500):
                    logger.info(f"  [EASY APPLY] Modal closed - assuming success")
                    return True
            except Exception:
                pass

            # Extract fields via JS
            modal_data = await self._extract_modal_fields_js()
            if modal_data.get("error"):
                break
            fields = modal_data.get("fields", [])

            # Stuck detection
            field_sig = str([(f.get("label", "")[:20], f.get("value", "")[:10]) for f in fields])
            if field_sig == prev_field_sig:
                stuck_count += 1
                if stuck_count >= 2:
                    logger.info(f"  [EASY APPLY] STUCK on same fields, skipping")
                    break
            else:
                stuck_count = 0
            prev_field_sig = field_sig

            # Fill fields
            await self._fill_modal_fields_js(fields)
            await self._handle_radio_buttons_js()
            await linkedin_human_delay(0.5, 1.0)

            # Dismiss typeahead
            try:
                typeahead = self.page.locator("div.search-typeahead-v2__hit").first
                if await typeahead.is_visible(timeout=300):
                    await self.page.locator("div.artdeco-modal__content").first.click(position={"x": 5, "y": 5})
                    await linkedin_human_delay(0.3, 0.5)
            except Exception:
                pass

            # Dismiss save dialog
            await self._dismiss_save_dialog()

            # Click buttons: Next > Review > Submit
            clicked = None
            try:
                for aria, name in [
                    ("Continue to next step", "Next"),
                    ("Review your application", "Review"),
                    ("Submit application", "Submit"),
                ]:
                    btn = self.page.locator(f":is(div.artdeco-modal, div[role='dialog']) button[aria-label='{aria}']").first
                    if await btn.is_visible(timeout=400):
                        try:
                            await btn.click(timeout=5000)
                        except Exception:
                            await self._dismiss_save_dialog()
                            await self.page.evaluate(f"document.querySelector('button[aria-label=\"{aria}\"]')?.click()")
                        clicked = name
                        logger.info(f"  [EASY APPLY] Clicked {name}")
                        break
            except Exception:
                pass

            if not clicked:
                # Fallback: primary button with text
                for text, name in [("Next", "Next"), ("Review", "Review"), ("Submit", "Submit")]:
                    try:
                        fb = self.page.locator(f":is(div.artdeco-modal, div[role='dialog']) button.artdeco-button--primary:has-text('{text}')").first
                        if await fb.is_visible(timeout=300):
                            await fb.click(timeout=5000)
                            clicked = f"{name} (fallback)"
                            break
                    except Exception:
                        continue

            if not clicked:
                logger.info(f"  [EASY APPLY] No button found, stopping")
                break

            # Check submit success
            if clicked and "Submit" in clicked:
                await linkedin_human_delay(2.0, 3.5)
                try:
                    if not await modal.is_visible(timeout=2000):
                        logger.info(f"  [EASY APPLY] Modal closed after Submit - SUCCESS!")
                        return True
                except Exception:
                    pass

        return False

    async def apply_to_job(self, job: dict, min_match_pct: int = 60) -> bool:
        self.last_match_score = 0
        self.last_match_reason = ""
        self.last_skip_reason = ""
        self.last_full_jd = ""
        self.last_qa_pairs = []

        job_title = job.get('title', 'Unknown')
        job_company = job.get('company', 'Unknown')
        print(f"\n{'='*60}")
        print(f"  JOB: {job_title} @ {job_company}")
        print(f"  URL: {job.get('url', '')[:80]}")
        print(f"{'='*60}")
        logger.info(f"Evaluating: {job_title} @ {job_company}")

        try:
            await self.page.goto(job["url"], timeout=60000, wait_until="domcontentloaded")
            await self.page.wait_for_load_state("domcontentloaded")
            await linkedin_human_delay(1.5, 3.0)

            full_jd = await self._extract_full_jd()
            self.last_full_jd = full_jd
            details = await self._extract_details(job)
            print(f"  JD length: {len(full_jd)} chars | Salary: '{details.get('salary','')}' | Exp: '{details.get('experience','')}'")

            if not full_jd.strip():
                self.last_skip_reason = "missing_jd"
                self.last_match_reason = "No LinkedIn job description extracted"
                print(f"  SKIP: No job description found")
                return False

            salary_txt = details.get("salary", "")
            exp_txt = details.get("experience", "")
            candidate_min_salary = self._candidate_min_salary_lpa()
            _, job_salary_max = self._parse_salary_range_lpa(salary_txt)

            # Ignore salary values < 1 LPA — likely false positives from page parsing
            if job_salary_max is not None and job_salary_max < 1:
                salary_txt = ""
                job_salary_max = None

            # Fresher mode: skip all salary/experience gating, accept jobs 0-6 years
            is_fresher = getattr(Config, 'CANDIDATE_LEVEL', '') == 'Fresher'
            if is_fresher:
                # Only skip if job explicitly requires 7+ years
                job_min_exp, _ = self._parse_experience_range_years(exp_txt)
                if job_min_exp is not None and job_min_exp > 6:
                    self.last_skip_reason = "experience_too_high"
                    self.last_match_reason = f"Job requires {job_min_exp}+ years, exceeds Fresher range (0-6)"
                    print(f"  SKIP: Job requires {job_min_exp}+ years (Fresher max: 6)")
                    return False
                logger.info(f"Fresher mode: skipping salary/experience gating")
                print(f"  Fresher mode: salary/exp checks skipped")
            else:
                if salary_txt and candidate_min_salary is not None and job_salary_max is not None:
                    if job_salary_max < candidate_min_salary:
                        self.last_skip_reason = "salary_below_min"
                        self.last_match_reason = (
                            f"Salary mismatch: job max {job_salary_max} LPA < expected {candidate_min_salary} LPA"
                        )
                        return False

                if not salary_txt:
                    if candidate_min_salary is not None and candidate_min_salary < 10:
                        logger.info(
                            f"Salary not mentioned but candidate min {candidate_min_salary} LPA < 10 — proceeding to score"
                        )
                    elif not self._is_experience_match(exp_txt):
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
            print(f"  Match Score: {match_score}% — {match_reason}")

            if match_score < min_match_pct:
                self.last_skip_reason = "low_score"
                print(f"  SKIP: Score {match_score}% below threshold {min_match_pct}%")
                return False

            # Navigate directly to apply URL (proven more reliable than button click)
            import re as _re
            job_id_match = _re.search(r'/jobs/view/(\d+)', job.get("url", ""))
            if job_id_match:
                apply_url = f"https://www.linkedin.com/jobs/view/{job_id_match.group(1)}/apply/"
                print(f"  >>> Navigating to apply URL...")
                await self.page.goto(apply_url, timeout=60000, wait_until="domcontentloaded")
                await linkedin_human_delay(3.0, 5.0)
            else:
                # Fallback: click Easy Apply button
                easy_apply = self.page.locator("button:has-text('Easy Apply')").first
                if not await easy_apply.is_visible(timeout=2000):
                    self.last_skip_reason = "no_easy_apply"
                    self.last_match_reason = "Easy Apply button not available"
                    print(f"  SKIP: No Easy Apply button found")
                    return False
                btn_text = (await easy_apply.inner_text()).strip().lower()
                if "applied" in btn_text:
                    self.last_skip_reason = "already_applied"
                    self.last_match_reason = "Already applied"
                    return False
                await easy_apply.click()
                await linkedin_human_delay(3.0, 5.0)

            # Check if modal appeared
            modal = self.page.locator("div.artdeco-modal, div[role='dialog']").first
            modal_appeared = await modal.is_visible(timeout=5000)

            if not modal_appeared:
                self.last_skip_reason = "modal_not_opened"
                self.last_match_reason = "Easy Apply modal did not open (likely already applied)"
                print(f"  SKIP: Modal did not open")
                return False

            print(f"  >>> Easy Apply modal opened, filling questions...")

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

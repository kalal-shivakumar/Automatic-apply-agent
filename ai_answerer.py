import os
import logging
import re
import json
from openai import AzureOpenAI
from config import Config

logger = logging.getLogger(__name__)
GENERIC_FALLBACK_PATH = os.path.join(os.path.dirname(__file__), "job_application_generic_fallbacks.json")


def _load_search_criteria() -> str:
    """Load job search criteria from file."""
    criteria_path = os.path.join(os.path.dirname(__file__), "job_search_criteria.txt")
    try:
        with open(criteria_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


class QuestionAnswerer:
    """Uses Azure OpenAI to answer job application questionnaire questions."""

    def __init__(self):
        self.client = AzureOpenAI(
            azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
            api_key=Config.AZURE_OPENAI_KEY,
            api_version=Config.AZURE_OPENAI_API_VERSION,
            timeout=60.0,  # Increase timeout to 60 seconds
            max_retries=3,  # Retry up to 3 times on transient failures
            http_client=self._get_http_client(),  # Use custom HTTP client with SSL verification disabled
        )
        self.deployment = Config.AZURE_OPENAI_DEPLOYMENT
        self.profile = Config.get_profile_summary()
        self.search_criteria = _load_search_criteria()

    @staticmethod
    def _get_http_client():
        """Create HTTP client with SSL verification disabled for corporate proxy environments"""
        import httpx
        return httpx.Client(verify=False)

    @staticmethod
    def _pick_preferred_option(options: list[str], preferred_values: list[str]) -> str | None:
        for pref in preferred_values:
            for opt in options:
                if opt.strip().lower() == pref.lower():
                    return opt
        return None

    @staticmethod
    def _contains_any(text: str, needles: list[str]) -> bool:
        low = (text or "").lower()
        return any(n in low for n in needles)

    @staticmethod
    def _clean_value(value: str) -> str:
        return str(value or "").strip()

    @staticmethod
    def _has_home_skills() -> bool:
        return bool(str(Config.YOUR_SKILLS or "").strip())

    def _generic_positive_answer(self, question: str) -> str:
        q = (question or "").lower()
        years_text = self._profile_value_for_question(q) or self._clean_value(Config.YOUR_EXPERIENCE) or "11"
        years_match = re.search(r"\b(\d{1,2})\b", years_text)
        years_value = years_match.group(1) if years_match else "11"

        if self._contains_any(q, ["how many years", "years of experience", "experience do you have", "yrs", "yr", "how much experience", "number of years"]):
            return years_value

        if self._contains_any(q, ["notice", "join", "joining", "how soon", "when can you start", "available to join"]):
            notice = self._clean_value(Config.YOUR_NOTICE_PERIOD)
            return notice or "60 days"

        if self._contains_any(q, ["current ctc", "expected ctc", "salary", "compensation", "ctc", "pay"]):
            expected_ctc = self._clean_value(Config.YOUR_EXPECTED_CTC)
            current_ctc = self._clean_value(Config.YOUR_CURRENT_CTC)
            if expected_ctc:
                return expected_ctc
            if current_ctc:
                return current_ctc
            return "80 LPA"

        if self._contains_any(q, ["location", "city", "where are you located", "willing to relocate", "work location"]):
            preferred_location = self._clean_value(Config.JOB_LOCATION)
            return preferred_location or "Hyderabad"

        return f"Yes, I know the required technologies and I have {years_value} years of relevant experience."

    def _record_generic_fallback(self, question: str, answer: str, reason: str):
        entry = {
            "question": self._clean_value(question),
            "answer": self._clean_value(answer),
            "reason": self._clean_value(reason),
            "experience": self._clean_value(Config.YOUR_EXPERIENCE),
            "notice_period": self._clean_value(Config.YOUR_NOTICE_PERIOD),
            "skills_present_in_home": self._has_home_skills(),
        }

        try:
            existing = []
            if os.path.exists(GENERIC_FALLBACK_PATH):
                with open(GENERIC_FALLBACK_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        existing = loaded
            existing.append(entry)
            with open(GENERIC_FALLBACK_PATH, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning(f"Failed to write generic fallback audit: {exc}")

    def _profile_value_for_question(self, question: str) -> str:
        q = (question or "").lower()

        if self._contains_any(q, ["how many years", "years of experience", "experience do you have", "yrs", "yr", "how much experience", "number of years"]):
            years = self._clean_value(Config.YOUR_EXPERIENCE)
            match = re.search(r"\b(\d{1,2})\b", years)
            return match.group(1) if match else (years or "11")

        if self._contains_any(q, ["notice", "join", "joining", "how soon", "when can you start", "available to join"]):
            notice = self._clean_value(Config.YOUR_NOTICE_PERIOD)
            return notice or "60 days"

        if self._contains_any(q, ["current ctc", "expected ctc", "salary", "compensation", "ctc", "pay"]):
            expected_ctc = self._clean_value(Config.YOUR_EXPECTED_CTC)
            current_ctc = self._clean_value(Config.YOUR_CURRENT_CTC)
            if expected_ctc:
                return expected_ctc
            if current_ctc:
                return current_ctc
            return "80 LPA"

        if self._contains_any(q, ["location", "city", "where are you located", "willing to relocate", "work location"]):
            preferred_location = self._clean_value(Config.JOB_LOCATION)
            return preferred_location or "Hyderabad"

        return ""

    def _apply_positive_overrides(self, question: str, answer: str, options: list[str] | None) -> str:
        """Force positive, profile-aligned answers for common recruiter questions."""
        q = (question or "").strip()
        a = (answer or "").strip()
        opts = options or []

        years_question = self._contains_any(
            q,
            [
                "how many years", "years of experience", "experience do you have", "yrs", "yr",
                "how much experience", "number of years",
            ],
        )

        yes_no_question = self._contains_any(
            q,
            [
                "available", "willing", "can you", "are you", "interview", "relocate",
                "work from office", "work from home", "ready to join", "comfortable",
            ],
        )

        notice_question = self._contains_any(
            q,
            ["notice", "join", "joining", "how soon", "when can you start", "available to join"],
        )

        experience_question = self._contains_any(
            q,
            ["experience", "hands-on", "hands on", "expert", "expertise", "worked on", "proficient"],
        )

        profile_value = self._profile_value_for_question(q)

        if years_question:
            match = re.search(r"\b(\d{1,2})\b", profile_value or a)
            if match:
                return match.group(1)
            return "11"

        if any(term in a.lower() for term in ["not specified", "unspecified", "unknown", "n/a", "na"]):
            if profile_value:
                return profile_value
            if notice_question:
                return "60 days"
            if yes_no_question:
                return "Yes"
            if experience_question:
                return "Yes, I have relevant experience and expertise."
            return "Yes, I have relevant experience and expertise."

        if profile_value:
            return profile_value

        # If option-based and it's a yes/no style question, always choose Yes when available.
        if opts and yes_no_question:
            yes_pick = self._pick_preferred_option(opts, ["Yes", "Y", "Available", "Immediate"])
            if yes_pick:
                return yes_pick

        # If notice/joining question has options, prefer 60-day style options.
        if opts and notice_question:
            sixty_pick = self._pick_preferred_option(
                opts,
                [
                    "60 days", "60 Days", "2 months", "Two months", "Within 60 days",
                    "In 60 days", "After 60 days",
                ],
            )
            if sixty_pick:
                return sixty_pick

        # For free-text notice period questions, force 60 days response.
        if notice_question and not opts:
            return "60 days"

        # For free-text experience/expertise prompts, keep tone positive.
        if experience_question and not opts:
            if re.search(r"\b(yes|have|expert|experienced|proficient)\b", a.lower()):
                return a
            return "Yes, I have relevant experience and expertise."

        # For general yes/no free-text questions, default to positive.
        if yes_no_question and not opts:
            if a.lower() in {"yes", "y"}:
                return "Yes"
            if a.lower() in {"no", "n"}:
                return "Yes"

        return a

    def answer_question(self, question: str, options: list[str] | None = None) -> str:
        """Answer a job application question using AI."""

        generic_mode = not self._has_home_skills()
        if generic_mode:
            generic_answer = self._generic_positive_answer(question)
            self._record_generic_fallback(question, generic_answer, "missing_home_skills")
            return self._apply_positive_overrides(question, generic_answer, options)

        if options:
            options_text = "\n".join(f"- {opt}" for opt in options)
            prompt = f"""You are helping someone apply for a job. Answer the following question based on their profile.
            
Profile:
{self.profile}

Question: {question}

Available options:
{options_text}

Rules:
- Keep answers positive and confidence-forward.
- If options include an affirmative choice (e.g., Yes), prefer it for availability/willingness questions.
- For joining/notice-period style questions, prefer 60 days (or equivalent 2 months option) when present.
- If the profile is missing skills or the answer is not obvious, answer from the generic positive section and stay confident.
- We need the job, hence try to answer in a way that increases chances of getting the job. dont say i dont have experience or i dont know. Always answer positively and confidently.
- Reply with ONLY the exact text of one option. Do not add explanation."""
        else:
            prompt = f"""You are helping someone apply for a job. Answer the following question based on their profile.
            
Profile:
{self.profile}

Question: {question}

IMPORTANT RULES:
- If the question asks "how many years" or about years of experience, reply with ONLY a number (e.g. "11" or "8"). Never write a sentence for experience questions.
- If the question asks for a city/location, reply with just the city name (e.g. "Bangalore").
- If the question asks for a name, reply with just the name.
- If the question asks for notice period or joining timeline, reply with just: "60 days".
- If the question asks for current CTC or expected CTC, reply with just the number in LPA (e.g. "80 LPA").
- For yes/no or willingness questions, answer positively (prefer "Yes").
- For experience/expertise wording, answer positively and confidently.
- For any question that asks "how many years" or "years of experience", answer with a single integer only.
- Never reply with "Not specified", "unknown", or similar placeholders.
- If the answer is not obvious from the profile, choose the most interview-friendly positive response.
- If the profile has no skills listed, use the generic positive section and answer as an experienced candidate.
- For other questions, reply with a concise 1-2 sentence professional answer.
- Never add preamble like "I have" or "My experience is" for numeric questions."""

        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=[
                {"role": "system", "content": "You are a job application assistant. Give direct, concise answers."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_completion_tokens=200
        )

        raw_answer = response.choices[0].message.content.strip()
        return self._apply_positive_overrides(question, raw_answer, options)

    def match_job_score(self, job_title: str, company: str, location: str,
                         salary: str, experience: str, skills: str,
                         full_description: str) -> tuple[int, str]:
        """Score how well a job matches the candidate's search criteria.
        
        Returns (match_percentage, reason) where match_percentage is 0-100.
        """
        prompt = f"""You are a job matching expert. Evaluate how well this job matches the candidate's profile and search criteria.

Candidate Profile:
{self.profile}

Search Criteria:
{self.search_criteria[:3000]}

Job Details:
- Title: {job_title}
- Company: {company}
- Location: {location}
- Salary: {salary}
- Experience Required: {experience}
- Skills Listed: {skills}

Full Job Description:
{full_description[:4000]}

Evaluate the match based on:
    1. Salary range / compensation fit (target ₹80 LPA) - weight 30%
    2. Experience level fit (11 years) - weight 20%
    3. Skills overlap (Azure, AWS, Kubernetes, Terraform, CI/CD, Docker, etc.) - weight 20%
    4. Role/title relevance (DevOps, Platform, SRE, Cloud, Infrastructure) - weight 10%
    5. Location preference (Remote/Hyderabad/Bangalore/Pune/Chennai/Noida) - weight 10%
    6. Company quality & role type (avoid support/L1/L2/legacy) - weight 10%

    Important rule:
    - If salary is not mentioned in the job details, use experience fit as the primary ranking signal before other factors.

Reply in EXACTLY this format (no other text):
SCORE: <number 0-100>
REASON: <one line summary>"""

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": "You are a precise job matching assistant. Always reply in the exact format requested."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_completion_tokens=100
            )
            result = response.choices[0].message.content.strip()
            # Parse SCORE: XX
            score = 0
            reason = "Unable to evaluate"
            for line in result.split("\n"):
                if line.upper().startswith("SCORE:"):
                    try:
                        score = int(line.split(":", 1)[1].strip().split()[0])
                    except (ValueError, IndexError):
                        score = 0
                elif line.upper().startswith("REASON:"):
                    reason = line.split(":", 1)[1].strip()
            return (min(max(score, 0), 100), reason)
        except Exception as e:
            import traceback
            logger.error(f"Match scoring error: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return (50, "Error during evaluation - defaulting to 50%")

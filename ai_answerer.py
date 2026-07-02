import os
import logging
from openai import AzureOpenAI
from config import Config

logger = logging.getLogger(__name__)


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

    def answer_question(self, question: str, options: list[str] | None = None) -> str:
        """Answer a job application question using AI."""

        if options:
            options_text = "\n".join(f"- {opt}" for opt in options)
            prompt = f"""You are helping someone apply for a job. Answer the following question based on their profile.
            
Profile:
{self.profile}

Question: {question}

Available options:
{options_text}

Reply with ONLY the exact text of the best matching option. Do not add explanation."""
        else:
            prompt = f"""You are helping someone apply for a job. Answer the following question based on their profile.
            
Profile:
{self.profile}

Question: {question}

IMPORTANT RULES:
- If the question asks "how many years" or about years of experience, reply with ONLY a number (e.g. "11" or "8"). Never write a sentence for experience questions.
- If the question asks for a city/location, reply with just the city name (e.g. "Bangalore").
- If the question asks for a name, reply with just the name.
- If the question asks for notice period, reply with just the period (e.g. "2 months").
- If the question asks for current CTC or expected CTC, reply with just the number in LPA (e.g. "80 LPA").
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

        return response.choices[0].message.content.strip()

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
1. Skills overlap (Azure, AWS, Kubernetes, Terraform, CI/CD, Docker, etc.) - weight 35%
2. Role/title relevance (DevOps, Platform, SRE, Cloud, Infrastructure) - weight 20%
3. Experience level fit (11 years) - weight 15%
4. Salary potential (target ₹80 LPA) - weight 10%
5. Location preference (Remote/Hyderabad/Bangalore/Pune/Chennai/Noida) - weight 10%
6. Company quality & role type (avoid support/L1/L2/legacy) - weight 10%

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

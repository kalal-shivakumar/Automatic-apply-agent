import os
from dotenv import load_dotenv

# Load .env file, overriding any existing environment variables
# This ensures values from .env take precedence over system env vars
load_dotenv(override=True)


class Config:
    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
    AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini")
    AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
    AZURE_OPENAI_ACCOUNT = os.getenv("AZURE_OPENAI_ACCOUNT", "")
    AZURE_OPENAI_MODEL = os.getenv("AZURE_OPENAI_MODEL", "")
    AZURE_RESOURCE_GROUP = os.getenv("AZURE_RESOURCE_GROUP", "")

    # Job search
    JOB_KEYWORDS = os.getenv("JOB_KEYWORDS", "Python Developer")
    JOB_LOCATION = os.getenv("JOB_LOCATION", "Bangalore")
    EXPERIENCE_YEARS = os.getenv("EXPERIENCE_YEARS", "3")
    JOB_AGE_DAYS = os.getenv("JOB_AGE_DAYS", "7")

    # Profile
    YOUR_NAME = os.getenv("YOUR_NAME", "")
    YOUR_EMAIL = os.getenv("YOUR_EMAIL", "")
    YOUR_PHONE = os.getenv("YOUR_PHONE", "")
    YOUR_EXPERIENCE = os.getenv("YOUR_EXPERIENCE", "")
    YOUR_SKILLS = os.getenv("YOUR_SKILLS", "")
    YOUR_EDUCATION = os.getenv("YOUR_EDUCATION", "")
    YOUR_CURRENT_COMPANY = os.getenv("YOUR_CURRENT_COMPANY", "")
    YOUR_CURRENT_ROLE = os.getenv("YOUR_CURRENT_ROLE", "")
    YOUR_NOTICE_PERIOD = os.getenv("YOUR_NOTICE_PERIOD", "")
    YOUR_EXPECTED_CTC = os.getenv("YOUR_EXPECTED_CTC", "")
    YOUR_CURRENT_CTC = os.getenv("YOUR_CURRENT_CTC", "")

    MAX_APPLICATIONS = int(os.getenv("MAX_APPLICATIONS", "50"))

    BROWSER_DATA_DIR = os.path.join(os.path.dirname(__file__), "browser_data")

    @classmethod
    def get_profile_summary(cls):
        return f"""
Name: {cls.YOUR_NAME}
Email: {cls.YOUR_EMAIL}
Phone: {cls.YOUR_PHONE}
Experience: {cls.YOUR_EXPERIENCE}
Skills: {cls.YOUR_SKILLS}
Education: {cls.YOUR_EDUCATION}
Current Company: {cls.YOUR_CURRENT_COMPANY}
Current Role: {cls.YOUR_CURRENT_ROLE}
Notice Period: {cls.YOUR_NOTICE_PERIOD}
Expected CTC: {cls.YOUR_EXPECTED_CTC}
Current CTC: {cls.YOUR_CURRENT_CTC}
"""

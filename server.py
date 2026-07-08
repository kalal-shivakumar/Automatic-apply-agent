"""FastAPI WebSocket server for the Naukri AI Job Agent webapp."""
import asyncio
import base64
import csv
import json
import logging
import io
import os
import random
import re
import sys
import tempfile
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import AzureOpenAI
from pypdf import PdfReader
from browser import NaukriBrowser
from naukri_agent import JobSearcher, JobApplicant, human_delay
from linkedin_browser import LinkedInBrowser
from linkedin_agent import LinkedInJobSearcher, LinkedInJobApplicant, linkedin_human_delay
from config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)

SEARCH_QUERIES = [
    ("Senior DevOps Engineer", "bangalore"),
    ("Senior DevOps Engineer", "hyderabad"),
    ("Senior DevOps Engineer", "pune"),
    ("Senior DevOps Engineer", "noida"),
    ("Senior DevOps Engineer", "chennai"),
    ("Lead DevOps Engineer", "bangalore"),
    ("Lead DevOps Engineer", "hyderabad"),
    ("Platform Engineer", "bangalore"),
    ("Platform Engineer", "hyderabad"),
    ("Cloud Infrastructure Engineer", "bangalore"),
    ("Cloud Infrastructure Engineer", "hyderabad"),
    ("Site Reliability Engineer", "bangalore"),
    ("Site Reliability Engineer", "hyderabad"),
    ("DevSecOps Engineer", "bangalore"),
    ("Cloud Architect", "bangalore"),
    ("Cloud Architect", "hyderabad"),
    ("Infrastructure Architect", "bangalore"),
    ("Principal DevOps Engineer", "bangalore"),
    ("Staff DevOps Engineer", "bangalore"),
    ("Terraform AKS GitHub", "bangalore"),
    ("Terraform AKS GitHub", "hyderabad"),
    ("Azure DevOps Kubernetes", "bangalore"),
    ("Azure DevOps Kubernetes", "hyderabad"),
    ("AWS DevOps Terraform", "bangalore"),
    ("AWS DevOps Terraform", "pune"),
]

PROFILE_PATH = os.path.join(os.path.dirname(__file__), "resume_profile.json")
CRITERIA_PATH = os.path.join(os.path.dirname(__file__), "job_search_criteria.txt")
LINKEDIN_DEBUG_RESULTS_PATH = os.path.join(
    os.path.dirname(__file__),
    "debug_extract_linkedin_structure_results.json",
)
LINKEDIN_DEEP_INSPECTION_PATH = os.path.join(
    os.path.dirname(__file__),
    "debug_linkedin_apply_flow_results.json",
)


def _default_stats() -> dict:
    return {"applied": 0, "skipped": 0, "already_applied": 0, "evaluated": 0, "current_query": ""}


def _default_profile() -> dict:
    return {
        "full_name": "",
        "skills": [],
        "job_titles": [],
        "salary_min_lpa": "",
        "salary_max_lpa": "",
        "overall_experience_years": "",
        "notice_period": "",
        "key_search_keywords": [],
        "preferred_location": "Hyderabad",
        "ready_to_relocate": True,
        "search_locations": [
            "Hyderabad",
            "Bangalore",
            "Chennai",
            "Pune",
            "Mumbai",
            "Noida",
            "Gurugram",
            "Delhi",
            "Kolkata",
            "Ahmedabad",
        ],
        "resume_file_name": "",
    }


def _normalize_location_list(values) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw_items = values.split(",")
    elif isinstance(values, list):
        raw_items = values
    else:
        raw_items = []

    cleaned = []
    for item in raw_items:
        loc = str(item).strip()
        if not loc:
            continue
        if loc.lower() not in [x.lower() for x in cleaned]:
            cleaned.append(loc)
    return cleaned


def _read_saved_profile() -> dict:
    if not os.path.exists(PROFILE_PATH):
        return _default_profile()
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                base = _default_profile()
                base.update(data)
                return base
    except Exception as e:
        logger.warning(f"Failed to read profile: {e}")
    return _default_profile()


def _write_saved_profile(profile: dict):
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def _extract_name(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in lines[:8]:
        if "@" in line or re.search(r"\d{10}", line):
            continue
        if 2 <= len(line.split()) <= 4 and len(line) <= 40:
            if re.match(r"^[A-Za-z][A-Za-z .'-]+$", line):
                return line
    return ""


def _extract_experience(text: str) -> str:
    match = re.search(r"(\d{1,2})\s*\+?\s*(?:years|year|yrs|yr)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def _extract_skills(text: str) -> list[str]:
    skill_catalog = [
        "azure", "aws", "gcp", "terraform", "ansible", "docker", "kubernetes", "helm",
        "linux", "windows", "powershell", "bash", "python", "java", "javascript", "typescript",
        "jenkins", "github actions", "azure devops", "gitlab ci", "ci/cd", "devops", "sre",
        "prometheus", "grafana", "elk", "splunk", "sql", "mongodb", "redis", "fastapi",
        "node.js", "react", "networking", "security", "iam", "automation", "microservices",
        "rest api", "api management", "service bus", "event hub", "azure functions", "app service",
    ]
    low = text.lower()
    found = []

    def add_skill(sk: str):
        clean = re.sub(r"\s+", " ", sk).strip(" -•\t")
        if not clean:
            return
        if len(clean) < 2 or len(clean) > 60:
            return
        if clean.lower() not in [x.lower() for x in found]:
            found.append(clean)

    for skill in skill_catalog:
        pattern = r"\b" + re.escape(skill) + r"\b"
        if re.search(pattern, low):
            add_skill(skill)

    # Parse technical-skill style sections and category lines to capture all listed skills.
    category_hints = [
        "platform", "language", "cloud", "network", "web", "container", "integration",
        "deployment", "configuration", "source code", "monitor", "logging", "database", "tool", "skills",
    ]
    heading_stop = ["work history", "experience", "education", "certification", "project", "summary"]

    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines() if ln.strip()]
    in_skill_block = False
    budget = 0
    for raw in lines:
        line = raw.strip("•-")
        lower = line.lower()

        if any(h in lower for h in ["technical skills", "core skills", "skills"]) and len(lower) < 80:
            in_skill_block = True
            budget = 45
            continue

        if in_skill_block:
            if budget <= 0 or any(stop in lower for stop in heading_stop):
                in_skill_block = False
            else:
                payload = line
                if ":" in line:
                    left, right = line.split(":", 1)
                    if any(h in left.lower() for h in category_hints):
                        payload = right
                payload = payload.replace("(", ",").replace(")", ",")
                for token in re.split(r"[,|;/]", payload):
                    tok = token.strip()
                    if not tok:
                        continue
                    if any(stop in tok.lower() for stop in ["years", "experience"]):
                        continue
                    add_skill(tok)
                budget -= 1

        if ":" in line:
            left, right = line.split(":", 1)
            if any(h in left.lower() for h in category_hints):
                payload = right.replace("(", ",").replace(")", ",")
                for token in re.split(r"[,|;/]", payload):
                    tok = token.strip()
                    if tok:
                        add_skill(tok)

    return [s.title() if s.islower() else s for s in found]


def _build_keywords(skills: list[str]) -> list[str]:
    if not skills:
        return []

    expanded = []
    for skill in skills[:12]:
        s = skill.lower()
        if "azure" in s:
            expanded.append("Azure DevOps Engineer")
        elif "terraform" in s:
            expanded.append("Terraform Engineer")
        elif "kubernetes" in s:
            expanded.append("Kubernetes Engineer")
        elif "python" in s:
            expanded.append("Python Automation Engineer")
        elif "powershell" in s:
            expanded.append("PowerShell Automation Engineer")
        elif "devops" in s:
            expanded.append("DevOps Engineer")
        elif "sre" in s:
            expanded.append("Site Reliability Engineer")
        else:
            expanded.append(skill)

    dedup = []
    for item in expanded:
        if item not in dedup:
            dedup.append(item)
    return dedup[:5]


def _derive_job_titles_from_skills(skills: list[str]) -> list[str]:
    seeds = []
    seeds.extend([str(k).strip() for k in _build_keywords(skills) if str(k).strip()])
    for skill in (skills or []):
        s = str(skill).strip()
        if not s:
            continue
        low = s.lower()
        if "devops" in low:
            seeds.append("DevOps Engineer")
        elif "azure" in low:
            seeds.append("Azure DevOps Engineer")
        elif "aws" in low:
            seeds.append("AWS DevOps Engineer")
        elif "terraform" in low:
            seeds.append("Terraform Engineer")
        elif "kubernetes" in low:
            seeds.append("Kubernetes Engineer")
        elif "docker" in low:
            seeds.append("Container Platform Engineer")
        elif "python" in low:
            seeds.append("Python Automation Engineer")
        elif "powershell" in low:
            seeds.append("PowerShell Automation Engineer")
        elif "sre" in low:
            seeds.append("Site Reliability Engineer")
        elif "linux" in low:
            seeds.append("Linux Platform Engineer")
        else:
            seeds.append(s)

    ordered = []
    for t in seeds:
        norm = t.strip()
        if not norm:
            continue
        if norm.lower() not in [x.lower() for x in ordered]:
            ordered.append(norm)

    # Expand resume-derived roles to reach minimum 10 without unrelated defaults.
    expanded = []
    for base in ordered:
        expanded.append(base)
        low = base.lower()
        if "engineer" in low:
            expanded.append(base.replace("Engineer", "Lead Engineer"))
            expanded.append(base.replace("Engineer", "Senior Engineer"))
        elif "architect" in low:
            expanded.append(base.replace("Architect", "Senior Architect"))
        elif "specialist" in low:
            expanded.append(base.replace("Specialist", "Engineer"))
        else:
            expanded.append(f"Senior {base}")

    final_titles = []
    for t in expanded:
        cleaned = re.sub(r"\s+", " ", t).strip(" -")
        if not cleaned:
            continue
        if cleaned.lower() not in [x.lower() for x in final_titles]:
            final_titles.append(cleaned)
        if len(final_titles) >= 20:
            break

    return final_titles[:20]


def _analyze_resume_text(file_name: str, resume_text: str) -> dict:
    resume_text = resume_text or ""
    profile = _default_profile()
    profile["resume_file_name"] = file_name or "resume"
    profile["full_name"] = _extract_name(resume_text)
    profile["skills"] = _extract_skills(resume_text)
    profile["overall_experience_years"] = _extract_experience(resume_text)
    profile["key_search_keywords"] = _build_keywords(profile["skills"])
    profile["job_titles"] = _derive_job_titles_from_skills(profile["skills"])
    return profile


def _extract_text_from_uploaded_file(file_name: str, mime_type: str, file_base64: str, resume_text: str) -> str:
    # Prefer explicit text payload for plain-text uploads.
    if resume_text and resume_text.strip():
        return resume_text

    if not file_base64:
        return ""

    ext = (os.path.splitext(file_name or "")[1] or "").lower()
    is_pdf = ext == ".pdf" or (mime_type or "").lower() == "application/pdf"
    if not is_pdf:
        return resume_text or ""

    try:
        raw = base64.b64decode(file_base64)
        reader = PdfReader(io.BytesIO(raw))
        chunks = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                chunks.append(page_text)
        return "\n".join(chunks).strip()
    except Exception as e:
        logger.warning(f"PDF parsing failed for '{file_name}': {e}")
        return ""


def _build_resume_summary_fallback(profile: dict, resume_text: str) -> list[str]:
    name = profile.get("full_name") or "The candidate"
    exp = profile.get("overall_experience_years") or "multiple"
    skills = profile.get("skills") or []
    top_skills = ", ".join(skills[:8]) if skills else "cloud, automation, and engineering skills"
    keywords = profile.get("key_search_keywords") or []
    top_keywords = ", ".join(keywords[:5]) if keywords else "DevOps Engineer, Cloud Engineer, Platform Engineer"
    salary_min = profile.get("salary_min_lpa") or ""
    salary_max = profile.get("salary_max_lpa") or ""
    notice_period = profile.get("notice_period") or ""

    salary_text = ""
    if salary_min and salary_max:
        salary_text = f" The candidate salary expectation is around {salary_min}-{salary_max} LPA."
    elif salary_min:
        salary_text = f" The candidate salary expectation is around {salary_min} LPA."

    notice_text = ""
    if notice_period:
        notice_text = f" The candidate notice period is {notice_period}."

    p1 = (
        f"{name} appears to have around {exp} years of experience with a strong focus on modern engineering practices. "
        f"Core strengths identified from the resume include {top_skills}."
    )
    p2 = (
        f"Based on the resume, suitable job search directions include roles around {top_keywords}."
        f" These keywords can be used to target better-matching opportunities in the Automatic Job Apply workflow.{salary_text}{notice_text}"
    )
    return [p1, p2]


def _build_resume_summary_with_ai(profile: dict, resume_text: str) -> list[str] | None:
    if not resume_text.strip():
        return None
    if not Config.AZURE_OPENAI_ENDPOINT or not Config.AZURE_OPENAI_KEY:
        return None

    try:
        client = AzureOpenAI(
            azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
            api_key=Config.AZURE_OPENAI_KEY,
            api_version=Config.AZURE_OPENAI_API_VERSION,
        )

        profile_json = json.dumps(profile, ensure_ascii=False)
        prompt = f"""Create a professional summary of this resume in exactly 2 concise paragraphs.

Rules:
- Return ONLY valid JSON with this schema:
  {{"summary_paragraphs": ["paragraph 1", "paragraph 2"]}}
- Keep both paragraphs factual and based on the resume/profile.
- Mention role fit, strengths, and likely search direction.
- Do not use markdown.

Structured profile:
{profile_json}

Resume text:
{resume_text[:9000]}
"""

        response = client.chat.completions.create(
            model=Config.AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "You write concise professional resume summaries and return strict JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_completion_tokens=400,
        )

        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.strip("`")
            content = content.replace("json", "", 1).strip()

        parsed = json.loads(content)
        paragraphs = [str(p).strip() for p in (parsed.get("summary_paragraphs") or []) if str(p).strip()]
        if len(paragraphs) >= 2:
            return [paragraphs[0], paragraphs[1]]
        return None
    except Exception as e:
        logger.warning(f"AI resume summary generation failed, falling back to template summary: {e}")
        return None


def _analyze_resume_with_ai(file_name: str, resume_text: str) -> dict | None:
    if not resume_text.strip():
        return None
    if not Config.AZURE_OPENAI_ENDPOINT or not Config.AZURE_OPENAI_KEY:
        return None

    try:
        client = AzureOpenAI(
            azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
            api_key=Config.AZURE_OPENAI_KEY,
            api_version=Config.AZURE_OPENAI_API_VERSION,
        )
        prompt = f"""Extract a structured candidate profile from this resume text.

Return ONLY valid JSON with this exact schema:
{{
  "full_name": "",
  "skills": ["... at least 10 ..."],
    "job_titles": ["... at least 10 ..."],
  "salary_min_lpa": "",
  "salary_max_lpa": "",
  "overall_experience_years": "",
  "key_search_keywords": ["... at least 5 ..."]
}}

Rules:
- skills must include at least 10 items.
- job_titles must include at least 10 job titles relevant to resume skills and experience.
- key_search_keywords must include at least 5 items.
- If salary is not in resume, keep salary_min_lpa and salary_max_lpa empty strings.
- Keep output concise and relevant to job search.

Resume text:
{resume_text[:12000]}
"""
        response = client.chat.completions.create(
            model=Config.AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "You extract resume fields and return strict JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_completion_tokens=700,
        )
        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.strip("`")
            content = content.replace("json", "", 1).strip()

        parsed = json.loads(content)
        profile = _default_profile()
        profile["resume_file_name"] = file_name or "resume"
        profile["full_name"] = str(parsed.get("full_name", "") or "")
        profile["salary_min_lpa"] = str(parsed.get("salary_min_lpa", "") or "")
        profile["salary_max_lpa"] = str(parsed.get("salary_max_lpa", "") or "")
        profile["overall_experience_years"] = str(parsed.get("overall_experience_years", "") or "")
        profile["skills"] = [str(s).strip() for s in (parsed.get("skills") or []) if str(s).strip()]
        profile["job_titles"] = [str(s).strip() for s in (parsed.get("job_titles") or []) if str(s).strip()]
        profile["key_search_keywords"] = [
            str(s).strip() for s in (parsed.get("key_search_keywords") or []) if str(s).strip()
        ][:10]

        if len(profile["skills"]) < 10:
            for s in _extract_skills(resume_text):
                if s not in profile["skills"]:
                    profile["skills"].append(s)
                if len(profile["skills"]) >= 10:
                    break

        if len(profile["key_search_keywords"]) < 5:
            for kw in _build_keywords(profile["skills"]):
                if kw not in profile["key_search_keywords"]:
                    profile["key_search_keywords"].append(kw)
                if len(profile["key_search_keywords"]) >= 5:
                    break

        derived_titles = _derive_job_titles_from_skills(profile["skills"])
        merged_titles = []
        for title in profile["job_titles"] + derived_titles:
            t = str(title).strip()
            if not t:
                continue
            if t.lower() not in [x.lower() for x in merged_titles]:
                merged_titles.append(t)
        profile["job_titles"] = merged_titles[:20]

        return profile
    except Exception as e:
        logger.warning(f"AI resume analysis failed, falling back to heuristic extraction: {e}")
        return None


def _apply_profile_to_runtime(profile: dict):
    Config.YOUR_NAME = str(profile.get("full_name", "") or "")
    Config.YOUR_EXPERIENCE = str(profile.get("overall_experience_years", "") or "")
    Config.YOUR_SKILLS = ", ".join(profile.get("skills", []))
    min_lpa = str(profile.get("salary_min_lpa", "") or "")
    max_lpa = str(profile.get("salary_max_lpa", "") or "")
    if min_lpa and max_lpa:
        Config.YOUR_EXPECTED_CTC = f"{min_lpa}-{max_lpa} LPA"
    elif min_lpa:
        Config.YOUR_EXPECTED_CTC = f"{min_lpa} LPA"
    else:
        Config.YOUR_EXPECTED_CTC = ""
    Config.MIN_MATCH_SCORE = int(profile.get("min_match_score", 60) or 60)
    exp = str(profile.get("overall_experience_years", "") or "")
    if exp:
        Config.EXPERIENCE_YEARS = exp
    notice_period = str(profile.get("notice_period", "") or "").strip()
    if notice_period:
        Config.YOUR_NOTICE_PERIOD = notice_period
    preferred = str(profile.get("preferred_location", "") or "").strip()
    if preferred:
        Config.JOB_LOCATION = preferred


def _write_search_criteria(profile: dict):
    skills = profile.get("skills", [])
    job_titles = profile.get("job_titles", [])
    keywords = profile.get("key_search_keywords", [])
    lines = [
        "Candidate Search Preferences",
        f"Full Name: {profile.get('full_name', '')}",
        f"Overall Experience: {profile.get('overall_experience_years', '')} years",
        f"Salary Expectation Range (LPA): {profile.get('salary_min_lpa', '')} - {profile.get('salary_max_lpa', '')}",
        f"Preferred Location: {profile.get('preferred_location', '')}",
        f"Ready to Relocate: {profile.get('ready_to_relocate', False)}",
        f"Target Cities: {', '.join(profile.get('search_locations', []))}",
        f"Skills: {', '.join(skills)}",
        f"Job Titles to Search: {', '.join(job_titles)}",
        f"Primary Search Keywords: {', '.join(keywords)}",
        "",
        "Use these preferences while matching and applying to jobs.",
    ]
    with open(CRITERIA_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_applied_job_exports(applied_jobs: list[dict]):
    if not applied_jobs:
        return

    json_tmp = None
    csv_tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=".", prefix="applied_jobs_", suffix=".json") as f:
            json.dump(applied_jobs, f, indent=2, ensure_ascii=False)
            json_tmp = f.name
        os.replace(json_tmp, "applied_jobs.json")

        csv_fields = [
            "company_name",
            "role_name",
            "job_link",
            "job_description",
            "key_skills_company_looking_for",
            "salary",
            "experience",
            "match_score",
            "match_reason",
            "questions_asked_and_answers_provided",
            "search_query",
            "status",
        ]
        with tempfile.NamedTemporaryFile("w", delete=False, newline="", encoding="utf-8-sig", dir=".", prefix="applied_jobs_", suffix=".csv") as f:
            csv_tmp = f.name
            writer = csv.DictWriter(f, fieldnames=csv_fields)
            writer.writeheader()
            for item in applied_jobs:
                qa_pairs = item.get("questions_answers") or []
                qa_text = " | ".join(
                    f"Q: {qa.get('question', '').strip()} -> A: {qa.get('answer', '').strip()}"
                    for qa in qa_pairs
                    if qa.get("question") and qa.get("answer")
                )
                writer.writerow({
                    "company_name": item.get("company", ""),
                    "role_name": item.get("title", ""),
                    "job_link": item.get("url", ""),
                    "job_description": item.get("job_description", ""),
                    "key_skills_company_looking_for": item.get("key_skills", ""),
                    "salary": item.get("salary", ""),
                    "experience": item.get("experience", ""),
                    "match_score": item.get("match_score", ""),
                    "match_reason": item.get("match_reason", ""),
                    "questions_asked_and_answers_provided": qa_text,
                    "search_query": item.get("search_query", ""),
                    "status": item.get("status", ""),
                })
        os.replace(csv_tmp, "applied_jobs_detailed.csv")
    finally:
        for tmp_path in (json_tmp, csv_tmp):
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass


def _write_linkedin_applied_job_exports(applied_jobs: list[dict]):
    if not applied_jobs:
        return

    json_tmp = None
    csv_tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=".", prefix="linkedin_applied_jobs_", suffix=".json") as f:
            json.dump(applied_jobs, f, indent=2, ensure_ascii=False)
            json_tmp = f.name
        os.replace(json_tmp, "linkedin_applied_jobs.json")

        csv_fields = [
            "company_name",
            "role_name",
            "job_link",
            "job_description",
            "key_skills_company_looking_for",
            "salary",
            "experience",
            "match_score",
            "match_reason",
            "questions_asked_and_answers_provided",
            "search_query",
            "status",
        ]
        with tempfile.NamedTemporaryFile("w", delete=False, newline="", encoding="utf-8-sig", dir=".", prefix="linkedin_applied_jobs_", suffix=".csv") as f:
            csv_tmp = f.name
            writer = csv.DictWriter(f, fieldnames=csv_fields)
            writer.writeheader()
            for item in applied_jobs:
                qa_pairs = item.get("questions_answers") or []
                qa_text = " | ".join(
                    f"Q: {qa.get('question', '').strip()} -> A: {qa.get('answer', '').strip()}"
                    for qa in qa_pairs
                    if qa.get("question") and qa.get("answer")
                )
                writer.writerow({
                    "company_name": item.get("company", ""),
                    "role_name": item.get("title", ""),
                    "job_link": item.get("url", ""),
                    "job_description": item.get("job_description", ""),
                    "key_skills_company_looking_for": item.get("key_skills", ""),
                    "salary": item.get("salary", ""),
                    "experience": item.get("experience", ""),
                    "match_score": item.get("match_score", ""),
                    "match_reason": item.get("match_reason", ""),
                    "questions_asked_and_answers_provided": qa_text,
                    "search_query": item.get("search_query", ""),
                    "status": item.get("status", ""),
                })
        os.replace(csv_tmp, "linkedin_applied_jobs_detailed.csv")
    finally:
        for tmp_path in (json_tmp, csv_tmp):
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass


def _get_search_queries() -> list[tuple[str, str]]:
    profile = state.saved_profile or _default_profile()
    titles = [str(t).strip() for t in (profile.get("job_titles") or []) if str(t).strip()]
    if not titles:
        titles = [str(k).strip() for k in (profile.get("key_search_keywords") or []) if str(k).strip()]
    if not titles:
        return []

    locations = _normalize_location_list(profile.get("search_locations") or [])
    if not locations:
        preferred = str(profile.get("preferred_location", "") or "").strip()
        if preferred:
            locations = [preferred]

    priority_order = ["hyderabad", "bangalore", "chennai"]
    ordered_locations = []
    for priority in priority_order:
        for loc in locations:
            if loc.lower() == priority and loc not in ordered_locations:
                ordered_locations.append(loc)
    for loc in locations:
        if loc not in ordered_locations:
            ordered_locations.append(loc)

    if not ordered_locations:
        return []

    dynamic = []
    for location in ordered_locations[:15]:
        for title in titles[:20]:
            dynamic.append((title, location.lower()))
    return dynamic


class AgentState:
    def __init__(self):
        self.browser = None
        self.is_running = False
        self.is_logged_in = False
        self.should_stop = False
        self.linkedin_browser = None
        self.linkedin_is_running = False
        self.linkedin_is_logged_in = False
        self.linkedin_should_stop = False
        self.clients: set[WebSocket] = set()
        self.jobs: list[dict] = []
        self.linkedin_jobs: list[dict] = []
        self.stats = _default_stats()
        self.linkedin_stats = _default_stats()
        self.saved_profile = _read_saved_profile()


state = AgentState()
_apply_profile_to_runtime(state.saved_profile)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if state.browser:
        try:
            await state.browser.close()
        except Exception:
            pass
    if state.linkedin_browser:
        try:
            await state.linkedin_browser.close()
        except Exception:
            pass


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve React app static files (react.js, react-dom.js, babel.js)
_webapp_dir = os.path.join(os.path.dirname(__file__), "webapp")
_static_dir = os.path.join(_webapp_dir, "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

@app.get("/")
async def serve_index():
    index = os.path.join(_webapp_dir, "index.html")
    return FileResponse(index, media_type="text/html")


@app.get("/linkedin/debug-readiness")
async def linkedin_debug_readiness():
    if not os.path.exists(LINKEDIN_DEBUG_RESULTS_PATH):
        return {
            "ok": False,
            "message": "LinkedIn debug results file not found. Run debug_extract_linkedin_structure.py first.",
            "automation_readiness": {},
        }

    try:
        with open(LINKEDIN_DEBUG_RESULTS_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)

        return {
            "ok": True,
            "captured_at": payload.get("captured_at", ""),
            "seed_url": payload.get("seed_url", ""),
            "automation_readiness": payload.get("automation_readiness", {}),
            "notes": payload.get("notes", []),
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Failed to read LinkedIn debug results: {exc}",
            "automation_readiness": {},
        }


@app.get("/linkedin/deep-inspection")
async def linkedin_deep_inspection():
    if not os.path.exists(LINKEDIN_DEEP_INSPECTION_PATH):
        return {
            "ok": False,
            "message": "Deep inspection file not found. Run debug_linkedin_apply_flow.py first.",
            "report": {},
        }

    try:
        with open(LINKEDIN_DEEP_INSPECTION_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return {
            "ok": True,
            "report": payload,
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Failed to read deep inspection report: {exc}",
            "report": {},
        }


async def broadcast(data: dict):
    msg = json.dumps(data, default=str)
    dead = set()
    for ws in state.clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    state.clients -= dead


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    state.clients.add(ws)

    # Send current state on connect
    await ws.send_text(json.dumps({
        "type": "init",
        "browser_launched": state.browser is not None,
        "logged_in": state.is_logged_in,
        "is_running": state.is_running,
        "jobs": state.jobs,
        "stats": state.stats,
        "linkedin_browser_launched": state.linkedin_browser is not None,
        "linkedin_logged_in": state.linkedin_is_logged_in,
        "linkedin_is_running": state.linkedin_is_running,
        "linkedin_jobs": state.linkedin_jobs,
        "linkedin_stats": state.linkedin_stats,
        "saved_profile": state.saved_profile,
    }, default=str))

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            action = msg.get("action")

            if action == "launch_browser":
                asyncio.create_task(launch_browser())
            elif action == "launch_browser_linkedin":
                asyncio.create_task(launch_linkedin_browser())
            elif action == "verify_login":
                asyncio.create_task(verify_login())
            elif action == "verify_login_linkedin":
                asyncio.create_task(verify_linkedin_login())
            elif action == "start":
                if not state.is_running:
                    state.should_stop = False
                    asyncio.create_task(run_agent())
            elif action == "start_linkedin":
                if not state.linkedin_is_running:
                    state.linkedin_should_stop = False
                    asyncio.create_task(run_linkedin_agent())
            elif action == "stop":
                state.should_stop = True
                state.is_running = False
                await broadcast({"type": "agent_stopped", "stats": state.stats,
                                 "message": "Agent stopped by user."})
            elif action == "stop_linkedin":
                state.linkedin_should_stop = True
                state.linkedin_is_running = False
                await broadcast({
                    "type": "linkedin_agent_stopped",
                    "stats": state.linkedin_stats,
                    "message": "LinkedIn agent stopped by user.",
                })
            elif action == "analyze_resume":
                resume_text = msg.get("resume_text", "")
                file_name = msg.get("file_name", "resume")
                mime_type = msg.get("mime_type", "")
                file_base64 = msg.get("file_base64", "")
                effective_text = _extract_text_from_uploaded_file(
                    file_name=file_name,
                    mime_type=mime_type,
                    file_base64=file_base64,
                    resume_text=resume_text,
                )

                if len((effective_text or "").strip()) < 80:
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "message": "Could not extract enough text from the uploaded resume. Please upload a text-based PDF (not scanned image) or try another file.",
                    }))
                    continue

                profile = _analyze_resume_with_ai(file_name, effective_text)
                if not profile:
                    profile = _analyze_resume_text(file_name, effective_text)

                if not profile.get("skills"):
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "message": "No skills could be extracted from this PDF. Please upload a clearer text PDF or edit skills manually.",
                    }))
                    continue

                if not profile.get("key_search_keywords"):
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "message": "No job keywords could be extracted from this PDF. Please edit keywords manually after upload.",
                    }))
                    continue

                summary_paragraphs = _build_resume_summary_with_ai(profile, effective_text)
                if not summary_paragraphs:
                    summary_paragraphs = _build_resume_summary_fallback(profile, effective_text)
                await ws.send_text(json.dumps({
                    "type": "resume_analyzed",
                    "profile": profile,
                    "summary_paragraphs": summary_paragraphs,
                    "message": "Resume analyzed. Review and edit the fields before saving.",
                }))
            elif action == "save_profile":
                incoming = msg.get("profile") or {}
                profile = _default_profile()
                profile.update(incoming)
                profile["skills"] = [str(s).strip() for s in profile.get("skills", []) if str(s).strip()]
                profile["job_titles"] = [str(t).strip() for t in profile.get("job_titles", []) if str(t).strip()][:20]
                profile["key_search_keywords"] = [
                    str(k).strip() for k in profile.get("key_search_keywords", []) if str(k).strip()
                ][:10]
                derived_titles = _derive_job_titles_from_skills(profile["skills"])
                merged_titles = []
                for title in profile["job_titles"] + derived_titles:
                    t = str(title).strip()
                    if not t:
                        continue
                    if t.lower() not in [x.lower() for x in merged_titles]:
                        merged_titles.append(t)
                profile["job_titles"] = merged_titles[:20]
                profile["preferred_location"] = str(profile.get("preferred_location", "") or "").strip() or "Hyderabad"
                profile["ready_to_relocate"] = bool(profile.get("ready_to_relocate", False))
                profile["notice_period"] = str(profile.get("notice_period", "") or "").strip()
                locations = _normalize_location_list(profile.get("search_locations") or [])
                if not locations:
                    locations = _default_profile()["search_locations"]
                profile["search_locations"] = locations[:15]
                _write_saved_profile(profile)
                _write_search_criteria(profile)
                _apply_profile_to_runtime(profile)
                state.saved_profile = profile
                await broadcast({
                    "type": "profile_saved",
                    "profile": profile,
                    "message": "Profile saved. Automatic Job Apply will use this profile.",
                })
    except WebSocketDisconnect:
        state.clients.discard(ws)


async def launch_browser():
    try:
        if state.browser:
            try:
                await state.browser.close()
            except Exception:
                pass
        state.browser = NaukriBrowser()
        await state.browser.launch()
        await state.browser.page.goto("https://www.naukri.com/")
        await state.browser.page.wait_for_load_state("networkidle")
        await broadcast({
            "type": "browser_status", "launched": True,
            "message": "Browser launched. Please login to Naukri.com in the browser window.",
        })
        logger.info("Browser launched for webapp")
    except Exception as e:
        logger.error(f"Browser launch error: {e}")
        await broadcast({
            "type": "browser_status", "launched": False,
            "message": f"Failed to launch browser: {e}",
        })


async def verify_login():
    if not state.browser or not state.browser.page:
        await broadcast({"type": "login_status", "logged_in": False,
                         "message": "Launch browser first."})
        return
    try:
        await state.browser.page.wait_for_selector(
            'a[href*="mnjuser"], .nI-gNb-header__right--loggedIn, .view-profile-wrapper',
            timeout=5000,
        )
        state.is_logged_in = True
        await broadcast({"type": "login_status", "logged_in": True,
                         "message": "Login verified! You can now start applying."})
        logger.info("Login verified via webapp")
    except Exception:
        state.is_logged_in = False
        await broadcast({"type": "login_status", "logged_in": False,
                         "message": "Login not detected. Please login in the browser window and try again."})


async def launch_linkedin_browser():
    try:
        if state.linkedin_browser:
            try:
                await state.linkedin_browser.close()
            except Exception:
                pass
        state.linkedin_browser = LinkedInBrowser()
        await state.linkedin_browser.launch()
        logged_in = await state.linkedin_browser.wait_for_login()
        state.linkedin_is_logged_in = bool(logged_in)
        await broadcast({
            "type": "linkedin_browser_status",
            "launched": True,
            "message": (
                "LinkedIn browser launched. Please login manually in this browser window, "
                "then click Verify Login."
            ),
        })
        logger.info("LinkedIn browser launched for webapp")
    except Exception as e:
        logger.error(f"LinkedIn browser launch error: {e}")
        await broadcast({
            "type": "linkedin_browser_status",
            "launched": False,
            "message": f"Failed to launch LinkedIn browser: {e}",
        })


async def verify_linkedin_login():
    if not state.linkedin_browser or not state.linkedin_browser.page:
        await broadcast({
            "type": "linkedin_login_status",
            "logged_in": False,
            "message": "Launch LinkedIn browser first.",
        })
        return

    try:
        state.linkedin_is_logged_in = await state.linkedin_browser.wait_for_login()
        if not state.linkedin_is_logged_in:
            await broadcast({
                "type": "linkedin_login_status",
                "logged_in": False,
                "message": "Login not detected. Please sign in to LinkedIn in the browser window and verify again.",
            })
            return
        await broadcast({
            "type": "linkedin_login_status",
            "logged_in": True,
            "message": "LinkedIn login verified. You can start LinkedIn Auto Apply.",
        })
        logger.info("LinkedIn login verified")
    except Exception:
        state.linkedin_is_logged_in = False
        await broadcast({
            "type": "linkedin_login_status",
            "logged_in": False,
            "message": "LinkedIn login not detected. Please login in browser and verify again.",
        })


async def run_linkedin_agent():
    state.linkedin_is_running = True
    state.linkedin_jobs = []
    state.linkedin_stats = _default_stats()

    try:
        if state.linkedin_browser and state.linkedin_browser.page:
            await state.linkedin_browser.page.evaluate("1")
    except Exception:
        logger.warning("LinkedIn browser connection stale, re-launching...")
        await broadcast({"type": "log", "message": "LinkedIn browser lost. Re-launching..."})
        try:
            if state.linkedin_browser:
                try:
                    await state.linkedin_browser.close()
                except Exception:
                    pass
            state.linkedin_browser = LinkedInBrowser()
            await state.linkedin_browser.launch()
            await state.linkedin_browser.page.goto("https://www.linkedin.com/jobs/")
            await state.linkedin_browser.page.wait_for_load_state("networkidle")
            try:
                await state.linkedin_browser.page.wait_for_selector(
                    'a[href*="/feed"], a[href*="/mynetwork"], button[aria-label*="Me"]',
                    timeout=5000,
                )
                state.linkedin_is_logged_in = True
            except Exception:
                state.linkedin_is_logged_in = False
                state.linkedin_is_running = False
                await broadcast({"type": "error", "message": "LinkedIn browser re-launched but login expired."})
                await broadcast({
                    "type": "linkedin_browser_status",
                    "launched": True,
                    "message": "LinkedIn browser re-launched. Please login again.",
                })
                return
        except Exception as e:
            state.linkedin_is_running = False
            await broadcast({"type": "error", "message": f"Failed to re-launch LinkedIn browser: {e}"})
            return

    page = state.linkedin_browser.page
    searcher = LinkedInJobSearcher(page)
    applicant = LinkedInJobApplicant(page)

    seen_urls = set()

    await broadcast({
        "type": "linkedin_agent_started",
        "message": "LinkedIn agent started. Searching and applying in parallel with Naukri if enabled.",
    })

    try:
        search_queries = _get_search_queries()
        if not search_queries:
            state.linkedin_is_running = False
            await broadcast({
                "type": "error",
                "message": "No saved resume-based keywords found for LinkedIn. Save profile in HOME tab first.",
            })
            await broadcast({
                "type": "linkedin_agent_stopped",
                "stats": state.linkedin_stats,
                "message": "LinkedIn agent stopped: missing profile keywords.",
            })
            return

        round_num = 0
        while not state.linkedin_should_stop and state.linkedin_stats["applied"] < Config.MAX_APPLICATIONS:
            round_num += 1

            for qi, (keywords, location) in enumerate(search_queries, 1):
                if state.linkedin_should_stop or state.linkedin_stats["applied"] >= Config.MAX_APPLICATIONS:
                    break

                state.linkedin_stats["current_query"] = (
                    f"{keywords} in {location} [{qi}/{len(search_queries)}] (Round {round_num})"
                )
                await broadcast({
                    "type": "linkedin_search_query",
                    "query_number": qi,
                    "total_queries": len(search_queries),
                    "keywords": keywords,
                    "location": location,
                })

                for page_no in range(1, 4):
                    if state.linkedin_should_stop or state.linkedin_stats["applied"] >= Config.MAX_APPLICATIONS:
                        break

                    jobs = await searcher.search_jobs(page_no=page_no, keywords=keywords, location=location)
                    if not jobs:
                        break

                    new_jobs = []
                    for job in jobs:
                        u = str(job.get("url", "")).split("?")[0]
                        if u and u not in seen_urls:
                            seen_urls.add(u)
                            new_jobs.append(job)

                    if not new_jobs:
                        break

                    for job in new_jobs:
                        if state.linkedin_should_stop or state.linkedin_stats["applied"] >= Config.MAX_APPLICATIONS:
                            break

                        state.linkedin_stats["evaluated"] += 1
                        job_entry = {
                            "id": state.linkedin_stats["evaluated"],
                            "title": job.get("title", ""),
                            "company": job.get("company", ""),
                            "location": job.get("location", "N/A"),
                            "salary": job.get("salary", "N/A"),
                            "experience": job.get("experience", "N/A"),
                            "skills": job.get("skills", "N/A")[:150],
                            "key_skills": job.get("skills", ""),
                            "url": job.get("url", ""),
                            "job_description": "",
                            "questions_answers": [],
                            "match_score": None,
                            "match_reason": "",
                            "status": "Evaluating...",
                            "search_query": f"{keywords} in {location}",
                        }
                        state.linkedin_jobs.append(job_entry)
                        await broadcast({
                            "type": "linkedin_job_update",
                            "job": job_entry,
                            "stats": state.linkedin_stats,
                        })

                        try:
                            _min_match = getattr(Config, 'MIN_MATCH_SCORE', 60)
                            success = await applicant.apply_to_job(job, min_match_pct=_min_match)

                            job_entry["match_score"] = applicant.last_match_score
                            job_entry["match_reason"] = applicant.last_match_reason
                            job_entry["job_description"] = applicant.last_full_jd
                            job_entry["questions_answers"] = applicant.last_qa_pairs

                            if success:
                                state.linkedin_stats["applied"] += 1
                                job_entry["status"] = "Applied ✓"
                                try:
                                    _write_linkedin_applied_job_exports(
                                        [j for j in state.linkedin_jobs if "Applied" in j.get("status", "")]
                                    )
                                except Exception as export_error:
                                    logger.warning(f"LinkedIn export failed after success: {export_error}")
                            else:
                                skip_reason = applicant.last_skip_reason
                                if skip_reason == "already_applied":
                                    state.linkedin_stats["already_applied"] += 1
                                    job_entry["status"] = "Skipped (Already Applied)"
                                elif skip_reason == "salary_below_min":
                                    state.linkedin_stats["skipped"] += 1
                                    job_entry["status"] = "Skipped (Salary Below Minimum)"
                                elif skip_reason == "salary_missing_experience_mismatch":
                                    state.linkedin_stats["skipped"] += 1
                                    job_entry["status"] = "Skipped (No Salary + Experience Mismatch)"
                                elif skip_reason == "no_easy_apply":
                                    state.linkedin_stats["skipped"] += 1
                                    job_entry["status"] = "Skipped (No Easy Apply)"
                                elif skip_reason == "button_disabled":
                                    state.linkedin_stats["skipped"] += 1
                                    job_entry["status"] = "Skipped (Button Disabled)"
                                elif skip_reason == "low_score" or applicant.last_match_score < _min_match:
                                    state.linkedin_stats["skipped"] += 1
                                    job_entry["status"] = "Skipped (Low Score)"
                                else:
                                    state.linkedin_stats["skipped"] += 1
                                    job_entry["status"] = "Skipped"
                        except Exception as e:
                            state.linkedin_stats["skipped"] += 1
                            job_entry["match_score"] = applicant.last_match_score
                            job_entry["match_reason"] = str(e)
                            job_entry["status"] = "Error"
                            logger.error(f"LinkedIn job processing error: {e}")

                        await broadcast({
                            "type": "linkedin_job_update",
                            "job": job_entry,
                            "stats": state.linkedin_stats,
                        })
                        await linkedin_human_delay(2.0, 5.0)

    except Exception as e:
        logger.error(f"LinkedIn agent error: {e}", exc_info=True)
        await broadcast({"type": "error", "message": f"LinkedIn agent error: {e}"})

    state.linkedin_is_running = False

    applied = [j for j in state.linkedin_jobs if "Applied" in j.get("status", "")]
    try:
        _write_linkedin_applied_job_exports(applied)
    except Exception as export_error:
        logger.warning(f"Final LinkedIn export failed: {export_error}")

    await broadcast({
        "type": "linkedin_agent_completed",
        "stats": state.linkedin_stats,
        "message": (
            f"LinkedIn completed. Applied: {state.linkedin_stats['applied']}, "
            f"Skipped: {state.linkedin_stats['skipped']}, Evaluated: {state.linkedin_stats['evaluated']}"
        ),
    })


async def run_agent():
    state.is_running = True
    state.jobs = []
    state.stats = {"applied": 0, "skipped": 0, "already_applied": 0, "evaluated": 0, "current_query": ""}

    # Verify browser page is still alive; re-launch if stale
    try:
        if state.browser and state.browser.page:
            await state.browser.page.evaluate("1")  # quick health check
    except Exception:
        logger.warning("Browser connection is stale, re-launching...")
        await broadcast({"type": "log", "message": "Browser connection lost. Re-launching..."})
        try:
            if state.browser:
                try:
                    await state.browser.close()
                except Exception:
                    pass
            state.browser = NaukriBrowser()
            await state.browser.launch()
            await state.browser.page.goto("https://www.naukri.com/")
            await state.browser.page.wait_for_load_state("networkidle")
            # Re-verify login
            try:
                await state.browser.page.wait_for_selector(
                    'a[href*="mnjuser"], .nI-gNb-header__right--loggedIn, .view-profile-wrapper',
                    timeout=5000,
                )
                state.is_logged_in = True
            except Exception:
                state.is_logged_in = False
                state.is_running = False
                await broadcast({"type": "error",
                                 "message": "Browser re-launched but login expired. Please login again."})
                await broadcast({"type": "browser_status", "launched": True,
                                 "message": "Browser re-launched. Please login again."})
                return
        except Exception as e:
            state.is_running = False
            await broadcast({"type": "error", "message": f"Failed to re-launch browser: {e}"})
            return

    page = state.browser.page
    searcher = JobSearcher(page)
    applicant = JobApplicant(page)

    seen_job_ids = set()

    await broadcast({"type": "agent_started",
                     "message": "Agent started. Searching for jobs..."})
    logger.info("Agent started via webapp")

    try:
        search_queries = _get_search_queries()
        if not search_queries:
            state.is_running = False
            await broadcast({
                "type": "error",
                "message": "No saved resume-based keywords found. Upload PDF in HOME tab, verify fields, and save profile before starting.",
            })
            await broadcast({"type": "agent_stopped", "stats": state.stats,
                             "message": "Agent stopped: missing resume-based keywords."})
            return

        round_num = 0
        while not state.should_stop and state.stats["applied"] < Config.MAX_APPLICATIONS:
            round_num += 1
            if round_num > 1:
                await broadcast({"type": "log",
                                 "message": f"--- Round {round_num}: Re-running all search queries (Applied: {state.stats['applied']}/{Config.MAX_APPLICATIONS}) ---"})
                logger.info(f"Starting round {round_num}")

            for qi, (keywords, location) in enumerate(search_queries, 1):
                if state.should_stop or state.stats["applied"] >= Config.MAX_APPLICATIONS:
                    break

                state.stats["current_query"] = f"{keywords} in {location} [{qi}/{len(search_queries)}] (Round {round_num})"
                await broadcast({
                    "type": "search_query",
                    "query_number": qi,
                    "total_queries": len(search_queries),
                    "keywords": keywords,
                    "location": location,
                })

                for page_no in range(1, 4):
                    if state.should_stop or state.stats["applied"] >= Config.MAX_APPLICATIONS:
                        break

                    jobs = await searcher.search_jobs(
                        page_no=page_no, keywords=keywords, location=location
                    )
                    if not jobs:
                        if page_no == 1:
                            await broadcast({
                                "type": "log",
                                "message": f"No jobs found for '{keywords}' in {location}",
                            })
                        break

                    new_jobs = []
                    for j in jobs:
                        jid = j.get("jobId", j["url"])
                        if jid not in seen_job_ids:
                            seen_job_ids.add(jid)
                            new_jobs.append(j)

                    if not new_jobs:
                        break

                    await broadcast({
                        "type": "log",
                        "message": (f"Page {page_no}: {len(new_jobs)} new jobs "
                                    f"({len(jobs) - len(new_jobs)} duplicates filtered)"),
                    })

                    for job in new_jobs:
                        if state.should_stop or state.stats["applied"] >= Config.MAX_APPLICATIONS:
                            break

                        state.stats["evaluated"] += 1
                        job_entry = {
                            "id": state.stats["evaluated"],
                            "title": job["title"],
                            "company": job["company"],
                            "location": job.get("location", "N/A"),
                            "salary": job.get("salary", "N/A"),
                            "experience": job.get("experience", "N/A"),
                            "skills": job.get("skills", "N/A")[:150],
                            "key_skills": job.get("skills", ""),
                            "url": job.get("url", ""),
                            "job_description": "",
                            "questions_answers": [],
                            "match_score": None,
                            "match_reason": "",
                            "status": "Evaluating...",
                            "search_query": f"{keywords} in {location}",
                        }
                        state.jobs.append(job_entry)
                        await broadcast({"type": "job_update", "job": job_entry,
                                         "stats": state.stats})

                        try:
                            _min_match = getattr(Config, 'MIN_MATCH_SCORE', 60)
                            success = await applicant.apply_to_job(job, min_match_pct=_min_match)

                            job_entry["match_score"] = applicant.last_match_score
                            job_entry["match_reason"] = applicant.last_match_reason
                            job_entry["job_description"] = applicant.last_full_jd
                            job_entry["questions_answers"] = applicant.last_qa_pairs

                            if success:
                                state.stats["applied"] += 1
                                job_entry["status"] = "Applied ✓"
                                try:
                                    _write_applied_job_exports([j for j in state.jobs if "Applied" in j.get("status", "")])
                                except Exception as export_error:
                                    logger.warning(f"Applied-job export failed after success: {export_error}")
                            else:
                                skip_reason = applicant.last_skip_reason
                                if skip_reason == "already_applied":
                                    state.stats["already_applied"] += 1
                                    job_entry["status"] = "Skipped (Already Applied)"
                                elif skip_reason == "salary_below_min":
                                    state.stats["skipped"] += 1
                                    job_entry["status"] = "Skipped (Salary Below Minimum)"
                                elif skip_reason == "salary_missing_experience_mismatch":
                                    state.stats["skipped"] += 1
                                    job_entry["status"] = "Skipped (No Salary + Experience Mismatch)"
                                elif skip_reason == "low_score" or applicant.last_match_score < _min_match:
                                    state.stats["skipped"] += 1
                                    job_entry["status"] = "Skipped (Low Score)"
                                elif skip_reason == "no_button":
                                    state.stats["skipped"] += 1
                                    job_entry["status"] = "Skipped (No Apply Button)"
                                elif skip_reason == "button_disabled":
                                    state.stats["skipped"] += 1
                                    job_entry["status"] = "Skipped (Button Disabled)"
                                else:
                                    state.stats["skipped"] += 1
                                    job_entry["status"] = "Skipped"
                        except Exception as e:
                            state.stats["skipped"] += 1
                            job_entry["match_score"] = applicant.last_match_score
                            job_entry["match_reason"] = str(e)
                            job_entry["status"] = "Error"
                            logger.error(f"Error processing job: {e}")

                        await broadcast({"type": "job_update", "job": job_entry,
                                         "stats": state.stats})
                        await asyncio.sleep(random.uniform(3.0, 8.0))

    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        await broadcast({"type": "error", "message": str(e)})

    state.is_running = False

    # Save results
    applied = [j for j in state.jobs if "Applied" in j.get("status", "")]
    try:
        _write_applied_job_exports(applied)
    except Exception as export_error:
        logger.warning(f"Final applied-job export failed: {export_error}")

    quota_reached = state.stats["applied"] >= Config.MAX_APPLICATIONS
    if quota_reached:
        msg = f"\u2705 Today's quota completed! Applied to {state.stats['applied']} jobs. Evaluated: {state.stats['evaluated']}, Skipped: {state.stats['skipped']}"
    else:
        msg = f"Agent completed. Applied: {state.stats['applied']}, Skipped: {state.stats['skipped']}, Evaluated: {state.stats['evaluated']}"

    await broadcast({
        "type": "agent_completed",
        "stats": state.stats,
        "message": msg,
    })
    logger.info(f"Agent completed: {state.stats}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

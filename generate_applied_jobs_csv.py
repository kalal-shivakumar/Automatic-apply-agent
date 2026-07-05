import asyncio
import csv
import html
import json
import re
from pathlib import Path
from typing import Any
from datetime import datetime

import httpx
import websockets

ROOT = Path(__file__).resolve().parent
APPLIED_JSON = ROOT / "applied_jobs.json"
OUTPUT_CSV = ROOT / "applied_jobs_detailed.csv"

QA_BY_URL = {
    "https://www.naukri.com/job-listings-devops-engineer-github-action-fastenal-bengaluru-5-to-8-years-020726016519": [
        ("How many years of experience do you have in Linux?", "5"),
        ("How many years of experience do you have in Github Actions?", "0"),
        ("How many years of experience do you have in JIRA?", "5"),
        ("How many years of experience in cloud platform and which cloud?", "5"),
    ],
    "https://www.naukri.com/job-listings-gcp-lead-infosys-limited-bengaluru-5-to-8-years-010726930161": [],
    "https://www.naukri.com/job-listings-azure-devops-engineer-globant-hyderabad-pune-bengaluru-6-to-11-years-030726012322": [],
    "https://www.naukri.com/job-listings-azure-devops-engineer-mobile-deployment-specialist-cloud-angles-digital-transformation-hyderabad-8-to-16-years-290626019343": [
        ("Are you currently living in or ready to relocate to Hyderabad ?", "Yes"),
        ("How many years of experience do you have in \"Azure Devops\" ?", "10-12 years"),
        ("Do you have experience do you have in Mobile Applications?", "No"),
    ],
    "https://www.naukri.com/job-listings-apim-engineer-applied-information-sciences-ais-hyderabad-7-to-12-years-260526019382": [
        ("How many years of experience do you have in APIM?", "0"),
    ],
    "https://www.naukri.com/job-listings-azure-cloud-with-devops-engineer-esolutionsfirst-hyderabad-8-to-13-years-080126926971": [],
}


def normalize_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


async def fetch_live_state() -> dict[str, Any]:
    try:
        async with websockets.connect("ws://127.0.0.1:8000/ws") as ws:
            payload = await ws.recv()
            return json.loads(payload)
    except Exception:
        return {}


async def fetch_description(client: httpx.AsyncClient, url: str) -> str:
    try:
        response = await client.get(url, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
    except Exception:
        return ""

    html_text = response.text
    scripts = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    for script in scripts:
        try:
            data = json.loads(script)
        except Exception:
            continue

        description = extract_description(data)
        if description:
            return normalize_text(description)

    meta_match = re.search(
        r'<meta[^>]+name="description"[^>]+content="([^"]+)"',
        html_text,
        flags=re.IGNORECASE,
    )
    if meta_match:
        return normalize_text(meta_match.group(1))

    return ""



def extract_description(data: Any) -> str:
    if isinstance(data, dict):
        if isinstance(data.get("description"), str) and data["description"].strip():
            return data["description"]
        for key in ("@graph", "graph", "mainEntity"):
            value = data.get(key)
            description = extract_description(value)
            if description:
                return description
    elif isinstance(data, list):
        for item in data:
            description = extract_description(item)
            if description:
                return description
    return ""


async def main() -> None:
    rows_by_url: dict[str, dict[str, Any]] = {}

    if APPLIED_JSON.exists():
        historical = json.loads(APPLIED_JSON.read_text(encoding="utf-8"))
        for item in historical:
            url = item.get("url", "").strip()
            if url:
                rows_by_url[url] = dict(item)

    live_state = await fetch_live_state()
    for item in live_state.get("jobs", []):
        if "Applied" not in str(item.get("status", "")):
            continue
        url = item.get("url", "").strip()
        if not url:
            continue
        merged = rows_by_url.get(url, {})
        merged.update(item)
        rows_by_url[url] = merged

    urls = list(rows_by_url.keys())
    descriptions: dict[str, str] = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(headers=headers, verify=False) as client:
        for url in urls:
            descriptions[url] = await fetch_description(client, url)

    fieldnames = [
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

    output_path = OUTPUT_CSV
    try:
        csv_file = output_path.open("w", newline="", encoding="utf-8-sig")
    except PermissionError:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = ROOT / f"applied_jobs_detailed_{timestamp}.csv"
        csv_file = output_path.open("w", newline="", encoding="utf-8-sig")

    with csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for url, item in sorted(rows_by_url.items(), key=lambda pair: pair[1].get("id", 0)):
            qas = QA_BY_URL.get(url, [])
            qa_text = " | ".join(f"Q: {q} -> A: {a}" for q, a in qas)
            writer.writerow({
                "company_name": first_non_empty(item.get("company")),
                "role_name": first_non_empty(item.get("title")),
                "job_link": url,
                "job_description": first_non_empty(
                    descriptions.get(url, ""),
                    "Job description could not be exported automatically because Naukri returned Access Denied to standalone scraper requests. Use the job link to view the full JD in the logged-in browser session.",
                ),
                "key_skills_company_looking_for": first_non_empty(item.get("skills")),
                "salary": first_non_empty(item.get("salary")),
                "experience": first_non_empty(item.get("experience")),
                "match_score": first_non_empty(item.get("match_score")),
                "match_reason": first_non_empty(item.get("match_reason")),
                "questions_asked_and_answers_provided": qa_text,
                "search_query": first_non_empty(item.get("search_query")),
                "status": first_non_empty(item.get("status")),
            })

    print(f"Wrote {len(rows_by_url)} rows to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())

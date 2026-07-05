# Naukri AI Job Agent

This project automates job applications on Naukri.com.

## Project Goal

Apply for matching jobs automatically with a profile-driven workflow.

## Website Chosen

- Naukri.com

## What This Project Is About

- Automatic job search and apply pipeline for Naukri
- Web app to control and monitor the automation
- AI-based answers for application questions
- Profile-aware matching before applying

## Core Capabilities

- Searches jobs across configured titles and locations
- Extracts job details and full job description
- Scores relevance with AI using resume/profile criteria
- Auto-skips low-quality or non-matching jobs
- Auto-fills and answers chatbot/application questions
- Writes applied job details to JSON and CSV exports
- Shows live status, match score, and skip reasons in the web UI

## Current Apply Rules

- If salary is below candidate minimum, skip the job
- If salary is not mentioned, apply only when experience matches
- Only proceed when overall match score passes threshold

## Web App Development

The project includes a browser-based dashboard for end-to-end control:

- Upload resume and save HOME/profile values
- Start/stop job application runs
- Observe live run statistics over WebSocket
- View status table with filters, sorting, hyperlinks, and reason text

Main web app files:

- webapp/index.html
- webapp/static/app.jsx
- webapp/static/app.css

## AI Answers

AI answers are generated from profile + question context with strict recruiter-friendly rules:

- Positive, employer-friendly responses
- Integer-only years for experience-count questions
- Profile-based values for notice period, salary, and location
- Generic positive fallback when profile skills are missing
- Fallback events are logged for audit/review

Main AI logic file:

- ai_answerer.py

## Backend and Automation Files

- server.py: FastAPI + WebSocket backend, orchestration, exports
- naukri_agent.py: Search, JD extraction, apply flow, gating/skip logic
- browser.py: Playwright browser/session handling
- config.py: Runtime profile and environment values

## Quick Start

1. Install dependencies:

```bash
pip install -r requirements.txt
playwright install chromium
```

2. Configure environment values in .env (Azure OpenAI + profile defaults).

3. Run the app:

```powershell
.\start-server.ps1
```

4. Open the web UI at:

- http://127.0.0.1:8000/

## Output Files

- applied_jobs.json
- applied_jobs_detailed.csv
- applied_jobs_detailed_*.csv
- job_application_generic_fallbacks.json

## Tech Stack

- Python
- FastAPI + WebSocket
- Playwright
- Azure OpenAI
- React-style frontend (app.jsx)

---

## License

This project is for educational and personal use only. Use responsibly and in compliance with Naukri.com's terms of service.

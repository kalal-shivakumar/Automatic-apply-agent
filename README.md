# Naukri.com AI Job Application Agent

An autonomous AI-powered agent that searches, evaluates, and applies for jobs on [Naukri.com](https://www.naukri.com). It uses **Azure OpenAI (GPT-4o-mini)** to score job relevance against your profile and answer application questionnaires automatically — including Naukri's chatbot, radio buttons, checkboxes, dropdowns, and free-text inputs.

---

## Features

| Feature | Description |
|---|---|
| **Multi-Query Search** | Rotates through 25+ keyword/location combinations (DevOps, SRE, Platform, Cloud Architect, etc.) across Bangalore, Hyderabad, Pune, Chennai, Noida |
| **Fresh Jobs Only** | Filters to jobs posted in the **last 1 day** (`jobAge=1`) |
| **AI Job Scoring** | Extracts full JD (JSON-LD, CSS selectors, JS heuristic) and scores match 0–100% using weighted criteria (skills 35%, role 20%, experience 15%, salary 10%, location 10%, quality 10%) |
| **Threshold Gating** | Only applies to jobs scoring **≥ 65%** match |
| **AI Questionnaire Answering** | Handles Naukri chatbot questions — text inputs, radio buttons, checkboxes, dropdowns, quick-reply chips, and contenteditable divs |
| **Persistent Login** | Playwright persistent browser context preserves login session across runs |
| **Human-Like Behavior** | Random delays, scrolling, and typing speed to avoid bot detection |
| **Stuck Detection** | Detects repeated questions and auto-skips after 3 attempts |
| **Duplicate Filtering** | Tracks seen job IDs across searches to avoid re-processing |
| **Azure OpenAI via Terraform** | IaC-provisioned Azure OpenAI resource and model deployment |

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐     ┌─────────────────┐
│  main.py    │────▶│  browser.py  │────▶│ naukri_agent.py │────▶│ ai_answerer.py  │
│ Orchestrator│     │  Playwright  │     │ Search + Apply  │     │ Azure OpenAI    │
└─────────────┘     │  Browser     │     │ JD Extraction   │     │ Score & Answer  │
                    └──────────────┘     │ Q&A Handling    │     └─────────────────┘
                                         └────────────────┘
                                                │
                                         ┌──────┴───────┐
                                         │  config.py   │
                                         │ .env + Profile│
                                         └──────────────┘
```

### File Structure

| File | Purpose |
|---|---|
| `main.py` | Entry point — defines 25 search queries, orchestrates search → evaluate → apply loop |
| `browser.py` | `NaukriBrowser` class — launches Chromium with persistent context, handles login detection |
| `naukri_agent.py` | `JobSearcher` — intercepts Naukri's `jobapi/v3/search` API responses to extract job listings; `JobApplicant` — navigates job pages, extracts full JD, clicks Apply, handles chatbot/form Q&A flow |
| `ai_answerer.py` | `QuestionAnswerer` — calls Azure OpenAI for job match scoring (0–100%) and answering application questions |
| `config.py` | Loads `.env` variables — Azure OpenAI credentials, job search params, candidate profile |
| `job_search_criteria.txt` | Detailed candidate profile, preferred titles, mandatory skills, evaluation criteria, ranking weights |
| `debug_drawer.py` | Debug utility — inspects Naukri's chatbot drawer DOM (contenteditable elements, inputs, buttons) |
| `debug_questions.py` | Debug utility — tests the full Q&A application flow on a single job |
| `test_apply.py` | Integration test — applies to a specific job with step-by-step verification |
| `terraform/` | Terraform IaC to provision Azure OpenAI resource group, cognitive account, and GPT model deployment |

---

## Prerequisites

- **Python 3.11+**
- **Azure OpenAI** resource with a deployed model (GPT-4o-mini recommended)
- **Naukri.com account** (you'll log in manually on first run)
- **Terraform** (optional, for provisioning Azure OpenAI)

---

## Setup

### 1. Clone & Install

```bash
git clone https://github.com/kalal-shivakumar/AI-Agent-Naukri.git
cd AI-Agent-Naukri
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Environment

Create a `.env` file in the project root:

```env
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_API_VERSION=2024-12-01-preview

# Job Search Defaults (overridden by SEARCH_QUERIES in main.py)
JOB_KEYWORDS=Senior DevOps Engineer
JOB_LOCATION=Bangalore
EXPERIENCE_YEARS=11

# Candidate Profile (used by AI to answer questions)
YOUR_NAME=Your Name
YOUR_EMAIL=your.email@example.com
YOUR_PHONE=+91-XXXXXXXXXX
YOUR_EXPERIENCE=11 years
YOUR_SKILLS=Azure, AWS, Kubernetes, Terraform, Docker, CI/CD, GitHub Actions, ArgoCD, Python, Ansible
YOUR_EDUCATION=B.Tech Computer Science
YOUR_CURRENT_COMPANY=Current Company
YOUR_CURRENT_ROLE=Senior DevOps Engineer
YOUR_NOTICE_PERIOD=60 days
YOUR_EXPECTED_CTC=80 LPA
YOUR_CURRENT_CTC=52 LPA

# Limits
MAX_APPLICATIONS=20
```

### 3. Provision Azure OpenAI (Optional — Terraform)

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your subscription ID

terraform init
terraform plan
terraform apply

# Grab outputs for your .env
terraform output openai_endpoint
terraform output -raw openai_primary_key
```

This creates:
- Resource Group (`rg-naukri-agent`)
- Azure OpenAI Cognitive Account
- GPT-4o-mini model deployment (GlobalStandard SKU, 10K TPM)

### 4. Customize Job Search Criteria

Edit `job_search_criteria.txt` with your profile details, preferred titles, mandatory skills, and evaluation criteria. The AI uses this file to score job relevance.

---

## Usage

### Run the Agent

```bash
python main.py
```

**First run:**
1. A Chromium browser window opens
2. Log in to Naukri.com manually in the browser
3. Press **Enter** in the terminal after logging in
4. The agent begins searching and applying

**Subsequent runs:** Your login session is preserved in `browser_data/` — no re-login needed.

### What Happens

```
For each of 25 search queries:
  For pages 1–3:
    ├─ Intercept Naukri API → extract job listings
    ├─ Filter duplicates (by jobId)
    └─ For each job:
        ├─ Open job page
        ├─ Extract full JD (JSON-LD → CSS selectors → JS heuristic)
        ├─ AI scores match (0–100%)
        ├─ Skip if < 65%
        ├─ Click Apply / Easy Apply
        ├─ Handle chatbot Q&A:
        │   ├─ Text input (contenteditable div)
        │   ├─ Radio buttons
        │   ├─ Checkboxes
        │   ├─ Dropdowns
        │   ├─ Quick-reply chips
        │   └─ Form fields
        └─ Submit application
```

### Output

- **Console** — real-time progress with match scores, questions, and AI answers
- **`agent.log`** — detailed log file
- **`applied_jobs.json`** — JSON array of all successfully applied jobs

### Debug & Testing

```bash
# Inspect chatbot DOM structure for a specific job
python debug_drawer.py

# Test Q&A flow on a single job
python debug_questions.py

# Full apply test with verification
python test_apply.py
```

---

## Configuration Reference

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | Yes | — | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_KEY` | Yes | — | Azure OpenAI API key |
| `AZURE_OPENAI_DEPLOYMENT` | No | `gpt-4o-mini` | Deployed model name |
| `AZURE_OPENAI_API_VERSION` | No | `2024-12-01-preview` | API version |
| `JOB_KEYWORDS` | No | `Python Developer` | Default search keywords |
| `JOB_LOCATION` | No | `Bangalore` | Default location |
| `EXPERIENCE_YEARS` | No | `3` | Experience filter for Naukri search |
| `MAX_APPLICATIONS` | No | `20` | Stop after this many successful applications |
| `YOUR_NAME` | Yes | — | Candidate name |
| `YOUR_EMAIL` | Yes | — | Candidate email |
| `YOUR_PHONE` | Yes | — | Candidate phone |
| `YOUR_EXPERIENCE` | Yes | — | e.g., "11 years" |
| `YOUR_SKILLS` | Yes | — | Comma-separated skill list |
| `YOUR_EDUCATION` | Yes | — | Education details |
| `YOUR_CURRENT_COMPANY` | Yes | — | Current employer |
| `YOUR_CURRENT_ROLE` | Yes | — | Current job title |
| `YOUR_NOTICE_PERIOD` | Yes | — | e.g., "60 days" |
| `YOUR_EXPECTED_CTC` | Yes | — | Expected compensation |
| `YOUR_CURRENT_CTC` | Yes | — | Current compensation |

### Match Scoring Weights

| Criterion | Weight | What It Evaluates |
|---|---|---|
| Skills overlap | 35% | Azure, AWS, Kubernetes, Terraform, CI/CD, Docker match |
| Role/title relevance | 20% | DevOps, Platform, SRE, Cloud, Infrastructure alignment |
| Experience level fit | 15% | 11 years experience match |
| Salary potential | 10% | Target ₹80 LPA achievability |
| Location preference | 10% | Remote / Hyderabad / Bangalore / Pune / Chennai / Noida |
| Company quality | 10% | Avoids support/L1/L2/legacy roles |

---

## Tech Stack

- **Python 3.11+** — async/await throughout
- **Playwright** — browser automation with persistent context
- **Azure OpenAI (GPT-4o-mini)** — job scoring and Q&A answering
- **python-dotenv** — environment configuration
- **Terraform** — Azure infrastructure provisioning

---

## Limitations

- Naukri.com UI changes frequently — CSS selectors may need updates
- External apply links (company websites) are not handled
- CAPTCHA or OTP challenges require manual intervention
- The agent runs in **headed mode** (visible browser) for monitoring
- Rate limiting by Naukri or Azure OpenAI may interrupt long runs

---

## License

This project is for educational and personal use only. Use responsibly and in compliance with Naukri.com's terms of service.

# Naukri.com AI Job Application Agent

An automated AI agent that searches and applies for jobs on Naukri.com, using OpenAI to answer application questionnaires.

## Features

- **Persistent Login** – Uses Playwright persistent browser context, so you only login once
- **AI-Powered Answers** – Uses GPT-4o-mini to answer job application questions based on your profile
- **Smart Job Matching** – Searches based on your keywords, location, and experience
- **Automated Application** – Clicks apply, fills forms, handles chatbot questionnaires

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your details:

```bash
cp .env.example .env
```

Edit `.env` with:
- Your **OpenAI API key**
- Job search preferences (keywords, location, experience)
- Your profile details (used by AI to answer questions)

### 3. Run the Agent

```bash
python main.py
```

On first run:
1. A browser window will open
2. Navigate to Naukri.com and **login manually**
3. Press Enter in the terminal after logging in
4. The agent will start searching and applying

On subsequent runs, your login session is preserved.

## Configuration

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Your OpenAI API key |
| `JOB_KEYWORDS` | Job search keywords (e.g., "Python Developer") |
| `JOB_LOCATION` | Preferred location (e.g., "Bangalore") |
| `EXPERIENCE_YEARS` | Years of experience |
| `MAX_APPLICATIONS` | Max jobs to apply per run |
| `YOUR_*` | Profile fields used by AI to answer questions |

## How It Works

1. **Browser Launch** – Opens Chromium with persistent user data
2. **Login Check** – Verifies you're logged in or prompts manual login
3. **Job Search** – Navigates to Naukri search with your filters
4. **Application Loop** – For each job:
   - Opens the job page
   - Clicks "Apply" / "Easy Apply"
   - Detects questionnaire (chatbot or form style)
   - Uses AI to answer each question based on your profile
   - Submits the application
5. **Pagination** – Moves through search result pages

## Notes

- The agent runs in **headed mode** (visible browser) so you can monitor it
- Logs are saved to `agent.log`
- Press `Ctrl+C` to stop at any time
- Naukri.com UI changes frequently; selectors may need updates

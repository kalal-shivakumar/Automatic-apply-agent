"""FastAPI WebSocket server for the Naukri AI Job Agent webapp."""
import asyncio
import json
import logging
import random
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from browser import NaukriBrowser
from naukri_agent import JobSearcher, JobApplicant, human_delay
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


class AgentState:
    def __init__(self):
        self.browser = None
        self.is_running = False
        self.is_logged_in = False
        self.should_stop = False
        self.clients: set[WebSocket] = set()
        self.jobs: list[dict] = []
        self.stats = {"applied": 0, "skipped": 0, "already_applied": 0, "evaluated": 0, "current_query": ""}


state = AgentState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if state.browser:
        try:
            await state.browser.close()
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
    }, default=str))

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            action = msg.get("action")

            if action == "launch_browser":
                asyncio.create_task(launch_browser())
            elif action == "verify_login":
                asyncio.create_task(verify_login())
            elif action == "start":
                if not state.is_running:
                    state.should_stop = False
                    asyncio.create_task(run_agent())
            elif action == "stop":
                state.should_stop = True
                state.is_running = False
                await broadcast({"type": "agent_stopped", "stats": state.stats,
                                 "message": "Agent stopped by user."})
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
        for qi, (keywords, location) in enumerate(SEARCH_QUERIES, 1):
            if state.should_stop or state.stats["applied"] >= Config.MAX_APPLICATIONS:
                break

            state.stats["current_query"] = f"{keywords} in {location} [{qi}/{len(SEARCH_QUERIES)}]"
            await broadcast({
                "type": "search_query",
                "query_number": qi,
                "total_queries": len(SEARCH_QUERIES),
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
                        "url": job.get("url", ""),
                        "match_score": None,
                        "match_reason": "",
                        "status": "Evaluating...",
                        "search_query": f"{keywords} in {location}",
                    }
                    state.jobs.append(job_entry)
                    await broadcast({"type": "job_update", "job": job_entry,
                                     "stats": state.stats})

                    try:
                        success = await applicant.apply_to_job(job, min_match_pct=60)

                        job_entry["match_score"] = applicant.last_match_score
                        job_entry["match_reason"] = applicant.last_match_reason

                        if success:
                            state.stats["applied"] += 1
                            job_entry["status"] = "Applied ✓"
                        else:
                            skip_reason = applicant.last_skip_reason
                            if skip_reason == "already_applied":
                                state.stats["already_applied"] += 1
                                job_entry["status"] = "Skipped (Already Applied)"
                            elif skip_reason == "low_score" or applicant.last_match_score < 60:
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
    if applied:
        with open("applied_jobs.json", "w", encoding="utf-8") as f:
            json.dump(applied, f, indent=2, ensure_ascii=False)

    await broadcast({
        "type": "agent_completed",
        "stats": state.stats,
        "message": (f"Agent completed. Applied: {state.stats['applied']}, "
                    f"Skipped: {state.stats['skipped']}, "
                    f"Evaluated: {state.stats['evaluated']}"),
    })
    logger.info(f"Agent completed: {state.stats}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

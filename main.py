import asyncio
import logging
import sys
import json
import random
from browser import NaukriBrowser
from naukri_agent import JobSearcher, JobApplicant, human_delay
from config import Config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)

# Search queries: (keywords, location) — rotated to cover all criteria
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


async def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║           Naukri.com AI Job Application Agent                ║
╠══════════════════════════════════════════════════════════════╣
║  1. Open browser (login session preserved)                  ║
║  2. Search across multiple job titles & locations            ║
║  3. Extract full JD, score match (≥65% to apply)            ║
║  4. Apply with AI-powered questionnaire answering           ║
║  5. Filter: Jobs posted in last 1 day only                  ║
╚══════════════════════════════════════════════════════════════╝
""")

    print(f"Experience: {Config.EXPERIENCE_YEARS} years")
    print(f"Max applications: {Config.MAX_APPLICATIONS}")
    print(f"Search queries: {len(SEARCH_QUERIES)}")
    print(f"Filter: Posted in last 24 hours | Match threshold: 60%")
    print()

    browser = NaukriBrowser()

    try:
        await browser.launch()

        logged_in = await browser.wait_for_login()
        if not logged_in:
            print("Could not verify login. Exiting.")
            return

        page = browser.page
        searcher = JobSearcher(page)
        applicant = JobApplicant(page)

        total_applied = 0
        total_skipped = 0
        total_already_applied = 0
        seen_job_ids = set()  # Avoid duplicate jobs across searches

        for query_idx, (keywords, location) in enumerate(SEARCH_QUERIES, 1):
            if total_applied >= Config.MAX_APPLICATIONS:
                break

            print(f"\n{'═' * 70}")
            print(f"  SEARCH [{query_idx}/{len(SEARCH_QUERIES)}]: "
                  f"{keywords} in {location}")
            print(f"{'═' * 70}")

            # Search pages 1-3 per query (last 1 day usually has fewer results)
            for page_no in range(1, 4):
                if total_applied >= Config.MAX_APPLICATIONS:
                    break

                jobs = await searcher.search_jobs(
                    page_no=page_no, keywords=keywords, location=location
                )

                if not jobs:
                    if page_no == 1:
                        print(f"  No jobs found for this search")
                    break

                # Filter out already-seen jobs
                new_jobs = []
                for job in jobs:
                    jid = job.get("jobId", job["url"])
                    if jid not in seen_job_ids:
                        seen_job_ids.add(jid)
                        new_jobs.append(job)

                if not new_jobs:
                    break

                print(f"  Page {page_no}: {len(new_jobs)} new jobs "
                      f"({len(jobs) - len(new_jobs)} duplicates filtered)")

                for job in new_jobs:
                    if total_applied >= Config.MAX_APPLICATIONS:
                        break

                    print(f"\n  {'─' * 66}")
                    print(f"  [{total_applied + 1}/{Config.MAX_APPLICATIONS}] "
                          f"{job['title']} @ {job['company']}")
                    print(f"    Location: {job['location']} | Salary: {job['salary']} "
                          f"| Exp: {job.get('experience', 'N/A')}")
                    print(f"    Skills: {job.get('skills', 'N/A')[:100]}")
                    print(f"  {'─' * 66}")

                    try:
                        success = await applicant.apply_to_job(job, min_match_pct=60)
                        if success:
                            total_applied += 1
                        else:
                            total_skipped += 1
                    except Exception as e:
                        logger.error(f"Failed on {job['title']}: {e}")
                        total_skipped += 1

                    # Random delay between jobs
                    await asyncio.sleep(random.uniform(3.0, 8.0))

        # Print results summary
        print(f"\n{'═' * 70}")
        print(f"  RESULTS SUMMARY")
        print(f"{'═' * 70}")
        print(f"  Applied:         {total_applied}")
        print(f"  Skipped/Failed:  {total_skipped}")
        print(f"  Jobs evaluated:  {len(seen_job_ids)}")
        print(f"{'═' * 70}")

        if applicant.applied_jobs:
            print(f"\n{'No':<4} {'Job Title':<35} {'Company':<25} {'Location':<20} {'Salary'}")
            print("-" * 110)
            for i, j in enumerate(applicant.applied_jobs, 1):
                print(f"{i:<4} {j['title'][:34]:<35} {j['company'][:24]:<25} "
                      f"{j['location'][:19]:<20} {j.get('salary', 'N/A')}")
            print("-" * 110)

        # Save results to JSON
        with open("applied_jobs.json", "w", encoding="utf-8") as f:
            json.dump(applicant.applied_jobs, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to applied_jobs.json")

    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
    finally:
        try:
            await browser.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass

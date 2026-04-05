"""
LinkedIn Job Application Bot — Main Entry Point
Runs on GitHub Actions, 3x/day, Mon-Fri
Target: 17 applications per run (~51/day)
"""

import os
import sys
import json
import time
import random
import logging
from datetime import datetime
from pathlib import Path

from login import LinkedInLogin
from job_searcher import JobSearcher
from easy_apply import EasyApply
from resume_tailor import ResumeTailor
from logger import ApplicationLogger

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
CONFIG = json.loads((ROOT / "data" / "config.json").read_text())
MASTER_RESUME = json.loads((ROOT / "data" / "master_resume.json").read_text())

MAX_PER_RUN = int(os.environ.get("RUN_TARGET", CONFIG["application_limits"]["max_per_run"]))


def main():
    log.info(f"=== LinkedIn Bot starting | Target: {MAX_PER_RUN} applications ===")
    log.info(f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

    email = os.environ["LINKEDIN_EMAIL"]
    password = os.environ["LINKEDIN_PASSWORD"]

    app_logger = ApplicationLogger(ROOT / "data" / "applied_jobs.json",
                                   ROOT / "data" / "pipeline.md")
    tailor = ResumeTailor(MASTER_RESUME, os.environ.get("ANTHROPIC_API_KEY", ""))

    with LinkedInLogin(headless=True) as browser:
        log.info("Logging into LinkedIn...")
        page = browser.login(email, password)

        if not page:
            log.error("Login failed. Exiting.")
            sys.exit(1)

        log.info("Login successful.")

        searcher = JobSearcher(page, CONFIG)
        applier = EasyApply(page, CONFIG, app_logger, tailor, MASTER_RESUME)

        applied_count = 0

        for job_config in CONFIG["job_search"]["titles"]:
            if applied_count >= MAX_PER_RUN:
                break

            for location in CONFIG["job_search"]["locations"]:
                if applied_count >= MAX_PER_RUN:
                    break

                log.info(f"Searching: '{job_config}' in '{location}'")
                jobs = searcher.search(job_config, location)
                log.info(f"  Found {len(jobs)} candidates")

                for job in jobs:
                    if applied_count >= MAX_PER_RUN:
                        break

                    # Skip companies on cooldown
                    if app_logger.is_on_cooldown(job.get("company", "")):
                        log.info(f"  SKIP (cooldown): {job.get('company')}")
                        continue

                    # Skip if already applied
                    if app_logger.already_applied(job.get("job_id", "")):
                        log.info(f"  SKIP (already applied): {job.get('title')} @ {job.get('company')}")
                        continue

                    log.info(f"  Applying: {job.get('title')} @ {job.get('company')} [{job.get('location')}]")

                    result = applier.apply(job)

                    if result["success"]:
                        applied_count += 1
                        app_logger.log_application(job, result)
                        log.info(f"  ✅ Applied ({applied_count}/{MAX_PER_RUN})")

                        # Human-like delay between applications
                        delay = random.uniform(
                            CONFIG["application_limits"]["min_delay_between_apps_sec"],
                            CONFIG["application_limits"]["max_delay_between_apps_sec"]
                        )
                        log.info(f"  Waiting {delay:.0f}s before next application...")
                        time.sleep(delay)

                    elif result.get("skip_reason") == "manual_review_required":
                        log.info(f"  ⚠️  Skipped (manual review required): {job.get('title')} @ {job.get('company')}")
                    else:
                        log.warning(f"  ❌ Failed: {result.get('error', 'Unknown error')}")

                # Small delay between searches
                time.sleep(random.uniform(5, 15))

    app_logger.save()
    log.info(f"=== Run complete | Applied to {applied_count} jobs ===")
    log.info(f"Total applied (all time): {app_logger.total_applied()}")


if __name__ == "__main__":
    main()

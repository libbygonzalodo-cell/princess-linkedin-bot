"""
LinkedIn Job Searcher
Searches for matching jobs using LinkedIn's jobs feed with filters
"""

import time
import random
import logging
from urllib.parse import urlencode, quote_plus
from playwright.sync_api import Page

log = logging.getLogger(__name__)

# LinkedIn filter codes
DATE_POSTED = {
    "past_24_hours": "r86400",
    "past_week": "r604800",
    "past_month": "r2592000",
    "any": ""
}

EXPERIENCE_LEVEL = {
    "Internship": "1",
    "Entry level": "2",
    "Associate": "3",
    "Mid-Senior level": "4",
    "Director": "5",
    "Executive": "6"
}

JOB_TYPE = {
    "Full-time": "F",
    "Part-time": "P",
    "Contract": "C",
    "Temporary": "T",
    "Internship": "I"
}


class JobSearcher:
    def __init__(self, page: Page, config: dict):
        self.page = page
        self.config = config
        self.search_cfg = config["job_search"]
        self.skip_cfg = config["skip_rules"]

    def build_search_url(self, title: str, location: str) -> str:
        date_code = DATE_POSTED.get(self.search_cfg.get("date_posted", "past_24_hours"), "r86400")
        exp_codes = ",".join([
            EXPERIENCE_LEVEL[e]
            for e in self.search_cfg.get("experience_levels", ["Entry level", "Associate", "Mid-Senior level"])
            if e in EXPERIENCE_LEVEL
        ])
        type_codes = ",".join([
            JOB_TYPE[t]
            for t in self.search_cfg.get("job_types", ["Full-time"])
            if t in JOB_TYPE
        ])

        params = {
            "keywords": title,
            "location": location,
            "f_TPR": date_code,
            "f_E": exp_codes,
            "f_JT": type_codes,
            "f_LF": "f_AL",   # Easy Apply filter
            "sortBy": "R",     # Relevance
        }
        return f"https://www.linkedin.com/jobs/search/?{urlencode(params)}"

    def search(self, title: str, location: str, max_results: int = 25) -> list[dict]:
        """Search LinkedIn and return list of job dicts."""
        url = self.build_search_url(title, location)
        jobs = []

        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2.5, 4.5))

            # Scroll to trigger lazy loading
            for _ in range(3):
                self.page.evaluate("window.scrollBy(0, 600)")
                time.sleep(random.uniform(0.8, 1.5))

            # Grab job cards
            job_cards = self.page.query_selector_all(".job-card-container, .jobs-search-results__list-item")

            for card in job_cards[:max_results]:
                try:
                    job = self._parse_card(card)
                    if job and self._passes_filters(job):
                        jobs.append(job)
                except Exception as e:
                    log.debug(f"Card parse error: {e}")
                    continue

        except Exception as e:
            log.warning(f"Search error for '{title}' in '{location}': {e}")

        return jobs

    def _parse_card(self, card) -> dict | None:
        """Extract job data from a result card element."""
        try:
            title_el = card.query_selector(".job-card-list__title, .jobs-unified-top-card__job-title a, a[data-control-name='job_card_title']")
            company_el = card.query_selector(".job-card-container__company-name, .artdeco-entity-lockup__subtitle")
            location_el = card.query_selector(".job-card-container__metadata-item, .artdeco-entity-lockup__caption")
            link_el = card.query_selector("a.job-card-container__link, a[href*='/jobs/view/']")

            if not title_el or not link_el:
                return None

            href = link_el.get_attribute("href") or ""
            job_id = ""
            if "/jobs/view/" in href:
                job_id = href.split("/jobs/view/")[-1].split("/")[0].split("?")[0]

            return {
                "title": (title_el.inner_text() or "").strip(),
                "company": (company_el.inner_text() if company_el else "").strip(),
                "location": (location_el.inner_text() if location_el else "").strip(),
                "job_id": job_id,
                "url": f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else href,
                "easy_apply": True,  # already filtered to Easy Apply
            }
        except Exception:
            return None

    def _passes_filters(self, job: dict) -> bool:
        """Apply skip rules to a job before attempting to apply."""
        title = job.get("title", "").lower()

        # Skip certain seniority levels we can't qualify for
        for skip_title in self.skip_cfg.get("skip_titles_containing", []):
            if skip_title.lower() in title:
                return False

        # Must have a job ID to apply
        if not job.get("job_id"):
            return False

        return True

    def get_job_details(self, job: dict) -> dict:
        """Navigate to a job listing and extract the full description."""
        try:
            self.page.goto(job["url"], wait_until="domcontentloaded", timeout=20000)
            time.sleep(random.uniform(1.5, 3.0))

            # Expand "Show more" if present
            show_more = self.page.query_selector("button[aria-label*='more'], .jobs-description__footer-button")
            if show_more:
                show_more.click()
                time.sleep(0.5)

            desc_el = self.page.query_selector(".jobs-description-content__text, .job-view-layout .jobs-box__html-content")
            description = (desc_el.inner_text() if desc_el else "").strip()

            # Check for salary info
            salary_el = self.page.query_selector(".compensation-module__salary, [class*='salary']")
            salary_text = (salary_el.inner_text() if salary_el else "").strip()

            job["description"] = description
            job["salary_text"] = salary_text

        except Exception as e:
            log.debug(f"Could not fetch job details for {job.get('job_id')}: {e}")
            job["description"] = ""
            job["salary_text"] = ""

        return job

"""
LinkedIn Job Searcher — updated for LinkedIn 2025/2026 UI
Uses data-attribute selectors which are more stable than CSS class names.
"""
import time
import random
import logging
from urllib.parse import urlencode
from playwright.sync_api import Page

log = logging.getLogger(__name__)

DATE_POSTED = {
    "past_24_hours": "r86400",
    "past_week": "r604800",
    "past_month": "r2592000",
    "any": "",
}

EXPERIENCE_LEVEL = {
    "Internship": "1",
    "Entry level": "2",
    "Associate": "3",
    "Mid-Senior level": "4",
    "Director": "5",
    "Executive": "6",
}

JOB_TYPE = {
    "Full-time": "F",
    "Part-time": "P",
    "Contract": "C",
    "Temporary": "T",
    "Internship": "I",
}


class JobSearcher:
    def __init__(self, page: Page, config: dict):
        self.page = page
        self.config = config
        self.search_cfg = config["job_search"]
        self.skip_cfg = config["skip_rules"]

    def build_search_url(self, title: str, location: str) -> str:
        date_key = self.search_cfg.get("date_posted", "past_week")
        date_code = DATE_POSTED.get(date_key, "r604800")

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
            "f_LF": "f_AL",   # Easy Apply only
            "sortBy": "DD",   # Most recent first
        }
        if date_code:
            params["f_TPR"] = date_code
        if exp_codes:
            params["f_E"] = exp_codes
        if type_codes:
            params["f_JT"] = type_codes

        return f"https://www.linkedin.com/jobs/search/?{urlencode(params)}"

    def search(self, title: str, location: str, max_results: int = 25) -> list[dict]:
        """Search LinkedIn and return list of job dicts."""
        url = self.build_search_url(title, location)
        jobs = []
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2.5, 4.0))

            # Check if we got redirected to login — if so, bail early
            current_url = self.page.url
            if "login" in current_url or "checkpoint" in current_url:
                log.warning(f"Session expired mid-search. Skipping '{title}' in '{location}'.")
                return jobs

            # Scroll to trigger lazy loading
            for _ in range(3):
                self.page.evaluate("window.scrollBy(0, 700)")
                time.sleep(random.uniform(0.8, 1.5))

            # Multiple selector strategies for LinkedIn's job cards (2024-2026 UI)
            # Strategy 1: data-job-id attribute (most reliable across UI versions)
            job_cards = self.page.query_selector_all("[data-job-id]")

            # Strategy 2: data-occludable-job-id (newer UI)
            if not job_cards:
                job_cards = self.page.query_selector_all("li[data-occludable-job-id]")

            # Strategy 3: classic class selectors
            if not job_cards:
                job_cards = self.page.query_selector_all(
                    ".job-card-container, .jobs-search-results__list-item"
                )

            log.debug(f"Found {len(job_cards)} raw cards for '{title}' in '{location}'")

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
        try:
            # Job ID — prefer data attribute, fall back to URL parsing
            job_id = (
                card.get_attribute("data-job-id")
                or card.get_attribute("data-occludable-job-id")
                or ""
            )

            # Title — multiple selector fallbacks
            title_el = (
                card.query_selector("a.job-card-container__link strong")
                or card.query_selector(".job-card-list__title")
                or card.query_selector(".artdeco-entity-lockup__title a")
                or card.query_selector("a[href*='/jobs/view/']")
            )

            # Company
            company_el = (
                card.query_selector(".job-card-container__company-name")
                or card.query_selector(".artdeco-entity-lockup__subtitle span")
                or card.query_selector("[class*='company']")
            )

            # Location
            location_el = (
                card.query_selector(".job-card-container__metadata-item")
                or card.query_selector(".artdeco-entity-lockup__caption span")
                or card.query_selector("[class*='location']")
            )

            # Link — extract job_id from href if not from data attribute
            link_el = card.query_selector("a[href*='/jobs/view/']")
            if link_el and not job_id:
                href = link_el.get_attribute("href") or ""
                if "/jobs/view/" in href:
                    job_id = href.split("/jobs/view/")[-1].split("/")[0].split("?")[0]

            if not title_el or not job_id:
                return None

            return {
                "title": (title_el.inner_text() or "").strip(),
                "company": (company_el.inner_text() if company_el else "").strip(),
                "location": (location_el.inner_text() if location_el else "").strip(),
                "job_id": job_id,
                "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
                "easy_apply": True,
            }
        except Exception:
            return None

    def _passes_filters(self, job: dict) -> bool:
        title = job.get("title", "").lower()
        for skip_title in self.skip_cfg.get("skip_titles_containing", []):
            if skip_title.lower() in title:
                return False
        if not job.get("job_id"):
            return False
        return True

    def get_job_details(self, job: dict) -> dict:
        try:
            self.page.goto(job["url"], wait_until="domcontentloaded", timeout=20000)
            time.sleep(random.uniform(1.5, 3.0))
            show_more = self.page.query_selector(
                "button[aria-label*='more'], .jobs-description__footer-button"
            )
            if show_more:
                show_more.click()
                time.sleep(0.5)
            desc_el = self.page.query_selector(
                ".jobs-description-content__text, .job-view-layout .jobs-box__html-content"
            )
            salary_el = self.page.query_selector(
                ".compensation-module__salary, [class*='salary']"
            )
            job["description"] = (desc_el.inner_text() if desc_el else "").strip()
            job["salary_text"] = (salary_el.inner_text() if salary_el else "").strip()
        except Exception as e:
            log.debug(f"Could not fetch job details for {job.get('job_id')}: {e}")
            job["description"] = ""
            job["salary_text"] = ""
        return job

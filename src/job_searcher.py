"""
LinkedIn Job Searcher - v3
Uses /search/results/jobs/ URL (LinkedIn global search) instead of /jobs/search/
to avoid ERR_TOO_MANY_REDIRECTS on GitHub Actions datacenter IPs.
Easy Apply is detected at the card level, not via URL filter.
"""

import time
import random
import logging
from urllib.parse import urlencode
from playwright.sync_api import Page

log = logging.getLogger(__name__)


class JobSearcher:
    def __init__(self, page: Page, config: dict):
        self.page = page
        self.config = config
        self.search_cfg = config["job_search"]
        self.skip_cfg = config["skip_rules"]

    def search(self, title: str, location: str, max_results: int = 25) -> list[dict]:
        """
        Search LinkedIn jobs via /search/results/jobs/ URL.
        This endpoint is less aggressively blocked than /jobs/search/ on datacenter IPs.
        Returns list of Easy Apply job dicts.
        """
        jobs = []
        try:
            params = {
                "keywords": title,
                "location": location,
                "sortBy": "DD",
                "f_TPR": "r86400",
            }
            url = "https://www.linkedin.com/search/results/jobs/?" + urlencode(params)
            log.info(f"Searching: {url}")

            if not self._safe_goto(url):
                log.warning(f"Could not load search page for '{title}' in '{location}'")
                return jobs

            time.sleep(random.uniform(2.5, 4.0))

            current_url = self.page.url
            if any(k in current_url for k in ["login", "checkpoint", "challenge"]):
                log.warning(f"Session expired. URL: {current_url}")
                return jobs

            log.info(f"Search results URL: {current_url}")

            for _ in range(5):
                self.page.evaluate("window.scrollBy(0, 800)")
                time.sleep(random.uniform(0.8, 1.5))

            job_cards = []
            for selector in [
                "li.reusable-search__result-container",
                ".job-card-container",
                "[data-job-id]",
                "li[data-occludable-job-id]",
                ".jobs-search-results__list-item",
                "ul.jobs-search__results-list li",
                ".scaffold-layout__list-container li",
            ]:
                job_cards = self.page.query_selector_all(selector)
                if job_cards:
                    log.info(f"Found {len(job_cards)} cards via: {selector}")
                    break

            if not job_cards:
                log.warning(f"No job cards found for '{title}' in '{location}'")
                return jobs

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

    def _safe_goto(self, url: str, max_retries: int = 2) -> bool:
        """
        Navigate to URL, handling redirect loops by refreshing via /feed/.
        Returns True if we landed on a non-auth page.
        """
        for attempt in range(max_retries):
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
                current = self.page.url
                if any(k in current for k in ["login", "checkpoint", "challenge"]):
                    log.warning(f"Landed on auth page: {current}")
                    return False
                return True
            except Exception as e:
                if "ERR_TOO_MANY_REDIRECTS" in str(e):
                    log.warning(f"Redirect loop (attempt {attempt + 1}/{max_retries}) - refreshing via /feed/")
                    try:
                        self.page.goto("https://www.linkedin.com/feed/",
                                       wait_until="domcontentloaded", timeout=30000)
                        time.sleep(random.uniform(4.0, 6.0))
                    except Exception:
                        pass
                else:
                    log.warning(f"Navigation error: {e}")
                    return False
        return False

    def _parse_card(self, card) -> dict | None:
        """Extract job data from a result card. Only returns Easy Apply jobs."""
        try:
            title_el = None
            for sel in [
                ".job-card-list__title",
                ".job-card-list__title--link",
                "a.job-card-container__link strong",
                ".artdeco-entity-lockup__title a",
                ".jobs-unified-top-card__job-title a",
                "a[data-control-name='job_card_title']",
                "strong",
            ]:
                title_el = card.query_selector(sel)
                if title_el:
                    break

            link_el = None
            for sel in [
                "a.job-card-container__link",
                "a[href*='/jobs/view/']",
                "a[href*='/jobs/']",
            ]:
                link_el = card.query_selector(sel)
                if link_el:
                    break

            if not title_el or not link_el:
                return None

            easy_apply = False
            for sel in [
                ".job-card-container__apply-method",
                "[aria-label*='Easy Apply']",
                "li-icon[type='linkedin-bug']",
                "span:text('Easy Apply')",
                ".job-card-list__footer-wrapper",
            ]:
                try:
                    badge = card.query_selector(sel)
                    if badge:
                        badge_text = badge.inner_text().lower()
                        if "easy apply" in badge_text or "linkedin" in badge_text:
                            easy_apply = True
                            break
                except Exception:
                    continue

            if not easy_apply:
                try:
                    card_text = card.inner_text().lower()
                    if "easy apply" in card_text:
                        easy_apply = True
                except Exception:
                    pass

            if not easy_apply:
                return None

            href = link_el.get_attribute("href") or ""
            job_id = ""
            if "/jobs/view/" in href:
                job_id = href.split("/jobs/view/")[-1].split("/")[0].split("?")[0]

            company_el = None
            for sel in [
                ".job-card-container__company-name",
                ".artdeco-entity-lockup__subtitle",
                ".job-card-list__company-name",
                "[data-control-name='job_card_company_url']",
            ]:
                company_el = card.query_selector(sel)
                if company_el:
                    break

            location_el = None
            for sel in [
                ".job-card-container__metadata-item",
                ".artdeco-entity-lockup__caption",
                ".job-card-list__metadata",
            ]:
                location_el = card.query_selector(sel)
                if location_el:
                    break

            return {
                "title": (title_el.inner_text() or "").strip(),
                "company": (company_el.inner_text() if company_el else "").strip(),
                "location": (location_el.inner_text() if location_el else "").strip(),
                "job_id": job_id,
                "url": f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else href,
                "easy_apply": True,
            }
        except Exception as e:
            log.debug(f"_parse_card error: {e}")
            return None

    def _passes_filters(self, job: dict) -> bool:
        """Apply skip rules to a job before attempting to apply."""
        title = job.get("title", "").lower()

        for skip_title in self.skip_cfg.get("skip_titles_containing", []):
            if skip_title.lower() in title:
                log.debug(f"Skipping '{job['title']}' - title filter: {skip_title}")
                return False

        if not job.get("job_id"):
            return False

        return True

    def get_job_details(self, job: dict) -> dict:
        """Navigate to a job listing and extract the full description."""
        try:
            if not self._safe_goto(job["url"]):
                job["description"] = ""
                job["salary_text"] = ""
                return job

            time.sleep(random.uniform(1.5, 3.0))

            for sel in [
                "button[aria-label*='more']",
                ".jobs-description__footer-button",
                "button:text('Show more')",
            ]:
                try:
                    btn = self.page.query_selector(sel)
                    if btn:
                        btn.click()
                        time.sleep(0.5)
                        break
                except Exception:
                    continue

            desc_el = None
            for sel in [
                ".jobs-description-content__text",
                ".job-view-layout .jobs-box__html-content",
                ".jobs-description__content",
                "#job-details",
            ]:
                desc_el = self.page.query_selector(sel)
                if desc_el:
                    break

            description = (desc_el.inner_text() if desc_el else "").strip()

            salary_el = None
            for sel in [
                ".compensation-module__salary",
                "[class*='salary']",
                ".jobs-unified-top-card__salary-main-rail-badge",
            ]:
                salary_el = self.page.query_selector(sel)
                if salary_el:
                    break

            salary_text = (salary_el.inner_text() if salary_el else "").strip()

            job["description"] = description
            job["salary_text"] = salary_text

        except Exception as e:
            log.debug(f"Could not fetch job details for {job.get('job_id')}: {e}")
            job["description"] = ""
            job["salary_text"] = ""

        return job

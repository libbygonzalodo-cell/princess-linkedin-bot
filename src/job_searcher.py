"""
LinkedIn Job Searcher
Uses LinkedIn search bar UI or direct search URL to find Easy Apply jobs.
Detects Easy Apply badge on job cards.
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

    def _navigate_to_jobs(self, max_retries: int = 3) -> bool:
        """Navigate to /jobs/ with retry logic for redirect loops.
        On redirect loop, visiting /feed/ first re-establishes session state.
        """
        for attempt in range(max_retries):
            try:
                self.page.goto(
                    "https://www.linkedin.com/jobs/",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                time.sleep(random.uniform(2.0, 3.0))
                current_url = self.page.url
                if "login" in current_url or "checkpoint" in current_url:
                    log.warning(f"Session expired navigating to /jobs/ (attempt {attempt+1})")
                    return False
                # Successfully on the jobs page
                return True
            except Exception as e:
                if "ERR_TOO_MANY_REDIRECTS" in str(e):
                    log.warning(f"/jobs/ redirect loop (attempt {attempt+1}/{max_retries}) - refreshing session via /feed/")
                    try:
                        self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
                        time.sleep(random.uniform(3.0, 5.0))
                    except Exception:
                        pass
                else:
                    log.warning(f"Navigation error to /jobs/ (attempt {attempt+1}): {e}")
                    time.sleep(random.uniform(2.0, 3.0))
        return False

    def _search_via_url(self, title: str, location: str) -> list:
        """Fallback: direct search URL without f_LF=f_AL filter. Detect Easy Apply on cards."""
        jobs = []
        try:
            params = {"keywords": title, "location": location, "sortBy": "DD"}
            url = f"https://www.linkedin.com/jobs/search/?{urlencode(params)}"
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2.0, 3.5))

            current_url = self.page.url
            if "login" in current_url or "checkpoint" in current_url:
                return jobs

            # Scroll to load cards
            for _ in range(3):
                self.page.evaluate("window.scrollBy(0, 600)")
                time.sleep(random.uniform(0.8, 1.2))

            job_cards = []
            for sel in ["[data-job-id]", "li[data-occludable-job-id]", ".job-card-container", ".jobs-search-results__list-item"]:
                job_cards = self.page.query_selector_all(sel)
                if job_cards:
                    log.info(f"URL fallback: found {len(job_cards)} cards via {sel}")
                    break

            for card in job_cards[:25]:
                try:
                    job = self._parse_card(card)
                    if job and self._passes_filters(job):
                        jobs.append(job)
                except Exception:
                    continue
        except Exception as e:
            log.warning(f"URL fallback search error: {e}")
        return jobs

    def search(self, title: str, location: str, max_results: int = 25) -> list[dict]:
        """Search LinkedIn Jobs. Tries search bar UI first, falls back to direct URL."""
        jobs = []
        try:
            # Navigate to Jobs page with redirect-loop retry
            if not self._navigate_to_jobs():
                log.warning(f"Could not reach /jobs/ for '{title}' - trying URL fallback")
                return self._search_via_url(title, location)

            current_url = self.page.url
            if "login" in current_url or "checkpoint" in current_url:
                return jobs

            log.info(f"On jobs page: {current_url}")

            # Find keyword search box - try multiple selectors for 2025/2026 UI
            keyword_box = None
            keyword_selectors = [
                "input[aria-label*='job title']",
                "input[aria-label*='Search by title']",
                "input[aria-label*='Search jobs']",
                "input[id*='jobs-search-box-keyword']",
                "input[id*='job-search-bar-keywords']",
                ".jobs-search-box__text-input",
                "input[placeholder*='title']",
                "input[placeholder*='job']",
                ".search-global-typeahead__input",
            ]
            for selector in keyword_selectors:
                try:
                    el = self.page.wait_for_selector(selector, timeout=3000, state="visible")
                    if el:
                        keyword_box = el
                        log.info(f"Found keyword box via: {selector}")
                        break
                except Exception:
                    continue

            if not keyword_box:
                log.warning(f"No keyword box found on /jobs/ - falling back to URL search")
                return self._search_via_url(title, location)

            # Type job title
            keyword_box.triple_click()
            time.sleep(random.uniform(0.3, 0.6))
            keyword_box.type(title, delay=random.randint(60, 130))
            time.sleep(random.uniform(0.5, 1.0))

            # Find location box
            location_box = None
            location_selectors = [
                "input[aria-label*='City, state, or zip']",
                "input[aria-label*='Location']",
                "input[id*='jobs-search-box-location']",
                "input[id*='job-search-bar-location']",
                "input[placeholder*='location']",
                "input[placeholder*='City']",
            ]
            for selector in location_selectors:
                try:
                    el = self.page.wait_for_selector(selector, timeout=3000, state="visible")
                    if el:
                        location_box = el
                        break
                except Exception:
                    continue

            if location_box:
                location_box.triple_click()
                time.sleep(random.uniform(0.3, 0.6))
                location_box.type(location, delay=random.randint(60, 130))
                time.sleep(random.uniform(0.5, 1.0))

            # Submit search
            keyword_box.press("Enter")
            time.sleep(random.uniform(3.0, 5.0))
            self.page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(random.uniform(1.5, 2.5))

            current_url = self.page.url
            if "login" in current_url or "checkpoint" in current_url:
                log.warning("Session expired after search submit.")
                return jobs

            log.info(f"Search results URL: {current_url}")

            # Scroll to trigger lazy load
            for _ in range(4):
                self.page.evaluate("window.scrollBy(0, 700)")
                time.sleep(random.uniform(0.8, 1.5))

            # Grab job cards
            job_cards = []
            for selector in ["[data-job-id]", "li[data-occludable-job-id]", ".job-card-container", ".jobs-search-results__list-item"]:
                job_cards = self.page.query_selector_all(selector)
                if job_cards:
                    log.info(f"Found {len(job_cards)} cards via: {selector}")
                    break

            if not job_cards:
                log.warning(f"No job cards found - trying URL fallback")
                return self._search_via_url(title, location)

            for card in job_cards[:max_results]:
                try:
                    job = self._parse_card(card)
                    if job and self._passes_filters(job):
                        jobs.append(job)
                except Exception as e:
                    log.debug(f"Card parse error: {e}")

        except Exception as e:
            log.warning(f"Search error for '{title}' in '{location}': {e}")

        return jobs

    def _parse_card(self, card) -> dict | None:
        """Extract job data. Only returns Easy Apply jobs."""
        try:
            title_el = None
            for sel in [".job-card-list__title", ".jobs-unified-top-card__job-title a", "a[data-control-name='job_card_title']", "a.job-card-container__link", "strong"]:
                title_el = card.query_selector(sel)
                if title_el:
                    break

            link_el = None
            for sel in ["a.job-card-container__link", "a[href*='/jobs/view/']", "a[href*='/jobs/']"]:
                link_el = card.query_selector(sel)
                if link_el:
                    break

            if not title_el or not link_el:
                return None

            # Check Easy Apply badge
            easy_apply = False
            for sel in [".job-card-container__apply-method", "[aria-label*='Easy Apply']", "li-icon[type='linkedin-bug']", ".job-card-list__footer-wrapper"]:
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
                    if "easy apply" in card.inner_text().lower():
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
            for sel in [".job-card-container__company-name", ".artdeco-entity-lockup__subtitle", ".job-card-list__company-name", "[data-control-name='job_card_company_url']"]:
                company_el = card.query_selector(sel)
                if company_el:
                    break

            location_el = None
            for sel in [".job-card-container__metadata-item", ".artdeco-entity-lockup__caption", ".job-card-list__metadata"]:
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
        title = job.get("title", "").lower()
        for skip_title in self.skip_cfg.get("skip_titles_containing", []):
            if skip_title.lower() in title:
                return False
        if not job.get("job_id"):
            return False
        return True

    def get_job_details(self, job: dict) -> dict:
        try:
            self.page.goto(job["url"], wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(1.5, 3.0))

            for sel in ["button[aria-label*='more']", ".jobs-description__footer-button"]:
                try:
                    btn = self.page.query_selector(sel)
                    if btn:
                        btn.click()
                        time.sleep(0.5)
                        break
                except Exception:
                    continue

            desc_el = None
            for sel in [".jobs-description-content__text", ".job-view-layout .jobs-box__html-content", ".jobs-description__content", "#job-details"]:
                desc_el = self.page.query_selector(sel)
                if desc_el:
                    break

            description = (desc_el.inner_text() if desc_el else "").strip()

            salary_el = None
            for sel in [".compensation-module__salary", "[class*='salary']"]:
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

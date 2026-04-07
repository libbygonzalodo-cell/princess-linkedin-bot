"""
LinkedIn Job Searcher - v5
Uses /feed/ global search bar via UI interaction (organic navigation).
Key fix: uses input[role='combobox'] selector + longer wait + JS fallback
to reliably find LinkedIn's 2026 nav search bar.
"""

import time
import random
import logging
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
        Search via /feed/ global search bar -> Jobs filter.
        Uses UI-driven navigation for organic Referer headers.
        """
        jobs = []
        try:
            # Step 1: Go to /feed/ - the only page reliably accessible from datacenter IPs
            log.info(f"Loading /feed/ to search for: '{title}'")
            try:
                self.page.goto("https://www.linkedin.com/feed/",
                               wait_until="domcontentloaded", timeout=30000)
                # Wait longer for JS-heavy LinkedIn nav to render
                time.sleep(random.uniform(5.0, 7.0))
            except Exception as e:
                log.warning(f"Could not load /feed/: {e}")
                return jobs

            current_url = self.page.url
            if any(k in current_url for k in ["login", "checkpoint", "challenge"]):
                log.warning(f"Session expired. URL: {current_url}")
                return jobs

            # Step 2: Find the global search bar
            # input[role='combobox'] is reliable across LinkedIn UI versions
            search_box = None
            selectors = [
                "input[role='combobox']",
                "input.search-global-typeahead__input",
                "input[aria-label='Search']",
                "input[aria-label*='Search']",
                "[aria-label*='Search'] input",
                "input[placeholder*='Search']",
                ".global-nav__search input",
                ".search-global-typeahead input",
                "header input",
                "nav input",
            ]
            for sel in selectors:
                try:
                    el = self.page.wait_for_selector(sel, state="visible", timeout=5000)
                    if el:
                        log.info(f"Found search bar: {sel}")
                        search_box = el
                        break
                except Exception:
                    continue

            # JS fallback: grab first visible combobox or input
            if not search_box:
                try:
                    handle = self.page.evaluate_handle(
                        "() => document.querySelector('input[role=\"combobox\"]') || Array.from(document.querySelectorAll('input')).find(i => i.offsetParent !== null)"
                    )
                    if handle:
                        el = handle.as_element()
                        if el:
                            search_box = el
                            log.info("Found search bar via JS fallback")
                except Exception as e:
                    log.debug(f"JS fallback error: {e}")

            if not search_box:
                log.warning("Global search bar not found on /feed/ - skipping")
                return jobs

            # Step 3: Type the job title and press Enter
            search_box.click()
            time.sleep(random.uniform(0.4, 0.8))
            search_box.triple_click()
            time.sleep(random.uniform(0.2, 0.4))
            search_box.type(title, delay=random.randint(60, 130))
            time.sleep(random.uniform(0.8, 1.5))
            search_box.press("Enter")

            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=20000)
            except Exception:
                pass
            time.sleep(random.uniform(2.5, 4.0))

            current_url = self.page.url
            log.info(f"After search Enter: {current_url}")

            if any(k in current_url for k in ["login", "checkpoint", "challenge"]):
                log.warning(f"Session expired. URL: {current_url}")
                return jobs

            # Step 4: Click the "Jobs" filter pill
            jobs_filter = None

            # Try direct selector
            for sel in [
                "button[aria-label='Jobs']",
                "a[aria-label='Jobs']",
                "button:text-is('Jobs')",
            ]:
                try:
                    el = self.page.wait_for_selector(sel, state="visible", timeout=5000)
                    if el:
                        jobs_filter = el
                        log.info(f"Found Jobs filter: {sel}")
                        break
                except Exception:
                    continue

            # Scan all filter pills for "Jobs" text
            if not jobs_filter:
                try:
                    for sel in [
                        ".search-reusables__filter-pill-button",
                        ".artdeco-pill",
                        "[data-test-id*='filter']",
                        "li button",
                    ]:
                        pills = self.page.query_selector_all(sel)
                        for pill in pills:
                            try:
                                if "jobs" in pill.inner_text().lower():
                                    jobs_filter = pill
                                    log.info(f"Found Jobs pill via scan: {sel}")
                                    break
                            except Exception:
                                continue
                        if jobs_filter:
                            break
                except Exception:
                    pass

            if jobs_filter:
                jobs_filter.click()
                try:
                    self.page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:
                    pass
                time.sleep(random.uniform(2.5, 4.0))
                current_url = self.page.url
                log.info(f"After Jobs filter: {current_url}")
            else:
                log.warning("Jobs filter not found - using current results page")

            if any(k in current_url for k in ["login", "checkpoint", "challenge"]):
                log.warning(f"Session expired. URL: {current_url}")
                return jobs

            # Step 5: Scroll to load results
            for _ in range(5):
                self.page.evaluate("window.scrollBy(0, 800)")
                time.sleep(random.uniform(0.8, 1.5))

            # Step 6: Collect job cards
            job_cards = []
            for selector in [
                "li.reusable-search__result-container",
                ".job-card-container",
                "[data-job-id]",
                "li[data-occludable-job-id]",
                ".jobs-search-results__list-item",
                "ul.jobs-search__results-list li",
            ]:
                job_cards = self.page.query_selector_all(selector)
                if job_cards:
                    log.info(f"Found {len(job_cards)} cards via: {selector}")
                    break

            if not job_cards:
                log.warning(f"No job cards found for '{title}'")
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
            log.warning(f"Search error for '{title}': {e}")

        return jobs

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
                        if "easy apply" in badge.inner_text().lower():
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
            for sel in [
                ".job-card-container__company-name",
                ".artdeco-entity-lockup__subtitle",
                ".job-card-list__company-name",
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
            for sel in [".jobs-description-content__text", ".jobs-description__content", "#job-details"]:
                desc_el = self.page.query_selector(sel)
                if desc_el:
                    break

            salary_el = None
            for sel in [".compensation-module__salary", "[class*='salary']"]:
                salary_el = self.page.query_selector(sel)
                if salary_el:
                    break

            job["description"] = (desc_el.inner_text() if desc_el else "").strip()
            job["salary_text"] = (salary_el.inner_text() if salary_el else "").strip()

        except Exception as e:
            log.debug(f"get_job_details error: {e}")
            job["description"] = ""
            job["salary_text"] = ""

        return job

"""
LinkedIn Job Searcher - v8
Search strategy: Python requests library via Playwright context cookies.
Extracts all cookies (including httpOnly li_at) from the Playwright browser,
builds a real HTTP session, and calls Voyager API directly.
This bypasses both headless browser detection and datacenter IP blocks.
"""

import time
import random
import logging
import urllib.parse
from playwright.sync_api import Page

log = logging.getLogger(__name__)


class JobSearcher:
    def __init__(self, page: Page, config: dict):
        self.page = page
        self.config = config
        self.search_cfg = config["job_search"]
        self.skip_cfg = config["skip_rules"]
        self._http_session = None   # requests.Session reused across searches
        self._csrf_token = None     # cached CSRF token

    def _init_http_session(self):
        """
        Build a requests.Session from cookies in the Playwright browser context.
        Playwright's context.cookies() returns ALL cookies including httpOnly li_at.
        This lets us call Voyager API as a plain HTTP client, bypassing bot detection.
        """
        try:
            import requests as req_lib

            all_cookies = self.page.context.cookies()
            log.info(f"[HTTP] Extracted {len(all_cookies)} cookies from browser context")

            # Extract CSRF from JSESSIONID
            jsessionid_raw = next(
                (c['value'] for c in all_cookies if c['name'] == 'JSESSIONID'), ''
            )
            csrf = urllib.parse.unquote(jsessionid_raw).strip('"')
            log.info(f"[HTTP] CSRF token: {csrf[:30] if csrf else 'EMPTY'}")

            if not csrf:
                log.warning("[HTTP] No JSESSIONID found — cannot build CSRF token")
                return False

            session = req_lib.Session()
            for c in all_cookies:
                try:
                    domain = c.get('domain', '.linkedin.com')
                    # requests needs domain without leading dot
                    session.cookies.set(c['name'], c['value'],
                                        domain=domain.lstrip('.'),
                                        path=c.get('path', '/'))
                except Exception:
                    pass

            # Standard browser headers to avoid bot detection
            session.headers.update({
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'accept-language': 'en-US,en;q=0.9',
                'accept-encoding': 'gzip, deflate, br',
                'referer': 'https://www.linkedin.com/jobs/search/',
                'origin': 'https://www.linkedin.com',
                'x-restli-protocol-version': '2.0.0',
                'x-li-lang': 'en_US',
                'x-li-track': '{"clientVersion":"1.13.12060","osName":"web","timezoneOffset":-7,"timezone":"America/Los_Angeles","deviceFormFactor":"DESKTOP","mpName":"voyager-web","displayDensity":1,"displayWidth":1366,"displayHeight":768}',
                'accept': 'application/vnd.linkedin.normalized+json+2.1',
                'csrf-token': csrf,
            })

            self._http_session = session
            self._csrf_token = csrf
            log.info("[HTTP] Session initialized successfully")
            return True

        except ImportError:
            log.error("[HTTP] requests library not available")
            return False
        except Exception as e:
            log.error(f"[HTTP] Session init error: {e}")
            return False

    def search(self, title: str, location: str, max_results: int = 25) -> list[dict]:
        """Search LinkedIn for Easy Apply jobs via direct HTTP (requests library)."""
        # Initialize HTTP session once per run
        if self._http_session is None:
            if not self._init_http_session():
                log.warning("HTTP session init failed — returning empty")
                return []

        jobs = self._strategy_http_voyager(title, location, max_results)
        if jobs is not None:
            return jobs

        log.warning(f"HTTP search failed for '{title}' in '{location}'")
        return []

    # -------------------------------------------------------------------------
    # Strategy: Python requests library -> Voyager API
    # -------------------------------------------------------------------------
    def _strategy_http_voyager(self, title: str, location: str, max_results: int):
        """Call Voyager API via Python requests (not from inside the browser page)."""
        try:
            params = {
                'q': 'all',
                'keywords': title,
                'origin': 'JOB_SEARCH_PAGE_KEYWORD_HISTORY',
                'start': '0',
                'count': str(max_results),
            }
            # Location filter — Voyager accepts geoUrn or just keyword location
            # We pass location as part of the filters list
            filters = 'List(resultType->JOBS,easyApply->true)'

            url = 'https://www.linkedin.com/voyager/api/search/blended'
            resp = self._http_session.get(
                url,
                params={**params, 'filters': filters},
                timeout=30,
            )

            log.info(f"[HTTP] Voyager {resp.status_code} for '{title}' | cookies sent: {list(self._http_session.cookies.keys())[:6]}")

            if resp.status_code == 401 or resp.status_code == 403:
                log.warning("[HTTP] Auth failure — li_at may be expired")
                return None

            if resp.status_code == 429:
                log.warning("[HTTP] Rate limited (429) — backing off 60s")
                time.sleep(60)
                return None

            if not resp.ok:
                log.warning(f"[HTTP] Voyager error {resp.status_code}: {resp.text[:200]}")
                return None

            try:
                data = resp.json()
            except Exception:
                log.warning(f"[HTTP] Could not parse JSON: {resp.text[:200]}")
                return None

            jobs = self._parse_voyager_jobs(data, title)
            log.info(f"[HTTP] Found {len(jobs)} Easy Apply jobs for '{title}'")
            return jobs

        except Exception as e:
            log.warning(f"[HTTP] Voyager request error: {e}")
            return None

    def _parse_voyager_jobs(self, data: dict, search_title: str) -> list[dict]:
        """Parse Voyager API response into job dicts."""
        jobs = []
        try:
            included = data.get("included", [])
            for item in included:
                item_type = item.get("$type", "")
                if "JobPosting" not in item_type and "jobPosting" not in item_type:
                    continue

                title = item.get("title", "").strip()
                if not title:
                    continue

                # Check for Easy Apply
                apply_method = item.get("applyMethod", {})
                apply_type = apply_method.get("$type", "")
                if "OffsiteApply" in apply_type:
                    continue

                urn = item.get("entityUrn", "")
                job_id = urn.split(":")[-1] if urn else ""

                company = ""
                company_details = item.get("companyDetails", {})
                if isinstance(company_details, dict):
                    company = (company_details.get("company", {}) or {}).get("name", "")
                    if not company:
                        company = company_details.get("companyName", "")

                location = item.get("formattedLocation", "") or item.get("location", "")

                if not job_id:
                    continue

                job = {
                    "title": title,
                    "company": company,
                    "location": location,
                    "job_id": job_id,
                    "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
                    "easy_apply": True,
                }

                if self._passes_filters(job):
                    jobs.append(job)

            log.info(f"[HTTP] Parsed {len(jobs)} Easy Apply jobs from Voyager response")
        except Exception as e:
            log.warning(f"[HTTP] Voyager parse error: {e}")
        return jobs

    def _passes_filters(self, job: dict) -> bool:
        """Apply skip rules to a job before attempting to apply."""
        title = job.get("title", "").lower()

        for skip_title in self.skip_cfg.get("skip_titles_containing", []):
            if skip_title.lower() in title:
                log.debug(f"Skipping '{job['title']}' -- filter: {skip_title}")
                return False

        if not job.get("job_id"):
            return False

        return True

    def get_job_details(self, job: dict) -> dict:
        """Navigate to a job listing and extract the full description."""
        try:
            self.page.goto(job["url"], wait_until="domcontentloaded", timeout=30000)
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

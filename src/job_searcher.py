"""
LinkedIn Job Searcher - v9
Uses Python requests library with direct HTTP session establishment.
Reads li_at from env, makes real HTTP requests to LinkedIn to get
a fresh authenticated JSESSIONID, then calls Voyager API.
Also includes public jobs API fallback (no auth needed).
"""

import os
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
        self._http_session = None
        self._csrf_token = None

    def _init_http_session(self):
        """
        Build an authenticated requests.Session by making real HTTP requests
        to LinkedIn with the li_at cookie. This gets a fresh JSESSIONID that
        LinkedIn trusts -- unlike the JSESSIONID from the headless browser
        which LinkedIn rejects from datacenter IPs.
        """
        try:
            import requests as req_lib

            li_at = os.environ.get("LINKEDIN_COOKIE", "").strip()
            if not li_at:
                # Fallback: try to get from browser context
                browser_cookies = self.page.context.cookies()
                li_at = next((c["value"] for c in browser_cookies if c["name"] == "li_at"), "")

            if not li_at:
                log.warning("[HTTP] No li_at cookie found in env or browser")
                return False

            log.info(f"[HTTP] li_at found ({len(li_at)} chars), building session...")

            session = req_lib.Session()
            session.headers.update({
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "accept-language": "en-US,en;q=0.9",
                "accept-encoding": "gzip, deflate, br",
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })

            # Inject li_at before every request
            session.cookies.set("li_at", li_at, domain=".linkedin.com", path="/")

            # Step 1: warm-up hit to linkedin.com (gets bcookie/bscookie)
            try:
                r0 = session.get("https://www.linkedin.com/", timeout=30, allow_redirects=True)
                log.info(f"[HTTP] Warm-up: {r0.status_code} | cookies so far: {list(session.cookies.keys())[:6]}")
            except Exception as e:
                log.warning(f"[HTTP] Warm-up failed: {e}")

            time.sleep(random.uniform(1.5, 3.0))

            # Step 2: GET /feed/ with li_at — LinkedIn issues an authenticated JSESSIONID
            session.cookies.set("li_at", li_at, domain=".linkedin.com", path="/")
            try:
                r1 = session.get("https://www.linkedin.com/feed/", timeout=30, allow_redirects=True)
                log.info(f"[HTTP] /feed/: {r1.status_code} | url: {r1.url}")
            except Exception as e:
                log.warning(f"[HTTP] Feed request failed: {e}")

            # Get JSESSIONID — prefer value from response cookies
            jsessionid = (
                session.cookies.get("JSESSIONID", domain="linkedin.com")
                or session.cookies.get("JSESSIONID", domain=".linkedin.com")
                or session.cookies.get("JSESSIONID")
                or ""
            )
            csrf = urllib.parse.unquote(jsessionid).strip('"') if jsessionid else ""
            log.info(f"[HTTP] CSRF: {csrf[:30] if csrf else 'EMPTY'} | all cookies: {list(session.cookies.keys())}")

            if not csrf:
                log.warning("[HTTP] No JSESSIONID after session init — cannot call Voyager")
                return False

            # Ensure li_at is still set
            session.cookies.set("li_at", li_at, domain=".linkedin.com", path="/")

            # Switch headers to Voyager API mode
            session.headers.update({
                "accept": "application/vnd.linkedin.normalized+json+2.1",
                "csrf-token": csrf,
                "x-restli-protocol-version": "2.0.0",
                "x-li-lang": "en_US",
                "referer": "https://www.linkedin.com/jobs/search/",
                "origin": "https://www.linkedin.com",
                "x-li-track": '{"clientVersion":"1.13.12060","osName":"web","timezoneOffset":-7,"timezone":"America/Los_Angeles","deviceFormFactor":"DESKTOP","mpName":"voyager-web","displayDensity":1,"displayWidth":1366,"displayHeight":768}',
            })

            self._http_session = session
            self._csrf_token = csrf
            log.info("[HTTP] Session ready for Voyager API calls")
            return True

        except ImportError:
            log.error("[HTTP] requests library not installed")
            return False
        except Exception as e:
            log.error(f"[HTTP] Session init error: {e}")
            return False

    def search(self, title: str, location: str, max_results: int = 25) -> list[dict]:
        """Search LinkedIn for Easy Apply jobs."""
        if self._http_session is None:
            if not self._init_http_session():
                log.warning("[HTTP] Session init failed — trying public API")
                return self._strategy_public_api(title, location, max_results) or []

        jobs = self._strategy_voyager(title, location, max_results)
        if jobs is not None:
            return jobs

        # Fallback: public jobs API (no auth, scrapes HTML)
        jobs = self._strategy_public_api(title, location, max_results)
        if jobs is not None:
            return jobs

        log.warning(f"All strategies failed for '{title}' in '{location}'")
        return []

    # -------------------------------------------------------------------------
    # Strategy 1: Voyager API via authenticated requests session
    # -------------------------------------------------------------------------
    def _strategy_voyager(self, title: str, location: str, max_results: int):
        """Call Voyager via Python requests (not from browser)."""
        try:
            params = {
                "q": "all",
                "keywords": title,
                "origin": "JOB_SEARCH_PAGE_KEYWORD_HISTORY",
                "start": "0",
                "count": str(max_results),
                "filters": "List(resultType->JOBS,easyApply->true)",
            }
            resp = self._http_session.get(
                "https://www.linkedin.com/voyager/api/search/blended",
                params=params,
                timeout=30,
            )
            log.info(f"[HTTP] Voyager {resp.status_code} for '{title}'")

            if resp.status_code in (401, 403):
                log.warning("[HTTP] Auth failure — li_at may be expired")
                self._http_session = None
                return None

            if resp.status_code == 429:
                log.warning("[HTTP] Rate limited (429) — will try public API")
                return None

            if not resp.ok:
                log.warning(f"[HTTP] Error {resp.status_code}: {resp.text[:200]}")
                return None

            data = resp.json()
            jobs = self._parse_voyager_jobs(data, title)
            log.info(f"[HTTP] Voyager returned {len(jobs)} Easy Apply jobs")
            return jobs

        except Exception as e:
            log.warning(f"[HTTP] Voyager error: {e}")
            return None

    # -------------------------------------------------------------------------
    # Strategy 2: Public LinkedIn jobs API (no auth required)
    # -------------------------------------------------------------------------
    def _strategy_public_api(self, title: str, location: str, max_results: int):
        """
        LinkedIn's guest/public jobs search API.
        Returns HTML cards with job info. No auth needed, works from any IP.
        """
        try:
            import requests as req_lib
            from html.parser import HTMLParser

            params = {
                "keywords": title,
                "location": location,
                "f_LF": "f_AL",   # Easy Apply only
                "sortBy": "DD",    # Most recent
                "start": "0",
            }
            resp = req_lib.get(
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search",
                params=params,
                headers={
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "accept": "text/html,application/xhtml+xml",
                    "accept-language": "en-US,en;q=0.9",
                },
                timeout=30,
            )
            log.info(f"[PUB] Public API: {resp.status_code} for '{title}' in '{location}'")

            if not resp.ok:
                log.warning(f"[PUB] Failed: {resp.status_code}")
                return None

            jobs = self._parse_public_jobs_html(resp.text, max_results)
            log.info(f"[PUB] Parsed {len(jobs)} jobs from public API")
            return jobs

        except Exception as e:
            log.warning(f"[PUB] Public API error: {e}")
            return None

    def _parse_public_jobs_html(self, html: str, max_results: int) -> list[dict]:
        """Parse LinkedIn guest jobs HTML into job dicts."""
        import re
        jobs = []
        try:
            # Each job card has data-entity-urn="urn:li:jobPosting:JOBID"
            job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(d+)"', html)
            titles = re.findall(r'class="base-search-card__title"[^>]*>([^<]+)<', html)
            companies = re.findall(r'class="base-search-card__subtitle"[^>]*>[sS]*?<a[^>]*>([^<]+)<', html)
            locations = re.findall(r'class="job-search-card__location"[^>]*>([^<]+)<', html)

            log.info(f"[PUB] Found IDs: {len(job_ids)}, titles: {len(titles)}, companies: {len(companies)}")

            for i, job_id in enumerate(job_ids[:max_results]):
                job = {
                    "title": titles[i].strip() if i < len(titles) else "",
                    "company": companies[i].strip() if i < len(companies) else "",
                    "location": locations[i].strip() if i < len(locations) else "",
                    "job_id": job_id,
                    "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
                    "easy_apply": True,  # f_LF=f_AL filter ensures Easy Apply
                }
                if job["title"] and self._passes_filters(job):
                    jobs.append(job)
        except Exception as e:
            log.warning(f"[PUB] HTML parse error: {e}")
        return jobs

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
                apply_method = item.get("applyMethod", {})
                if "OffsiteApply" in apply_method.get("$type", ""):
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
        except Exception as e:
            log.warning(f"[HTTP] Parse error: {e}")
        return jobs

    def _passes_filters(self, job: dict) -> bool:
        title = job.get("title", "").lower()
        for skip_title in self.skip_cfg.get("skip_titles_containing", []):
            if skip_title.lower() in title:
                return False
        return bool(job.get("job_id"))

    def get_job_details(self, job: dict) -> dict:
        """Navigate to a job listing and extract the full description."""
        try:
            self.page.goto(job["url"], wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(1.5, 3.0))
            for sel in ["button[aria-label*='more']", ".jobs-description__footer-button", "button:text('Show more')"]:
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
            for sel in [".compensation-module__salary", "[class*='salary']", ".jobs-unified-top-card__salary-main-rail-badge"]:
                salary_el = self.page.query_selector(sel)
                if salary_el:
                    break
            job["description"] = description
            job["salary_text"] = (salary_el.inner_text() if salary_el else "").strip()
        except Exception as e:
            log.debug(f"Could not fetch job details for {job.get('job_id')}: {e}")
            job["description"] = ""
            job["salary_text"] = ""
        return job

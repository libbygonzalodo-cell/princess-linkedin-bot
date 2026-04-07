"""
LinkedIn Job Searcher - v7
Anti-detection strategy using 2 layers:
  1. /feed/ keyboard '/' shortcut (bypasses CSS selector issues; includes page diagnostics)
  2. Voyager API via page.evaluate(fetch()) -- same-origin XHR, bypasses ALL IP blocks
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
        self._on_feed = False  # track so we don't reload /feed/ every single search

    def search(self, title: str, location: str, max_results: int = 25) -> list[dict]:
        """Search LinkedIn for Easy Apply jobs.
        Strategy 1: /feed/ search bar via keyboard shortcut (requires page to render)
        Strategy 2: Voyager API same-origin XHR (bypasses all IP-level blocks)
        """
        # --- Strategy 1: /feed/ global search bar ---
        jobs = self._strategy_keyboard_search(title, location, max_results)
        if jobs is not None:
            return jobs

        # --- Strategy 2: Voyager API via same-origin fetch() ---
        jobs = self._strategy_voyager_api(title, location, max_results)
        if jobs is not None:
            return jobs

        log.warning(f"Both strategies failed for '{title}' in '{location}'")
        return []

    # -------------------------------------------------------------------------
    # Strategy 1 -- /feed/ keyboard shortcut
    # -------------------------------------------------------------------------
    def _strategy_keyboard_search(self, title: str, location: str, max_results: int):
        """Use '/' keyboard shortcut to focus LinkedIn global search on /feed/."""
        try:
            cur = self.page.url
            # Navigate to /feed/ if we're not already on a rendered LinkedIn page
            body_len = self.page.evaluate("() => document.body?.innerText?.length || 0")
            if "linkedin.com" not in cur or body_len < 50:
                log.info(f"[S1] Navigating to /feed/ (cur={cur[:60]}, body_len={body_len})")
                self.page.goto("https://www.linkedin.com/feed/",
                               wait_until="networkidle", timeout=45000)
                time.sleep(random.uniform(3.0, 5.0))
            else:
                log.info(f"[S1] Already on rendered LinkedIn page (body_len={body_len})")
                time.sleep(random.uniform(1.0, 2.0))

            # -- Diagnostics: see what LinkedIn is actually serving --
            diag = self.page.evaluate("""() => ({
                title: document.title,
                url: location.href,
                inputs: Array.from(document.querySelectorAll('input'))
                    .map(i => i.type + '|role=' + (i.getAttribute('role') || '') +
                         '|ph=' + (i.placeholder || '') +
                         '|vis=' + (i.offsetParent !== null))
                    .slice(0, 10),
                bodyText: document.body?.innerText?.slice(0, 200) || ''
            })""")
            log.info(f"[S2] Page title: '{diag.get('title')}' | URL: {diag.get('url')}")
            log.info(f"[S2] Inputs found: {diag.get('inputs')}")
            log.info(f"[S2] Body preview: {diag.get('bodyText', '')[:150]}")

            # -- Try '/' keyboard shortcut --
            self.page.keyboard.press("/")
            time.sleep(random.uniform(0.5, 1.0))

            active = self.page.evaluate("""() => {
                const el = document.activeElement;
                if (!el) return 'none';
                return el.tagName + '[type=' + el.type + '][role=' +
                       (el.getAttribute('role') || '') + '][ph=' +
                       (el.placeholder || '') + ']';
            }""")
            log.info(f"[S2] Active element after '/': {active}")

            if "INPUT" not in active.upper():
                # '/' didn't focus a search box -- try clicking first visible input
                log.info("[S2] '/' didn't focus an input -- trying JS click on search bar")
                clicked = self.page.evaluate("""() => {
                    const inputs = Array.from(document.querySelectorAll('input'));
                    const visible = inputs.find(i => i.offsetParent !== null);
                    if (visible) { visible.focus(); visible.click(); return true; }
                    return false;
                }""")
                time.sleep(0.5)
                if not clicked:
                    log.warning("[S2] No visible input found -- strategy 1 failed")
                    return None

            # Type the search query
            self.page.keyboard.type(title, delay=random.randint(60, 130))
            time.sleep(random.uniform(0.5, 1.0))
            self.page.keyboard.press("Enter")
            time.sleep(random.uniform(3.5, 5.5))
            self.page.wait_for_load_state("domcontentloaded", timeout=20000)

            current = self.page.url
            log.info(f"[S2] After search, URL: {current}")

            # Click the Jobs filter pill if we landed on general search results
            if "search/results/all" in current or "search/results" in current:
                for sel in [
                    "button[aria-label='Jobs']",
                    "button:text('Jobs')",
                    "a[href*='search/results/jobs']",
                    "[data-control-name='jobs_search_entity_type']",
                ]:
                    try:
                        el = self.page.wait_for_selector(sel, timeout=4000)
                        if el:
                            el.click()
                            time.sleep(random.uniform(2, 3))
                            log.info("[S2] Clicked Jobs filter pill")
                            break
                    except Exception:
                        continue

            current = self.page.url
            if any(k in current for k in ["login", "checkpoint"]):
                log.warning("[S2] Session expired -- strategy 1 failed")
                return None

            return self._collect_cards(max_results)

        except Exception as e:
            log.warning(f"[S2] Error: {e}")
            return None

    # -------------------------------------------------------------------------
    # Strategy 2 -- Voyager API (same-origin XHR)
    # -------------------------------------------------------------------------
    def _strategy_voyager_api(self, title: str, location: str, max_results: int):
        """
        Call LinkedIn's internal Voyager search API via fetch() from page context.
        Since the call is made FROM linkedin.com, cookies flow automatically and
        LinkedIn's IP-level navigation blocks don't apply (it's an XHR, not a page load).
        """
        try:
            log.info(f"[S3] Voyager API search: '{title}' in '{location}'")

            # Make sure we're on linkedin.com
            cur = self.page.url
            if "linkedin.com" not in cur:
                self.page.goto("https://www.linkedin.com/feed/",
                               wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(5, 7))

            result = self.page.evaluate(f"""
                async () => {{
                    // CSRF extraction -- LinkedIn puts it in JSESSIONID cookie (not httpOnly)
                    // or in window globals set by the SPA.
                    let csrf = '';
                    const cookieMatch = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
                    if (cookieMatch) {{
                        csrf = decodeURIComponent(cookieMatch[1]);
                    }}
                    if (!csrf && window.voyager && window.voyager.csrfToken) {{
                        csrf = window.voyager.csrfToken;
                    }}
                    if (!csrf) {{
                        // Try any cookie that starts with "ajax:"
                        const ajaxMatch = document.cookie.match(/ajax%3A(\\d+)/);
                        if (ajaxMatch) csrf = 'ajax:' + ajaxMatch[1];
                    }}

                    const debug = {{
                        csrf: csrf ? csrf.slice(0, 25) : 'EMPTY',
                        allCookieKeys: document.cookie.split(';').map(c => c.trim().split('=')[0]),
                        bodyLen: document.body?.innerText?.length || 0,
                    }};

                    const params = new URLSearchParams({{
                        q: 'all',
                        keywords: {repr(title)},
                        origin: 'JOB_SEARCH_PAGE_KEYWORD_HISTORY',
                        start: '0',
                        count: '25',
                    }});
                    params.append('filters', 'List(resultType->JOBS,easyApply->true)');
                    const url = '/voyager/api/search/blended?' + params.toString();

                    try {{
                        const resp = await fetch(url, {{
                            method: 'GET',
                            credentials: 'include',
                            headers: {{
                                'accept': 'application/vnd.linkedin.normalized+json+2.1',
                                'csrf-token': csrf,
                                'x-restli-protocol-version': '2.0.0',
                                'x-li-lang': 'en_US',
                                'x-li-page-instance': 'urn:li:page:d_flagship3_search_srp_jobs;',
                            }},
                        }});
                        const text = await resp.text();
                        return {{ status: resp.status, ok: resp.ok, body: text.slice(0, 8000), debug: debug }};
                    }} catch(e) {{
                        return {{ status: 0, ok: false, body: e.message, debug: debug }};
                    }}
                }}
            """)

            log.info(f"[S3] Voyager status: {result.get('status')} | debug: {result.get('debug')}")

            if not result.get('ok'):
                log.warning(f"[S3] Voyager failed: {result.get('body', '')[:300]}")
                return None

            import json
            try:
                data = json.loads(result.get('body', '{}'))
            except Exception:
                log.warning("[S3] Could not parse Voyager JSON")
                return None

            return self._parse_voyager_jobs(data, title)

        except Exception as e:
            log.warning(f"[S3] Voyager error: {e}")
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
                # ComplexOnsiteApply = Easy Apply; OffsiteApply = external
                if "OffsiteApply" in apply_type:
                    continue
                # If no applyMethod or ComplexOnsiteApply, treat as potential Easy Apply

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

            log.info(f"[S3] Voyager parsed {len(jobs)} Easy Apply jobs from response")
        except Exception as e:
            log.warning(f"[S3] Voyager parse error: {e}")
        return jobs

    # -------------------------------------------------------------------------
    # Shared card collection (used by Strategy 1)
    # -------------------------------------------------------------------------
    def _collect_cards(self, max_results: int) -> list[dict]:
        """Scroll and collect job cards from current search results page."""
        jobs = []
        try:
            # Scroll to load more
            for _ in range(4):
                self.page.evaluate("window.scrollBy(0, 700)")
                time.sleep(random.uniform(0.7, 1.3))

            # Try multiple card selectors
            job_cards = []
            for selector in [
                "[data-job-id]",
                "li[data-occludable-job-id]",
                ".job-card-container",
                ".jobs-search-results__list-item",
                "li.scaffold-layout__list-item",
            ]:
                job_cards = self.page.query_selector_all(selector)
                if job_cards:
                    log.info(f"Found {len(job_cards)} cards via: {selector}")
                    break

            if not job_cards:
                log.warning("No job cards found on page")
                return jobs

            for card in job_cards[:max_results]:
                try:
                    job = self._parse_card(card)
                    if job and self._passes_filters(job):
                        jobs.append(job)
                except Exception as e:
                    log.debug(f"Card parse error: {e}")

        except Exception as e:
            log.warning(f"_collect_cards error: {e}")

        return jobs

    def _parse_card(self, card) -> dict | None:
        """Extract job data from a result card. Only returns Easy Apply jobs."""
        try:
            title_el = None
            for sel in [
                ".job-card-list__title",
                ".jobs-unified-top-card__job-title a",
                "a[data-control-name='job_card_title']",
                "a.job-card-container__link",
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

            # Easy Apply detection
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

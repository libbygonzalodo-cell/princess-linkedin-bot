"""
LinkedIn Login Handler using Playwright with stealth settings.
Supports cookie-based auth (li_at) for GitHub Actions runs where
datacenter IPs trigger LinkedIn CAPTCHA on password login.
"""

import os
import time
import random
import logging
from playwright.sync_api import sync_playwright, BrowserContext, Page

log = logging.getLogger(__name__)

STEALTH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--disable-infobars",
    "--window-size=1366,768",
    "--lang=en-US",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


class LinkedInLogin:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def _make_context(self) -> BrowserContext:
        """Create a browser context with stealth settings."""
        self._playwright = sync_playwright().start()
        ua = random.choice(USER_AGENTS)
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=STEALTH_ARGS,
            slow_mo=random.randint(80, 150),
        )
        context = self._browser.new_context(
            user_agent=ua,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/Los_Angeles",
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)
        return context

    def login(self, email: str = None, password: str = None) -> Page | None:
        """
        Login to LinkedIn. Prefers cookie-based auth (LINKEDIN_COOKIE env var).
        Falls back to email/password if no cookie is set.
        """
        li_at = os.environ.get("LINKEDIN_COOKIE", "").strip()
        if li_at:
            log.info("Using cookie-based authentication (li_at)...")
            return self._cookie_login(li_at)

        if email and password:
            log.info("Using email/password authentication...")
            return self._password_login(email, password)

        log.error("No LINKEDIN_COOKIE set and no credentials provided.")
        return None

    def _cookie_login(self, li_at: str) -> Page | None:
        """
        Login using the li_at session cookie.
        Pattern: warm-up visit to get bcookie/bscookie -> inject li_at -> /feed/
        The warm-up prevents ERR_TOO_MANY_REDIRECTS when injecting li_at cold.
        """
        context = self._make_context()
        self._context = context
        self._page = context.new_page()

        try:
            log.info("Warm-up: visiting linkedin.com homepage...")
            self._page.goto("https://www.linkedin.com/", wait_until="domcontentloaded", timeout=60000)
            time.sleep(random.uniform(1.5, 2.5))

            context.add_cookies([{
                "name": "li_at",
                "value": li_at,
                "domain": ".linkedin.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
            }])
            log.info("li_at cookie injected.")

            try:
                self._page.goto(
                    "https://www.linkedin.com/feed/",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
            except Exception as nav_err:
                if "ERR_TOO_MANY_REDIRECTS" in str(nav_err):
                    log.error("Cookie rejected - redirect loop. Cookie may be expired.")
                    log.error("Get a fresh li_at cookie from browser DevTools and update the LINKEDIN_COOKIE secret.")
                    return None
                raise

            time.sleep(random.uniform(3.0, 5.0))

            url = self._page.url
            if any(k in url for k in ["feed", "jobs", "mynetwork", "messaging"]):
                log.info(f"Cookie login successful. URL: {url}")
                return self._page
            elif any(k in url for k in ["login", "checkpoint", "challenge"]):
                log.error(f"Cookie rejected - landed on: {url}")
                log.error("Update LINKEDIN_COOKIE secret with a fresh value from browser DevTools.")
                return None
            else:
                log.info(f"Cookie login - URL: {url} (treating as success)")
                return self._page

        except Exception as e:
            log.error(f"Cookie login error: {e}")
            return None

    def _password_login(self, email: str, password: str) -> Page | None:
        """
        Fallback: email + password login.
        NOTE: Triggers CAPTCHA from GitHub Actions IPs. Use cookie auth instead.
        """
        context = self._make_context()
        self._context = context
        self._page = context.new_page()

        try:
            self._page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60000)
            time.sleep(random.uniform(1.5, 3.0))

            self._page.fill("#username", email)
            time.sleep(random.uniform(0.5, 1.2))
            self._page.click("#password")
            time.sleep(random.uniform(0.3, 0.8))
            self._page.fill("#password", password)
            time.sleep(random.uniform(0.8, 1.5))

            self._page.click('[data-litms-control-urn="login-submit"]')
            self._page.wait_for_load_state("domcontentloaded", timeout=60000)
            time.sleep(random.uniform(2.0, 4.0))

            current_url = self._page.url
            if any(k in current_url for k in ["feed", "mynetwork", "jobs"]):
                log.info(f"Password login successful. URL: {current_url}")
                return self._page
            elif any(k in current_url for k in ["checkpoint", "challenge"]):
                log.error("Security challenge detected - use cookie auth instead.")
                return None
            elif "login" in current_url:
                log.error("Still on login page - credentials may be wrong.")
                return None
            else:
                log.info(f"Password login likely successful. URL: {current_url}")
                return self._page

        except Exception as e:
            log.error(f"Password login error: {e}")
            return None

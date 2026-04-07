"""
LinkedIn Login Handler — supports cookie auth (preferred) and email/password fallback
Cookie auth bypasses LinkedIn's security challenges on datacenter IPs (GitHub Actions).
"""
import os
import time
import random
import logging
from playwright.sync_api import sync_playwright, Page

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

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = { runtime: {} };
"""


class LinkedInLogin:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
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

    def _make_context(self):
        ua = random.choice(USER_AGENTS)
        self._playwright = sync_playwright().start()
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
        context.add_init_script(STEALTH_JS)
        return context

    def login(self, email: str = None, password: str = None) -> Page | None:
        li_at = os.environ.get("LINKEDIN_COOKIE", "").strip()
        if li_at:
            log.info("Using cookie-based authentication...")
            return self._cookie_login(li_at)
        log.info("Using email/password authentication...")
        return self._password_login(email, password)

    def _cookie_login(self, li_at: str) -> Page | None:
        """Inject li_at session cookie — bypasses security challenges."""
        context = self._make_context()
        context.add_cookies([{
            "name": "li_at",
            "value": li_at,
            "domain": ".linkedin.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "None",
        }])
        self._page = context.new_page()
        try:
            self._page.goto("https://www.linkedin.com/feed/", wait_until="networkidle", timeout=30000)
            time.sleep(random.uniform(2.0, 3.5))
            url = self._page.url
            if "feed" in url or "jobs" in url or "mynetwork" in url:
                log.info(f"Cookie login successful. URL: {url}")
                return self._page
            elif "login" in url or "checkpoint" in url or "challenge" in url:
                log.error(f"Cookie login failed — cookie may be expired. URL: {url}")
                return None
            else:
                log.info(f"Cookie login — landed at: {url}")
                return self._page
        except Exception as e:
            log.error(f"Cookie login error: {e}")
            return None

    def _password_login(self, email: str, password: str) -> Page | None:
        """Fallback: email/password login (may trigger security challenge on new IPs)."""
        context = self._make_context()
        self._page = context.new_page()
        try:
            self._page.goto("https://www.linkedin.com/login", wait_until="networkidle", timeout=30000)
            time.sleep(random.uniform(1.5, 3.0))
            self._page.fill("#username", email)
            time.sleep(random.uniform(0.5, 1.2))
            self._page.click("#password")
            time.sleep(random.uniform(0.3, 0.8))
            self._page.fill("#password", password)
            time.sleep(random.uniform(0.8, 1.5))
            self._page.click('[data-litms-control-urn="login-submit"]')
            self._page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(random.uniform(2.0, 4.0))
            current_url = self._page.url
            if "feed" in current_url or "mynetwork" in current_url or "jobs" in current_url:
                log.info(f"Login successful. URL: {current_url}")
                return self._page
            elif "checkpoint" in current_url or "challenge" in current_url:
                log.error("LinkedIn security challenge detected. Manual intervention required.")
                return None
            elif "login" in current_url:
                log.error("Still on login page. Credentials may be wrong.")
                return None
            else:
                log.info(f"Login likely successful. URL: {current_url}")
                return self._page
        except Exception as e:
            log.error(f"Login error: {e}")
            return None

"""
LinkedIn Login Handler using Playwright with stealth settings
"""

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

    def login(self, email: str, password: str) -> Page | None:
        self._playwright = sync_playwright().start()

        ua = random.choice(USER_AGENTS)
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=STEALTH_ARGS,
            slow_mo=random.randint(80, 150)
        )

        context = self._browser.new_context(
            user_agent=ua,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/Los_Angeles",
        )

        # Inject stealth JS to mask Playwright fingerprint
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)

        self._page = context.new_page()

        try:
            self._page.goto("https://www.linkedin.com/login", wait_until="networkidle", timeout=30000)
            time.sleep(random.uniform(1.5, 3.0))

            # Fill email
            self._page.fill("#username", email)
            time.sleep(random.uniform(0.5, 1.2))

            # Fill password with human-like typing
            self._page.click("#password")
            time.sleep(random.uniform(0.3, 0.8))
            self._page.fill("#password", password)
            time.sleep(random.uniform(0.8, 1.5))

            # Click sign in
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

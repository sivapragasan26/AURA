import time
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from playwright.sync_api import sync_playwright, Playwright, Browser, BrowserContext, Page
from aura.config import settings
from aura.browser.runtime_collector import RuntimeCollector
from aura.utils.logger import logger


class BrowserManager:
    """Manages Playwright browser instance, page context, viewport setup, and screenshot capture."""

    def __init__(self, headless: bool = settings.BROWSER_HEADLESS):
        self.headless = headless
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self.collector = RuntimeCollector()

    def start(self, viewport: Dict[str, int]):
        """Starts Playwright browser session with specified viewport."""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        self._context = self._browser.new_context(
            viewport=viewport,
            device_scale_factor=1.0,
            ignore_https_errors=True
        )
        self._page = self._context.new_page()
        # Fresh telemetry per audit: a reused engine must not carry console/network events
        # from a previously audited page into this one
        self.collector = RuntimeCollector()
        self.collector.attach_listeners(self._page)

    def navigate(self, url: str) -> Tuple[bool, str, float]:
        """Navigates to URL and measures page load timing."""
        if not self._page:
            return False, "Browser page not initialized", 0.0

        start_time = time.time()
        try:
            response = self._page.goto(
                url,
                timeout=settings.NAVIGATION_TIMEOUT_MS,
                wait_until="domcontentloaded"
            )
            # Give short pause for dynamic rendering
            self._page.wait_for_timeout(1000)
            elapsed_ms = (time.time() - start_time) * 1000
            self.collector.set_load_time(elapsed_ms)

            status_code = response.status if response else 200
            if status_code >= 400:
                return False, f"HTTP Error status code: {status_code}", elapsed_ms

            return True, "Page loaded successfully", elapsed_ms
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(f"Navigation error: {str(e)}")
            return False, f"Navigation failed: {str(e)}", elapsed_ms

    def capture_screenshots(self, output_dir: Path) -> Tuple[str, str]:
        """Captures viewport and full-page screenshots, returning local file paths."""
        if not self._page:
            raise RuntimeError("Page is not initialized")

        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        viewport_path = output_dir / f"screenshot_viewport_{timestamp}.png"
        fullpage_path = output_dir / f"screenshot_fullpage_{timestamp}.png"

        self._page.screenshot(path=str(viewport_path), full_page=False)
        self._page.screenshot(path=str(fullpage_path), full_page=True)

        return str(viewport_path), str(fullpage_path)

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Page is not active")
        return self._page

    def stop(self):
        """Closes browser session and Playwright driver safely."""
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.warning(f"Error closing browser session: {e}")
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None


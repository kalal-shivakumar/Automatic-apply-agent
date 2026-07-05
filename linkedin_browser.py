import logging
import os
import asyncio

from playwright.async_api import BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)


class LinkedInBrowser:
    """Manages a dedicated persistent browser session for LinkedIn."""

    def __init__(self):
        self.playwright = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.user_data_dir = os.path.join(os.path.dirname(__file__), "browser_data_linkedin")
        self.storage_state_path = os.path.join(os.path.dirname(__file__), "linkedin_storage_state.json")

    async def launch(self):
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
        )
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()
        logger.info("LinkedIn browser launched with persistent profile")

    async def wait_for_login(self) -> bool:
        """Navigate to LinkedIn and verify whether user is logged in."""
        await self.page.goto("https://www.linkedin.com/")
        await self.page.wait_for_load_state("networkidle")

        try:
            await self.page.wait_for_selector(
                'a[href*="/feed"], a[href*="/mynetwork"], button[aria-label*="Me"]',
                timeout=5000,
            )
            try:
                await self.context.storage_state(path=self.storage_state_path)
                logger.info(f"LinkedIn storage state saved: {self.storage_state_path}")
            except Exception as exc:
                logger.warning(f"LinkedIn storage state save failed: {exc}")
            logger.info("Already logged in to LinkedIn")
            return True
        except Exception:
            logger.info("LinkedIn login not detected yet. Waiting for manual login.")
            # Keep a tiny async pause so the page can settle before explicit verify calls from UI.
            await asyncio.sleep(0.5)
            return False

    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("LinkedIn browser closed")

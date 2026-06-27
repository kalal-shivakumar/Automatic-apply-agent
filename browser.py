import asyncio
import logging
from playwright.async_api import async_playwright, Page, BrowserContext
from config import Config

logger = logging.getLogger(__name__)


class NaukriBrowser:
    """Manages browser connection with persistent login session."""

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def launch(self):
        """Launch browser with persistent context (keeps login session)."""
        self.playwright = await async_playwright().start()

        # Use persistent context so user login is preserved across runs
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=Config.BROWSER_DATA_DIR,
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
        )

        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()

        logger.info("Browser launched with persistent context")

    async def wait_for_login(self):
        """Navigate to naukri.com and wait for user to login if needed."""
        await self.page.goto("https://www.naukri.com/")
        await self.page.wait_for_load_state("networkidle")

        # Check if already logged in by looking for profile icon or login button
        try:
            await self.page.wait_for_selector(
                'a[href*="mnjuser"], .nI-gNb-header__right--loggedIn, .view-profile-wrapper',
                timeout=5000
            )
            logger.info("Already logged in to Naukri.com")
            return True
        except Exception:
            logger.info("Not logged in. Please login manually in the browser window...")
            print("\n" + "=" * 60)
            print("Please LOGIN to Naukri.com in the browser window.")
            print("After logging in, press Enter here to continue...")
            print("=" * 60 + "\n")
            await asyncio.get_event_loop().run_in_executor(None, input)

            # Verify login after user presses Enter
            try:
                await self.page.wait_for_selector(
                    'a[href*="mnjuser"], .nI-gNb-header__right--loggedIn, .view-profile-wrapper',
                    timeout=10000
                )
                logger.info("Login confirmed!")
                return True
            except Exception:
                logger.error("Login could not be verified. Please try again.")
                return False

    async def close(self):
        """Close browser."""
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Browser closed")

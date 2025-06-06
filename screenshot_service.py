import asyncio
from playwright.async_api import async_playwright
import pathlib
import logging
from logging import Logger
from common.display_config import DisplayConfig

DISPLAY_CONFIG_FILE_PATH = './display_config.json'
ZOOM_FACTOR = 1.2

async def capture_dashboards(logger: Logger, display_config: DisplayConfig):
    async with async_playwright() as playwright:
        # Launch Firefox with specified screen size and accept-language header for German
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 800, "height": 480},
            locale="de-DE", # Set browser locale to German
            extra_http_headers={"Accept-Language": "de-DE"} # Ensure header is also set
        )
        page = await context.new_page()

        # Create a directory for screenshots
        screenshot_dir = pathlib.Path(display_config.config['display']['screenshot_dir'])
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        # List of dashboard URLs to capture
        dashboard_urls = display_config.config['display']['screenshot_urls']

        for i, url in enumerate(dashboard_urls):
            filename = f"screenshot_{i}.png"
            screenshot_path = screenshot_dir / filename

            logger.info(f"Navigating to {url}...")
            try:
                await page.goto(url, wait_until="networkidle", timeout=60000)

                logger.info(f"Waiting for <hui-card> on {url}...")
                await page.wait_for_selector("hui-card", state="visible", timeout=240000) # Waits for the element to be in the DOM
                await page.evaluate(f"document.body.style.zoom = '{ZOOM_FACTOR}'")
                await page.wait_for_timeout(1000) # Give it an extra second to truly settle
                await page.screenshot(path=screenshot_path, full_page=False)
                logger.info(f"Screenshot saved: {screenshot_path}")
            except Exception as e:
                logger.error(f"Error capturing {url}: {e}")

        await browser.close()
        logger.info("\nAll specified dashboards captured!")

if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.DEBUG)
    display_config = DisplayConfig(logger, DISPLAY_CONFIG_FILE_PATH)
    asyncio.run(capture_dashboards(logger, display_config))
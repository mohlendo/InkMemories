import asyncio
from playwright.async_api import async_playwright
import pathlib

async def capture_dashboards():
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
        screenshot_dir = pathlib.Path("homeassistant_screenshots")
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        # List of dashboard URLs to capture
        dashboard_urls = [
            "https://homeassistant.moh.ovh/dashboard-inky/0?kiosk",
            "https://homeassistant.moh.ovh/dashboard-inky/1?kiosk"
        ]

        for i, url in enumerate(dashboard_urls):
            filename = f"dashboard_{i}.png"
            screenshot_path = screenshot_dir / filename

            print(f"Navigating to {url}...")
            try:
                await page.goto(url, wait_until="networkidle", timeout=60000)

                print(f"Waiting for <hui-card> on {url}...")
                await page.wait_for_selector("hui-card", state="visible", timeout=240000) # Waits for the element to be in the DOM
                await page.wait_for_timeout(1000) # Give it an extra second to truly settle
                await page.screenshot(path=screenshot_path, full_page=False)
                print(f"Screenshot saved: {screenshot_path}")
            except Exception as e:
                print(f"Error capturing {url}: {e}")

        await browser.close()
        print("\nAll specified dashboards captured!")

if __name__ == "__main__":
    asyncio.run(capture_dashboards())
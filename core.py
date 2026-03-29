"""Core screenshot logic using Playwright with browser pooling."""

import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)


@dataclass
class ScreenshotParams:
    url: str
    viewport_width: int = 1280
    viewport_height: int = 720
    full_page: bool = False
    format: str = "png"
    wait_for: Optional[str] = None
    inject_css: Optional[str] = None
    block_cookies: bool = False
    delay_ms: int = 0

    def cache_key(self) -> str:
        raw = (
            f"{self.url}|{self.viewport_width}|{self.viewport_height}|"
            f"{self.full_page}|{self.format}|{self.wait_for}|"
            f"{self.inject_css}|{self.block_cookies}|{self.delay_ms}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def content_type(self) -> str:
        mapping = {"png": "image/png", "jpeg": "image/jpeg", "pdf": "application/pdf"}
        return mapping.get(self.format, "image/png")

    @property
    def file_extension(self) -> str:
        return self.format if self.format != "jpeg" else "jpg"


class BrowserPool:
    """Manages a pool of browser pages for concurrent screenshot requests."""

    def __init__(self, max_pages: int = 5):
        self._max_pages = max_pages
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._semaphore = asyncio.Semaphore(max_pages)
        self._started = False
        self._lock = asyncio.Lock()

    async def start(self):
        async with self._lock:
            if self._started:
                return
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--no-first-run",
                ],
            )
            self._started = True
            logger.info("Browser pool started with max %d concurrent pages", self._max_pages)

    async def stop(self):
        async with self._lock:
            if not self._started:
                return
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            self._started = False
            logger.info("Browser pool stopped")

    @asynccontextmanager
    async def acquire_page(self, params: ScreenshotParams):
        """Acquire a browser page from the pool."""
        if not self._started:
            await self.start()

        async with self._semaphore:
            context: BrowserContext = await self._browser.new_context(
                viewport={"width": params.viewport_width, "height": params.viewport_height},
                ignore_https_errors=True,
            )

            if params.block_cookies:
                await context.add_cookies([])
                await context.clear_cookies()

            page: Page = await context.new_page()
            try:
                yield page
            finally:
                await page.close()
                await context.close()


# Global browser pool
_pool: Optional[BrowserPool] = None


async def get_pool() -> BrowserPool:
    global _pool
    if _pool is None:
        _pool = BrowserPool(max_pages=5)
        await _pool.start()
    return _pool


async def shutdown_pool():
    global _pool
    if _pool is not None:
        await _pool.stop()
        _pool = None


async def take_screenshot(
    url: str,
    viewport_width: int = 1280,
    viewport_height: int = 720,
    full_page: bool = False,
    format: str = "png",
    wait_for: Optional[str] = None,
    inject_css: Optional[str] = None,
    block_cookies: bool = False,
    delay_ms: int = 0,
) -> bytes:
    """Take a screenshot of the given URL and return the image bytes."""
    params = ScreenshotParams(
        url=url,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        full_page=full_page,
        format=format,
        wait_for=wait_for,
        inject_css=inject_css,
        block_cookies=block_cookies,
        delay_ms=delay_ms,
    )

    pool = await get_pool()
    async with pool.acquire_page(params) as page:
        # Block cookie banners if requested
        if block_cookies:
            await page.route(
                "**/*",
                lambda route: route.abort()
                if any(
                    kw in route.request.url.lower()
                    for kw in ["cookie", "consent", "gdpr", "onetrust", "cookiebot"]
                )
                else route.continue_(),
            )

        # Navigate to URL
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            # Fallback: try with just domcontentloaded
            logger.warning("networkidle timeout for %s, falling back to domcontentloaded", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for specific selector if provided
        if wait_for:
            try:
                await page.wait_for_selector(wait_for, timeout=10000)
            except Exception:
                logger.warning("Selector '%s' not found within timeout", wait_for)

        # Inject custom CSS
        if inject_css:
            await page.add_style_tag(content=inject_css)

        # Additional delay
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)

        # Take screenshot or generate PDF
        if format == "pdf":
            data = await page.pdf(
                width=f"{viewport_width}px",
                height=f"{viewport_height}px",
                print_background=True,
            )
        else:
            screenshot_type = "png" if format == "png" else "jpeg"
            kwargs = {
                "type": screenshot_type,
                "full_page": full_page,
            }
            if screenshot_type == "jpeg":
                kwargs["quality"] = 85
            data = await page.screenshot(**kwargs)

    return data

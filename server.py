"""FastAPI REST API for the Screenshot Service."""

import asyncio
import base64
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl

from core import take_screenshot, shutdown_pool, ScreenshotParams
from cache import get_cache
from auth import get_auth_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("screenshot-api")

CLEANUP_INTERVAL = int(os.environ.get("CLEANUP_INTERVAL", "1800"))  # 30 min


async def periodic_cleanup():
    """Periodically clean up expired cache entries and old usage records."""
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        try:
            cache = get_cache()
            removed = await cache.cleanup()
            auth_db = get_auth_db()
            old_usage = auth_db.cleanup_old_usage()
            if removed or old_usage:
                logger.info("Cleanup: %d cache entries, %d old usage records", removed, old_usage)
        except Exception as e:
            logger.error("Cleanup error: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("Screenshot API starting up")
    cleanup_task = asyncio.create_task(periodic_cleanup())
    yield
    cleanup_task.cancel()
    await shutdown_pool()
    logger.info("Screenshot API shut down")


app = FastAPI(
    title="Screenshot API",
    description="Pixel-perfect website screenshot service",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScreenshotRequest(BaseModel):
    url: str = Field(..., description="URL to capture")
    viewport_width: int = Field(1280, ge=320, le=3840, description="Viewport width in pixels")
    viewport_height: int = Field(720, ge=240, le=2160, description="Viewport height in pixels")
    full_page: bool = Field(False, description="Capture entire scrollable page")
    format: str = Field("png", pattern="^(png|jpeg|pdf)$", description="Output format")
    wait_for: Optional[str] = Field(None, description="CSS selector to wait for before capture")
    block_cookies: bool = Field(False, description="Block cookie consent banners")
    inject_css: Optional[str] = Field(None, description="Custom CSS to inject before capture")
    delay_ms: int = Field(0, ge=0, le=10000, description="Additional delay in ms after page load")


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _check_auth(request: Request, api_key: Optional[str]) -> dict:
    """Validate API key and check rate limits. Returns rate limit info."""
    auth_db = get_auth_db()

    if api_key:
        key_info = auth_db.validate_key(api_key)
        if not key_info:
            raise HTTPException(status_code=401, detail="Invalid API key")
        tier = key_info["tier"]
        identity = api_key
    else:
        tier = "free"
        identity = _get_client_ip(request)

    rate_info = auth_db.check_rate_limit(identity, tier)
    if not rate_info["allowed"]:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "tier": tier,
                "limit": rate_info["limit"],
                "used": rate_info["used"],
                "resets": "midnight UTC",
            },
        )
    return {"identity": identity, "tier": tier, "rate_info": rate_info}


async def _do_screenshot(params: ScreenshotParams) -> bytes:
    """Take screenshot with caching."""
    cache = get_cache()
    cache_key = params.cache_key()

    # Check cache
    cached = await cache.get(cache_key, params.file_extension)
    if cached is not None:
        logger.info("Cache hit for %s", params.url)
        return cached

    # Take the screenshot
    data = await take_screenshot(
        url=params.url,
        viewport_width=params.viewport_width,
        viewport_height=params.viewport_height,
        full_page=params.full_page,
        format=params.format,
        wait_for=params.wait_for,
        inject_css=params.inject_css,
        block_cookies=params.block_cookies,
        delay_ms=params.delay_ms,
    )

    # Store in cache
    await cache.put(cache_key, data, params.file_extension)

    return data


@app.post("/screenshot")
async def post_screenshot(
    body: ScreenshotRequest,
    request: Request,
    x_api_key: Optional[str] = Header(None),
):
    """Take a screenshot of the given URL (POST with JSON body)."""
    auth_info = await _check_auth(request, x_api_key)

    params = ScreenshotParams(
        url=body.url,
        viewport_width=body.viewport_width,
        viewport_height=body.viewport_height,
        full_page=body.full_page,
        format=body.format,
        wait_for=body.wait_for,
        inject_css=body.inject_css,
        block_cookies=body.block_cookies,
        delay_ms=body.delay_ms,
    )

    try:
        data = await _do_screenshot(params)
    except Exception as e:
        logger.error("Screenshot failed for %s: %s", body.url, e)
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {str(e)}")

    # Increment usage after success
    get_auth_db().increment_usage(auth_info["identity"])

    return Response(
        content=data,
        media_type=params.content_type,
        headers={
            "X-Cache-Key": params.cache_key()[:16],
            "X-Rate-Remaining": str(auth_info["rate_info"]["remaining"] - 1),
        },
    )


@app.get("/screenshot")
async def get_screenshot(
    request: Request,
    url: str = Query(..., description="URL to capture"),
    width: int = Query(1280, ge=320, le=3840),
    height: int = Query(720, ge=240, le=2160),
    full_page: bool = Query(False),
    format: str = Query("png", pattern="^(png|jpeg|pdf)$"),
    wait_for: Optional[str] = Query(None),
    block_cookies: bool = Query(False),
    delay_ms: int = Query(0, ge=0, le=10000),
    x_api_key: Optional[str] = Header(None),
):
    """Take a screenshot via GET request (simpler, no CSS injection)."""
    auth_info = await _check_auth(request, x_api_key)

    params = ScreenshotParams(
        url=url,
        viewport_width=width,
        viewport_height=height,
        full_page=full_page,
        format=format,
        wait_for=wait_for,
        block_cookies=block_cookies,
        delay_ms=delay_ms,
    )

    try:
        data = await _do_screenshot(params)
    except Exception as e:
        logger.error("Screenshot failed for %s: %s", url, e)
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {str(e)}")

    get_auth_db().increment_usage(auth_info["identity"])

    return Response(
        content=data,
        media_type=params.content_type,
        headers={
            "X-Cache-Key": params.cache_key()[:16],
            "X-Rate-Remaining": str(auth_info["rate_info"]["remaining"] - 1),
        },
    )


@app.post("/screenshot/base64")
async def screenshot_base64(
    body: ScreenshotRequest,
    request: Request,
    x_api_key: Optional[str] = Header(None),
):
    """Take a screenshot and return it as a base64-encoded string."""
    auth_info = await _check_auth(request, x_api_key)

    params = ScreenshotParams(
        url=body.url,
        viewport_width=body.viewport_width,
        viewport_height=body.viewport_height,
        full_page=body.full_page,
        format=body.format,
        wait_for=body.wait_for,
        inject_css=body.inject_css,
        block_cookies=body.block_cookies,
        delay_ms=body.delay_ms,
    )

    try:
        data = await _do_screenshot(params)
    except Exception as e:
        logger.error("Screenshot failed for %s: %s", body.url, e)
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {str(e)}")

    get_auth_db().increment_usage(auth_info["identity"])

    b64 = base64.b64encode(data).decode("ascii")
    return JSONResponse(
        content={
            "url": body.url,
            "format": body.format,
            "content_type": params.content_type,
            "base64": b64,
            "size_bytes": len(data),
        },
        headers={
            "X-Rate-Remaining": str(auth_info["rate_info"]["remaining"] - 1),
        },
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "screenshot-api", "version": "0.1.0"}


@app.get("/stats")
async def stats(x_api_key: Optional[str] = Header(None)):
    """Return cache and usage statistics."""
    cache = get_cache()
    auth_db = get_auth_db()
    return {
        "cache": await cache.stats(),
        "usage": auth_db.get_usage_stats(),
    }


@app.post("/admin/keys")
async def create_api_key(
    key: str = Query(...),
    tier: str = Query("basic"),
    owner: str = Query(""),
    x_admin_key: str = Header(...),
):
    """Create a new API key (admin only)."""
    admin_key = os.environ.get("ADMIN_KEY", "")
    if not admin_key or x_admin_key != admin_key:
        raise HTTPException(status_code=403, detail="Forbidden")

    auth_db = get_auth_db()
    if auth_db.create_key(key, tier, owner):
        return {"status": "created", "key": key, "tier": tier}
    raise HTTPException(status_code=409, detail="Key already exists or invalid tier")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8500"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)

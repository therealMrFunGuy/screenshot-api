"""FastAPI REST API for the Screenshot Service."""

import asyncio
import base64
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, HttpUrl

from core import take_screenshot, shutdown_pool, ScreenshotParams
from cache import get_cache
from auth import get_auth_db
from auth_client import require_auth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("screenshot-api")

AUTH_SERVICE_URL = os.environ.get("AUTH_SERVICE_URL", "http://localhost:8499")
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


LANDING_PAGE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>ScreenshotAPI - Pixel-Perfect Website Screenshots via API</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    html { scroll-behavior: smooth; }
    .code-block { background: #1e293b; color: #e2e8f0; border-radius: 0.5rem; padding: 1.25rem; overflow-x: auto; font-size: 0.85rem; line-height: 1.6; }
    .code-block code { font-family: 'Menlo', 'Monaco', 'Courier New', monospace; }
    .tab-btn.active { border-color: #6366f1; color: #6366f1; background: #eef2ff; }
  </style>
</head>
<body class="bg-white text-gray-900 antialiased">

  <!-- Nav -->
  <nav class="sticky top-0 z-50 bg-white/80 backdrop-blur border-b border-gray-200">
    <div class="max-w-6xl mx-auto flex items-center justify-between px-6 py-4">
      <a href="#" class="flex items-center gap-2 text-xl font-bold text-indigo-600">
        <svg class="w-7 h-7" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><circle cx="7" cy="6" r="1"/><circle cx="11" cy="6" r="1"/></svg>
        ScreenshotAPI
      </a>
      <div class="hidden md:flex items-center gap-8 text-sm font-medium text-gray-600">
        <a href="#features" class="hover:text-indigo-600 transition">Features</a>
        <a href="#pricing" class="hover:text-indigo-600 transition">Pricing</a>
        <a href="#docs" class="hover:text-indigo-600 transition">Docs</a>
        <a href="https://github.com/therealMrFunGuy/screenshot-api" target="_blank" class="hover:text-indigo-600 transition">GitHub</a>
      </div>
      <a href="#demo" class="hidden md:inline-flex items-center gap-1 bg-indigo-600 text-white text-sm font-medium px-4 py-2 rounded-lg hover:bg-indigo-700 transition">
        Try it free &rarr;
      </a>
    </div>
  </nav>

  <!-- Hero -->
  <section class="relative overflow-hidden bg-gradient-to-br from-indigo-600 via-blue-600 to-indigo-800 text-white">
    <div class="absolute inset-0 opacity-10">
      <div class="absolute top-10 left-10 w-72 h-72 bg-white rounded-full blur-3xl"></div>
      <div class="absolute bottom-10 right-10 w-96 h-96 bg-blue-300 rounded-full blur-3xl"></div>
    </div>
    <div class="relative max-w-6xl mx-auto px-6 py-24 md:py-32 text-center">
      <h1 class="text-4xl md:text-6xl font-extrabold leading-tight tracking-tight">
        Pixel-Perfect Website<br/>Screenshots via API
      </h1>
      <p class="mt-6 text-lg md:text-xl text-indigo-100 max-w-2xl mx-auto">
        Capture any webpage as PNG, JPEG, or PDF. Built on Playwright with built-in caching, API key auth, and a first-class MCP server for AI tool integration.
      </p>

      <!-- Live Demo -->
      <div id="demo" class="mt-12 max-w-xl mx-auto">
        <form action="/screenshot" method="get" target="_blank" class="flex flex-col sm:flex-row gap-3">
          <input type="text" name="url" placeholder="https://example.com" required
            class="flex-1 px-4 py-3 rounded-lg text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-300 shadow-lg"/>
          <button type="submit" class="bg-white text-indigo-700 font-semibold px-6 py-3 rounded-lg hover:bg-indigo-50 transition shadow-lg whitespace-nowrap">
            Capture &rarr;
          </button>
        </form>
        <p class="mt-3 text-xs text-indigo-200">Enter any URL above to get a live screenshot. No sign-up required.</p>
      </div>
    </div>
  </section>

  <!-- Code Examples -->
  <section class="py-20 bg-gray-50">
    <div class="max-w-6xl mx-auto px-6">
      <h2 class="text-3xl font-bold text-center mb-2">Get started in seconds</h2>
      <p class="text-center text-gray-500 mb-10">Works with any language, any platform. First-class MCP support for AI agents.</p>

      <div class="flex gap-2 mb-4 border-b border-gray-200">
        <button onclick="showTab('curl')" id="tab-curl" class="tab-btn active px-4 py-2 text-sm font-medium border-b-2 border-transparent rounded-t transition">cURL</button>
        <button onclick="showTab('python')" id="tab-python" class="tab-btn px-4 py-2 text-sm font-medium border-b-2 border-transparent rounded-t transition">Python</button>
        <button onclick="showTab('mcp')" id="tab-mcp" class="tab-btn px-4 py-2 text-sm font-medium border-b-2 border-transparent rounded-t transition">MCP Config</button>
      </div>

      <div id="code-curl" class="code-block"><code>curl "https://your-host/screenshot?url=https://example.com&amp;width=1280&amp;height=720" \\
  -H "X-API-Key: your_key" \\
  -o screenshot.png</code></div>

      <div id="code-python" class="code-block hidden"><code>import requests

resp = requests.post("https://your-host/screenshot", json={
    "url": "https://example.com",
    "viewport_width": 1280,
    "viewport_height": 720,
    "full_page": True,
    "format": "png"
}, headers={"X-API-Key": "your_key"})

with open("screenshot.png", "wb") as f:
    f.write(resp.content)</code></div>

      <div id="code-mcp" class="code-block hidden"><code>{
  "mcpServers": {
    "screenshot": {
      "command": "uvx",
      "args": ["mcp-server-screenshot"],
      "env": {
        "SCREENSHOT_API_URL": "https://your-host",
        "SCREENSHOT_API_KEY": "your_key"
      }
    }
  }
}</code></div>
    </div>
  </section>

  <script>
    function showTab(name) {
      document.querySelectorAll('[id^="code-"]').forEach(el => el.classList.add('hidden'));
      document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
      document.getElementById('code-' + name).classList.remove('hidden');
      document.getElementById('tab-' + name).classList.add('active');
    }
  </script>

  <!-- Features -->
  <section id="features" class="py-20">
    <div class="max-w-6xl mx-auto px-6">
      <h2 class="text-3xl font-bold text-center mb-2">Everything you need</h2>
      <p class="text-center text-gray-500 mb-12">Production-ready screenshot infrastructure out of the box.</p>

      <div class="grid md:grid-cols-2 lg:grid-cols-4 gap-8">
        <div class="bg-white border border-gray-200 rounded-xl p-6 hover:shadow-lg transition">
          <div class="w-12 h-12 bg-indigo-100 text-indigo-600 rounded-lg flex items-center justify-center mb-4">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/></svg>
          </div>
          <h3 class="font-semibold text-lg mb-2">Playwright-Powered</h3>
          <p class="text-sm text-gray-500">Real Chromium browser rendering. Supports JavaScript, SPAs, cookie banners, custom CSS injection, and wait-for selectors.</p>
        </div>

        <div class="bg-white border border-gray-200 rounded-xl p-6 hover:shadow-lg transition">
          <div class="w-12 h-12 bg-blue-100 text-blue-600 rounded-lg flex items-center justify-center mb-4">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
          </div>
          <h3 class="font-semibold text-lg mb-2">Smart Caching</h3>
          <p class="text-sm text-gray-500">Automatic content-based caching with configurable TTL. Identical requests are served instantly from disk cache.</p>
        </div>

        <div class="bg-white border border-gray-200 rounded-xl p-6 hover:shadow-lg transition">
          <div class="w-12 h-12 bg-emerald-100 text-emerald-600 rounded-lg flex items-center justify-center mb-4">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
          </div>
          <h3 class="font-semibold text-lg mb-2">API Key Auth</h3>
          <p class="text-sm text-gray-500">Tiered API keys with per-day rate limiting. Free tier included. Admin endpoints for key management.</p>
        </div>

        <div class="bg-white border border-gray-200 rounded-xl p-6 hover:shadow-lg transition">
          <div class="w-12 h-12 bg-purple-100 text-purple-600 rounded-lg flex items-center justify-center mb-4">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
          </div>
          <h3 class="font-semibold text-lg mb-2">MCP Server</h3>
          <p class="text-sm text-gray-500">First-class Model Context Protocol server. Drop into Claude, Cursor, or any MCP-compatible AI agent as a tool.</p>
        </div>
      </div>
    </div>
  </section>

  <!-- Pricing -->
  <section id="pricing" class="py-20 bg-gray-50">
    <div class="max-w-6xl mx-auto px-6">
      <h2 class="text-3xl font-bold text-center mb-2">Simple, transparent pricing</h2>
      <p class="text-center text-gray-500 mb-12">Start free, scale when you need to.</p>

      <div class="grid md:grid-cols-3 gap-8 max-w-4xl mx-auto">
        <!-- Free -->
        <div class="bg-white border border-gray-200 rounded-xl p-8">
          <h3 class="text-lg font-semibold text-gray-900">Free</h3>
          <div class="mt-4 flex items-baseline gap-1">
            <span class="text-4xl font-extrabold">$0</span>
            <span class="text-gray-500 text-sm">/month</span>
          </div>
          <ul class="mt-6 space-y-3 text-sm text-gray-600">
            <li class="flex items-center gap-2"><svg class="w-4 h-4 text-indigo-500 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>100 screenshots / day</li>
            <li class="flex items-center gap-2"><svg class="w-4 h-4 text-indigo-500 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>1280&times;720 default</li>
            <li class="flex items-center gap-2"><svg class="w-4 h-4 text-indigo-500 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>PNG &amp; JPEG formats</li>
            <li class="flex items-center gap-2"><svg class="w-4 h-4 text-indigo-500 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>Community support</li>
          </ul>
          <a href="#demo" class="mt-8 block text-center bg-gray-100 text-gray-700 font-medium py-2.5 rounded-lg hover:bg-gray-200 transition">Get started</a>
        </div>

        <!-- Pro -->
        <div class="bg-white border-2 border-indigo-600 rounded-xl p-8 relative shadow-lg">
          <span class="absolute -top-3 left-1/2 -translate-x-1/2 bg-indigo-600 text-white text-xs font-bold px-3 py-1 rounded-full">Popular</span>
          <h3 class="text-lg font-semibold text-gray-900">Pro</h3>
          <div class="mt-4 flex items-baseline gap-1">
            <span class="text-4xl font-extrabold">$19</span>
            <span class="text-gray-500 text-sm">/month</span>
          </div>
          <ul class="mt-6 space-y-3 text-sm text-gray-600">
            <li class="flex items-center gap-2"><svg class="w-4 h-4 text-indigo-500 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>10,000 screenshots / day</li>
            <li class="flex items-center gap-2"><svg class="w-4 h-4 text-indigo-500 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>Custom viewports up to 4K</li>
            <li class="flex items-center gap-2"><svg class="w-4 h-4 text-indigo-500 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>PDF export</li>
            <li class="flex items-center gap-2"><svg class="w-4 h-4 text-indigo-500 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>Priority support</li>
          </ul>
          <a href="#demo" class="mt-8 block text-center bg-indigo-600 text-white font-medium py-2.5 rounded-lg hover:bg-indigo-700 transition">Start free trial</a>
        </div>

        <!-- Enterprise -->
        <div class="bg-white border border-gray-200 rounded-xl p-8">
          <h3 class="text-lg font-semibold text-gray-900">Enterprise</h3>
          <div class="mt-4 flex items-baseline gap-1">
            <span class="text-4xl font-extrabold">Custom</span>
          </div>
          <ul class="mt-6 space-y-3 text-sm text-gray-600">
            <li class="flex items-center gap-2"><svg class="w-4 h-4 text-indigo-500 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>Custom daily limits</li>
            <li class="flex items-center gap-2"><svg class="w-4 h-4 text-indigo-500 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>SLA guarantee</li>
            <li class="flex items-center gap-2"><svg class="w-4 h-4 text-indigo-500 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>Dedicated support</li>
            <li class="flex items-center gap-2"><svg class="w-4 h-4 text-indigo-500 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>Self-hosted option</li>
          </ul>
          <a href="mailto:hello@rjctdlabs.xyz" class="mt-8 block text-center bg-gray-100 text-gray-700 font-medium py-2.5 rounded-lg hover:bg-gray-200 transition">Contact us</a>
        </div>
      </div>
    </div>
  </section>

  <!-- API Reference -->
  <section id="docs" class="py-20">
    <div class="max-w-6xl mx-auto px-6">
      <h2 class="text-3xl font-bold text-center mb-2">API Reference</h2>
      <p class="text-center text-gray-500 mb-12">Four endpoints. That's it.</p>

      <div class="grid md:grid-cols-2 gap-6 max-w-4xl mx-auto">
        <div class="border border-gray-200 rounded-xl p-6">
          <div class="flex items-center gap-2 mb-3">
            <span class="bg-blue-100 text-blue-700 text-xs font-bold px-2 py-1 rounded">POST</span>
            <code class="text-sm font-mono font-semibold">/screenshot</code>
          </div>
          <p class="text-sm text-gray-500">Capture a screenshot with full options. Accepts JSON body with <code class="text-xs bg-gray-100 px-1 py-0.5 rounded">url</code>, <code class="text-xs bg-gray-100 px-1 py-0.5 rounded">viewport_width</code>, <code class="text-xs bg-gray-100 px-1 py-0.5 rounded">viewport_height</code>, <code class="text-xs bg-gray-100 px-1 py-0.5 rounded">full_page</code>, <code class="text-xs bg-gray-100 px-1 py-0.5 rounded">format</code>, <code class="text-xs bg-gray-100 px-1 py-0.5 rounded">inject_css</code>, and more. Returns the image binary.</p>
        </div>

        <div class="border border-gray-200 rounded-xl p-6">
          <div class="flex items-center gap-2 mb-3">
            <span class="bg-emerald-100 text-emerald-700 text-xs font-bold px-2 py-1 rounded">GET</span>
            <code class="text-sm font-mono font-semibold">/screenshot</code>
          </div>
          <p class="text-sm text-gray-500">Simple query-string capture. Pass <code class="text-xs bg-gray-100 px-1 py-0.5 rounded">url</code>, <code class="text-xs bg-gray-100 px-1 py-0.5 rounded">width</code>, <code class="text-xs bg-gray-100 px-1 py-0.5 rounded">height</code>, <code class="text-xs bg-gray-100 px-1 py-0.5 rounded">full_page</code>, <code class="text-xs bg-gray-100 px-1 py-0.5 rounded">format</code> as query params. Great for browser testing.</p>
        </div>

        <div class="border border-gray-200 rounded-xl p-6">
          <div class="flex items-center gap-2 mb-3">
            <span class="bg-blue-100 text-blue-700 text-xs font-bold px-2 py-1 rounded">POST</span>
            <code class="text-sm font-mono font-semibold">/screenshot/base64</code>
          </div>
          <p class="text-sm text-gray-500">Same as POST /screenshot but returns a JSON object with <code class="text-xs bg-gray-100 px-1 py-0.5 rounded">base64</code> encoded image data. Ideal for embedding or piping to AI models.</p>
        </div>

        <div class="border border-gray-200 rounded-xl p-6">
          <div class="flex items-center gap-2 mb-3">
            <span class="bg-emerald-100 text-emerald-700 text-xs font-bold px-2 py-1 rounded">GET</span>
            <code class="text-sm font-mono font-semibold">/stats</code>
          </div>
          <p class="text-sm text-gray-500">Returns cache statistics and usage data. Shows total cached items, hit/miss rates, and per-key usage counts.</p>
        </div>
      </div>

      <p class="text-center mt-8 text-sm text-gray-400">Full interactive docs available at <a href="/docs" class="text-indigo-600 hover:underline">/docs</a> (Swagger UI) and <a href="/redoc" class="text-indigo-600 hover:underline">/redoc</a></p>
    </div>
  </section>

  <!-- Footer -->
  <footer class="bg-gray-900 text-gray-400 py-12">
    <div class="max-w-6xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-6">
      <div class="text-sm">
        Powered by <a href="https://rjctdlabs.xyz" target="_blank" class="text-white hover:text-indigo-400 transition">rjctdlabs.xyz</a>
      </div>
      <div class="flex items-center gap-6 text-sm">
        <a href="https://github.com/therealMrFunGuy/screenshot-api" target="_blank" class="hover:text-white transition">GitHub</a>
        <a href="https://pypi.org/project/mcp-server-screenshot/" target="_blank" class="hover:text-white transition">PyPI</a>
        <a href="/docs" class="hover:text-white transition">API Docs</a>
        <a href="/health" class="hover:text-white transition">Status</a>
      </div>
    </div>
  </footer>

</body>
</html>
"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing_page():
    """Serve the landing page."""
    return HTMLResponse(content=LANDING_PAGE_HTML)


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
    auth: dict = Depends(require_auth),
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
    auth: dict = Depends(require_auth),
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
    auth: dict = Depends(require_auth),
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
async def stats(x_api_key: Optional[str] = Header(None), auth: dict = Depends(require_auth)):
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

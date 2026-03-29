# Screenshot API

Pixel-perfect website screenshot service that captures any URL as PNG, JPEG, or PDF. Exposed as both a REST API (FastAPI) and an MCP server for use with Claude Desktop, Cursor, and other MCP-compatible clients. Uses Playwright with a pooled Chromium browser for fast, reliable rendering.

## Quick Start

### Docker (recommended)

```bash
docker-compose up -d
```

The API will be available at `http://localhost:8500`.

### Local Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bash setup_browsers.sh
python server.py
```

## MCP Installation

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "screenshot": {
      "command": "python",
      "args": ["/path/to/mcp-services/screenshot-api/mcp_server.py"]
    }
  }
}
```

### Cursor

Add to your Cursor MCP settings:

```json
{
  "mcpServers": {
    "screenshot": {
      "command": "python",
      "args": ["/path/to/mcp-services/screenshot-api/mcp_server.py"]
    }
  }
}
```

### Via uvx (after PyPI publish)

```json
{
  "mcpServers": {
    "screenshot": {
      "command": "uvx",
      "args": ["mcp-server-screenshot"]
    }
  }
}
```

## API Documentation

### Endpoints

#### `POST /screenshot`

Take a screenshot with full control over parameters.

**Request body (JSON):**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | string | *required* | URL to capture |
| `viewport_width` | int | 1280 | Viewport width (320-3840) |
| `viewport_height` | int | 720 | Viewport height (240-2160) |
| `full_page` | bool | false | Capture entire scrollable page |
| `format` | string | "png" | Output: "png", "jpeg", or "pdf" |
| `wait_for` | string | null | CSS selector to wait for |
| `block_cookies` | bool | false | Block cookie consent banners |
| `inject_css` | string | null | Custom CSS to inject |
| `delay_ms` | int | 0 | Extra delay after load (0-10000) |

**Example:**

```bash
curl -X POST http://localhost:8500/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "full_page": true, "format": "png"}' \
  -o screenshot.png
```

#### `GET /screenshot`

Simple GET-based screenshot (no CSS injection support).

```bash
curl "http://localhost:8500/screenshot?url=https://example.com&width=1920&height=1080&format=jpeg" -o screenshot.jpg
```

**Query parameters:** `url`, `width`, `height`, `full_page`, `format`, `wait_for`, `block_cookies`, `delay_ms`

#### `POST /screenshot/base64`

Same parameters as POST /screenshot, returns JSON with base64-encoded image.

```bash
curl -X POST http://localhost:8500/screenshot/base64 \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

**Response:**

```json
{
  "url": "https://example.com",
  "format": "png",
  "content_type": "image/png",
  "base64": "iVBORw0KGgo...",
  "size_bytes": 45231
}
```

#### `GET /health`

Health check. Returns `{"status": "ok"}`.

#### `GET /stats`

Cache and usage statistics.

#### `POST /admin/keys`

Create API keys (requires `X-Admin-Key` header matching `ADMIN_KEY` env var).

```bash
curl -X POST "http://localhost:8500/admin/keys?key=my-api-key&tier=pro&owner=alice" \
  -H "X-Admin-Key: your-admin-key"
```

### Authentication

| Header | Description |
|--------|-------------|
| `X-API-Key` | Your API key. Omit for free tier. |

### Response Headers

| Header | Description |
|--------|-------------|
| `X-Cache-Key` | Truncated cache key for debugging |
| `X-Rate-Remaining` | Remaining requests today |

## MCP Tools

When used as an MCP server, two tools are available:

### `take_screenshot`

Returns the screenshot as a viewable image (ImageContent for PNG/JPEG, TextContent with base64 for PDF).

### `screenshot_to_base64`

Returns the screenshot as a base64 string in a TextContent response, suitable for passing to other tools or embedding.

Both tools accept: `url`, `viewport_width`, `viewport_height`, `full_page`, `format`, `wait_for`, `inject_css`.

## Pricing Tiers

| Tier | Daily Limit | Auth |
|------|-------------|------|
| Free | 100/day per IP | No key needed |
| Basic | 1,000/day | API key |
| Pro | 10,000/day | API key |
| Enterprise | 100,000/day | API key |

## Caching

Screenshots are cached using SHA256(url + params) as the key. Default TTL is 1 hour (configurable via `CACHE_TTL`). Expired entries are cleaned up automatically every 30 minutes.

## Self-Hosting

### Environment Variables

See `.env.example` for all options. Key settings:

- `CACHE_DIR` - Where cached screenshots are stored (default: `/data/cache`)
- `CACHE_TTL` - Cache duration in seconds (default: `3600`)
- `MAX_FREE_DAILY` - Free tier daily limit (default: `100`)
- `ADMIN_KEY` - Secret key for the admin endpoints
- `PORT` - API port (default: `8500`)

### Docker Resource Limits

The default `docker-compose.yml` limits the container to 2 CPU cores and 2GB RAM. Adjust in the `deploy.resources` section as needed.

### Persistent Storage

The docker-compose file uses a named volume `screenshot-data` for the cache and SQLite database. To use a host directory instead:

```yaml
volumes:
  - /path/on/host:/data
```

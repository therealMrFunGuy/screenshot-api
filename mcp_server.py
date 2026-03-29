"""MCP Server for the Screenshot Service.

Exposes take_screenshot and screenshot_to_base64 as MCP tools.
Can be run standalone: python mcp_server.py
Or installed via: uvx mcp-server-screenshot
"""

import asyncio
import base64
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent

from core import take_screenshot, shutdown_pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-screenshot")

server = Server("mcp-server-screenshot")


SCREENSHOT_PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "The URL to capture a screenshot of",
        },
        "viewport_width": {
            "type": "integer",
            "description": "Viewport width in pixels (default: 1280)",
            "default": 1280,
            "minimum": 320,
            "maximum": 3840,
        },
        "viewport_height": {
            "type": "integer",
            "description": "Viewport height in pixels (default: 720)",
            "default": 720,
            "minimum": 240,
            "maximum": 2160,
        },
        "full_page": {
            "type": "boolean",
            "description": "Capture the entire scrollable page (default: false)",
            "default": False,
        },
        "format": {
            "type": "string",
            "enum": ["png", "jpeg", "pdf"],
            "description": "Output format (default: png)",
            "default": "png",
        },
        "wait_for": {
            "type": "string",
            "description": "CSS selector to wait for before capturing",
        },
        "inject_css": {
            "type": "string",
            "description": "Custom CSS to inject before capturing",
        },
    },
    "required": ["url"],
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="take_screenshot",
            description=(
                "Take a pixel-perfect screenshot of a website URL. "
                "Returns the screenshot as an image that can be viewed directly. "
                "Supports PNG, JPEG, and PDF output formats."
            ),
            inputSchema=SCREENSHOT_PARAMS_SCHEMA,
        ),
        Tool(
            name="screenshot_to_base64",
            description=(
                "Take a screenshot of a website URL and return it as a base64-encoded string. "
                "Useful for embedding screenshots inline in responses or passing to other tools. "
                "Supports PNG, JPEG, and PDF output formats."
            ),
            inputSchema=SCREENSHOT_PARAMS_SCHEMA,
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent]:
    url = arguments.get("url")
    if not url:
        return [TextContent(type="text", text="Error: 'url' parameter is required")]

    viewport_width = arguments.get("viewport_width", 1280)
    viewport_height = arguments.get("viewport_height", 720)
    full_page = arguments.get("full_page", False)
    fmt = arguments.get("format", "png")
    wait_for = arguments.get("wait_for")
    inject_css = arguments.get("inject_css")

    try:
        data = await take_screenshot(
            url=url,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            full_page=full_page,
            format=fmt,
            wait_for=wait_for,
            inject_css=inject_css,
        )
    except Exception as e:
        logger.error("Screenshot failed for %s: %s", url, e)
        return [TextContent(type="text", text=f"Screenshot failed: {str(e)}")]

    if name == "take_screenshot":
        if fmt == "pdf":
            b64 = base64.b64encode(data).decode("ascii")
            return [
                TextContent(
                    type="text",
                    text=f"PDF screenshot of {url} ({len(data)} bytes). Base64-encoded data follows:",
                ),
                TextContent(type="text", text=b64),
            ]
        media_type = "image/png" if fmt == "png" else "image/jpeg"
        b64 = base64.b64encode(data).decode("ascii")
        return [
            ImageContent(type="image", data=b64, mimeType=media_type),
        ]

    elif name == "screenshot_to_base64":
        b64 = base64.b64encode(data).decode("ascii")
        content_type = {
            "png": "image/png",
            "jpeg": "image/jpeg",
            "pdf": "application/pdf",
        }.get(fmt, "image/png")
        return [
            TextContent(
                type="text",
                text=(
                    f"Screenshot of {url}\n"
                    f"Format: {fmt} | Size: {len(data)} bytes | "
                    f"Viewport: {viewport_width}x{viewport_height}\n"
                    f"Content-Type: {content_type}\n"
                    f"Base64: {b64}"
                ),
            ),
        ]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    logger.info("Starting MCP Screenshot Server (stdio)")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
    await shutdown_pool()


if __name__ == "__main__":
    asyncio.run(main())

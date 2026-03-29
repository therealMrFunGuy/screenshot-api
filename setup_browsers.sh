#!/usr/bin/env bash
# Install Playwright and Chromium browser for local development.
# Run this after pip install -r requirements.txt

set -euo pipefail

echo "Installing Playwright Chromium browser..."
playwright install chromium

echo "Installing system dependencies for Chromium..."
playwright install-deps chromium

echo "Done. Chromium is ready for screenshot capture."

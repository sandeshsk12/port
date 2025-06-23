#!/bin/bash
set -e

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers
python -m playwright install

# Install system dependencies for Playwright
python -m playwright install-deps

#!/bin/bash
set -e

echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "Installing Playwright browsers..."
python -m playwright install --with-deps

# Create public directory if it doesn't exist
mkdir -p public

# The index.html is already in the public directory
# No need to generate it here

echo "Build completed successfully!"

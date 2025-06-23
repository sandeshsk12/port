#!/bin/bash
set -e

# Install Python
python --version

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright and its dependencies
python -m playwright install --with-deps

# Create public directory
mkdir -p public

# Create a simple redirect page
echo "<html><head><meta http-equiv=\"refresh\" content=\"0;url=https://share.streamlit.io/sandeshsk12/port/streamlit_app.py\"></head><body>Redirecting to Streamlit Cloud...</body></html>" > public/index.html

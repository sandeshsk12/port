#!/bin/bash
set -e

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers
python -m playwright install

# Create a static version of the Streamlit app
mkdir -p public
echo "<html><head><meta http-equiv=\"refresh\" content=\"0;url=https://share.streamlit.io/YOUR_USERNAME/REPO_NAME/streamlit_app.py\"></head><body>Redirecting to Streamlit Cloud...</body></html>" > public/index.html

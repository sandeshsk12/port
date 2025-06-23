# Website Scraper with Streamlit

This is a Streamlit application that allows users to scrape websites and download their content locally.

## Local Development

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   python -m playwright install
   ```
3. Run the app:
   ```
   streamlit run streamlit_app.py
   ```

## Deployment

This app is configured for deployment on Streamlit Cloud or similar services. The `netlify.toml` file contains the build configuration.

### Requirements

- Python 3.11
- Playwright browsers (installed automatically during setup)

### Environment Variables

No environment variables are required by default, but you can create a `.env` file for any sensitive configuration.

## License

MIT

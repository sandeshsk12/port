# Offline Website Downloader

This tool creates an offline mirror of a website with tabbed navigation. It automatically detects and downloads all main navigation tabs, including their resources (CSS, JS, images), and creates a local, browsable version of the site.

## Features

- ✅ Downloads complete web pages including all assets
- ✅ Handles dynamic tabbed navigation
- ✅ Preserves original styling and layout
- ✅ Creates a clean index page for easy navigation
- ✅ Works with modern JavaScript-heavy websites
- ✅ Removes watermarks and unwanted UI elements

## Requirements

- Python 3.10+
- Playwright
- BeautifulSoup4
- aiohttp
- aiofiles

## Installation

1. Clone this repository
2. Install the required packages:
   ```bash
   pip install playwright beautifulsoup4 aiohttp aiofiles
   playwright install
   ```

## Usage

1. Edit the `URL` constant in `clicker.py` to point to the website you want to download
2. Run the script:
   ```bash
   python clicker.py
   ```
3. Open `offline_index.html` in your browser to browse the downloaded pages

## How It Works

1. The script first loads the main page and identifies all navigation buttons
2. It then simulates clicks on each button to load the corresponding pages
3. For each page, it downloads all assets (CSS, JS, images) and updates the HTML to use local paths
4. Finally, it creates an index page with links to all downloaded pages

## Customization

- To adjust which elements are considered navigation buttons, modify the `collect_click_paths` function in `clicker.py`
- To customize the offline index page, edit `offline_index.html`
- To modify how resources are downloaded, see the `download_resource` function in `website_downloader.py`

## License

MIT

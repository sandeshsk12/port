"""combined_downloader.py

A single‑entry script that orchestrates the workflow of:

1.  Downloading the landing page and its assets (`website_downloader.py`).
2.  Discovering navigation‑tab buttons in the downloaded HTML.
3.  Iteratively visiting each tab in a real headless browser session and
    downloading its fully rendered HTML with all referenced resources
    (`download_tabs_with_resources.py`).

Edit the URL constant below as required, then simply run:

    python combined_downloader.py

All pages are saved under ./downloaded_pages/<tab-name>/ …
"""

import asyncio
from pathlib import Path
from typing import List, Dict

from bs4 import BeautifulSoup

# Local modules
from website_downloader import download_website
from download_tabs_with_resources import TabDownloader


# ────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────
URL: str = (
    "https://flipsidecrypto.xyz/Sandesh/my-pet-hooligan---the-fps-frontier--Q7dYU"
)

# You can safely change the URL above or set it programmatically.


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def extract_nav_tabs(html_file: Path) -> List[Dict[str, str]]:
    """Return a list of navigation‑tab dictionaries → {name, id}.

    Heuristics:
        * ``<button>`` element with an ``id`` containing "trigger-tab-layout"
        * Falls back to role="tab" buttons
    """
    with open(html_file, "r", encoding="utf-8") as fh:
        soup = BeautifulSoup(fh, "html.parser")

    tabs: List[Dict[str, str]] = []

    # Strategy 1 – id contains trigger‑tab‑layout (matches Radix primitives)
    for btn in soup.find_all("button", id=lambda x: x and "trigger-tab-layout" in x):
        tab_name = btn.get_text(strip=True) or btn["id"]
        tabs.append({"name": tab_name, "id": btn["id"]})

    # Strategy 2 – role="tab" as a generic fallback
    if not tabs:
        for btn in soup.find_all("button", attrs={"role": "tab"}):
            tab_id = btn.get("id")
            if tab_id:
                tab_name = btn.get_text(strip=True) or tab_id
                tabs.append({"name": tab_name, "id": tab_id})

    # De‑duplicate while preserving order
    seen = set()
    unique_tabs = []
    for t in tabs:
        if t["id"] not in seen:
            unique_tabs.append(t)
            seen.add(t["id"])

    return unique_tabs


def main() -> None:
    # 1. Download landing page
    html_path = Path(download_website(URL))
    if not html_path.exists():
        raise FileNotFoundError(
            f"Landing page not downloaded correctly: {html_path}"
        )

    # 2. Detect navigation tabs
    tabs = extract_nav_tabs(html_path)
    if not tabs:
        print("❗  No navigation tabs detected — stopping.")
        return

    print("Detected navigation tabs:")
    for t in tabs:
        print(f"  • {t['name']}  (id={t['id']})")

    # 3. Download each tab (including assets)
    downloader = TabDownloader(URL)
    asyncio.run(downloader.run(tabs))


if __name__ == "__main__":
    main()

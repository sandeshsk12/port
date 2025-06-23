"""Script to update navigation <a> href values in landing_page.html (or any
HTML file) so they point to already-downloaded offline pages under
`downloaded_pages/<slug>/index.html` instead of the original live URL.

Usage (run once):
    python update_links.py landing_page.html

The script keeps a backup <filename>.bak before writing changes.
"""

import sys
from pathlib import Path
from bs4 import BeautifulSoup

# Slugs that have been downloaded already – add more if you download extra pages
SLUGS = [
    "about",
    "airdrop",
    "author",
    "governance",
    "houekeeping",
    "nft",
    "socials",
    "tokens",
]


def build_mapping():
    """Return dict mapping original href values to local file path."""
    mapping = {}
    for slug in SLUGS:
        # original URLs might show up in different shapes, account for common ones
        originals = {
            f"/{slug}",
            f"/{slug}/",  # trailing slash
            f"/{slug}/index",  # sometimes
            f"https://flipsidecrypto.xyz/{slug}",
        }
        local_path = f"downloaded_pages/{slug}/index.html"
        for o in originals:
            mapping[o] = local_path
    # special-case home page
    mapping["/"] = "landing_page.html"  # or offline_index.html if you prefer
    return mapping


def update_file(html_path: Path):
    html_text = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html_text, "html.parser")

    mapping = build_mapping()
    changed = False

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # strip query string when comparing
        href_base = href.split("?")[0]
        if href_base in mapping:
            new_href = mapping[href_base]
            if href != new_href:
                a["href"] = new_href
                changed = True
    if changed:
        backup = html_path.with_suffix(html_path.suffix + ".bak")
        html_path.rename(backup)
        html_path.write_text(str(soup), encoding="utf-8")
        print(f"Updated {html_path} (backup saved as {backup})")
    else:
        print(f"No changes needed for {html_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python update_links.py <html-file> [more files...]\n")
        sys.exit(1)
    for file_arg in sys.argv[1:]:
        update_file(Path(file_arg))

#!/usr/bin/env python3
"""rewrite_nav_buttons.py

Walks through the *landing page* and every HTML file in the **downloaded_pages/**
mirror, finds navigation `<button>` elements, and turns them into working
offline links by wrapping them in an `<a href="…">` that points at the
corresponding local file.

It is *idempotent*: running it multiple times won’t duplicate wrappers.

Usage
-----
```bash
python rewrite_nav_buttons.py            # uses defaults: landing_page.html + downloaded_pages/
python rewrite_nav_buttons.py --root out --landing homepage.html
```

Requires **beautifulsoup4** (`pip install beautifulsoup4`).
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from bs4 import BeautifulSoup

ENCODING = "utf-8"

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Return a filesystem‑safe slug for *text*."""
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "untitled"


def button_selector(tag) -> bool:  # type: ignore[valid-type]
    """Heuristic: does *tag* look like a nav button we care about?"""
    if tag.name != "button":
        return False
    if tag.has_attr("id") and "trigger-tab-layout" in tag["id"]:
        return True
    return tag.get("role") == "tab"


def find_target_html(button, root: Path) -> Path | None:
    """Given a `<button>`, return the path to its mirrored HTML file if present."""
    label = button.get_text(strip=True)
    for candidate in (label, button.get("id")):
        if not candidate:
            continue
        slug = slugify(candidate)
        html_path = root / slug / "index.html"
        if html_path.exists():
            return html_path
    return None


def rewrite_file(html_path: Path, root: Path) -> bool:
    """Rewrite *html_path* in‑place; return True if it changed."""
    try:
        # Read the file with explicit encoding
        content = html_path.read_text(encoding=ENCODING)
        soup = BeautifulSoup(content, "html.parser")
        changed = False

        for btn in soup.find_all(button_selector):
            try:
                dest = find_target_html(btn, root)
                if not dest:
                    continue
                    
                # Get relative path from html_path's parent to the destination
                try:
                    rel_link = os.path.relpath(
                        str(dest.absolute()),
                        str(html_path.parent.absolute())
                    ).replace("\\", "/")
                except ValueError:
                    # Fallback to relative path if absolute path resolution fails
                    rel_link = str(dest.relative_to(html_path.parent)).replace("\\", "/")


                # Skip if already correctly linked
                if btn.parent.name == "a" and btn.parent.get("href") == rel_link:
                    continue

                # Create and configure the anchor tag
                anchor = soup.new_tag("a", href=rel_link)
                anchor['style'] = "text-decoration: none;"
                
                # Copy important attributes from button to anchor
                for attr in ['class', 'style', 'title']:
                    if btn.get(attr):
                        if attr == 'style':
                            anchor['style'] = f"{anchor.get('style', '')}; {btn['style']}"
                        else:
                            anchor[attr] = btn[attr]
                
                # Wrap the button with the anchor
                btn.wrap(anchor)
                changed = True
                
            except Exception as e:
                print(f"  ⚠️  Error processing button in {html_path.name}: {e}")
                continue

        if changed:
            # Create a backup before modifying
            backup_path = html_path.with_suffix(f"{html_path.suffix}.bak")
            if not backup_path.exists():
                html_path.rename(backup_path)
            
            # Write the modified content
            html_path.write_text(soup.prettify(), encoding=ENCODING)
            return True
            
    except Exception as e:
        print(f"❌ Error processing {html_path.name}: {e}")
        raise
        
    return False


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def get_relative_path(path: Path) -> str:
    """Get a relative path from cwd, or absolute if not possible."""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path.absolute())

def main() -> None:
    parser = argparse.ArgumentParser(description="Make mirrored nav buttons clickable")
    parser.add_argument("--root", default="downloaded_pages", help="Root directory of downloaded pages")
    parser.add_argument("--landing", default="landing_page.html", help="Landing page HTML file")
    args = parser.parse_args()

    # Convert to absolute paths
    root_dir = Path(args.root).resolve()
    landing = Path(args.landing).resolve()
    
    # Ensure the root directory exists
    if not root_dir.exists():
        print(f"❌ Error: Directory not found: {root_dir}")
        return

    # Collect all HTML files
    html_files = []
    if landing.exists():
        html_files.append(landing)
    
    # Add all HTML files from the root directory
    html_files.extend([f.resolve() for f in root_dir.rglob("*.html")])

    if not html_files:
        print("ℹ️  No HTML files found to process.")
        return

    # Process each file
    modified_count = 0
    for html in html_files:
        try:
            if rewrite_file(html, root_dir):
                print(f"🔗  Fixed navigation in {get_relative_path(html)}")
                modified_count += 1
        except Exception as e:
            print(f"⚠️  Error processing {get_relative_path(html)}: {e}")

    print(f"\n✅  {modified_count} file(s) modified. All buttons are now offline‑clickable.")


if __name__ == "__main__":
    main()

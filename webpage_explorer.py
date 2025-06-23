#!/usr/bin/env python3
"""
Download every tab of an interactive dashboard and mirror it locally.

Usage
-----
python webpage_explorer.py  [URL]

If no URL is supplied, a demo Flipside dashboard is mirrored.
"""

import asyncio
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Dict, List

import aiofiles
import aiohttp
from bs4 import BeautifulSoup, NavigableString
from playwright.async_api import async_playwright, Browser, Route
from urllib.parse import urlparse, urljoin

DEFAULT_DASHBOARD = (
    "https://flipsidecrypto.xyz/Sandesh/"
    "my-pet-hooligan---the-fps-frontier--Q7dYU"
)

# ──────────────────────────────────────────────────────────────
# Main class
# ──────────────────────────────────────────────────────────────


class WebpageExplorer:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.parsed_base = urlparse(base_url)
        self.session: aiohttp.ClientSession | None = None
        self.browser: Browser | None = None
        self.context = None
        self.page = None

        # cache url-hash → local-path so we don’t redownload
        self.downloaded_resources: Dict[str, str] = {}

    # ────────────────────────────────────
    # Playwright / aiohttp lifecycle
    # ────────────────────────────────────
    async def init_session(self):
        self.session = aiohttp.ClientSession()

    async def close(self):
        if self.session:
            await self.session.close()
        if self.browser:
            await self.browser.close()

    # ────────────────────────────────────
    # Navigation-tab discovery
    # ────────────────────────────────────
    async def find_navigation_buttons(self) -> List[Dict]:
        """Return a list of tab descriptors with text + CSS selector."""
        if not self.page:
            pw = await async_playwright().start()
            self.browser = await pw.chromium.launch(headless=False)
            self.context = await self.browser.new_context()
            self.page = await self.context.new_page()
            await self.page.goto(self.base_url, wait_until="networkidle")
            await self.page.wait_for_timeout(3000)

        soup = BeautifulSoup(await self.page.content(), "html.parser")

        tab_elements = []

        # Radix UI, roles, classes, etc.  – feel free to extend
        tab_elements.extend(
            soup.find_all(attrs={"data-radix-collection-item": True})
        )
        tab_elements.extend(soup.find_all(attrs={"role": "tab"}))

        tab_classes = [
            "tab",
            "nav-tab",
            "tab-button",
            "tab-link",
            "nav-item",
            "nav-link",
            "tab-item",
        ]
        for cls in tab_classes:
            tab_elements.extend(
                soup.find_all(class_=lambda x, cls=cls: x and cls in x.split())
            )

        tabs: List[Dict] = []
        seen_ids: set[str] = set()

        for el in tab_elements:
            el = el if el.name else el.parent
            if not el:
                continue

            text = el.get_text(strip=True)
            if not text or len(text) > 30:
                continue
            if text.lower() in {
                "login",
                "sign in",
                "sign up",
                "search",
                "menu",
                "close",
            }:
                continue

            selector = None
            if el.get("id"):
                selector = f'#{el["id"]}'
            elif el.get("class"):
                for cls in el.get("class", []):
                    if cls and cls[0].isalpha():
                        selector = f".{cls}"
                        break
            selector = selector or el.name or "button"

            marker = selector + text.lower()
            if marker in seen_ids:
                continue

            seen_ids.add(marker)
            tabs.append(
                {
                    "text": text,
                    "selector": selector,
                    "tag": el.name,
                    "attributes": dict(el.attrs),
                }
            )

        return tabs or [{"text": "home", "selector": "body"}]

    # ────────────────────────────────────
    # Screenshot helper
    # ────────────────────────────────────
    async def take_full_page_screenshot(self, output_path: str):
        total_height = await self.page.evaluate(
            """() => Math.max(
                document.body.scrollHeight,
                document.body.offsetHeight,
                document.documentElement.clientHeight,
                document.documentElement.scrollHeight,
                document.documentElement.offsetHeight
            )"""
        )
        viewport_width = await self.page.evaluate("window.innerWidth")
        await self.page.set_viewport_size(
            {"width": viewport_width, "height": total_height}
        )
        await self.page.screenshot(path=output_path, full_page=True)

    # ────────────────────────────────────
    # CSS-url fixer for downloaded CSS
    # ────────────────────────────────────
    def fix_css_url(self, url, css_url, assets_dir):
        if not url or url.startswith(("data:", "http:", "https:", "//")):
            return url

        if url.startswith(('"', "'")) and url.endswith(('"', "'")):
            url = url[1:-1]

        if url.startswith("/"):
            parsed_css = urlparse(css_url)
            base = f"{parsed_css.scheme}://{parsed_css.netloc}"
            full_url = urljoin(base, url)
        else:
            full_url = urljoin(css_url, url)

        filename = os.path.basename(urlparse(full_url).path.split("?")[0])
        if not filename:
            return url
        return f"../{assets_dir}/{filename}"

    # ────────────────────────────────────
    # Resource downloader
    # ────────────────────────────────────
    async def download_resource(self, url: str, tab_name: str, max_retries=2):
        if not url or url.startswith(
            ("data:", "javascript:", "mailto:", "tel:")
        ):
            return None

        if not url.startswith(("http:", "https:")):
            if url.startswith("//"):
                url = f"{self.parsed_base.scheme}:{url}"
            elif url.startswith("/"):
                url = f"{self.parsed_base.scheme}://{self.parsed_base.netloc}{url}"
            else:
                url = urljoin(self.base_url, url)

        url = url.split("#")[0].split("?")[0]

        url_hash = hashlib.md5(url.encode()).hexdigest()
        if url_hash in self.downloaded_resources:
            return self.downloaded_resources[url_hash]

        for attempt in range(max_retries + 1):
            try:
                async with self.session.get(url) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP {resp.status}")
                    ctype = resp.headers.get("Content-Type", "").lower()

                    if "css" in ctype:
                        ext, folder = ".css", "css"
                    elif "javascript" in ctype or "ecmascript" in ctype:
                        ext, folder = ".js", "js"
                    elif "image/" in ctype:
                        ext = "." + ctype.split("/")[1].split(";")[0]
                        folder = "images"
                    else:
                        ext, folder = ".bin", "other"

                    fname = (
                        f"{url_hash[:8]}_{os.path.basename(urlparse(url).path)}"
                        if os.path.basename(urlparse(url).path)
                        else f"{url_hash}{ext}"
                    )
                    if not Path(fname).suffix:
                        fname += ext

                    save_path = (
                        Path("downloaded_pages")
                        / tab_name
                        / "assets"
                        / folder
                        / fname
                    )
                    save_path.parent.mkdir(parents=True, exist_ok=True)

                    if "text/" in ctype:
                        text = await resp.text(errors="ignore")
                        if "css" in ctype:
                            text = re.sub(
                                r"url\\((['\"]?)(.*?)\\1\\)",
                                lambda m: f"url('{self.fix_css_url(m.group(2), url, os.path.join('..', 'images'))}')",
                                text,
                            )
                        async with aiofiles.open(
                            save_path, "w", encoding="utf-8"
                        ) as f:
                            await f.write(text)
                    else:
                        async with aiofiles.open(save_path, "wb") as f:
                            await f.write(await resp.read())

                    rel = Path("assets") / folder / fname
                    self.downloaded_resources[url_hash] = str(rel)
                    print(f"  ✓ Downloaded: {rel}")
                    return str(rel)

            except Exception as e:
                print(f"  Retry {attempt+1}/{max_retries}: {url} ({e})")
                await asyncio.sleep(1)
        return None

    # ────────────────────────────────────
    # HTML rewriter  (missing piece)
    # ────────────────────────────────────
    async def process_html(self, html: str, base_url: str, tab_slug: str) -> str:
        soup = BeautifulSoup(html, "html.parser")

        def absolutise(u: str) -> str:
            if not u or u.startswith(
                ("data:", "javascript:", "mailto:", "tel:")
            ):
                return u
            if u.startswith("//"):
                return f"{urlparse(base_url).scheme}:{u}"
            if u.startswith(("http://", "https://")):
                return u
            if u.startswith("/"):
                return f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}{u}"
            return urljoin(base_url, u)

        for tag in soup.find_all(True):
            for attr in ("href", "src", "poster", "data"):
                if tag.has_attr(attr):
                    tag[attr] = absolutise(tag[attr])

        for tag in soup.find_all(srcset=True):
            new_set = []
            for item in tag["srcset"].split(","):
                parts = item.strip().split()
                if parts:
                    parts[0] = absolutise(parts[0])
                    new_set.append(" ".join(parts))
            tag["srcset"] = ", ".join(new_set)

        for tag in soup.find_all(style=True):
            try:
                tag["style"] = re.sub(
                    r'url\(([\'\"]?)(.*?)\1\)',
                    lambda m: f"url('{absolutise(m.group(2))}')",
                    tag["style"]
                )
            except re.error as e:
                print(f"  Warning: CSS URL processing error - {e}")

        # Remove any base tag to prevent it from affecting relative URLs
        for base in soup.find_all('base'):
            base.decompose()
            
        # Convert buttons to links after processing all resources
        self._convert_nav_buttons(soup, tab_slug)
        
        return str(soup)
        
    def _extract_nav_slugs(self, soup) -> list[str]:
        """Extract navigation slugs from the page content.
        
        Args:
            soup: BeautifulSoup object of the current HTML page
            
        Returns:
            List of slug strings
        """
        from pathlib import Path
        import re
        
        slugs = set()
        
        # 1. Find all navigation buttons/links in the page
        # Common patterns for navigation elements
        nav_selectors = [
            'nav a[href]',  # Links in nav elements
            '.nav a[href]', # Links in elements with nav class
            'header a[href]', # Links in header
            'button',        # All buttons
            '[role="tab"]', # ARIA tabs
            '[role="navigation"] a[href]' # Navigation role links
        ]
        
        # 2. Extract unique hrefs from navigation elements
        seen_hrefs = set()
        for selector in nav_selectors:
            for element in soup.select(selector):
                href = element.get('href', '')
                if not href or href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                    continue
                    
                # Clean and normalize the URL
                href = href.split('?')[0].split('#')[0].rstrip('/')
                if not href or href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                
                # Extract the last path component as slug
                slug = Path(href).name.lower()
                if slug and slug not in ('', 'index.html', 'index.htm'):
                    slugs.add(slug)
                
                # Also check button text as fallback
                text = element.get_text(strip=True).lower()
                if text and len(text) < 30:  # Reasonable length for a tab name
                    slugs.add(text)
        
        # 3. Look for common navigation patterns in the page
        common_nav_terms = [
            'about', 'tokens', 'nft', 'governance', 'airdrop', 
            'socials', 'author', 'docs', 'features', 'pricing',
            'contact', 'blog', 'home', 'portfolio', 'projects', 'IRL'
        ]
        
        # Check page text for common navigation terms
        page_text = soup.get_text().lower()
        for term in common_nav_terms:
            if term in page_text:
                slugs.add(term)
        
        # Remove any empty strings and sort
        slugs.discard('')
        return sorted(list(slugs))

    def _convert_nav_buttons(self, soup, current_tab_slug: str):
        """Convert navigation buttons to clickable links.
        
        Args:
            soup: BeautifulSoup object of the current HTML page
            current_tab_slug: Slug of the current tab being processed
        """
        # Extract navigation slugs from the page content
        all_slugs = self._extract_nav_slugs(soup)
        
        # Build mapping of tab slug → relative path
        TAB_MAPPING = {}
        for slug in all_slugs:
            # Always use relative paths from the current location . 
            if current_tab_slug:  # we are inside downloaded_pages/<current>/index.html
                TAB_MAPPING[slug] = f"../{slug}/index.html"
            else:  # landing page scenario
                TAB_MAPPING[slug] = f"downloaded_pages/{slug}/index.html"
        
        # Convert current_tab_slug to match our mapping
        current_tab = current_tab_slug.lower()
        
        # Find all potential navigation buttons
        # Try different selectors that might indicate navigation buttons
        selectors = [
            'button',  # Standard button elements
            'div[role="button"]',  # Divs acting as buttons
            'a[role="button"]',  # Links styled as buttons
            'button.tab-button',  # Common class for tab buttons
            'button.nav-button',  # Another common class
            'button[data-tab]',  # Buttons with data-tab attribute
            'div.tab',  # Divs acting as tabs
            'a.tab'  # Links acting as tabs
        ]
        
        # Find all elements that match our selectors
        buttons = []
        for selector in selectors:
            buttons.extend(soup.select(selector))
            
        if not buttons:
            print("  No navigation buttons found with standard selectors")
            # Fallback: look for any elements with tab-related text
            tab_texts = list(TAB_MAPPING.keys()) + [t.capitalize() for t in TAB_MAPPING.keys()]
            for text in tab_texts:
                elements = soup.find_all(string=text)
                for el in elements:
                    parent = el.parent
                    if parent.name in ['button', 'a', 'div']:
                        buttons.append(parent)
        
        if not buttons:
            print("  No navigation buttons found with any selector")
            return
            
        print(f"  Found {len(buttons)} potential navigation elements")
        
        modified_count = 0
        
        for button in buttons:
            try:
                # If it's already an <a> element, just update its href to the local file
                if button.name == 'a':
                    button_text = button.get_text(strip=True).lower()
                    if button_text in TAB_MAPPING:
                        button['href'] = TAB_MAPPING[button_text]
                        modified_count += 1
                        print(f"  Updated anchor '{button_text}' to {TAB_MAPPING[button_text]}")
                    continue
                
                # Get button text for matching
                button_text = button.get_text(strip=True).lower()
                
                # Skip if no matching tab or if it's the current tab
                if button_text not in TAB_MAPPING or button_text == current_tab:
                    continue
                    
                target_file = TAB_MAPPING[button_text]
                
                # Create a new anchor tag
                anchor = soup.new_tag('a', href=target_file)
                
                # Preserve button's classes and styles
                if button.get('class'):
                    anchor['class'] = button['class']
                    
                # Preserve button's styles
                anchor_style = "text-decoration: none; cursor: pointer;"
                if button.get('style'):
                    anchor_style += button['style']
                anchor['style'] = anchor_style
                
                # Preserve other attributes
                for attr in ['title', 'data-tab', 'role']:
                    if button.get(attr):
                        anchor[attr] = button[attr]
                
                # If the button had an onclick handler, move it to the anchor
                if button.get('onclick'):
                    anchor['onclick'] = button['onclick']
                    del button['onclick']
                
                # Replace the button with the anchor
                button.replace_with(anchor)
                anchor.append(button)
                
                # Remove any existing href from the button
                if button.get('href'):
                    del button['href']
                    
                modified_count += 1
                print(f"  Converted '{button_text}' button to link to {target_file}")
                
            except Exception as e:
                print(f"  Error processing button: {e}")
                continue
                
        # Pass 2 – fix any remaining <a> elements that still point to the online site
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Normalise to slug (remove protocol+domain)
            for slug in TAB_MAPPING:
                if re.search(rf"(?:/|^){slug}(?:/|$)", href, re.IGNORECASE):
                    if a.get("href") != TAB_MAPPING[slug]:
                        a["href"] = TAB_MAPPING[slug]
                        modified_count += 1
                        break

        if modified_count > 0:
            print(f"  Successfully converted {modified_count} navigation elements (including anchors)")
        else:
            print("  No navigation elements needed conversion")
        
    # ────────────────────────────────────
    # Tab exploration
    # ────────────────────────────────────
    async def explore_tab(self, tab_info: Dict, idx: int):
        slug = tab_info["text"].lower()
        tab_dir = Path("downloaded_pages") / slug
        tab_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nProcessing tab {idx + 1}: {tab_info['text']}")

        try:
            # navigate or click
            if "href" in tab_info.get("attributes", {}):
                target = urljoin(self.base_url, tab_info["attributes"]["href"])
                await self.page.goto(target, wait_until="networkidle")
            else:
                sel = tab_info.get("selector", "")
                btn = await self.page.wait_for_selector(sel, timeout=10_000)
                await btn.click()
                await self.page.wait_for_load_state("networkidle")

            await self.page.wait_for_timeout(2000)

            # screenshot
            shot = tab_dir / "screenshot.png"
            await self.take_full_page_screenshot(str(shot))

            # process HTML
            raw_html = await self.page.content()
            processed = await self.process_html(raw_html, self.base_url, slug)

            (tab_dir / "raw.html").write_text(raw_html, encoding="utf-8")
            (tab_dir / "index.html").write_text(processed, encoding="utf-8")

            # resource list
            resources = await self.page.evaluate(
                """
                () => [...new Set(
                    [...document.querySelectorAll('link[href], img[src], source[src], script[src], iframe[src]')]
                      .map(el => el.href || el.src)
                )]
                """
            )
            print(f"  Found {len(resources)} external resources")
            await asyncio.gather(
                *[self.download_resource(u, slug) for u in resources]
            )
            print(f"✓ Saved {tab_info['text']}")

        except Exception as e:
            print(f"✗ Error on {tab_info['text']}: {e}")

    # ────────────────────────────────────
    # Top-level driver
    # ────────────────────────────────────
    async def explore_website(self):
        await self.init_session()
        try:
            pw = await async_playwright().start()
            self.browser = await pw.chromium.launch(headless=False)
            self.context = await self.browser.new_context()
            self.page = await self.context.new_page()
            await self.page.goto(self.base_url, wait_until="networkidle")

            tabs = await self.find_navigation_buttons()
            print(f"\nFound {len(tabs)} tabs:")
            for i, t in enumerate(tabs, 1):
                print(f"  {i}. {t['text']}")

            for i, tab in enumerate(tabs):
                await self.explore_tab(tab, i)

        finally:
            await self.close()


# ──────────────────────────────────────────────────────────────
# CLI entry-point
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import shutil
    
    # Delete downloaded_pages directory if it exists
    download_dir = Path("downloaded_pages")
    if download_dir.exists() and download_dir.is_dir():
        print("🧹  Removing existing downloaded_pages directory...")
        shutil.rmtree(download_dir)
        print("✅  Removed downloaded_pages directory")
    
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DASHBOARD
    print(f"\n🌐  Mirroring: {target}")
    try:
        explorer = WebpageExplorer(target)
        asyncio.run(explorer.explore_website())
    except KeyboardInterrupt:
        print("\n🛑  Interrupted by user")
    except Exception as e:
        print(f"\n❌  Error: {e}")
        raise

import os
import subprocess
import sys
import streamlit as st
import asyncio
import json
import re
import shutil
import builtins
from pathlib import Path
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ————— Corrected & Robust Playwright Installation —————
@st.cache_resource
def install_playwright_deps():
    """
    Installs the chromium browser for Playwright and system dependencies.
    The @st.cache_resource decorator ensures this runs only once.
    """
    try:
        # Show installation status
        status = st.status("Installing Playwright dependencies...")
        
        with status:
            st.write("Installing Playwright browser...")
            # Install Chromium browser
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                st.error(f"Failed to install Playwright browser: {result.stderr}")
                
            st.write("Installing system dependencies...")
            # Try to install system dependencies (may not work on all platforms)
            try:
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install-deps"],
                    capture_output=True,
                    text=True
                )
            except Exception as e:
                st.warning(f"Note: Some system dependencies might be missing: {e}")
                st.warning("The app might not work correctly in this environment.")
                
            st.success("Playwright setup completed!")
    except Exception as e:
        st.error(f"Failed to set up Playwright: {str(e)}")
        st.warning("The app might not work correctly. Some features may be limited.")
        st.stop()

# Run the installer at the start of the script
install_playwright_deps()
# ——————————————————————————————————————————————————————

#
# ——— Your existing functions (no changes needed here) ———
#

def slugify(text):
    return re.sub(r'[^a-z0-9]+', '-', text.strip().lower()).strip('-') or 'untitled'

async def download_resource(session, url, output_path):
    try:
        async with session.get(url) as response:
            if response.status == 200:
                content = await response.read()
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'wb') as f:
                    f.write(content)
                return True
    except Exception:
        pass
    return False

def rewrite_links(soup, current_html_path, site_map, base_output_dir):
    nav_elements = soup.select('a, button, [role="button"]')
    current_dir = Path(current_html_path).parent

    for el in nav_elements:
        text = el.get_text(strip=True)
        if not text:
            continue
        
        slug = slugify(text)
        if slug in site_map:
            target_path = Path(base_output_dir) / site_map[slug]
            relative_path = os.path.relpath(target_path.resolve(), current_dir.resolve())

            if el.name == 'a':
                el['href'] = relative_path
            else:
                anchor = soup.new_tag('a', href=relative_path)
                if el.get('class'):
                    anchor['class'] = el.get('class')
                anchor['style'] = el.get('style', '') + ' text-decoration: none; color: inherit; cursor: pointer;'
                anchor.string = el.get_text()
                el.replace_with(anchor)
    return soup

async def save_page_with_assets(page, session, output_dir, file_slug, site_map, base_output_dir):
    print(f"    -> Processing page: {Path(output_dir).relative_to(base_output_dir)}/{file_slug}")
    print("      Waiting 5 seconds for page to load...")
    await page.wait_for_timeout(5000)
    html = await page.content()
    base_url = page.url
    soup = BeautifulSoup(html, 'html.parser')

    assets_dir_name = f"{file_slug}_files"
    assets_out_dir = Path(output_dir) / assets_dir_name
    assets_out_dir.mkdir(parents=True, exist_ok=True)

    for link_tag in soup.find_all('link', rel='stylesheet'):
        css_url = link_tag.get('href')
        if not css_url:
            continue
        abs_css_url = urljoin(base_url, css_url)
        css_filename = os.path.basename(abs_css_url.split('?')[0]) or "style.css"
        local_css_path = assets_out_dir / css_filename
        if await download_resource(session, abs_css_url, str(local_css_path)):
            link_tag['href'] = f"{assets_dir_name}/{css_filename}"

    fpath = Path(output_dir) / f"{file_slug}.html"
    soup = rewrite_links(soup, str(fpath), site_map, base_output_dir)

    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(str(soup))
    print(f"      Saved and linked HTML to {fpath}")

async def discover_site_structure(page):
    print("--- Starting Site Discovery Phase ---")
    site_map = {}
    main_tabs_handles = await page.query_selector_all('div[role="tablist"]:first-of-type >> [role="tab"]')

    for i in range(len(main_tabs_handles)):
        main_tabs = await page.query_selector_all('div[role="tablist"]:first-of-type >> [role="tab"]')
        main_tab_element = main_tabs[i]
        main_name = await main_tab_element.inner_text()
        main_slug = slugify(main_name)
        
        await main_tab_element.click()
        await page.wait_for_timeout(2000)

        all_tablists = await page.query_selector_all('[role="tablist"]')
        
        if len(all_tablists) <= 1:
            site_map[main_slug] = str(Path(main_slug) / "index.html")
        else:
            sub_tabs_handles = await all_tablists[1].query_selector_all('[role="tab"]')
            if sub_tabs_handles:
                first_sub_name = await sub_tabs_handles[0].inner_text()
                site_map[main_slug] = str(Path(main_slug) / f"{slugify(first_sub_name)}.html")

                for sub_tab_handle in sub_tabs_handles:
                    sub_name = await sub_tab_handle.inner_text()
                    site_map[slugify(sub_name)] = str(Path(main_slug) / f"{slugify(sub_name)}.html")

    print("--- Site Discovery Complete ---")
    print(json.dumps(site_map, indent=2))
    await page.goto(page.url, wait_until="networkidle")
    return site_map

async def main_scraper(url: str, out_dir_base: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")

        if Path(out_dir_base).exists():
            print(f"--- Removing existing output directory: {out_dir_base} ---")
            shutil.rmtree(out_dir_base)
        Path(out_dir_base).mkdir(exist_ok=True)

        main_tabs_handles = await page.query_selector_all(
            'div[role="tablist"]:first-of-type >> [role="tab"]'
        )

        async with aiohttp.ClientSession() as session:
            if not main_tabs_handles:
                print("--- No tabs found. Saving as a single page. ---")
                await save_page_with_assets(page, session, out_dir_base, "index", {}, out_dir_base)
            else:
                site_map = await discover_site_structure(page)
                print("\n--- Starting Download and Rewrite Phase ---")
                for i in range(len(main_tabs_handles)):
                    main_tabs = await page.query_selector_all(
                        'div[role="tablist"]:first-of-type >> [role="tab"]'
                    )
                    name = await main_tabs[i].inner_text()
                    print(f"\nProcessing main tab: {name}")

                    try:
                        await main_tabs[i].click()
                        await page.wait_for_timeout(2000)

                        slug = slugify(name)
                        tab_out_dir = Path(out_dir_base) / slug
                        tab_out_dir.mkdir(parents=True, exist_ok=True)

                        all_tablists = await page.query_selector_all('[role="tablist"]')
                        if len(all_tablists) <= 1:
                            await save_page_with_assets(
                                page, session, str(tab_out_dir), "index", site_map, out_dir_base
                            )
                        else:
                            print(f"  Found sub-tabs for '{name}'")
                            # Get the initial count of sub-tabs to loop through
                            sub_tabs_list = await page.query_selector_all('div[role="tablist"] >> nth=1 >> [role="tab"]')
                            
                            for j in range(len(sub_tabs_list)):
                                # In each iteration, re-fetch the tab elements to avoid stale element errors
                                all_tablists_again = await page.query_selector_all('[role="tablist"]')
                                sub_tabs_container = all_tablists_again[1]
                                sub_tabs = await sub_tabs_container.query_selector_all('[role="tab"]') # <-- FIXED

                                sub_name = await sub_tabs[j].inner_text()
                                try:
                                    await sub_tabs[j].click()
                                    await page.wait_for_timeout(1500)
                                    await save_page_with_assets(
                                        page,
                                        session,
                                        str(tab_out_dir),
                                        slugify(sub_name),
                                        site_map,
                                        out_dir_base,
                                    )
                                except Exception as sub_e:
                                    print(f"    -> Error on sub-tab '{sub_name}': {sub_e}")

                    except Exception as e:
                        print(f"  -> Error on main tab '{name}': {e}")

        await browser.close()
        print("\n✅ All tabs and assets downloaded and linked.")


#
# ——— Streamlit UI ———
#

st.title("💾 Tab-Structured Site Snapshotter")
st.markdown(
    """
    Enter the URL of a dashboard or any tab-structured site below, click **Start Download**,  
    and this tool will grab all tabs (and sub-tabs), download their HTML + CSS assets,  
    rewrite links to work offline, and package them for you.
    """
)

url = st.text_input("🔗 Dashboard URL", placeholder="https://example.com/your-dashboard")
out_dir = st.text_input("📁 Output directory", value="tab_snapshots")

if st.button("🚀 Start Download"):
    if not url.strip():
        st.error("Please enter a valid URL.")
    else:
        logs = []
        original_print = builtins.print

        def _capture_print(*args, **kwargs):
            original_print(*args, **kwargs)
            logs.append(" ".join(str(a) for a in args))

        builtins.print = _capture_print  # monkey-patchss
        try:
            with st.spinner("Downloading… this may take a few minutes…"):
                asyncio.run(main_scraper(url, out_dir))
            st.success("✅ Download complete!")
        except Exception as e:
            logs.append(f"❌ Error: {e}")
            st.error(f"Download failed: {e}")
        finally:
            builtins.print = original_print

        # Show logs
        st.subheader("📝 Logs")
        st.text_area("", "\n".join(logs), height=300)

        # Offer ZIP download
        if Path(out_dir).exists():
            zip_path = shutil.make_archive(out_dir, 'zip', out_dir)
            with open(zip_path, "rb") as fp:
                st.download_button(
                    label="📥 Download ZIP of snapshots",
                    data=fp,
                    file_name=f"{out_dir}.zip",
                    mime="application/zip"
                )
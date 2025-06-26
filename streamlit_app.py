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
    Installs the chromium browser for Playwright.
    The @st.cache_resource decorator ensures this runs only once.
    """
    try:
        # Using sys.executable ensures we use the same Python environment
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            capture_output=True, # Use capture_output to hide stdout/stderr unless there's an error
            text=True
        )
    except subprocess.CalledProcessError as e:
        st.error(f"Failed to install Playwright browsers: {e.stderr}")
        # Stop the app if the installation fails, as it cannot proceed.
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

async def wait_for_dynamic_content(page, timeout=30000):
    """Wait for dynamic content to load, including charts and numbers"""
    try:
        # Wait for charts to be rendered
        await page.wait_for_selector('.plotly', state='attached', timeout=timeout)
        
        # Wait for numbers to be populated (adjust the selector based on your actual number elements)
        await page.wait_for_function("""() => {
            const numberElements = document.querySelectorAll('[class*="value"], [class*="number"], [class*="metric"]');
            return Array.from(numberElements).every(el => {
                const text = el.textContent || '';
                return text.trim() !== '' && !text.includes('...');
            });
        }""", timeout=timeout)
        
        # Give a small buffer time for any final animations
        await page.wait_for_timeout(1000)
        return True
    except Exception as e:
        print(f"Warning while waiting for dynamic content: {str(e)}")
        return False

async def save_page_with_assets(page, session, output_dir, file_slug, site_map, base_output_dir):
    print(f"    -> Processing page: {Path(output_dir).relative_to(base_output_dir)}/{file_slug}")
    
    # Wait for dynamic content to load
    print("      Waiting for dynamic content to load...")
    await wait_for_dynamic_content(page)
    
    # Take a screenshot for debugging
    screenshot_path = Path(output_dir) / f"{file_slug}_screenshot.png"
    await page.screenshot(path=str(screenshot_path), full_page=True)
    print(f"      Screenshot saved to {screenshot_path}")
    
    # Get the HTML after dynamic content has loaded
    html = await page.content()
    base_url = page.url
    soup = BeautifulSoup(html, 'html.parser')
    
    # Inject JavaScript to ensure all numbers are visible
    await page.add_script_tag(content="""
    // Force all number elements to be visible
    document.querySelectorAll('[class*="value"], [class*="number"], [class*="metric"]').forEach(el => {
        el.style.visibility = 'visible';
        el.style.opacity = '1';
    });
    
    // Force all charts to render completely
    if (typeof Plotly !== 'undefined') {
        document.querySelectorAll('.plotly-graph-div').forEach(plot => {
            Plotly.relayout(plot, {});
        });
    }
    """)
    
    # Wait a bit more after injecting JS
    await page.wait_for_timeout(1000)
    
    # Get the final HTML after all modifications
    html = await page.content()
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

async def navigate_with_retry(page, url, max_retries=3, initial_timeout=30000):
    """Helper function to navigate with retry logic and exponential backoff"""
    last_error = None
    for attempt in range(max_retries):
        try:
            # Increase timeout with each retry
            timeout = min(initial_timeout * (2 ** attempt), 120000)  # Cap at 2 minutes
            print(f"Attempt {attempt + 1}/{max_retries} - Loading {url} (timeout: {timeout}ms)")
            await page.goto(url, 
                         wait_until="domcontentloaded",  # More reliable than networkidle
                         timeout=timeout)
            # Wait for a short time after loading to ensure dynamic content is rendered
            await page.wait_for_timeout(2000)
            return True
        except Exception as e:
            last_error = e
            print(f"Attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = 5 * (attempt + 1)  # Exponential backoff
                print(f"Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
    print(f"Failed to load {url} after {max_retries} attempts")
    raise last_error

async def main_scraper(url: str, out_dir_base: str):
    # Configure browser with additional arguments for better reliability
    browser_args = [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-accelerated-2d-canvas',
        '--no-first-run',
        '--no-zygote',
        '--single-process',
        '--disable-gpu'
    ]
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=browser_args,
            timeout=120000  # 2 minutes timeout for browser operations
        )
        
        # Create a new browser context with custom settings
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            java_script_enabled=True,
            ignore_https_errors=True
        )
        
        page = await context.new_page()
        
        # Set default navigation timeout
        page.set_default_navigation_timeout(60000)  # 60 seconds
        page.set_default_timeout(30000)  # 30 seconds
        
        # Try to load the page with retries
        success = await navigate_with_retry(page, url)
        if not success:
            raise Exception(f"Failed to load initial URL: {url}")

        if Path(out_dir_base).exists():
            print(f"--- Removing existing output directory: {out_dir_base} ---")
            shutil.rmtree(out_dir_base)
        Path(out_dir_base).mkdir(exist_ok=True)

        # Wait for the main content to load
        await page.wait_for_selector('div[role="tablist"]', timeout=30000)
        
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
                    # Refresh the tab list to avoid stale elements
                    main_tabs = await page.query_selector_all(
                        'div[role="tablist"]:first-of-type >> [role="tab"]'
                    )
                    if i >= len(main_tabs):
                        print(f"Warning: Tab index {i} is out of bounds. Skipping...")
                        continue
                            
                    try:
                        name = await main_tabs[i].inner_text()
                        print(f"\nProcessing main tab: {name} ({i+1}/{len(main_tabs_handles)})")
                        
                        # Scroll the tab into view and click with retry
                        await main_tabs[i].scroll_into_view_if_needed()
                        await main_tabs[i].click()
                        
                        # Wait for content to load after clicking
                        await page.wait_for_load_state('networkidle', timeout=30000)
                        await asyncio.sleep(2)  # Additional wait for dynamic content

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

        builtins.print = _capture_print  # monkey-patch
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
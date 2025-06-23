import asyncio
import json
import os
import re
from urllib.parse import urljoin
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import shutil

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
    output_dir_path = Path(output_dir)
    if output_dir_path.name == file_slug:
        print(f"    -> Correcting main page slug to 'index' for {file_slug}")
        file_slug = "index"

    print(f"    -> Processing page: {output_dir_path.name}/{file_slug}")
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
        if not css_url: continue
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

async def main(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")

        site_map = await discover_site_structure(page)

        print("\n--- Starting Download and Rewrite Phase ---")
        out_dir_base = 'tab_snapshots'
        if Path(out_dir_base).exists():
            print(f"--- Removing existing output directory: {out_dir_base} ---")
            shutil.rmtree(out_dir_base)
        Path(out_dir_base).mkdir(exist_ok=True)

        async with aiohttp.ClientSession() as session:
            main_tabs_handles = await page.query_selector_all('div[role="tablist"]:first-of-type >> [role="tab"]')
            for i in range(len(main_tabs_handles)):
                main_tabs = await page.query_selector_all('div[role="tablist"]:first-of-type >> [role="tab"]')
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
                        await save_page_with_assets(page, session, str(tab_out_dir), "index", site_map, out_dir_base)
                    else:
                        print(f"  Found sub-tabs for '{name}'")
                        sub_tab_buttons = await all_tablists[1].query_selector_all('[role="tab"]')
                        for j in range(len(sub_tab_buttons)):
                            sub_tabs = await (await page.query_selector_all('[role="tablist"]'))[1].query_selector_all('[role="tab"]')
                            sub_name = await sub_tabs[j].inner_text()
                            try:
                                await sub_tabs[j].click()
                                await page.wait_for_timeout(1500)
                                await save_page_with_assets(page, session, str(tab_out_dir), slugify(sub_name), site_map, out_dir_base)
                            except Exception as sub_e:
                                print(f"    -> Error on sub-tab '{sub_name}': {sub_e}")

                except Exception as e:
                    print(f"  -> Error on main tab '{name}': {e}")

        await browser.close()
        print("\n✅ All tabs and assets downloaded and linked.")

if __name__ == "__main__":
    dashboard_url = 'https://flipsidecrypto.xyz/Sandesh/nekodex-Uk50Sh'
    asyncio.run(main(dashboard_url))

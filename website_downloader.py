import os
import re
import asyncio
import aiohttp
import aiofiles
from pathlib import Path
from urllib.parse import urlparse, urljoin
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def download_resources(session, base_url, html_content, output_dir):
    """Download all resources (CSS, JS, images) and update HTML."""
    soup = BeautifulSoup(html_content, 'html.parser')
    base_parsed = urlparse(base_url)
    base_domain = f"{base_parsed.scheme}://{base_parsed.netloc}"
    
    # Create assets directory
    assets_dir = os.path.join(output_dir, 'assets')
    os.makedirs(assets_dir, exist_ok=True)
    
    # Process all resource tags
    tags = {
        'link': 'href',
        'script': 'src',
        'img': 'src',
        'source': 'src',
        'iframe': 'src',
        'embed': 'src'
    }
    
    for tag_name, attr in tags.items():
        for element in soup.find_all(tag_name, **{f'{attr}': True}):
            resource_url = element[attr]
            if not resource_url or resource_url.startswith(('data:', 'blob:', '#')):
                continue
                
            # Handle different URL formats
            if resource_url.startswith('//'):
                resource_url = f"{base_parsed.scheme}:{resource_url}"
            elif resource_url.startswith('/'):
                resource_url = f"{base_domain}{resource_url}"
            elif not resource_url.startswith(('http://', 'https://')):
                resource_url = urljoin(base_url, resource_url)
            
            # Only process same-domain resources
            if urlparse(resource_url).netloc != base_parsed.netloc:
                continue
            
            try:
                # Download the resource
                async with session.get(resource_url) as response:
                    if response.status != 200:
                        continue
                        
                    # Generate a local path for the resource
                    resource_path = urlparse(resource_url).path.lstrip('/')
                    if not resource_path:
                        continue
                        
                    # Create directories if they don't exist
                    local_path = os.path.join(output_dir, resource_path)
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    
                    # Save the resource
                    content = await response.read()
                    async with aiofiles.open(local_path, 'wb') as f:
                        await f.write(content)
                    
                    # Update the HTML to use local path
                    element[attr] = os.path.relpath(local_path, os.path.dirname(os.path.join(output_dir, 'index.html')))
                    
            except Exception as e:
                print(f"  Error downloading {resource_url}: {str(e)}")
    
    return str(soup)

async def download_website_async(url, output_dir='downloaded_pages', wait_time=5000):
    try:
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        async with async_playwright() as p, aiohttp.ClientSession() as session:
            # Launch browser (Chromium, Firefox, or WebKit)
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            
            try:
                # Create a new page
                page = await context.new_page()
                
                print(f"Loading {url}...")
                # Increase navigation timeout and wait for the page to be fully loaded
                page.set_default_navigation_timeout(60000)  # 60 seconds timeout for navigation
                await page.goto(url, wait_until='domcontentloaded')
                
                # Wait for the page to load completely with a longer timeout
                print(f"Waiting for page to load (timeout: {wait_time/1000} seconds)...")
                try:
                    await page.wait_for_load_state('networkidle', timeout=wait_time)
                except Exception as e:
                    print(f"Note: {e} - Continuing with current page state")
                
                # Wait an additional 5 seconds to ensure all dynamic content is loaded
                print("Waiting 5 seconds to ensure all content is loaded...")
                await asyncio.sleep(5)
                
                # Get the page content after JavaScript execution
                content = await page.content()
                
                # Download all resources and update HTML
                print("Downloading resources (CSS, JS, images)...")
                updated_html = await download_resources(session, url, content, output_dir)
                
                # Save the final HTML
                filename = 'index.html'
                filepath = os.path.join(output_dir, filename)
                
                async with aiofiles.open(filepath, 'w', encoding='utf-8') as file:
                    await file.write(updated_html)
                
                print(f"Successfully downloaded website from {url} to {filepath}")
                return filepath
                
            finally:
                # Always close the browser
                await browser.close()
    
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        return None

def download_website(url, output_dir='downloaded_pages', wait_time=5000):
    return asyncio.get_event_loop().run_until_complete(
        download_website_async(url, output_dir, wait_time)
    )

if __name__ == "__main__":
    # Get URL from user input
    url = "https://flipsidecrypto.xyz/Sandesh/my-pet-hooligan---the-fps-frontier--Q7dYU"
    
    # Add https:// if no scheme is specified
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    download_website(url)

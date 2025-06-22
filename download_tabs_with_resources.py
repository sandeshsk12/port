import os
import asyncio
import aiohttp
import aiofiles
from urllib.parse import urlparse, urljoin
from pathlib import Path
from playwright.async_api import async_playwright
import re

class TabDownloader:
    def __init__(self, base_url):
        self.base_url = base_url
        self.parsed_base = urlparse(base_url)
        self.base_domain = f"{self.parsed_base.scheme}://{self.parsed_base.netloc}"
        self.session = None
        self.visited_urls = set()
    
    async def init_session(self):
        self.session = aiohttp.ClientSession()
    
    async def close(self):
        if self.session:
            await self.session.close()
    
    def get_local_path(self, url, tab_name):
        """Convert URL to local filesystem path for a specific tab."""
        parsed = urlparse(url)
        path = parsed.path.lstrip('/')
        
        # For root path, use index.html
        if not path:
            return os.path.join('downloaded_pages', tab_name, 'index.html')
            
        # For assets, put them in the tab's assets directory
        return os.path.join('downloaded_pages', tab_name, 'assets', path.lstrip('/'))
    
    async def download_resource(self, url, tab_name):
        """Download a single resource and save it locally."""
        if not url or url in self.visited_urls:
            return
            
        self.visited_urls.add(url)
        
        try:
            # Handle relative URLs
            if url.startswith('//'):
                url = f"{self.parsed_base.scheme}:{url}"
            elif url.startswith('/'):
                url = f"{self.base_domain}{url}"
            elif not url.startswith(('http://', 'https://')):
                url = urljoin(self.base_url, url)
            
            # Skip external resources
            if not url.startswith(self.base_domain):
                return
                
            local_path = self.get_local_path(url, tab_name)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    content = await response.read()
                    
                    # Handle text content (HTML, CSS, JS)
                    content_type = response.headers.get('content-type', '')
                    if any(t in content_type for t in ['text/html', 'text/css', 'application/javascript']):
                        content = content.decode('utf-8')
                        async with aiofiles.open(local_path, 'w', encoding='utf-8') as f:
                            await f.write(content)
                    else:
                        # Binary content (images, fonts, etc.)
                        async with aiofiles.open(local_path, 'wb') as f:
                            await f.write(content)
                    
                    print(f"✓ Downloaded: {url}")
                    return local_path
                    
        except Exception as e:
            print(f"✗ Error downloading {url}: {str(e)}")
        return None
    
    async def process_html(self, html, base_url, tab_name):
        """Process HTML content and update resource URLs."""
        # Update all resource URLs in the HTML
        def update_url(match):
            url = match.group(1) or match.group(2)
            if not url or url.startswith(('data:', 'blob:', '#')):
                return match.group(0)
                
            # Handle URL
            if url.startswith('//'):
                url = f"{self.parsed_base.scheme}:{url}"
            elif url.startswith('/'):
                url = f"{self.base_domain}{url}"
            elif not url.startswith(('http://', 'https://')):
                url = urljoin(base_url, url)
            
            # Only process same-domain resources
            if not url.startswith(self.base_domain):
                return match.group(0)
            
            # Queue the resource for download
            local_path = self.get_local_path(url, tab_name)
            relative_path = os.path.relpath(local_path, os.path.dirname(self.get_local_path(base_url, tab_name)))
            relative_path = relative_path.replace('\\', '/')  # Ensure forward slashes
            
            # Update the URL in the HTML
            return f'"{relative_path}"'
        
        # Update all resource URLs in the HTML
        html = re.sub(r'href=["\'](.*?)["\']', lambda m: f'href={update_url(m)}', html)
        html = re.sub(r'src=["\'](.*?)["\']', lambda m: f'src={update_url(m)}', html)
        html = re.sub(r'url\(["\']?(.*?)["\']?\)', lambda m: f'url({update_url(m)})', html)
        
        return html
    
    async def download_tab(self, tab_info):
        """Download content of a specific tab with all its resources."""
        tab_name = tab_info['name']
        tab_id = tab_info['id']
        
        # Create tab directory
        tab_dir = os.path.join('downloaded_pages', tab_name.lower())
        assets_dir = os.path.join(tab_dir, 'assets')
        os.makedirs(assets_dir, exist_ok=True)
        
        print(f"\nProcessing tab: {tab_name}")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            
            try:
                # Navigate to the main page
                print(f"Loading {self.base_url}...")
                await page.goto(self.base_url, wait_until='domcontentloaded')
                await page.wait_for_load_state('networkidle')
                
                # Click the tab
                print(f"Clicking tab: {tab_name}")
                tab_selector = f'[id=\"{tab_id}\"]'
                await page.wait_for_selector(tab_selector, state='visible', timeout=10000)
                await page.click(tab_selector)
                
                # Wait for content to load
                print("Waiting for content to load...")
                await asyncio.sleep(15)
                
                # Get all resource URLs from the page
                resources = await page.evaluate('''() => {
                    const resources = [];
                    // Get all resource URLs from the page
                    document.querySelectorAll('link[rel="stylesheet"], script[src], img[src], source[src], iframe[src], embed[src], object[data]').forEach(el => {
                        const url = el.href || el.src || el.data;
                        if (url) resources.push(url);
                    });
                    // Get all URLs from inline styles
                    document.querySelectorAll('*[style]').forEach(el => {
                        const matches = el.style.cssText.matchAll(/url\(['"]?(.*?)['"]?\)/g);
                        for (const match of matches) {
                            if (match[1]) resources.push(match[1]);
                        }
                    });
                    return [...new Set(resources)]; // Remove duplicates
                }''')
                
                # Download all resources
                print(f"Downloading {len(resources)} resources...")
                download_tasks = [self.download_resource(url, tab_name.lower()) for url in resources]
                await asyncio.gather(*download_tasks, return_exceptions=True)
                
                # Get the final HTML
                content = await page.content()
                
                # Process the HTML to update resource URLs
                processed_content = await self.process_html(content, self.base_url, tab_name.lower())
                
                # Save the HTML
                filepath = os.path.join(tab_dir, 'index.html')
                async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
                    await f.write(processed_content)
                
                print(f"✓ Successfully saved {tab_name} to {filepath}")
                return True
                
            except Exception as e:
                print(f"✗ Error processing {tab_name}: {str(e)}")
                import traceback
                traceback.print_exc()
                return False
            finally:
                await browser.close()
    
    async def run(self, tabs):
        """Run the downloader for all tabs."""
        await self.init_session()
        
        try:
            for tab in tabs:
                await self.download_tab(tab)
            
            print("\nAll tabs have been processed with their resources!")
            print("Directory structure:")
            print("downloaded_pages/")
            for tab in tabs:
                print(f"  {tab['name'].lower()}/")
                print("    ├── index.html")
                print("    └── assets/")
                print("        ├── css/")
                print("        ├── js/")
                print("        └── images/")
                
        finally:
            await self.close()

if __name__ == "__main__":
    url = "https://flipsidecrypto.xyz/Sandesh/my-pet-hooligan---the-fps-frontier--Q7dYU"
    
    # List of tabs with their IDs
    tabs = [
        {"name": "About", "id": "radix-«r18»-trigger-tab-layout-k06v"},
        {"name": "Tokens", "id": "radix-«r18»-trigger-tab-layout-Hd4j"},
        {"name": "NFT", "id": "radix-«r18»-trigger-tab-layout-hmm8"},
        {"name": "Governance", "id": "radix-«r18»-trigger-tab-layout-ld3m"},
        {"name": "Airdrop", "id": "radix-«r18»-trigger-tab-layout-lhvD"},
        {"name": "Socials", "id": "radix-«r18»-trigger-tab-layout-Ehnu"},
        {"name": "Author", "id": "radix-«r18»-trigger-tab-layout-v8Re"},
        {"name": "Houekeeping", "id": "radix-«r18»-trigger-tab-layout-PjcS"}
    ]
    
    downloader = TabDownloader(url)
    asyncio.run(downloader.run(tabs))

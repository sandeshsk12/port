#!/usr/bin/env python3
import os
import re
import asyncio
import aiohttp
import aiofiles
from pathlib import Path
from urllib.parse import urlparse, urljoin, parse_qs
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

class WebpageExplorer:
    def __init__(self, base_url):
        self.base_url = base_url
        self.parsed_base = urlparse(base_url)
        self.session = None
        self.browser = None
        self.context = None
        self.page = None
        
    async def init_session(self):
        """Initialize aiohttp session."""
        self.session = aiohttp.ClientSession()
        
    async def close(self):
        """Close all resources."""
        if self.session:
            await self.session.close()
        if self.browser:
            await self.browser.close()
    
    async def find_navigation_buttons(self):
        """Find all navigation buttons/links on the page using multiple strategies."""
        if not self.page:
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(headless=False)
            self.context = await self.browser.new_context()
            self.page = await self.context.new_page()
            await self.page.goto(self.base_url, wait_until='networkidle')
        
        # Wait for page to load completely
        await self.page.wait_for_timeout(5000)
        
        tabs = []
        
        # First, try to find tabs using the page content
        content = await self.page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
        # Try to find tabs using known patterns from the page
        tab_elements = []
        
        # 1. Look for elements with data-radix-collection-item (common in Radix UI)
        tab_elements.extend(soup.find_all(attrs={'data-radix-collection-item': True}))
        
        # 2. Look for elements with role="tab"
        tab_elements.extend(soup.find_all(attrs={'role': 'tab'}))
        
        # 3. Look for elements with tab-related data attributes
        tab_elements.extend(soup.find_all(attrs={'data-state': 'active'}))  # Active tab
        tab_elements.extend(soup.find_all(attrs={'data-state': 'inactive'}))  # Inactive tabs
        
        # 4. Look for elements with tab-related classes
        tab_classes = ['tab', 'nav-tab', 'tab-button', 'tab-link', 'nav-item', 'nav-link', 'tab-item']
        for cls in tab_classes:
            tab_elements.extend(soup.find_all(class_=lambda x: x and cls in x.split()))
        
        # 5. Find elements with tab-related text
        tab_texts = ['about', 'tokens', 'nft', 'governance', 'airdrop', 'socials', 'author', 'home', 'houekeeping']
        for text in tab_texts:
            tab_elements.extend(soup.find_all(string=lambda t: t and text in t.lower()))
        
        # Process found elements
        seen = set()
        for element in tab_elements:
            try:
                # Get the actual button/link element
                el = element if element.name else element.parent
                if not el:
                    continue
                    
                # Skip if we've already processed this element
                element_id = str(id(el))
                if element_id in seen:
                    continue
                seen.add(element_id)
                
                # Get element text
                text = el.get_text(strip=True)
                if not text or len(text) > 30:  # Skip long or empty texts
                    continue
                
                # Skip common non-tab elements
                if text.lower() in ['login', 'sign in', 'sign up', 'search', 'menu', 'close']:
                    continue
                
                # Get element attributes
                attrs = {}
                for attr in el.attrs:
                    attrs[attr] = el[attr]
                
                # Create a simple selector based on ID or class
                selector = None
                if el.get('id'):
                    selector = f'#{el["id"]}'
                elif el.get('class'):
                    # Use the first class that doesn't start with a number
                    for cls in el.get('class', []):
                        if cls and cls[0].isalpha():
                            selector = f'.{cls}'
                            break
                
                # If no good selector found, try to find a parent with an ID
                if not selector:
                    parent = el.find_parent(attrs={'id': True})
                    if parent and parent.get('id'):
                        selector = f'#{parent["id"]} {el.name}'
                
                # If still no selector, use the element name
                if not selector:
                    selector = el.name or 'button'
                
                # Add to tabs if not already present
                if not any(t['text'].lower() == text.lower() for t in tabs):
                    tabs.append({
                        'text': text,
                        'selector': selector,
                        'tag': el.name,
                        'attributes': attrs,
                        'index': len(tabs) + 1,
                        'element_id': element_id
                    })
                    
            except Exception as e:
                print(f"Error processing tab element: {str(e)}")
                continue
        
        # If we found tabs, return them
        if tabs:
            return tabs
            
        # Fallback: Try to find any clickable elements that might be tabs
        print("No tabs found with standard methods, trying fallback...")
        
        # Look for any clickable elements that might be tabs
        clickable = soup.find_all(['button', 'a', 'div', 'span'], 
                               attrs={'role': lambda x: x in ['button', 'tab']})
        
        for el in clickable:
            try:
                text = el.get_text(strip=True)
                if not text or len(text) > 30:
                    continue
                    
                # Skip common non-tab elements
                if text.lower() in ['login', 'sign in', 'sign up', 'search', 'menu', 'close']:
                    continue
                
                # Skip elements that are probably not tabs
                if len(text) < 2:  # Too short
                    continue
                    
                # Create a simple selector
                selector = None
                if el.get('id'):
                    selector = f'#{el["id"]}'
                elif el.get('class'):
                    for cls in el.get('class', []):
                        if cls and cls[0].isalpha():
                            selector = f'.{cls}'
                            break
                
                if not selector:
                    selector = el.name or 'button'
                
                tabs.append({
                    'text': text,
                    'selector': selector,
                    'tag': el.name,
                    'index': len(tabs) + 1,
                    'attributes': el.attrs
                })
                
            except Exception as e:
                continue
        
        # If we still don't have tabs, create a default tab for the main page
        if not tabs:
            tabs.append({
                'text': 'Home',
                'selector': 'body',
                'tag': 'body',
                'index': 1,
                'attributes': {}
            })
        
        return tabs
    
    async def take_full_page_screenshot(self, page, output_path):
        """Take a full page screenshot with scrolling."""
        # Get the total height of the page
        total_height = await page.evaluate('''() => {
            const body = document.body;
            const html = document.documentElement;
            return Math.max(
                body.scrollHeight,
                body.offsetHeight,
                html.clientHeight,
                html.scrollHeight,
                html.offsetHeight
            );
        }''')
        
        # Set viewport to full page height
        viewport_width = await page.evaluate('window.innerWidth')
        await page.set_viewport_size({"width": viewport_width, "height": total_height})
            
        # Fallback: Try to find any clickable elements that might be tabs
        print("No tabs found with standard methods, trying fallback...")
            
        # Look for any clickable elements that might be tabs
        clickable = soup.find_all(['button', 'a', 'div', 'span'], 
                               attrs={'role': lambda x: x in ['button', 'tab']})
            
        for el in clickable:
            try:
                text = el.get_text(strip=True)
                if not text or len(text) > 30:
                    continue
                        
                # Skip common non-tab elements
                if text.lower() in ['login', 'sign in', 'sign up', 'search', 'menu', 'close']:
                    continue
                    
                # Skip elements that are probably not tabs
                if len(text) < 2:  # Too short
                    continue
                        
                # Create a simple selector
                selector = None
                if el.get('id'):
                    selector = f'#{el["id"]}'
                elif el.get('class'):
                    for cls in el.get('class', []):
                        if cls and cls[0].isalpha():
                            selector = f'.{cls}'
                            break
                    
                if not selector:
                    selector = el.name or 'button'
                    
                tabs.append({
                    'text': text,
                    'selector': selector,
                    'tag': el.name,
                    'index': len(tabs) + 1,
                    'attributes': el.attrs
                })
                    
            except Exception as e:
                continue
            
        # If we still don't have tabs, create a default tab for the main page
        if not tabs:
            tabs.append({
                'text': 'Home',
                'selector': 'body',
                'tag': 'body',
                'index': 1,
                'attributes': {}
            })
            
        return tabs
    
    async def take_full_page_screenshot(self, page, output_path):
        """Take a full page screenshot with scrolling."""
        # Get the total height of the page
        total_height = await page.evaluate('''() => {
            const body = document.body;
            const html = document.documentElement;
            return Math.max(
                body.scrollHeight,
                body.offsetHeight,
                html.clientHeight,
                html.scrollHeight,
                html.offsetHeight
            );
        }''')
            
        # Set viewport to full page height
        viewport_width = await page.evaluate('window.innerWidth')
        await page.set_viewport_size({"width": viewport_width, "height": total_height})
            
        # Take the screenshot
        await page.screenshot(path=output_path, full_page=True)
        print(f"✓ Screenshot saved to {output_path}")
    
    def fix_css_url(self, url, css_url, assets_dir):
        """
        Fix URLs in CSS files to point to local resources.
        
        Args:
            url: The URL from the CSS file
            css_url: The URL of the CSS file (for resolving relative URLs)
            assets_dir: The directory where assets are stored
                
        Returns:
            str: The fixed URL
        """
        if not url or url.startswith(('data:', 'http:', 'https:', '//')):
            return url
                
        # Handle quoted URLs
        if (url.startswith('"') and url.endswith('"')) or (url.startswith("'") and url.endswith("'")):
            url = url[1:-1]
            
        # Handle absolute paths
        if url.startswith('/'):
            parsed_css = urlparse(css_url)
            base = f"{parsed_css.scheme}://{parsed_css.netloc}"
            full_url = urljoin(base, url)
        else:
            # Handle relative to CSS file
            full_url = urljoin(css_url, url)
            
        # Extract filename and create local path
        filename = os.path.basename(urlparse(full_url).path.split('?')[0])
        if not filename:
            return url  # Return original if no filename could be extracted
                
        return f'../{assets_dir}/{filename}'
    
    async def download_resource(self, url, tab_name, max_retries=2):
        """
        Download a resource and save it to the appropriate location.
        
        Args:
            url: The URL of the resource to download
            tab_name: Name of the current tab (for organizing files)
            max_retries: Maximum number of retry attempts
                
        Returns:
            str: The local path to the downloaded resource, or None if download failed
        """
        # Skip data URLs and invalid URLs
        if not url or url.startswith(('data:', 'javascript:', 'mailto:', 'tel:')):
            return None
                
        # Ensure URL is absolute
        if not url.startswith(('http:', 'https:')):
            if url.startswith('//'):
                url = f"{self.parsed_base.scheme}:{url}"
            elif url.startswith('/'):
                url = f"{self.parsed_base.scheme}://{self.parsed_base.netloc}{url}"
            else:
                url = urljoin(self.base_url, url)
            
        # Clean up URL
        url = url.split('#')[0]  # Remove fragments
        url = url.split('?')[0]  # Remove query parameters
        
        # Skip if already downloaded
        url_hash = hashlib.md5(url.encode()).hexdigest()
        if url_hash in self.downloaded_resources:
            return self.downloaded_resources[url_hash]
        
        for attempt in range(max_retries + 1):
            try:
                async with self.session.get(url) as response:
                    if response.status == 200:
                        # Get content type
                        content_type = response.headers.get('Content-Type', '').lower()
                        
                        # Determine file extension and save directory
                        ext = ''
                        if 'css' in content_type:
                            ext = '.css'
                            save_dir = 'css'
                        elif 'javascript' in content_type or 'ecmascript' in content_type:
                            ext = '.js'
                            save_dir = 'js'
                        elif 'image/' in content_type:
                            ext = f".{content_type.split('/')[-1].split(';')[0]}"
                            save_dir = 'images'
                        else:
                            save_dir = 'other'
                        
                        # If no extension from content type, try to get from URL
                        if not ext:
                            path = urlparse(url).path
                            ext = os.path.splitext(path)[1]
                            if not ext or len(ext) > 5:  # If no extension or too long
                                ext = '.bin'
                        
                        # Create a safe filename (preserve original if possible)
                        original_name = os.path.basename(urlparse(url).path.split('?')[0])
                        if original_name and len(original_name) < 100:  # Reasonable filename length
                            filename = f"{url_hash[:8]}_{original_name}"
                        else:
                            filename = f"{url_hash}{ext}"
                        
                        # Ensure filename has an extension
                        if not os.path.splitext(filename)[1]:
                            filename += ext
                        
                        # Create save path
                        save_path = os.path.join('downloaded_pages', tab_name.lower(), 'assets', save_dir, filename)
                        
                        # Ensure directory exists
                        os.makedirs(os.path.dirname(save_path), exist_ok=True)
                        
                        # Get content
                        if 'text/' in content_type:
                            content = await response.text(encoding='utf-8', errors='ignore')
                            # For CSS files, fix relative URLs
                            if 'css' in content_type:
                                content = re.sub(
                                    r'url\(["\']?(.*?)["\']?\)',
                                    lambda m: f"url('{self.fix_css_url(m.group(1), url, os.path.join('..', 'images'))}')",
                                    content
                                )
                            # Save as text
                            async with aiofiles.open(save_path, 'w', encoding='utf-8') as f:
                                await f.write(content)
                        else:
                            # Save as binary
                            content = await response.read()
                            with open(save_path, 'wb') as f:
                                f.write(content)
                        
                        print(f"  ✓ Downloaded: {os.path.basename(save_path)}")
                        
                        # Cache the downloaded resource
                        rel_path = os.path.join('assets', save_dir, filename)
                        self.downloaded_resources[url_hash] = rel_path
                        return rel_path
                    
                    print(f"  Failed to download {url}: {response.status}")
            except Exception as e:
                print(f"  Error downloading {url} (attempt {attempt + 1}/{max_retries + 1}): {str(e)}")
                if attempt == max_retries:
                    print(f"  Max retries reached for {url}")
                await asyncio.sleep(1)  # Wait before retrying
        
        return None
        
        # Add base tag for relative URLs
        if not soup.find('base'):
            base_tag = soup.new_tag('base', href='../')
            soup.head.insert(0, base_tag)
        
        # Add critical CSS first to prevent layout shifts
        critical_css = """
        /* Critical CSS to prevent layout shifts */
        html, body {
            width: 100% !important;
            height: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow-x: hidden !important;
        }
        
        /* Ensure all elements use border-box sizing */
        *, *::before, *::after {
            box-sizing: border-box !important;
        }
        
        /* Fix for common layout issues */
        body > * {
            max-width: 100% !important;
            width: 100% !important;
        }
        
        /* Fix for padding/margin issues */
        [style*="padding-"],
        [class*="padding"],
        [class*="margin"],
        [class*="container"] {
            max-width: 100% !important;
            width: 100% !important;
            padding-left: 0 !important;
            padding-right: 0 !important;
            margin-left: 0 !important;
            margin-right: 0 !important;
        }
        
        /* Ensure images are responsive */
        img, svg, video, iframe {
            max-width: 100% !important;
            height: auto !important;
            display: block !important;
        }
        
        /* Fix for flex/grid layouts */
        [class*="flex"],
        [class*="grid"] {
            max-width: 100% !important;
            width: 100% !important;
            overflow: hidden !important;
        }
        """
        
        # Add critical CSS as first style tag
        critical_style = soup.new_tag('style')
        critical_style.string = critical_css
        soup.head.insert(0, critical_style)
        
        # Add CSS to fix layout issues
        style = soup.new_tag('style')
        style.string = """
            html, body {
                width: 100% !important;
                max-width: 100% !important;
                overflow-x: hidden !important;
                margin: 0 !important;
                padding: 0 !important;
            }
            body > * {
                max-width: 100% !important;
                box-sizing: border-box !important;
            }
            [style*="padding-right"],
            [class*="padding"],
            [class*="container"] {
                max-width: 100% !important;
                width: 100% !important;
                padding-right: 0 !important;
                margin-right: 0 !important;
            }
        """
        soup.head.append(style)
        
        # Helper function to fix relative URLs
        def fix_url(url, base):
            if not url or url.startswith(('data:', 'http:', 'https:', '//')):
                return url
            return urljoin(base, url)
        
        # Process all resource links
        for tag in soup.find_all(['link', 'script', 'img', 'source', 'iframe', 'style', 'meta']):
            # Handle CSS files
            if tag.name == 'link' and tag.get('rel') and 'stylesheet' in tag['rel'] and tag.get('href'):
                css_url = fix_url(tag['href'], base_url)
                css_filename = os.path.basename(urlparse(css_url).path.split('?')[0]) or 'style.css'
                css_path = os.path.join('css', css_filename)
                tag['href'] = f'../{css_path}'
                
                # Download and process the CSS file
                try:
                    css_dir = os.path.join('downloaded_pages', tab_name.lower(), 'assets', 'css')
                    os.makedirs(css_dir, exist_ok=True)
                    css_filepath = os.path.join(css_dir, css_filename)
                    
                    async with self.session.get(css_url) as response:
                        if response.status == 200:
                            css_content = await response.text()
                            # Fix relative URLs in CSS
                            css_content = re.sub(
                                r'url\(["\']?(.*?)["\']?\)',
                                lambda m: f"url('{self.fix_css_url(m.group(1), css_url, 'images')}')",
                                css_content
                            )
                            # Save the CSS file
                            async with aiofiles.open(css_filepath, 'w', encoding='utf-8') as f:
                                await f.write(css_content)
                except Exception as e:
                    print(f"  Warning: Could not process CSS {css_url}: {str(e)}")
            
            # Handle inline styles
            elif tag.name == 'style' and tag.string:
                # Fix URLs in inline styles
                style_content = str(tag.string)
                style_content = re.sub(
                    r'url\(["\']?(.*?)["\']?\)',
                    lambda m: f"url('{self.fix_css_url(m.group(1), base_url, 'images')}')",
                    style_content
                )
                tag.string = style_content
            
            # Handle images
            elif tag.name == 'img' and tag.get('src'):
                img_url = fix_url(tag['src'], base_url)
                img_filename = os.path.basename(urlparse(img_url).path.split('?')[0]) or 'image.png'
                img_path = os.path.join('images', img_filename)
                tag['src'] = f'../{img_path}'
                
                # Download the image
                await self.download_resource(img_url, tab_name)
            
            # Handle JavaScript files
            elif tag.name == 'script' and tag.get('src'):
                js_url = fix_url(tag['src'], base_url)
                js_filename = os.path.basename(urlparse(js_url).path.split('?')[0]) or 'script.js'
                js_path = os.path.join('js', js_filename)
                tag['src'] = f'../{js_path}'
                
                # Download the JS file
                await self.download_resource(js_url, tab_name)
            
            # Handle other resources with href
            elif tag.has_attr('href'):
                tag['href'] = fix_url(tag['href'], base_url)
            
            # Handle srcset attributes
            if tag.has_attr('srcset'):
                srcset = []
                for src in tag['srcset'].split(','):
                    src_parts = src.strip().split()
                    if src_parts:
                        src_url = fix_url(src_parts[0], base_url)
                        if len(src_parts) > 1:
                            srcset.append(f"{src_url} {' '.join(src_parts[1:])}")
                        else:
                            srcset.append(src_url)
                tag['srcset'] = ', '.join(srcset)
    
    async def explore_tab(self, tab_info, index):
        """Explore a single tab and download its contents with improved navigation."""
        tab_name = tab_info['text']
        tab_dir = os.path.join('downloaded_pages', tab_name.lower())
        os.makedirs(tab_dir, exist_ok=True)
        
        print(f"\nProcessing tab {index + 1}: {tab_name}")
        
        try:
            # Take a before-navigation screenshot for debugging
            debug_screenshot = os.path.join(tab_dir, f'debug_before_{tab_name.lower()}.png')
            await self.page.screenshot(path=debug_screenshot)
            
            # Try multiple navigation strategies
            try:
                # Strategy 1: If it's a direct link, navigate to it
                if 'href' in tab_info.get('attributes', {}):
                    target_url = urljoin(self.base_url, tab_info['attributes']['href'])
                    print(f"  Navigating to: {target_url}")
                    await self.page.goto(target_url, wait_until='networkidle', timeout=30000)
                # Strategy 2: If it has an onclick handler, execute it
                elif 'onclick' in tab_info.get('attributes', {}):
                    print(f"  Executing onclick handler for: {tab_name}")
                    await self.page.evaluate(tab_info['attributes']['onclick'])
                # Strategy 3: Try to click the element
                else:
                    print(f"  Clicking element: {tab_info.get('selector', 'unknown')}")
                    try:
                        # Try to wait for and click the element
                        element = await self.page.wait_for_selector(
                            tab_info['selector'], 
                            state='visible',
                            timeout=10000
                        )
                        await element.scroll_into_view_if_needed()
                        await element.click(button='left', delay=100)
                    except Exception as click_error:
                        print(f"  Click failed, trying alternative click method: {str(click_error)}")
                        # Try alternative click method
                        await self.page.evaluate(f'''
                            const element = document.querySelector('{tab_info["selector"]}');
                            if (element) element.click();
                        ''')
                
                # Wait for content to load with multiple strategies
                print("  Waiting for content to load...")
                
                # Wait for network to be idle
                await self.page.wait_for_load_state('networkidle')
                
                # Additional wait for dynamic content
                await self.page.wait_for_timeout(3000)
                
                # Check if we're still on the same page
                current_url = self.page.url
                if '#' in current_url:
                    # If this is a single-page app with hash routing, wait for content updates
                    await self.page.wait_for_function('''() => {
                        // Wait for common loading indicators to disappear
                        const loaders = document.querySelectorAll('.loading, [role="progressbar"], .spinner');
                        return loaders.length === 0 || Array.from(loaders).every(el => 
                            window.getComputedStyle(el).display === 'none');
                    }''', timeout=10000)
                
            except Exception as nav_error:
                print(f"  Navigation warning: {str(nav_error)}")
                # Take a screenshot to help with debugging
                error_screenshot = os.path.join(tab_dir, f'error_{tab_name.lower()}.png')
                await self.page.screenshot(path=error_screenshot)
                print(f"  Screenshot saved to: {error_screenshot}")
            
            # Wait for content to load
            await self.page.wait_for_timeout(3000)
            
            # Take screenshot of the tab content
            screenshot_path = os.path.join(tab_dir, 'screenshot.png')
            print("  Taking full page screenshot...")
            try:
                await self.take_full_page_screenshot(self.page, screenshot_path)
                print(f"  Screenshot saved to: {screenshot_path}")
            except Exception as screenshot_error:
                print(f"  Failed to take full page screenshot: {str(screenshot_error)}")
                # Fallback to viewport screenshot
                await self.page.screenshot(path=screenshot_path)
                print(f"  Viewport screenshot saved to: {screenshot_path}")
            
            # Get page content
            content = await self.page.content()
            
            # Save raw HTML
            raw_html_path = os.path.join(tab_dir, 'raw.html')
            with open(raw_html_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Process HTML and save
            processed_content = await self.process_html(content, self.base_url, tab_name.lower())
            with open(os.path.join(tab_dir, 'index.html'), 'w', encoding='utf-8') as f:
                f.write(processed_content)
            
            # Download resources
            resources = await self.page.evaluate('''() => {
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
            
            print(f"✓ Successfully saved {tab_name} to {tab_dir}/index.html")
            return True
            
        except Exception as e:
            print(f"✗ Error processing {tab_name}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    async def explore_website(self):
        """Main method to explore the website."""
        await self.init_session()
        
        try:
            # Initialize Playwright
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(headless=False)
            self.context = await self.browser.new_context()
            self.page = await self.context.new_page()
            
            # Go to the main page
            await self.page.goto(self.base_url, wait_until='networkidle')
            
            # Find navigation buttons
            print("\nFinding navigation buttons...")
            tabs = await self.find_navigation_buttons()
            
            if not tabs:
                print("No navigation tabs found. Saving the main page only.")
                tabs = [{'text': 'home', 'selector': 'body'}]
            
            print(f"\nFound {len(tabs)} navigation tabs:")
            for i, tab in enumerate(tabs):
                print(f"{i + 1}. {tab['text']}")
            
            # Process each tab
            for i, tab in enumerate(tabs):
                await self.explore_tab(tab, i)
            
            print("\nExploration complete!")
            print("Directory structure:")
            print("downloaded_pages/")
            for tab in tabs:
                tab_name = tab['text'].lower()
                print(f"  {tab_name}/")
                print("    ├── index.html")
                print("    ├── raw.html")
                print("    ├── screenshot.png")
                print("    └── assets/")
                print("        ├── css/")
                print("        ├── js/")
                print("        ├── images/")
                print("        └── other/")
                
        finally:
            await self.close()

if __name__ == "__main__":
    import sys
    
    # Default dashboard URL - you can change this to your preferred dashboard
    DEFAULT_DASHBOARD = "https://flipsidecrypto.xyz/Sandesh/my-pet-hooligan---the-fps-frontier--Q7dYU"
    
    # Use provided URL or default dashboard
    if len(sys.argv) > 1:
        url = sys.argv[1]
        print(f"Using provided URL: {url}")
    else:
        url = DEFAULT_DASHBOARD
        print(f"No URL provided. Using default dashboard: {url}")
    
    # Run the explorer
    try:
        explorer = WebpageExplorer(url)
        asyncio.run(explorer.explore_website())
    except KeyboardInterrupt:
        print("\nExploration interrupted by user.")
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        print("\nExploration complete!")

from bs4 import BeautifulSoup

def find_nav_buttons(html_file):
    # Read the HTML file
    with open(html_file, 'r', encoding='utf-8') as file:
        html_content = file.read()
    
    # Parse the HTML
    soup = BeautifulSoup(html_content, 'html.parser')
    
    print("Navigation Tabs Found:")
    print("-" * 50)
    
    # Find all tab buttons (they have data-[state] attributes)
    tab_buttons = soup.find_all(lambda tag: tag.name == 'button' and 
                              any('data-[state]' in ' '.join(tag.get('class', [])) 
                                  for class_ in tag.get('class', [])))
    
    # Alternative approach: find buttons with tab-related text
    if not tab_buttons:
        tab_texts = ['about', 'tokens', 'nft', 'governance', 'airdrop', 'socials', 'author']
        tab_buttons = soup.find_all('button', 
                                  string=lambda text: text and text.lower().strip() in tab_texts,
                                  recursive=True)
    
    # If still no buttons found, try finding by parent container
    if not tab_buttons:
        # Look for common navigation containers
        nav_containers = soup.find_all(['nav', 'div'], class_=lambda x: x and any(c in x for c in ['tabs', 'nav', 'navigation']))
        for container in nav_containers:
            tab_buttons.extend(container.find_all('button'))
    
    # Print the found navigation buttons
    for i, button in enumerate(tab_buttons, 1):
        text = button.get_text(strip=True)
        classes = ' '.join(button.get('class', []))
        is_active = 'data-[state=active]' in classes or 'active' in classes
        
        print(f"Tab {i}:")
        print(f"  Text: {text}")
        print(f"  Active: {'Yes' if is_active else 'No'}")
        print(f"  Classes: {classes}")
        print("-" * 50)
    
    if not tab_buttons:
        print("No navigation tabs found. Here's what we found:")
        all_buttons = soup.find_all('button')
        for i, button in enumerate(all_buttons[:10], 1):  # Show first 10 buttons if no nav found
            text = button.get_text(strip=True)
            print(f"Button {i}: {text}")

if __name__ == "__main__":
    html_file = "downloaded_pages/index.html"
    find_nav_buttons(html_file)

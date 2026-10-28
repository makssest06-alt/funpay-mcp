import sys
sys.path.insert(0, 'src')
from funpay_mcp.client import FunPayClient

COOKIES_FILE = 'cookies.txt'

def test():
    c = FunPayClient(cookies_file=COOKIES_FILE)
    ok = c.is_authenticated()
    print(f'Authenticated: {ok}, user_id: {c.user_id}')
    
    if not c.user_id:
        print('ERROR: Not authenticated')
        return
    
    soup = c._get(f'/users/{c.user_id}/')
    text = str(soup)
    print(f'Profile page length: {len(text)} chars')
    
    all_links = soup.select('a')
    print(f'Total links: {len(all_links)}')
    
    offer_links = soup.select('a[href*="offer?id="]')
    print(f'Offer links found: {len(offer_links)}')
    
    with open('test_page.html', 'w', encoding='utf-8') as f:
        f.write(text)
    
    for a in offer_links[:5]:
        href = a.get('href', '')
        text_content = a.get_text(strip=True)[:100]
        parent = a.parent
        price = '?'
        for i in range(6):
            if parent is None: break
            print(f'  level {i}: tag={parent.name}, class={parent.get("class","")}')
            p_el = parent.select_one('[class*="price"], .tc-price')
            if p_el:
                price = p_el.get_text(strip=True)[:30]
                print(f'  PRICE at level {i}: "{price}"')
                break
            parent = parent.parent
        print(f'  href={href}, text="{text_content}", price="{price}"')
        print()

if __name__ == '__main__':
    test()

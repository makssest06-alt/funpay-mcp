import sys
sys.path.insert(0, 'src')
from funpay_mcp.client import FunPayClient

c = FunPayClient(cookies_file='cookies.txt')
soup = c._get('/')
text = str(soup)
# Save raw HTML
with open('homepage.html', 'w', encoding='utf-8') as f:
    f.write(text)
print(f'Homepage length: {len(text)} chars')

# Find game links - look for /games/ or similar
from bs4 import BeautifulSoup
s2 = BeautifulSoup(text, 'html.parser')

# Find all links that go to game pages
for a in s2.select('a[href*="/games/"], a[href*="/chips/"], a[href*="/lots/"]')[:50]:
    href = a.get('href', '')
    txt = a.get_text(strip=True)[:60]
    print(f'  {href} -> "{txt}"')

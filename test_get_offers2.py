import sys
sys.path.insert(0, 'src')
from funpay_mcp.client import FunPayClient

c = FunPayClient(cookies_file='cookies.txt')
soup = c._get('/users/19702923/')

# Find the showcase and print its inner HTML
import re
text = str(soup)
# Find the showcase section
idx = text.find('showcase-table')
if idx >= 0:
    # Print 3000 chars around it
    start = max(0, idx - 200)
    end = min(len(text), idx + 3000)
    print(text[start:end])

import sys
sys.path.insert(0, 'src')
from funpay_mcp.client import FunPayClient

c = FunPayClient(cookies_file='cookies.txt')
games = c.get_all_games()
print(f'Total games found: {len(games)}')
for i, g in enumerate(games[:25]):
    print(f'{i+1}. {g.get("name", g.get("title", "?"))} (url={g.get("url", g.get("href", ""))})')

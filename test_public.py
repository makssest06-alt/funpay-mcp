"""
Test all public (no auth) FunPay MCP tools.
Run: uv run python test_public.py
"""

import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from funpay_mcp.client import FunPayClient
from funpay_mcp.server import (
    check_auth, search_games, get_all_games,
    get_game_categories, get_user_profile,
    get_listings, get_offer_details,
    analyze_market, analyze_competitors, suggest_price,
    create_market_report, get_reviews,
)


def test(name, func, *args, **kwargs):
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"{'='*60}")
    try:
        result = func(*args, **kwargs)
        output = str(result)
        if len(output) > 2000:
            print(output[:2000] + "\n...(truncated)")
        else:
            print(output)
        print(f"\nPASS: {name}")
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    passed = 0
    total = 0

    # 1. check auth (no cookies)
    total += 1
    if test("check-auth (no auth)", check_auth):
        passed += 1

    # 2. search games
    for query in ["EVE Online", "World of Warcraft", "Genshin", "Lineage 2", "Aion"]:
        total += 1
        if test(f"search-games: {query}", search_games, query):
            passed += 1

    # 3. all games
    total += 1
    if test("get-all-games", get_all_games):
        passed += 1

    # 4. categories for games
    for url, label in [("/chips/8/", "EVE Online"), ("/chips/1/", "Lineage 2")]:
        total += 1
        if test(f"get-game-categories: {label} ({url})", get_game_categories, url):
            passed += 1

    # 5. listings
    total += 1
    if test("get-listings: EVE ISK", get_listings, "/chips/8/", 1):
        passed += 1

    # 6. market analysis
    total += 1
    if test("analyze-market: EVE Online", analyze_market, "/chips/8/", None, 2):
        passed += 1

    total += 1
    if test("analyze-market: EVE /lots/22/", analyze_market, "/chips/8/", "/lots/22/", 1):
        passed += 1

    # 7. competitors
    total += 1
    if test("analyze-competitors: EVE ISK", analyze_competitors, "/chips/8/", None, 5, 1):
        passed += 1

    # 8. suggest price
    total += 1
    if test("suggest-price: EVE ISK", suggest_price, "/chips/8/", None, 2):
        passed += 1

    # 9. market report
    total += 1
    if test("create-market-report: EVE", create_market_report, "/chips/8/", 1):
        passed += 1

    # 10. user profile (try to get from first listing)
    total += 1
    try:
        client = FunPayClient()
        listings = client.get_listings("/chips/8/", max_pages=1)
        if listings and listings[0].seller_id:
            if test(f"get-user-profile: {listings[0].seller_id}",
                    get_user_profile, listings[0].seller_id):
                passed += 1
        else:
            print("SKIP: get-user-profile (no seller_id)")
            passed += 1
    except Exception as e:
        print(f"SKIP: get-user-profile ({e})")
        passed += 1

    print(f"\n{'='*60}")
    print(f"RESULT: {passed}/{total} tests passed")
    print(f"{'='*60}")
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

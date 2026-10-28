"""
Скрипт входа на FunPay через браузер.
Открывает окно, ты логинишься, куки сохраняются.

Использование:
    python browser_login.py [path_to_cookies.txt]
"""

import os
import sys
import time


def save_cookies_netscape(cookies, path):
    """Сохраняет куки в формате Netscape (с expiry)."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        f.write("# https://curl.haxx.se/docs/http-cookies.html\n\n")
        for c in cookies:
            domain = c.get("domain", "")
            if not domain.startswith("."):
                domain = "." + domain
            flag = "TRUE"
            path_val = c.get("path", "/")
            secure = "TRUE" if c.get("secure") else "FALSE"
            expires = str(int(c.get("expires", 0)))
            name = c.get("name", "")
            value = c.get("value", "")
            f.write(f"{domain}\t{flag}\t{path_val}\t{secure}\t{expires}\t{name}\t{value}\n")


def main():
    if len(sys.argv) < 2:
        cookies_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cookies.txt"
        )
    else:
        cookies_path = sys.argv[1]
    cookies_path = os.path.abspath(cookies_path)

    print("[BROWSER] Opening browser for FunPay login...")
    print(f"[BROWSER] Cookies will be saved to: {cookies_path}")
    print("[BROWSER] Log in to FunPay in the opened window.")
    print("[BROWSER] Waiting up to 5 minutes...\n")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # Пробуем реальный Chrome (он не банится Cloudflare)
        chrome_paths = [
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            os.path.expanduser("~\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe"),
        ]
        exe = next((pth for pth in chrome_paths if os.path.exists(pth)), None)
        if not exe:
            import shutil
            exe = shutil.which("chrome") or shutil.which("google-chrome")

        launch_opts = {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=ChromeWhatsNewUI",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        }
        if exe:
            launch_opts["executable_path"] = exe

        browser = p.chromium.launch(**launch_opts)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ru-RU",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/149.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto("https://funpay.com/")

        # Ждём логина
        logged_in = False
        start = time.time()
        timeout = 300

        while time.time() - start < timeout:
            remaining = int(timeout - (time.time() - start))
            try:
                el = page.query_selector(".user-link-name")
                if el:
                    username = el.inner_text().strip()
                    print(f"\n[OK] Logged in as: {username}")
                    logged_in = True
                    break
            except Exception:
                pass
            if remaining % 30 == 0 and remaining > 0:
                print(f"[WAIT] {remaining}s remaining...")
            time.sleep(1)

        if not logged_in:
            print("[ERROR] Login timeout. Cookies not saved.")
            print("[ERROR] Try exporting cookies manually via 'Get cookies.txt' extension.")
            browser.close()
            return 1

        cookies = context.cookies()
        save_cookies_netscape(cookies, cookies_path)
        print(f"[OK] Saved {len(cookies)} cookies")

        names = [c["name"] for c in cookies if c["name"] in ("golden_key", "PHPSESSID")]
        if names:
            print(f"[OK] Session: {', '.join(names)}")
        else:
            print("[WARN] golden_key/PHPSESSID not found!")
            print("[WARN] Try: set FUNPAY_COOKIES_STR manually")

        browser.close()
        print("[OK] Login complete! Session saved permanently.")
        return 0


if __name__ == "__main__":
    sys.exit(main())

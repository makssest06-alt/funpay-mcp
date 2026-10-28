"""
FunPay Client — HTTP-клиент для всех действий на FunPay.
Реализует каждый endpoint, доступный пользователю на сайте.
"""

import json
import logging
import os
import random
import re
import time
from typing import Any, Optional
from urllib.parse import urljoin, urlencode

import requests
from bs4 import BeautifulSoup
from .models import (
    AccountInfo,
    ChatDialog,
    FunPayListing,
    FunPayOffer,
    GameCategory,
    MarketAnalysis,
    NodeField,
    Order,
    Review,
)

logger = logging.getLogger("funpay-mcp")

BASE_URL = "https://funpay.com"
def _get_ua():
    from fake_useragent import UserAgent
    return UserAgent(browsers=["chrome", "firefox", "edge"])


class FunPayClient:
    """
    Полноценный клиент для взаимодействия с FunPay.
    Поддерживает все действия, доступные пользователю на сайте.

    Аутентификация:
    - golden_key + PHPSESSID cookies (экспорт из браузера)
    - CSRF-токен из data-app-data

    Использование:
        client = FunPayClient(cookies_file="cookies.txt")
        client.login()  # проверит/восстановит сессию
        info = client.get_account_info()
        listings = client.get_listings("/chips/8/")
        offers = client.get_my_offers()
    """

    def __init__(
        self,
        cookies_file: str | None = None,
        cookies_str: str | None = None,
    ):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })
        self._rotate_ua()

        self.csrf_token: str | None = None
        self.user_id: str | None = None
        self._authenticated = False
        self.cookies_file = cookies_file

        if cookies_file and os.path.exists(cookies_file):
            self._load_cookies_from_file(cookies_file)
        elif cookies_str:
            self._load_cookies_from_string(cookies_str)

        # Пробуем восстановить сессию
        self._restore_session()

    # =========================================================================
    # ВНУТРЕННИЕ МЕТОДЫ
    # =========================================================================

    def _rotate_ua(self):
        self.session.headers.update({"User-Agent": _get_ua().random})

    def _random_delay(self, min_s=0.3, max_s=1.5):
        time.sleep(random.uniform(min_s, max_s))

    def _save_cookies(self):
        """Сохраняет текущие куки в файл (Netscape формат с expiry).
        Сохраняет ТОЛЬКО если есть golden_key или PHPSESSID."""
        if not self.cookies_file:
            return
        try:
            funpay_cookies = []
            for cookie in self.session.cookies:
                domain = getattr(cookie, 'domain', '') or ''
                name = getattr(cookie, 'name', '')
                value = getattr(cookie, 'value', '')
                if not name or not value:
                    continue
                if 'funpay' not in domain:
                    continue
                funpay_cookies.append((domain, name, value, cookie))

            # Не перезаписываем файл если нет ОБЕИХ ключевых кук
            names = {c[1] for c in funpay_cookies}
            if 'golden_key' not in names or 'PHPSESSID' not in names:
                logger.debug("Нет golden_key/PHPSESSID — куки не сохранены")
                return

            with open(self.cookies_file, 'w', encoding='utf-8') as f:
                f.write("# Netscape HTTP Cookie File\n")
                f.write("# https://curl.haxx.se/docs/http-cookies.html\n\n")
                for domain, name, value, cookie in funpay_cookies:
                    if not domain.startswith('.'):
                        domain = '.' + domain
                    flag = "TRUE"
                    path = getattr(cookie, 'path', '/') or '/'
                    secure = "TRUE" if getattr(cookie, 'secure', False) else "FALSE"
                    expires_val = getattr(cookie, 'expires', None)
                    if expires_val is None:
                        expires = "0"
                    else:
                        expires = str(int(expires_val))
                    f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
            logger.debug("Куки сохранены в %s (%d cookies)", self.cookies_file, len(funpay_cookies))
        except Exception as e:
            logger.warning("Ошибка сохранения куки: %s", e)

    def _check_auth_ok(self, soup) -> bool:
        """Проверяет, что мы не на странице логина/привязки телефона."""
        if soup is None:
            return True
        title = soup.title.string.lower() if soup.title else ''
        if 'вход' in title or 'login' in title:
            self._authenticated = False
            return False
        if 'привязка телефона' in title or 'phone' in title:
            self._authenticated = False
            return False
        return True

    def _load_cookies_from_file(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    # Netscape cookie format
                    self.session.cookies.set(
                        parts[5], parts[6],
                        domain=parts[0], path=parts[2],
                        secure=parts[3].lower() == "true",
                    )
                elif "=" in line:
                    # Simple name=value format
                    name, value = line.split("=", 1)
                    self.session.cookies.set(
                        name.strip(), value.strip(),
                        domain=".funpay.com",
                    )

    def _load_cookies_from_string(self, s: str):
        # Netscape формат (с табуляцией) — 7 колонок
        if "\t" in s and s.count("\t") >= 6:
            for line in s.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    self.session.cookies.set(
                        parts[5].strip(), parts[6].strip(),
                        domain=parts[0].strip(), path=parts[2].strip(),
                        secure=parts[3].lower() == "true",
                    )
            return
        # Простой name=value формат через ;
        for item in s.split(";"):
            item = item.strip()
            if "=" in item:
                name, value = item.split("=", 1)
                self.session.cookies.set(name.strip(), value.strip(), domain=".funpay.com")

    def _request(
        self, method: str, path: str,
        data: dict | None = None,
        files: dict | None = None,
        headers: dict | None = None,
        allow_redirects: bool = True,
        parse: bool = True,
    ) -> requests.Response | BeautifulSoup:
        """Базовый HTTP-запрос с автопарсингом HTML и автообновлением сессии"""
        url = urljoin(BASE_URL, path)
        self._rotate_ua()
        self._random_delay()

        req_headers = headers or {}

        # CSRF-заголовок для POST/PUT/DELETE
        if method.upper() in ("POST", "PUT", "DELETE") and self.csrf_token:
            req_headers.setdefault("x-csrf-token", self.csrf_token)

        logger.debug("%s %s", method.upper(), url)

        try:
            resp = self.session.request(
                method, url,
                data=data,
                files=files,
                headers=req_headers,
                allow_redirects=allow_redirects,
                timeout=30,
            )
            resp.raise_for_status()

            if not parse or "application/json" in resp.headers.get("Content-Type", ""):
                return resp

            if "text/html" in resp.headers.get("Content-Type", ""):
                soup = BeautifulSoup(resp.text, "lxml")
                self._extract_csrf(soup)
                self._check_auth_ok(soup)
                return soup

            return resp

        except requests.exceptions.HTTPError as e:
            code = e.response.status_code
            logger.error("HTTP %s: %s %s", code, method.upper(), url)
            if code == 403 or code == 401:
                logger.warning("Сессия устарела, пробуем восстановить")
                self._restore_session()
            raise
        except requests.exceptions.RequestException as e:
            logger.error("Ошибка запроса: %s", e)
            raise

    def _get(self, path: str, **kwargs):
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, data: dict | None = None, **kwargs):
        return self._request("POST", path, data=data, **kwargs)

    def _extract_csrf(self, soup: BeautifulSoup):
        """Извлекает CSRF-токен из data-app-data"""
        body = soup.select_one("body")
        if body and body.get("data-app-data"):
            try:
                app_data = json.loads(body["data-app-data"])
                token = app_data.get("csrf-token")
                uid = app_data.get("userId", "0")
                if token:
                    self.csrf_token = token
                if uid and uid != "0":
                    self.user_id = uid
                    self._authenticated = True
                logger.debug("CSRF: %s, UserID: %s", token, uid)
            except (json.JSONDecodeError, KeyError):
                pass
        # fallback: hidden input
        if not self.csrf_token:
            inp = soup.select_one('input[name="csrf_token"]')
            if inp:
                self.csrf_token = inp.get("value")

    def _extract_csrf_from_text(self, html: str):
        soup = BeautifulSoup(html, "lxml")
        self._extract_csrf(soup)
        return soup

    def _restore_session(self):
        """Пробует восстановить сессию — загружает главную, ищет CSRF"""
        try:
            soup = self._get("/")
            logger.info("Сессия восстановлена. Auth=%s, UserID=%s",
                         self._authenticated, self.user_id)
            return True
        except Exception as e:
            logger.warning("Не удалось восстановить сессию: %s", e)
            return False

    def get_csrf_token(self) -> str:
        """Гарантирует наличие CSRF-токена"""
        if not self.csrf_token:
            self._restore_session()
        if not self.csrf_token:
            raise RuntimeError("Не удалось получить CSRF-токен. Обновите cookies.")
        return self.csrf_token

    # =========================================================================
    # ПУБЛИЧНЫЕ МЕТОДЫ — АККАУНТ / АВТОРИЗАЦИЯ
    # =========================================================================

    def is_authenticated(self) -> bool:
        return self._authenticated

    def login(self, login: str, password: str) -> dict:
        """
        Вход в аккаунт.
        Примечание: требуется Cloudflare Turnstile, который невозможно
        пройти без браузера. Рекомендуется использовать cookies.
        """
        token = self.get_csrf_token()
        data = {
            "csrf_token": token,
            "login": login,
            "password": password,
        }
        try:
            soup = self._post("/account/login", data=data)
            self._restore_session()
            if self._authenticated:
                return {"success": True, "user_id": self.user_id}
            # Проверяем ошибку
            err = soup.select_one(".alert, .error, .help-block")
            return {"success": False, "error": err.text.strip() if err else "Ошибка входа"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def login_via_browser(self) -> dict:
        """
        Вход через браузер (Playwright).
        Открывает окно Chrome, пользователь входит вручную,
        после чего сессия сохраняется в cookies.txt навсегда.
        """
        import subprocess
        import sys

        login_script = os.path.join(os.path.dirname(__file__), "browser_login.py")
        cookies_path = self.cookies_file or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "cookies.txt"
        )

        result = subprocess.run(
            [sys.executable, login_script, cookies_path],
            capture_output=True, text=True, timeout=300
        )

        if result.returncode == 0:
            self._load_cookies_from_file(cookies_path)
            self._restore_session()
            if self._authenticated:
                return {"success": True, "user_id": self.user_id}
            return {"success": False, "error": "Не удалось восстановить сессию после входа"}
        return {"success": False, "error": result.stderr.strip() or result.stdout.strip()}

    def get_account_info(self) -> AccountInfo | None:
        """Информация об аккаунте"""
        if not self._authenticated:
            return None
        try:
            soup = self._get("/")
            body = soup.select_one("body")
            app_data = {}
            if body and body.get("data-app-data"):
                app_data = json.loads(body["data-app-data"])

            # Парсим имя пользователя и баланс
            username = "Unknown"
            balance = "0"
            rating = "0"
            avatar = ""

            user_name_el = soup.select_one(".user-link-name")
            if user_name_el:
                username = user_name_el.get_text(strip=True)

            balance_el = soup.select_one(".balance, .user-balance, [class*='balance']")
            if balance_el:
                balance = balance_el.get_text(strip=True)

            rating_el = soup.select_one(
                ".current-rating, .rating-value, .user-rating, [class*='rating']"
            )
            if rating_el:
                rating = rating_el.get_text(strip=True)

            avatar_el = soup.select_one(".avatar img, .user-avatar img, img.avatar")
            if avatar_el:
                avatar = avatar_el.get("src", "")

            return AccountInfo(
                user_id=app_data.get("userId", "0"),
                username=username,
                balance=balance,
                balance_raw=self._parse_price(balance),
                rating=rating,
                rating_value=float(re.sub(r"[^\d.]", "", rating) or 0),
                avatar_url=avatar,
                csrf_token=self.csrf_token or "",
            )
        except Exception as e:
            logger.error("Ошибка получения инфо об аккаунте: %s", e)
            return None

    def get_my_offers(self) -> list[FunPayOffer]:
        """Мои объявления (продавца) — парсит профиль"""
        if not self._authenticated or not self.user_id:
            return []
        try:
            soup = self._get(f"/users/{self.user_id}/")
            offers = []
            seen = set()
            for offer_block in soup.select("div.offer"):
                title_link = offer_block.select_one("h3 a[href*='/lots/']")
                if not title_link:
                    continue
                node = ""
                nm = re.search(r'/lots/(\d+)/', title_link.get('href', ''))
                if nm:
                    node = nm.group(1)
                for item in offer_block.select("a.tc-item"):
                    href = item.get("href", "")
                    if not href or href in seen:
                        continue
                    seen.add(href)
                    offer_id = ""
                    om = re.search(r"offer[?&]id=(\d+)", href)
                    if om:
                        offer_id = om.group(1)
                    title_el = item.select_one(".tc-desc-text")
                    title = title_el.get_text(strip=True) if title_el else ""
                    price_el = item.select_one(".tc-price")
                    price_raw = 0.0
                    price = ""
                    if price_el:
                        data_s = price_el.get("data-s", "")
                        if data_s:
                            try:
                                price_raw = float(data_s)
                            except ValueError:
                                pass
                        price_text = price_el.get_text(strip=True)
                        # Убираем значок автовыдачи из цены
                        if price_text:
                            price = price_text
                    stock_el = item.select_one(".tc-amount")
                    stock = stock_el.get_text(strip=True) if stock_el else "1"
                    offers.append(FunPayOffer(
                        offer_id=offer_id,
                        node=node,
                        title=title or "Объявление",
                        price=price,
                        price_raw=price_raw,
                        stock=stock,
                        status="active",
                        description="",
                        url=urljoin(BASE_URL, href),
                    ))
            return offers
        except Exception as e:
            logger.error("Ошибка получения своих объявлений: %s", e)
            return []

    def get_my_orders(self, page: int = 1) -> list[Order]:
        """Мои заказы"""
        if not self._authenticated:
            return []
        try:
            soup = self._get(f"/orders/?page={page}")
            orders = []
            for row in soup.select("tr.order-row, .order-item, [class*='order']"):
                cells = row.select("td")
                if len(cells) < 4:
                    continue
                link_el = row.select_one("a[href]")
                oid = ""
                if link_el:
                    m = re.search(r"order_id=(\d+)", link_el.get("href", ""))
                    if m:
                        oid = m.group(1)
                orders.append(Order(
                    id=oid,
                    type="",
                    title=cells[0].get_text(strip=True) if len(cells) > 0 else "",
                    price=cells[1].get_text(strip=True) if len(cells) > 1 else "",
                    status=cells[2].get_text(strip=True) if len(cells) > 2 else "",
                    seller="",
                    buyer="",
                    created_at=cells[3].get_text(strip=True) if len(cells) > 3 else "",
                    url=link_el.get("href", "") if link_el else "",
                ))
            return orders
        except Exception as e:
            logger.error("Ошибка получения заказов: %s", e)
            return []

    def get_balance(self) -> dict:
        """Баланс и финансовая информация"""
        if not self._authenticated:
            return {"error": "Не авторизован"}
        try:
            soup = self._get("/account/balance")
            balance_data = {}
            for row in soup.select(".balance-row, [class*='balance']"):
                label = row.select_one("[class*='label'], dt")
                value = row.select_one("[class*='value'], dd")
                if label and value:
                    balance_data[label.get_text(strip=True)] = value.get_text(strip=True)
            return balance_data or {"error": "Не удалось распарсить баланс"}
        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # ПУБЛИЧНЫЕ МЕТОДЫ — ПРОФИЛЬ / НАСТРОЙКИ
    # =========================================================================

    def get_settings_page(self) -> BeautifulSoup:
        """Страница настроек аккаунта"""
        return self._get("/account/settings")

    def update_profile(
        self,
        username: str | None = None,
        about: str | None = None,
        email: str | None = None,
    ) -> dict:
        """Обновить профиль"""
        if not self._authenticated:
            return {"success": False, "error": "Не авторизован"}
        try:
            token = self.get_csrf_token()
            data = {"csrf_token": token}
            if username:
                data["name"] = username
            if about:
                data["about"] = about
            if email:
                data["email"] = email
            soup = self._post("/account/settings", data=data)
            msg = soup.select_one(".alert-success, .alert-danger, .help-block")
            text = msg.get_text(strip=True) if msg else ""
            success = bool(soup.select_one(".alert-success"))
            return {"success": success, "message": text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def upload_avatar(self, image_path: str) -> dict:
        """Загрузить/сменить аватарку"""
        if not self._authenticated:
            return {"success": False, "error": "Не авторизован"}
        if not os.path.exists(image_path):
            return {"success": False, "error": f"Файл не найден: {image_path}"}
        try:
            token = self.get_csrf_token()
            with open(image_path, "rb") as f:
                files = {"avatar": f}
                data = {"csrf_token": token}
                soup = self._post("/account/settings", data=data, files=files)
            msg = soup.select_one(".alert-success, .alert-danger")
            text = msg.get_text(strip=True) if msg else "Аватарка обновлена"
            success = bool(soup.select_one(".alert-success"))
            return {"success": success, "message": text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def change_password(self, current: str, new: str) -> dict:
        """Смена пароля"""
        if not self._authenticated:
            return {"success": False, "error": "Не авторизован"}
        try:
            token = self.get_csrf_token()
            data = {
                "csrf_token": token,
                "password_current": current,
                "password": new,
                "password_confirm": new,
            }
            soup = self._post("/account/settings", data=data)
            success = bool(soup.select_one(".alert-success"))
            msg = soup.select_one(".alert-success, .alert-danger, .help-block")
            text = msg.get_text(strip=True) if msg else ""
            return {"success": success, "message": text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_user_profile(self, user_id: str) -> dict:
        """Просмотр профиля любого пользователя"""
        try:
            soup = self._get(f"/users/{user_id}/")
            info = {
                "user_id": user_id,
                "username": "",
                "rating": "",
                "reviews_count": 0,
                "registered": "",
                "offers": [],
            }
            title = soup.select_one("h1, .media-heading")
            if title:
                info["username"] = title.get_text(strip=True)

            rating_el = soup.select_one(".current-rating, .rating, [class*='rating']")
            if rating_el:
                info["rating"] = rating_el.get_text(strip=True)

            reg_el = soup.select_one(
                ".registration-date, .reg-date, [class*='registered']"
            )
            if reg_el:
                info["registered"] = reg_el.get_text(strip=True)

            # Список предложений пользователя
            for offer in soup.select(".tc-item, .offer-item, [class*='offer']"):
                link = offer.select_one("a[href]")
                price = offer.select_one("[class*='price']")
                info["offers"].append({
                    "title": link.get_text(strip=True) if link else "",
                    "url": link.get("href", "") if link else "",
                    "price": price.get_text(strip=True) if price else "",
                })

            # Количество отзывов
            reviews_header = soup.select_one(".review-list h2, .reviews-header")
            if reviews_header:
                m = re.search(r"(\d+)", reviews_header.get_text())
                if m:
                    info["reviews_count"] = int(m.group(1))

            return info
        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # ПУБЛИЧНЫЕ МЕТОДЫ — ПОИСК ИГР И КАТЕГОРИЙ
    # =========================================================================

    def search_games(self, query: str) -> list[dict]:
        """Поиск игр по названию.
        FunPay не имеет серверного поиска — фильтрация происходит на клиенте
        через JavaScript. Поэтому мы загружаем полный список игр и фильтруем локально.
        """
        try:
            all_games = self._get_game_list_from_homepage()
            q = query.lower().strip()
            matches = [
                g for g in all_games
                if q in g["name"].lower()
            ]
            # Если точных совпадений нет — ищем по частям
            if not matches:
                for g in all_games:
                    for word in q.split():
                        if word in g["name"].lower():
                            matches.append(g)
                            break
            return matches
        except Exception as e:
            logger.error("Ошибка поиска игр: %s", e)
            return []

    def _get_game_list_from_homepage(self) -> list[dict]:
        """Загружает полный список игр с главной страницы"""
        soup = self._get("/")
        games = []
        seen_urls = set()
        sub_cats = {"isk", "кинары", "серебро", "золото", "кк", "все", "сферы poe 2"}

        for col in soup.select(".col-md-3, .col-xs-6"):
            for a in col.select("a[href*='/chips/']"):
                href = a.get("href", "")
                name = a.get_text(strip=True)
                if not href or not name:
                    continue
                if not re.match(r"^https://funpay\.com/chips/\d+/(\?|$)", href) and \
                   not re.match(r"^/chips/\d+/(\?|$)", href):
                    continue
                if name.lower() in sub_cats:
                    continue
                key = href.split("?")[0]
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                games.append({"name": name, "url": href})

        return games

    def get_game_categories(self, game_url: str) -> list[GameCategory]:
        """Категории для игры"""
        try:
            soup = self._get(game_url)
            categories = []

            # Основная навигация: .counter-item внутри .cd-forward
            for a in soup.select(".counter-list a.counter-item, .cd-forward a.counter-item"):
                param = a.select_one(".counter-param")
                value = a.select_one(".counter-value")
                if param:
                    name = param.get_text(strip=True)
                    count = 0
                    if value:
                        count = int(re.sub(r"\D", "", value.get_text(strip=True)) or 0)
                    categories.append(GameCategory(
                        name=name,
                        url=a.get("href", ""),
                        listings_count=count,
                    ))

            # Fallback: боковая навигация (subcategory list)
            if not categories:
                for a in soup.select("a[class*='subcategory'], .subcategory-list a, .lots-nav a"):
                    name = a.get_text(strip=True)
                    href = a.get("href", "")
                    if name and href and name not in ("ISK", "Все"):
                        count_match = re.search(r"(\d+)", name)
                        count = int(count_match.group(1)) if count_match else 0
                        clean_name = re.sub(r"\d+", "", name).strip()
                        categories.append(GameCategory(
                            name=clean_name or name,
                            url=href,
                            listings_count=count,
                        ))

            return categories
        except Exception as e:
            logger.error("Ошибка получения категорий: %s", e)
            return []

    def get_all_games(self) -> list[dict]:
        """Полный список всех игр на FunPay"""
        try:
            return self._get_game_list_from_homepage()
        except Exception as e:
            logger.error("Ошибка получения списка игр: %s", e)
            return []

    # =========================================================================
    # ПУБЛИЧНЫЕ МЕТОДЫ — ОБЪЯВЛЕНИЯ (ЛОТЫ)
    # =========================================================================

    def get_listings(
        self,
        url: str,
        max_pages: int = 3,
        filters: dict | None = None,
    ) -> list[FunPayListing]:
        """Собирает объявления со страницы категории"""
        all_items = []
        for page in range(1, max_pages + 1):
            page_url = f"{url}?page={page}" if page > 1 else url
            if filters:
                qs = urlencode(filters)
                page_url = f"{page_url}{'&' if '?' in page_url else '?'}{qs}"
            try:
                soup = self._get(page_url)
                items = self._parse_listings(soup)
                if not items:
                    break
                all_items.extend(items)
            except Exception as e:
                logger.debug("Страница %s: %s", page_url, e)
                break
        return all_items

    def _parse_listings(self, soup: BeautifulSoup) -> list[FunPayListing]:
        items = []
        for el in soup.select("a.tc-item, tr.tc-item, .tc-item, .offer-row"):
            try:
                # Для <a class="tc-item"> сам элемент является ссылкой
                link = el if el.name == "a" and el.get("href") else el.select_one("a[href]")
                url = link.get("href", "") if link else ""

                oid = ""
                m = re.search(r"id=(\d+)", url)
                if m:
                    oid = m.group(1)
                elif link:
                    m2 = re.search(r"offer[?=](\d+)", url)
                    if m2:
                        oid = m2.group(1)

                # server
                server_el = el.select_one(".tc-server, .server, [class*='server']")
                server = server_el.get_text(strip=True) if server_el else ""

                # seller name: .media-user-name
                name_el = el.select_one(
                    ".media-user-name, .tc-desc, .tc-desc-text, [class*='desc'], "
                    ".offer-title, .lot-name"
                )
                title = name_el.get_text(strip=True) if name_el else ""

                # seller name is specifically in .media-user-name
                seller_el = el.select_one(".media-user-name, .seller-name, .user-name")
                seller_name = seller_el.get_text(strip=True) if seller_el else ""

                # seller id from data-user attribute
                seller_id = el.get("data-user", "")
                if not seller_id:
                    avatar = el.select_one(".avatar-photo")
                    if avatar:
                        dhref = avatar.get("data-href", "")
                        mu = re.search(r"/users/(\d+)", dhref)
                        if mu:
                            seller_id = mu.group(1)

                # price
                price_el = el.select_one(
                    ".tc-price, .price, [class*='price'], .offer-price"
                )
                price_text = price_el.get_text(strip=True) if price_el else "N/A"
                price_val = self._parse_price(price_text)

                # rating (stars)
                stars_el = el.select_one(".rating-stars, [class*='rating-stars'], .rating")
                rating = 0
                if stars_el:
                    star_count = len(stars_el.select("i.fas, .fas, [class*='star']"))
                    if star_count:
                        rating = star_count
                    else:
                        rating = len(re.findall(r"[★☆]", stars_el.get_text()))

                # reviews count
                reviews = 0
                rev_el = el.select_one(
                    ".rating-mini-count, .reviews-count, .media-user-reviews span"
                )
                if rev_el:
                    m3 = re.search(r"(\d+)", rev_el.get_text())
                    if m3:
                        reviews = int(m3.group(1))

                # quantity
                qty_el = el.select_one(
                    ".tc-amount, .amount, [class*='amount'], .offer-stock"
                )
                qty = qty_el.get_text(strip=True) if qty_el else "1"

                # years on site
                years = 0
                info_el = el.select_one(".media-user-info, .user-info, [class*='info']")
                if info_el:
                    m4 = re.search(r"(\d+)\s*(лет|год|года)", info_el.get_text())
                    if m4:
                        years = int(m4.group(1))
                if not years:
                    all_text = el.get_text()
                    m4 = re.search(r"(\d+)\s*(лет|год|года)\s*на\s*сайте", all_text)
                    if m4:
                        years = int(m4.group(1))

                items.append(FunPayListing(
                    id=oid,
                    title=title,
                    price=price_text,
                    price_value=price_val,
                    seller=seller_name or "Unknown",
                    seller_id=seller_id,
                    seller_rating=rating,
                    seller_reviews=reviews,
                    seller_years=years,
                    quantity=qty.strip(),
                    server=server,
                    url=urljoin(BASE_URL, url) if url else "",
                ))
            except Exception as e:
                logger.debug("Ошибка парсинга лота: %s", e)
                continue
        return items

    def _parse_price(self, text: str) -> float:
        text = text.replace(",", ".").replace(" ", "").replace("\u202f", "")
        m = re.search(r"(\d+\.?\d*)", text)
        return float(m.group(1)) if m else 0.0

    def get_offer_details(self, offer_url: str) -> dict:
        """Детальная информация о конкретном предложении"""
        try:
            soup = self._get(offer_url)
            info = {"parameters": {}}

            title = soup.select_one("h1, .page-header h1")
            if title:
                info["title"] = title.get_text(strip=True)

            for param in soup.select(".param-item, .param-list .row"):
                label = param.select_one(".control-label, dt, strong")
                value = param.select_one(".controls, dd, span")
                if label and value:
                    info["parameters"][label.get_text(strip=True)] = \
                        value.get_text(strip=True)

            # Цена
            price_el = soup.select_one("[class*='price'], .product-price, .order-sum")
            if price_el:
                info["price"] = price_el.get_text(strip=True)

            # Продавец
            seller_el = soup.select_one(
                ".media-user .media-heading a, .seller-info a, [class*='seller'] a"
            )
            if seller_el:
                info["seller"] = seller_el.get_text(strip=True)
                m = re.search(r"/users/(\d+)", seller_el.get("href", ""))
                if m:
                    info["seller_id"] = m.group(1)

            # Чат (data-offer для отправки сообщений)
            chat_box = soup.select_one(".chat, [data-offer]")
            if chat_box:
                info["chat_offer"] = chat_box.get("data-offer", "")
                info["chat_seller"] = chat_box.get("data-seller", "")

            return info
        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # ПУБЛИЧНЫЕ МЕТОДЫ — УПРАВЛЕНИЕ ОБЪЯВЛЕНИЯМИ
    # =========================================================================

    def get_node_schema(self, node: str) -> list[NodeField]:
        """
        Получает схему полей для категории (перед созданием лота).
        Позволяет узнать какие поля и значения доступны.
        """
        try:
            soup = self._get(f"/lots/{node}/trade")
            fields = []

            for select in soup.select("select.lot-field-input, select.form-control"):
                field_id = select.get("name", "").replace("f-", "")
                label_el = soup.select_one(f'label[for="f-{field_id}"]')
                label = label_el.get_text(strip=True) if label_el else field_id

                options = []
                for opt in select.select("option"):
                    if opt.get("value"):
                        options.append({
                            "value": opt.get("value"),
                            "label": opt.get_text(strip=True),
                        })

                fields.append(NodeField(
                    id=field_id,
                    type=5,  # select
                    label=label,
                    conditions=[],
                    options=options,
                ))

            return fields
        except Exception as e:
            logger.error("Ошибка получения схемы: %s", e)
            return []

    def _post_json(self, path: str, data: dict | None = None, referer: str | None = None, **kwargs):
        """POST-запрос, возвращающий JSON (для offerSave и подобных)."""
        headers = kwargs.pop("headers", {})
        headers.setdefault("X-Requested-With", "XMLHttpRequest")
        referer = referer or "/lots/offerEdit"
        headers.setdefault("Referer", urljoin(BASE_URL, referer))
        resp = self._request("POST", path, data=data, headers=headers, parse=False, **kwargs)
        if isinstance(resp, requests.Response):
            return resp.json()
        return resp

    def create_lot(
        self,
        node: str,
        title_ru: str,
        title_en: str = "",
        price: float = 1.50,
        amount: int = 99999,
        desc_ru: str = "",
        desc_en: str = "",
        payment_msg_ru: str = "",
        payment_msg_en: str = "",
        secrets: str = "",
        server_id: str = "",
        region: str = "",
        active: bool = True,
        auto_delivery: bool = True,
    ) -> dict:
        """
        Создаёт новый лот (объявление) через offerSave.

        Аргументы:
            node — ID категории (например '879')
            title_ru — заголовок (RU)
            title_en — заголовок (EN)
            price — цена
            amount — количество
            desc_ru — подробное описание (RU)
            desc_en — подробное описание (EN)
            payment_msg_ru — сообщение покупателю после оплаты (RU)
            payment_msg_en — сообщение покупателю после оплаты (EN)
            secrets — содержимое для автовыдачи (построчно)
            server_id — ID платформы/сервера (например '415' = Social Club)
            region — регион (Россия, СНГ, Украина, Казахстан, Турция, Аргентина, Другой регион)
            active — активно ли объявление
            auto_delivery — включить ли автовыдачу
        """
        if not self._authenticated:
            return {"success": False, "error": "Не авторизован"}
        try:
            token = self.get_csrf_token()
            import time
            data = {
                "csrf_token": token,
                "form_created_at": str(int(time.time())),
                "offer_id": "0",
                "node_id": node,
                "location": "",
                "deleted": "",
                "fields[summary][ru]": title_ru,
                "fields[summary][en]": title_en or title_ru,
                "fields[desc][ru]": desc_ru,
                "fields[desc][en]": desc_en or desc_ru,
                "fields[payment_msg][ru]": payment_msg_ru,
                "fields[payment_msg][en]": payment_msg_en or payment_msg_ru,
                "price": str(price),
                "amount": str(amount),
            }
            if region:
                data["fields[region]"] = region
            if server_id:
                data["server_id"] = server_id
            if auto_delivery:
                data["auto_delivery"] = "on"
            if secrets:
                data["secrets"] = secrets
            if active:
                data["active"] = "on"

            result = self._post_json("/lots/offerSave", data=data, referer=f"/lots/offerEdit?node={node}")

            done = result.get("done", False)
            offer_id = result.get("offer_id", "")
            url = result.get("url", "")
            if not offer_id and url:
                m = re.search(r"offer[=/](\d+)", url)
                if m:
                    offer_id = m.group(1)

            return {
                "success": done,
                "offer_id": offer_id,
                "url": url,
                "message": result.get("error", "Объявление создано"),
                "errors": result.get("errors", []),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_form_data(self, offer_id: str, node: str = "") -> dict:
        """Загружает форму offerEdit и возвращает все поля."""
        path = f"/lots/offerEdit?offer={offer_id}"
        if node:
            path += f"&node={node}"
        soup = self._get(path)
        data = {}
        for inp in soup.select("input[name], textarea[name], select[name]"):
            name = inp.get("name", "")
            if not name:
                continue
            tag = inp.name
            if tag == "select":
                opts = inp.select("option[selected]")
                if opts:
                    data[name] = opts[0].get("value", "")
                else:
                    opts = inp.select("option")
                    if opts:
                        data[name] = opts[0].get("value", "")
            elif tag == "textarea":
                data[name] = inp.get_text()
            else:
                val = inp.get("value", "")
                if inp.get("type") == "checkbox":
                    if inp.has_attr("checked"):
                        data[name] = "on"
                else:
                    data[name] = val
        return data

    def update_lot(
        self,
        offer_id: str,
        node: str = "",
        title_ru: str | None = None,
        title_en: str | None = None,
        price: float | None = None,
        amount: int | None = None,
        desc_ru: str | None = None,
        desc_en: str | None = None,
        payment_msg_ru: str | None = None,
        payment_msg_en: str | None = None,
        secrets: str | None = None,
        server_id: str | None = None,
        active: bool | None = None,
        auto_delivery: bool | None = None,
    ) -> dict:
        """Обновляет существующий лот. Загружает текущие поля формы и меняет только указанные."""
        if not self._authenticated:
            return {"success": False, "error": "Не авторизован"}
        try:
            import time
            data = self._get_form_data(offer_id)
            token = data.pop("csrf_token", "")
            if not token:
                return {"success": False, "error": "Не удалось получить CSRF"}

            data["csrf_token"] = token
            data["offer_id"] = offer_id
            data["form_created_at"] = str(int(time.time()))
            if node:
                data["node_id"] = node
            if title_ru is not None:
                data["fields[summary][ru]"] = title_ru
            if title_en is not None:
                data["fields[summary][en]"] = title_en
            if price is not None:
                data["price"] = str(price)
            if amount is not None:
                data["amount"] = str(amount)
            if desc_ru is not None:
                data["fields[desc][ru]"] = desc_ru
            if desc_en is not None:
                data["fields[desc][en]"] = desc_en
            if payment_msg_ru is not None:
                data["fields[payment_msg][ru]"] = payment_msg_ru
            if payment_msg_en is not None:
                data["fields[payment_msg][en]"] = payment_msg_en
            if secrets is not None:
                data["secrets"] = secrets
            if server_id is not None:
                data["server_id"] = server_id
            if active is not None:
                data["active"] = "on" if active else "off"
            if auto_delivery is not None:
                data["auto_delivery"] = "on" if auto_delivery else "off"

            result = self._post_json("/lots/offerSave", data=data, referer=f"/lots/offerEdit?offer={offer_id}")
            done = result.get("done", False)
            return {
                "success": done,
                "offer_id": offer_id,
                "message": "Объявление обновлено",
                "errors": result.get("errors", []),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_lot(self, offer_id: str, node: str = "") -> dict:
        """Удаляет лот. Загружает форму и отправляет с deleted=1."""
        if not self._authenticated:
            return {"success": False, "error": "Не авторизован"}
        try:
            import time
            # Пробуем найти node из списка моих офферов если не передан
            if not node:
                for o in self.get_my_offers():
                    if o.offer_id == offer_id:
                        node = o.node
                        break
            data = self._get_form_data(offer_id, node=node)
            token = data.pop("csrf_token", "")
            if not token:
                return {"success": False, "error": "Не удалось получить CSRF"}

            data["csrf_token"] = token
            data["offer_id"] = offer_id
            data["form_created_at"] = str(int(time.time()))
            data["deleted"] = "1"
            result = self._post_json("/lots/offerSave", data=data, referer=f"/lots/offerEdit?offer={offer_id}")

            done = result.get("done", False)
            return {
                "success": done,
                "offer_id": offer_id,
                "message": "Объявление удалено" if done else "Ошибка удаления",
                "error": result.get("error", ""),
                "errors": result.get("errors", []),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def clone_lot(self, source_offer_id: str, target_nodes: list[str]) -> dict:
        """Клонирует объявление в другие категории"""
        if not self._authenticated:
            return {"success": False, "error": "Не авторизован"}
        try:
            token = self.get_csrf_token()
            data = {
                "csrf_token": token,
                "offer_id": source_offer_id,
                "nodes": ",".join(target_nodes),
            }
            result = self._post_json("/lots/offerClone", data=data)
            done = result.get("done", False)
            return {
                "success": done,
                "message": "Лот склонирован" if done else "Ошибка клонирования",
                "error": result.get("error", ""),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # ПУБЛИЧНЫЕ МЕТОДЫ — ЧАТ
    # =========================================================================

    def get_dialogs(self) -> list[ChatDialog]:
        """Список диалогов (из сайдбара на главной)"""
        if not self._authenticated:
            return []
        try:
            soup = self._get("/")
            dialogs = []
            for d in soup.select(".media.media-user"):
                name_el = d.select_one(".media-user-name a")
                msg_el = d.select_one(".chat-msg-text, .chat-msg-body")
                unread_el = d.select_one(".unread, .badge, [class*='unread']")

                href = name_el.get("href", "") if name_el else ""
                user_id = ""
                m = re.search(r"/users/(\d+)", href)
                if m:
                    user_id = m.group(1)

                dialogs.append(ChatDialog(
                    id=user_id,
                    user_name=name_el.get_text(strip=True) if name_el else "",
                    user_id=user_id,
                    last_message=msg_el.get_text(strip=True)[:100] if msg_el else "",
                    url=urljoin(BASE_URL, f"/users/{user_id}/") if user_id else "",
                    unread=bool(unread_el),
                ))
            return dialogs
        except Exception as e:
            logger.error("Ошибка получения диалогов: %s", e)
            return []

    def _resolve_node_name(self, dialog_id: str) -> str:
        """Преобразует dialog_id (user_id или node_id) в node name для API"""
        if "-" in dialog_id:
            return dialog_id
        if self.user_id:
            return f"users-{dialog_id}-{self.user_id}"
        return dialog_id

    def get_dialog_messages(self, dialog_id: str, limit: int = 100) -> list[dict]:
        """Сообщения в диалоге (через /runner/ chat_node API)"""
        if not self._authenticated:
            return []
        try:
            node_name = self._resolve_node_name(dialog_id)
            token = self.get_csrf_token()
            resp = self.session.post(
                urljoin(BASE_URL, "/runner/"),
                data={
                    "objects": json.dumps([{
                        "type": "chat_node",
                        "id": node_name,
                        "tag": "msgs",
                        "data": {"node": node_name, "last_message": -1, "content": ""},
                    }]),
                    "request": "false",
                    "csrf_token": token,
                },
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": urljoin(BASE_URL, "/chat/"),
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                },
                timeout=15,
            )
            data = resp.json()
            messages = []
            objects = data.get("objects") or []
            for obj in objects:
                obj_data = obj.get("data") or {}
                raw_msgs = obj_data.get("messages") or []
                for msg in raw_msgs[:limit]:
                    msg_id = msg.get("id", "")
                    html = msg.get("html", "")
                    msg_soup = BeautifulSoup(html, "lxml")
                    chat_msg = msg_soup.select_one(".chat-message")
                    if not chat_msg:
                        chat_msg = msg_soup
                    author_el = chat_msg.select_one(".media-user-name")
                    text_el = chat_msg.select_one(".chat-msg-text")
                    time_el = chat_msg.select_one(".chat-msg-date")
                    text = text_el.get_text(" ", strip=True) if text_el else ""
                    messages.append({
                        "id": msg_id,
                        "author": author_el.get_text(strip=True) if author_el else "",
                        "text": text,
                        "time": time_el.get_text(strip=True) if time_el else "",
                    })
            return messages
        except Exception as e:
            logger.error("Ошибка получения сообщений: %s", e)
            return []

    def send_message(self, dialog_id: str, message: str) -> dict:
        """Отправить сообщение через /runner/ endpoint"""
        if not self._authenticated:
            return {"success": False, "error": "Не авторизован"}
        try:
            token = self.get_csrf_token()
            node_name = self._resolve_node_name(dialog_id)
            request_data = {
                "action": "chat_message",
                "data": {
                    "node": node_name,
                    "content": message,
                    "last_message": 0,
                    "compact": False,
                    "show_avatar": False,
                },
            }
            resp = self.session.post(
                urljoin(BASE_URL, "/runner/"),
                data={
                    "objects": json.dumps([]),
                    "request": json.dumps(request_data),
                    "csrf_token": token,
                },
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": urljoin(BASE_URL, f"/chat/?node={dialog_id}" if dialog_id.isdigit() else "/chat/"),
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                },
                timeout=15,
            )
            result = resp.json()
            response = result.get("response") or {}
            if response.get("error"):
                return {"success": False, "error": response["error"]}
            return {"success": True, "message": "Сообщение отправлено"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # ПУБЛИЧНЫЕ МЕТОДЫ — ЗАКАЗЫ
    # =========================================================================

    def create_order(
        self,
        offer_id: str,
        offer_type: str = "lot",
        amount: int = 1,
        player_name: str = "",
        payment_method: str = "",
    ) -> dict:
        """Создать заказ (купить)"""
        if not self._authenticated:
            return {"success": False, "error": "Не авторизован"}
        try:
            token = self.get_csrf_token()
            data = {
                "csrf_token": token,
                "type": offer_type,
                "preview": "1",
                "offer_id": offer_id,
                "amount": str(amount),
                "method": payment_method,
            }
            if player_name:
                data["player"] = player_name

            soup = self._post("/orders/new", data=data)
            success = bool(
                soup.select_one(".alert-success, .order-success, [class*='success']")
            )
            msg = soup.select_one(".alert, .help-block, .order-info")
            text = msg.get_text(strip=True) if msg else "Заказ создан"
            return {"success": success, "message": text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def confirm_order(self, order_id: str) -> dict:
        """Подтвердить получение заказа"""
        if not self._authenticated:
            return {"success": False, "error": "Не авторизован"}
        try:
            token = self.get_csrf_token()
            data = {"csrf_token": token, "order_id": order_id, "action": "confirm"}
            soup = self._post("/orders/confirm", data=data)
            success = bool(
                soup.select_one(".alert-success, .success, [class*='success']")
            )
            return {"success": success, "message": "Заказ подтверждён" if success else "Ошибка"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def dispute_order(self, order_id: str, reason: str) -> dict:
        """Открыть спор по заказу"""
        if not self._authenticated:
            return {"success": False, "error": "Не авторизован"}
        try:
            token = self.get_csrf_token()
            data = {
                "csrf_token": token,
                "order_id": order_id,
                "action": "dispute",
                "reason": reason,
            }
            soup = self._post("/orders/dispute", data=data)
            success = bool(
                soup.select_one(".alert-success, .success, [class*='success']")
            )
            return {"success": success, "message": "Спор открыт" if success else "Ошибка"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def cancel_order(self, order_id: str) -> dict:
        """Отменить заказ"""
        if not self._authenticated:
            return {"success": False, "error": "Не авторизован"}
        try:
            token = self.get_csrf_token()
            data = {"csrf_token": token, "order_id": order_id, "action": "cancel"}
            soup = self._post("/orders/cancel", data=data)
            success = bool(
                soup.select_one(".alert-success, .success, [class*='success']")
            )
            return {"success": success, "message": "Заказ отменён" if success else "Ошибка"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # ПУБЛИЧНЫЕ МЕТОДЫ — ОТЗЫВЫ
    # =========================================================================

    def get_user_reviews(
        self,
        user_id: str,
        page: int = 1,
        filter_rating: int = 0,
    ) -> list[Review]:
        """Отзывы пользователя"""
        try:
            data = {"user_id": user_id, "continue": str(page)}
            if filter_rating:
                data["filter"] = str(filter_rating)

            resp = self._post("/users/reviews", data=data, parse=False)
            try:
                raw = resp.json()
                reviews = []
                for r in raw if isinstance(raw, list) else raw.get("reviews", []):
                    reviews.append(Review(
                        id=str(r.get("id", "")),
                        author=r.get("author", ""),
                        rating=int(r.get("rating", 0)),
                        text=r.get("text", ""),
                        date=r.get("date", ""),
                    ))
                return reviews
            except (json.JSONDecodeError, AttributeError):
                # Fallback: HTML
                soup = self._extract_csrf_from_text(resp.text)
                reviews = []
                for r in soup.select(".review-item, .review, [class*='review']"):
                    author = r.select_one(".review-author, .author, [class*='author']")
                    rating = r.select_one(".review-rating, [class*='rating']")
                    text = r.select_one(".review-text, .text, [class*='text']")
                    date = r.select_one(".review-date, .date, [class*='date']")
                    reviews.append(Review(
                        id="",
                        author=author.get_text(strip=True) if author else "",
                        rating=int(re.sub(r"\D", "", rating.get_text(strip=True)))
                            if rating else 0,
                        text=text.get_text(strip=True) if text else "",
                        date=date.get_text(strip=True) if date else "",
                    ))
                return reviews
        except Exception as e:
            logger.error("Ошибка получения отзывов: %s", e)
            return []

    def leave_review(self, order_id: str, rating: int, text: str) -> dict:
        """Оставить отзыв о продавце/покупателе"""
        if not self._authenticated:
            return {"success": False, "error": "Не авторизован"}
        try:
            token = self.get_csrf_token()
            data = {
                "csrf_token": token,
                "order_id": order_id,
                "rating": str(rating),
                "text": text,
            }
            soup = self._post("/orders/review", data=data)
            success = bool(soup.select_one(".alert-success, .success"))
            return {
                "success": success,
                "message": "Отзыв оставлен" if success else "Ошибка",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # ПУБЛИЧНЫЕ МЕТОДЫ — ПОДДЕРЖКА
    # =========================================================================

    def get_support_tickets(self) -> list[dict]:
        """Тикеты в поддержку"""
        if not self._authenticated:
            return []
        try:
            soup = self._get("/support")
            tickets = []
            for t in soup.select(".ticket-item, [class*='ticket']"):
                link = t.select_one("a[href]")
                status = t.select_one("[class*='status']")
                subject = t.select_one("[class*='subject'], [class*='title']")
                tickets.append({
                    "id": re.search(r"/(\d+)", link.get("href", "")).group(1)
                        if link and re.search(r"/(\d+)", link.get("href", "")) else "",
                    "subject": subject.get_text(strip=True) if subject else "",
                    "status": status.get_text(strip=True) if status else "",
                    "url": link.get("href", "") if link else "",
                })
            return tickets
        except Exception as e:
            return []

    # =========================================================================
    # ПУБЛИЧНЫЕ МЕТОДЫ — АНАЛИЗ РЫНКА
    # =========================================================================

    def analyze_market(
        self,
        game_url: str,
        category_url: str | None = None,
        max_pages: int = 5,
    ) -> MarketAnalysis:
        """Полный анализ рынка: статистика цен, топ продавцов, рекомендации"""
        target_url = category_url or game_url
        listings = self.get_listings(target_url, max_pages=max_pages)

        # Название игры
        game_name = game_url.strip("/").split("/")[-1]
        try:
            soup = self._get(game_url)
            h1 = soup.select_one("h1")
            if h1:
                game_name = h1.get_text(strip=True)
        except Exception:
            pass

        if not listings:
            return MarketAnalysis(
                game=game_name, category=category_url or "all",
                total_listings=0, price_min=0, price_max=0,
                price_avg=0, price_median=0,
                top_sellers=[], price_distribution={},
                recommendation="Нет данных для анализа",
            )

        prices = sorted([l.price_value for l in listings if l.price_value > 0])
        if not prices:
            prices = [0]

        n = len(prices)
        price_min = prices[0]
        price_max = prices[-1]
        price_avg = sum(prices) / n
        price_median = prices[n // 2] if n % 2 else \
            (prices[n // 2 - 1] + prices[n // 2]) / 2

        # Распределение цен
        distribution = {}
        for p in prices:
            bucket = round(p, 1)
            distribution[bucket] = distribution.get(bucket, 0) + 1

        # Топ продавцов
        sellers = {}
        for l in listings:
            if l.seller and l.seller not in sellers:
                sellers[l.seller] = {
                    "name": l.seller,
                    "price": l.price_value,
                    "rating": l.seller_rating,
                    "reviews": l.seller_reviews,
                    "years": l.seller_years,
                    "listing_url": l.url,
                }
        top_sellers = sorted(sellers.values(), key=lambda x: x["reviews"], reverse=True)[:10]

        # Категория
        cat_name = "все"
        if category_url:
            try:
                soup = self._get(category_url)
                active = soup.select_one("a.active, .selected, [class*='active']")
                if active:
                    cat_name = active.get_text(strip=True)
            except Exception:
                cat_name = category_url.strip("/").split("/")[-1]

        # Рекомендация
        recommendation = self._generate_recommendation(prices, price_avg, price_median)

        return MarketAnalysis(
            game=game_name,
            category=cat_name,
            total_listings=n,
            price_min=price_min,
            price_max=price_max,
            price_avg=round(price_avg, 2),
            price_median=round(price_median, 2),
            top_sellers=top_sellers,
            price_distribution={str(k): v for k, v in sorted(distribution.items())},
            recommendation=recommendation,
        )

    def _generate_recommendation(
        self, prices: list[float], avg: float, median: float
    ) -> str:
        if len(prices) < 3:
            return f"Мало данных ({len(prices)} объявлений). Средняя: {avg:.2f} €"

        sorted_p = sorted(prices)
        q1 = sorted_p[len(sorted_p) // 4]
        q3 = sorted_p[3 * len(sorted_p) // 4]
        fast_sale = round(q1 * 0.95, 2)
        competitive = round(median, 2)
        premium = round(q3, 2)

        return (
            f"📊 Анализ на основе {len(sorted_p)} объявлений:\n"
            f"  Диапазон: {sorted_p[0]:.2f} – {sorted_p[-1]:.2f} €\n"
            f"  Средняя: {avg:.2f} € | Медиана: {median:.2f} €\n"
            f"  Q1 (25%): {q1:.2f} € | Q3 (75%): {q3:.2f} €\n\n"
            f"💡 Рекомендации:\n"
            f"  • Быстрая продажа: {fast_sale:.2f} €\n"
            f"  • Конкурентоспособная: {competitive:.2f} €\n"
            f"  • Макс. прибыль: {premium:.2f} €"
        )

    # =========================================================================
    # ЗАКРЫТИЕ
    # =========================================================================

    def close(self):
        self.session.close()

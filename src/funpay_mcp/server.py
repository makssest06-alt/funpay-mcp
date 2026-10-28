"""
FunPay MCP Server — Полный MCP сервер для всех действий на FunPay.

Предоставляет AI-ассистентам инструменты для:
  - Анализа рынка и конкурентов
  - Управления объявлениями (создание, редактирование, удаление, клонирование)
  - Чата с покупателями
  - Управления заказами
  - Управления профилем (аватарка, настройки, пароль)
  - Отзывов
  - Работы с поддержкой
  - Получения информации об аккаунте

Подключение к AI:
  Claude Desktop: добавь в mcpServers в claude_desktop_config.json
  Cursor: настрой в .cursor/mcp.json
  Любой MCP-клиент: поддерживает stdio и streamable-http
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .client import FunPayClient
from .models import AccountInfo, MarketAnalysis

logger = logging.getLogger("funpay-mcp")

# =============================================================================
# MCP СЕРВЕР
# =============================================================================

mcp = FastMCP("FunPay MCP")

_client: FunPayClient | None = None


def get_client() -> FunPayClient:
    global _client
    if _client is None:
        _client = FunPayClient(
            cookies_file=os.environ.get("FUNPAY_COOKIES_FILE"),
            cookies_str=os.environ.get("FUNPAY_COOKIES_STR"),
        )
    return _client


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ
# =============================================================================

def _ensure_auth() -> str | None:
    """Проверяет авторизацию. Возвращает None если всё ок, иначе сообщение."""
    client = get_client()
    if not client.is_authenticated():
        return (
            "❌ Не авторизован на FunPay.\n\n"
            "Как войти (выбери способ):\n"
            "  1. Используй инструмент 'browser-login' — откроет браузер\n"
            "  2. Используй 'set-cookies' — вставь куки из расширения 'Get cookies.txt'\n"
            "     (установи расширение, зайди на funpay.com, нажми на иконку → Export)\n"
            "  3. Или задай переменную:\n"
            "     FUNPAY_COOKIES_STR='golden_key=xxx; PHPSESSID=yyy'"
        )
    return None


def _safe_call(func, *args, **kwargs) -> str:
    """Безопасный вызов с форматированием ошибок"""
    try:
        result = func(*args, **kwargs)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"❌ Ошибка: {e!s}"


# =============================================================================
# ИНСТРУМЕНТЫ (TOOLS)
# =============================================================================

# ---------------------------------------------------------------------------
# 1. АККАУНТ И АВТОРИЗАЦИЯ
# ---------------------------------------------------------------------------

@mcp.tool(
    name="set-cookies",
    description=(
        "ВСТАВИТЬ КУКИ FUNPAY ВРУЧНУЮ.\n"
        "Скопируй cookies.txt из расширения 'Get cookies.txt' (Chrome).\n"
        "На FunPay → расширение → Export → скопируй всё содержимое сюда."
    )
)
def set_cookies(cookies_text: str) -> str:
    client = get_client()
    client._load_cookies_from_string(cookies_text)
    client._save_cookies()
    client._restore_session()
    if client.is_authenticated():
        return "OK: Авторизация успешна! Куки сохранены в cookies.txt."
    return "ERROR: Не удалось авторизоваться. Проверь куки."


@mcp.tool(
    name="browser-login",
    description=(
        "ВОЙТИ НА FUNPAY ЧЕРЕЗ БРАУЗЕР (рекомендуется).\n"
        "Открывает окно Chrome, ты входишь в аккаунт,\n"
        "после чего сессия сохраняется НАВСЕГДА в cookies.txt.\n"
        "PHPSESSID больше не нужно обновлять — всё хранится в браузере."
    )
)
def browser_login() -> str:
    client = get_client()
    result = client.login_via_browser()
    if result.get("success"):
        return (
            f"✅ Успешный вход!\n"
            f"User ID: {result.get('user_id')}\n"
            f"Сессия сохранена: {client.cookies_file}\n"
            f"Теперь можно работать с FunPay через MCP инструменты."
        )
    return f"❌ Ошибка: {result.get('error', 'Неизвестная ошибка')}"


@mcp.tool(
    name="check-auth",
    description="Проверить авторизацию на FunPay. Выполни первой."
)
def check_auth() -> str:
    client = get_client()
    if client.is_authenticated():
        info = client.get_account_info()
        if info:
            return (
                f"✅ Авторизован как: {info.username}\n"
                f"ID: {info.user_id}\n"
                f"Баланс: {info.balance}\n"
                f"Рейтинг: {info.rating}"
            )
        return "✅ Авторизован (ID не определён)"
    return (
        "❌ Не авторизован.\n"
        "Настрой cookies:\n"
        "  export FUNPAY_COOKIES_FILE=/path/to/cookies.txt\n"
        "  # или экспорт строкой:\n"
        "  export FUNPAY_COOKIES_STR='golden_key=...; PHPSESSID=...'"
    )


@mcp.tool(
    name="get-account-info",
    description="Детальная информация об аккаунте: ID, имя, баланс, рейтинг, аватарка."
)
def get_account_info() -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(lambda: _format_account(get_client().get_account_info()))


@mcp.tool(
    name="get-balance",
    description="Баланс и фин. информация аккаунта."
)
def get_balance() -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(get_client().get_balance)


# ---------------------------------------------------------------------------
# 2. ПОИСК ИГР И КАТЕГОРИЙ
# ---------------------------------------------------------------------------

@mcp.tool(
    name="search-games",
    description="Поиск игр на FunPay по названию. Пример: 'EVE Online', 'Genshin'"
)
def search_games(query: str) -> str:
    return _safe_call(
        lambda: _format_games(get_client().search_games(query), query)
    )


@mcp.tool(
    name="get-all-games",
    description="Полный список всех игр на FunPay."
)
def get_all_games() -> str:
    return _safe_call(
        lambda: _format_games(get_client().get_all_games(), "все")
    )


@mcp.tool(
    name="get-game-categories",
    description="Категории для конкретной игры. Укажите URL игры (например '/chips/8/')."
)
def get_game_categories(game_url: str) -> str:
    return _safe_call(lambda: _format_categories(
        get_client().get_game_categories(game_url), game_url
    ))


@mcp.tool(
    name="get-user-profile",
    description="Профиль любого пользователя. Укажите user_id. Пример: '12345'"
)
def get_user_profile(user_id: str) -> str:
    return _safe_call(get_client().get_user_profile, user_id)


# ---------------------------------------------------------------------------
# 3. ОБЪЯВЛЕНИЯ И РЫНОК
# ---------------------------------------------------------------------------

@mcp.tool(
    name="get-listings",
    description=(
        "Получить объявления по URL категории. "
        "Пример url: '/chips/8/' (ISK), '/lots/22/' (аккаунты). "
        "Опционально: фильтры server='Tranquility', online_only=true"
    )
)
def get_listings(
    url: str,
    max_pages: int = 2,
    server: str = "",
    online_only: bool = False,
    min_price: float | None = None,
    max_price: float | None = None,
) -> str:
    filters = {}
    if server:
        filters["server"] = server
    if online_only:
        filters["online"] = "1"

    client = get_client()
    listings = client.get_listings(url, max_pages=min(max_pages, 5), filters=filters)

    if min_price is not None:
        listings = [l for l in listings if l.price_value >= min_price]
    if max_price is not None:
        listings = [l for l in listings if l.price_value <= max_price]

    return _format_listings(listings, url)


@mcp.tool(
    name="get-offer-details",
    description=(
        "Детали конкретного предложения/лота. "
        "Укажите URL offer (например '/lots/offer?id=12345' или '/chips/offer?id=...')."
    )
)
def get_offer_details(offer_url: str) -> str:
    return _safe_call(get_client().get_offer_details, offer_url)


@mcp.tool(
    name="analyze-market",
    description=(
        "ПОЛНЫЙ АНАЛИЗ РЫНКА: собирает объявления, считает статистику цен, "
        "определяет топ-продавцов, рекомендует цену. "
        "Используй ПЕРВЫМ для понимания рынка."
    )
)
def analyze_market(
    game_url: str,
    category_url: str | None = None,
    max_pages: int = 5,
) -> str:
    return _safe_call(
        lambda: _format_market(
            get_client().analyze_market(game_url, category_url, max_pages=max_pages)
        )
    )


@mcp.tool(
    name="analyze-competitors",
    description=(
        "Детальный разбор конкурентов: продавцы, цены, рейтинг, отзывы. "
        "Фильтр по минимальному количеству отзывов."
    )
)
def analyze_competitors(
    game_url: str,
    category_url: str | None = None,
    min_reviews: int = 10,
    max_pages: int = 3,
) -> str:
    return _safe_call(
        lambda: _format_competitors(
            get_client().get_listings(
                category_url or game_url, max_pages=min(max_pages, 5)
            ),
            min_reviews,
        )
    )


@mcp.tool(
    name="suggest-price",
    description=(
        "Рекомендация конкурентоспособной цены. "
        "Анализирует рынок и предлагает 3 варианта: быстрая продажа, "
        "конкурентная, премиум."
    )
)
def suggest_price(
    game_url: str,
    category_url: str | None = None,
    max_pages: int = 3,
) -> str:
    analysis = get_client().analyze_market(game_url, category_url, max_pages=max_pages)
    return analysis.recommendation if analysis.total_listings > 0 else "Нет данных"


@mcp.tool(
    name="create-market-report",
    description=(
        "КОМПЛЕКСНЫЙ ОТЧЁТ ПО РЫНКУ: категории, статистика цен, "
        "конкуренты, стратегия. Используй для принятия решений."
    )
)
def create_market_report(game_url: str, max_pages: int = 3) -> str:
    return _safe_call(lambda: _format_report(
        get_client(), game_url, max_pages
    ))


# ---------------------------------------------------------------------------
# 4. УПРАВЛЕНИЕ ОБЪЯВЛЕНИЯМИ (ТРЕБУЕТ АВТОРИЗАЦИИ)
# ---------------------------------------------------------------------------

@mcp.tool(
    name="get-my-offers",
    description="Мои активные объявления (список)."
)
def get_my_offers() -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(lambda: _format_my_offers(get_client().get_my_offers()))


@mcp.tool(
    name="get-node-schema",
    description=(
        "Получить схему полей для категории перед созданием лота. "
        "Укажите node (ID категории, например '108'). "
        "Вернёт все доступные поля и их варианты."
    )
)
def get_node_schema(node: str) -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(lambda: _format_schema(get_client().get_node_schema(node), node))


@mcp.tool(
    name="create-lot",
    description=(
        "СОЗДАТЬ НОВОЕ ОБЪЯВЛЕНИЕ.\n\n"
        "Параметры:\n"
        "  node — ID категории (число)\n"
        "  title_ru — заголовок (русский)\n"
        "  title_en — заголовок (английский)\n"
        "  price — цена в евро (default: 1.50)\n"
        "  amount — количество (default: 99999)\n"
        "  desc_ru — подробное описание (русский)\n"
        "  desc_en — подробное описание (английский)\n"
        "  payment_msg_ru — сообщение покупателю (русский)\n"
        "  payment_msg_en — сообщение покупателю (английский)\n"
        "  secrets — содержимое автовыдачи\n"
        "  server_id — ID платформы/сервера\n"
        "  region — регион (Россия, СНГ, Украина, Казахстан, Турция, Аргентина, Другой регион)\n"
        "  active — активно (default: true)\n"
        "  auto_delivery — автовыдача (default: true)\n"
    )
)
def create_lot(
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
) -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(
        get_client().create_lot,
        node, title_ru, title_en, price, amount,
        desc_ru, desc_en, payment_msg_ru, payment_msg_en,
        secrets, server_id, region, active, auto_delivery,
    )


@mcp.tool(
    name="update-lot",
    description=(
        "Обновить существующее объявление. "
        "Укажите offer_id и изменяемые поля."
    )
)
def update_lot(
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
) -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(
        get_client().update_lot,
        offer_id, node, title_ru, title_en, price, amount,
        desc_ru, desc_en, payment_msg_ru, payment_msg_en,
        secrets, server_id, active, auto_delivery,
    )


@mcp.tool(
    name="delete-lot",
    description="Удалить объявление по offer_id."
)
def delete_lot(offer_id: str) -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(get_client().delete_lot, offer_id)


@mcp.tool(
    name="clone-lot",
    description=(
        "Клонировать объявление в другие категории. "
        "source_offer_id — исходное объявление, "
        "target_nodes — список ID категорий через запятую."
    )
)
def clone_lot(source_offer_id: str, target_nodes: str) -> str:
    err = _ensure_auth()
    if err:
        return err
    nodes = [n.strip() for n in target_nodes.split(",") if n.strip()]
    return _safe_call(get_client().clone_lot, source_offer_id, nodes)


# ---------------------------------------------------------------------------
# 5. ЧАТ
# ---------------------------------------------------------------------------

@mcp.tool(
    name="get-dialogs",
    description="Список чатов/диалогов с покупателями."
)
def get_dialogs() -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(lambda: _format_dialogs(get_client().get_dialogs()))


@mcp.tool(
    name="get-dialog-messages",
    description="Сообщения в диалоге. dialog_id — ID чата (число)."
)
def get_dialog_messages(dialog_id: str) -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(lambda: _format_messages(
        get_client().get_dialog_messages(dialog_id), dialog_id
    ))


@mcp.tool(
    name="send-message",
    description=(
        "Отправить сообщение в чат. "
        "dialog_id — ID диалога (из get-dialogs). "
        "message — текст сообщения."
    )
)
def send_message(dialog_id: str, message: str) -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(get_client().send_message, dialog_id, message)


# ---------------------------------------------------------------------------
# 6. ЗАКАЗЫ
# ---------------------------------------------------------------------------

@mcp.tool(
    name="get-my-orders",
    description="Мои заказы (покупки и продажи)."
)
def get_my_orders(page: int = 1) -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(lambda: _format_orders(get_client().get_my_orders(page)))


@mcp.tool(
    name="create-order",
    description=(
        "Купить/создать заказ. "
        "offer_id — ID предложения, offer_type — 'lot' или 'chip', "
        "amount — количество."
    )
)
def create_order(
    offer_id: str,
    offer_type: str = "lot",
    amount: int = 1,
    player_name: str = "",
    payment_method: str = "",
) -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(
        get_client().create_order, offer_id, offer_type, amount,
        player_name, payment_method
    )


@mcp.tool(
    name="confirm-order",
    description="Подтвердить получение заказа (освободить оплату продавцу)."
)
def confirm_order(order_id: str) -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(get_client().confirm_order, order_id)


@mcp.tool(
    name="dispute-order",
    description="Открыть спор по заказу. order_id и причина."
)
def dispute_order(order_id: str, reason: str) -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(get_client().dispute_order, order_id, reason)


@mcp.tool(
    name="cancel-order",
    description="Отменить заказ по order_id."
)
def cancel_order(order_id: str) -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(get_client().cancel_order, order_id)


# ---------------------------------------------------------------------------
# 7. ОТЗЫВЫ
# ---------------------------------------------------------------------------

@mcp.tool(
    name="get-reviews",
    description=(
        "Отзывы пользователя. user_id — ID пользователя, "
        "page — страница, filter_rating — фильтр по рейтингу (0 = все)."
    )
)
def get_reviews(user_id: str, page: int = 1, filter_rating: int = 0) -> str:
    return _safe_call(lambda: _format_reviews(
        get_client().get_user_reviews(user_id, page, filter_rating),
        user_id,
    ))


@mcp.tool(
    name="leave-review",
    description="Оставить отзыв. order_id — ID заказа, rating — 1-5, text — текст."
)
def leave_review(order_id: str, rating: int, text: str) -> str:
    err = _ensure_auth()
    if err:
        return err
    if rating < 1 or rating > 5:
        return "❌ Рейтинг должен быть от 1 до 5"
    return _safe_call(get_client().leave_review, order_id, rating, text)


# ---------------------------------------------------------------------------
# 8. ПРОФИЛЬ И НАСТРОЙКИ
# ---------------------------------------------------------------------------

@mcp.tool(
    name="update-profile",
    description="Обновить профиль: username, about (о себе), email."
)
def update_profile(
    username: str | None = None,
    about: str | None = None,
    email: str | None = None,
) -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(get_client().update_profile, username, about, email)


@mcp.tool(
    name="upload-avatar",
    description=(
        "Загрузить/сменить аватарку. "
        "image_path — абсолютный путь к файлу изображения на диске."
    )
)
def upload_avatar(image_path: str) -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(get_client().upload_avatar, image_path)


@mcp.tool(
    name="change-password",
    description="Сменить пароль. current — текущий, new — новый."
)
def change_password(current: str, new: str) -> str:
    err = _ensure_auth()
    if err:
        return err
    if len(new) < 6:
        return "❌ Пароль должен быть минимум 6 символов"
    return _safe_call(get_client().change_password, current, new)


# ---------------------------------------------------------------------------
# 9. ПОДДЕРЖКА
# ---------------------------------------------------------------------------

@mcp.tool(
    name="get-support-tickets",
    description="Мои тикеты в поддержку."
)
def get_support_tickets() -> str:
    err = _ensure_auth()
    if err:
        return err
    return _safe_call(lambda: _format_tickets(get_client().get_support_tickets()))


# =============================================================================
# ФОРМАТТЕРЫ
# =============================================================================

def _format_account(info: AccountInfo | None) -> str:
    if not info:
        return "❌ Не удалось получить информацию"
    return (
        f"👤 Имя: {info.username}\n"
        f"🆔 ID: {info.user_id}\n"
        f"💰 Баланс: {info.balance}\n"
        f"⭐ Рейтинг: {info.rating}\n"
        f"🖼 Аватарка: {info.avatar_url}"
    )


def _format_games(games: list[dict], query: str) -> str:
    if not games:
        return f"❌ Ничего не найдено по запросу '{query}'"
    lines = [f"🔍 Результаты поиска '{query}': ({len(games)})", ""]
    for g in games[:20]:
        lines.append(f"  • {g['name']}\n    {g['url']}")
    if len(games) > 20:
        lines.append(f"\n... и ещё {len(games) - 20}")
    return "\n".join(lines)


def _format_categories(categories: list, game_url: str) -> str:
    if not categories:
        return "Нет категорий"
    lines = ["📂 Категории:", ""]
    for c in categories:
        lines.append(f"  • {c.name}: {c.listings_count} объявлений")
        lines.append(f"    {c.url}")
    return "\n".join(lines)


def _format_listings(listings: list, url: str) -> str:
    if not listings:
        return "Нет объявлений."
    lines = [f"📋 {len(listings)} объявлений", ""]
    for i, l in enumerate(listings[:20], 1):
        lines.append(
            f"{i}. {l.title[:60]}"
        )
        lines.append(f"   💰 {l.price} | 📦 {l.quantity} | 🌐 {l.server}")
        lines.append(f"   👤 {l.seller} ({'★' * l.seller_rating}) отзывов: {l.seller_reviews}")
        lines.append(f"   🔗 {l.url}")
        lines.append("")
    if len(listings) > 20:
        lines.append(f"... и ещё {len(listings) - 20}")
    return "\n".join(lines)


def _format_market(result: MarketAnalysis) -> str:
    if result.total_listings == 0:
        return "❌ Нет данных для анализа."
    lines = [
        f"📊 Анализ рынка: {result.game} — {result.category}",
        f"   Проанализировано: {result.total_listings} объявлений",
        "",
        "💰 ЦЕНЫ:",
        f"   • Минимум: {result.price_min:.2f} €",
        f"   • Максимум: {result.price_max:.2f} €",
        f"   • Средняя: {result.price_avg:.2f} €",
        f"   • Медиана: {result.price_median:.2f} €",
        "",
        "🏆 ТОП-5 ПРОДАВЦОВ:",
    ]
    for i, s in enumerate(result.top_sellers[:5], 1):
        lines.append(
            f"   {i}. {s['name']} — {s['price']:.2f} € "
            f"({'★' * s['rating']}) {s['reviews']} отзывов"
        )
    lines.extend([
        "",
        "💡 РЕКОМЕНДАЦИЯ:",
        f"   {result.recommendation}",
    ])
    return "\n".join(lines)


def _format_competitors(listings: list, min_reviews: int) -> str:
    if not listings:
        return "Нет объявлений."
    sellers = {}
    for l in listings:
        if l.seller and l.seller not in sellers:
            sellers[l.seller] = {
                "name": l.seller,
                "price": l.price_value,
                "rating": l.seller_rating,
                "reviews": l.seller_reviews,
                "years": l.seller_years,
            }
    filtered = [s for s in sellers.values() if s["reviews"] >= min_reviews]
    if not filtered:
        return f"Нет конкурентов с ≥{min_reviews} отзывами. Всего: {len(sellers)}"
    filtered.sort(key=lambda x: x["reviews"], reverse=True)
    lines = [
        f"📊 Конкуренты (с ≥{min_reviews} отзывами):",
        f"   Всего: {len(sellers)}, прошло: {len(filtered)}",
        "",
    ]
    for i, s in enumerate(filtered[:15], 1):
        lines.append(
            f"{i}. {s['name']} | {s['price']:.2f} € | "
            f"{'★' * s['rating']} | {s['reviews']} отзывов | {s['years']} лет"
        )
    if len(filtered) > 15:
        lines.append(f"\n... и ещё {len(filtered) - 15}")
    return "\n".join(lines)


def _format_my_offers(offers: list) -> str:
    if not offers:
        return "Нет активных объявлений."
    lines = [f"📦 Мои объявления ({len(offers)}):", ""]
    for o in offers:
        lines.append(f"  • {o.title[:60]}")
        lines.append(f"    Цена: {o.price} | В наличии: {o.stock}")
        if o.node:
            lines.append(f"    {o.url} | node={o.node}")
        else:
            lines.append(f"    {o.url}")
        lines.append("")
    return "\n".join(lines)


def _format_schema(fields: list, node: str) -> str:
    if not fields:
        return f"❌ Нет полей для категории {node} (или нет доступа)"
    lines = [f"📋 Схема полей для категории {node}:", ""]
    for f in fields:
        lines.append(f"  • {f.label} (f-{f.id})")
        for opt in f.options[:10]:
            lines.append(f"    - {opt['label']} (value: {opt['value']})")
        if len(f.options) > 10:
            lines.append(f"    ... и ещё {len(f.options) - 10} опций")
        lines.append("")
    return "\n".join(lines)


def _format_dialogs(dialogs: list) -> str:
    if not dialogs:
        return "Нет диалогов."
    lines = ["💬 Диалоги:", ""]
    for d in dialogs:
        unread = "📩" if d.unread else "  "
        lines.append(f"  {unread} {d.user_name} (ID: {d.id})")
        lines.append(f"     {d.last_message[:80]}")
        lines.append("")
    return "\n".join(lines)


def _format_messages(messages: list, dialog_id: str) -> str:
    if not messages:
        return f"Нет сообщений в диалоге {dialog_id}."
    lines = [f"💬 Диалог {dialog_id}:", ""]
    for m in messages:
        lines.append(f"  [{m['time']}] {m['author']}:")
        lines.append(f"    {m['text']}")
        lines.append("")
    return "\n".join(lines)


def _format_orders(orders: list) -> str:
    if not orders:
        return "Нет заказов."
    lines = [f"📋 Заказы ({len(orders)}):", ""]
    for o in orders:
        lines.append(f"  • {o.title[:50]}")
        lines.append(f"    Цена: {o.price} | Статус: {o.status} | {o.created_at}")
        lines.append("")
    return "\n".join(lines)


def _format_reviews(reviews: list, user_id: str) -> str:
    if not reviews:
        return f"Нет отзывов для пользователя {user_id}."
    lines = [f"⭐ Отзывы пользователя {user_id}:", ""]
    for r in reviews[:20]:
        lines.append(f"  {'★' * r.rating}{'☆' * (5 - r.rating)} | {r.date}")
        lines.append(f"    {r.author}: {r.text[:100]}")
        lines.append("")
    if len(reviews) > 20:
        lines.append(f"... и ещё {len(reviews) - 20}")
    return "\n".join(lines)


def _format_tickets(tickets: list) -> str:
    if not tickets:
        return "Нет тикетов в поддержку."
    lines = ["🎫 Тикеты:", ""]
    for t in tickets:
        lines.append(f"  • #{t['id']}: {t['subject']} [{t['status']}]")
    return "\n".join(lines)


def _format_report(client, game_url: str, max_pages: int) -> str:
    categories = client.get_game_categories(game_url)
    analysis = client.analyze_market(game_url, max_pages=max_pages)
    cat_names = ", ".join(c.name for c in categories[:10]) if categories else "—"

    report = [
        f"📊 ОТЧЁТ ПО РЫНКУ: {analysis.game}",
        f"   Сформирован: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"📂 Категории: {cat_names}",
        f"📦 Проанализировано: {analysis.total_listings}",
        "",
        "💰 СТАТИСТИКА ЦЕН:",
        f"   Минимум: {analysis.price_min:.2f} €",
        f"   Максимум: {analysis.price_max:.2f} €",
        f"   Средняя: {analysis.price_avg:.2f} €",
        f"   Медиана: {analysis.price_median:.2f} €",
        "",
        "🏆 ТОП-5:",
    ]
    for s in analysis.top_sellers[:5]:
        report.append(
            f"   • {s['name']}: {s['price']:.2f} €, "
            f"{'★' * s['rating']}, {s['reviews']} отзывов"
        )
    report.extend([
        "",
        "💡 РЕКОМЕНДАЦИЯ:",
        f"   {analysis.recommendation}",
    ])
    return "\n".join(report)


# =============================================================================
# PROMPTS
# =============================================================================

@mcp.prompt()
def market_analyst_prompt() -> str:
    return (
        "Ты — эксперт по анализу рынка FunPay. Твоя задача:\n"
        "1. Проанализировать рынок (analyze-market)\n"
        "2. Посмотреть конкурентов (analyze-competitors)\n"
        "3. Получить рекомендацию цены (suggest-price)\n"
        "4. Предложить стратегию продавцу\n\n"
        "Всегда начинай с analyze-market!"
    )


@mcp.prompt()
def seller_assistant_prompt() -> str:
    return (
        "Ты — ассистент продавца на FunPay. Можешь:\n"
        "• Анализировать рынок и конкурентов\n"
        "• Создавать и обновлять объявления\n"
        "• Отвечать в чате покупателям\n"
        "• Управлять заказами\n"
        "• Менять настройки профиля\n\n"
        "Спрашивай у пользователя что нужно сделать."
    )


# =============================================================================
# RESOURCES
# =============================================================================

@mcp.resource(
    "funpay://market/{game_url}",
    description="Анализ рынка для игры. game_url: '/chips/8/'"
)
def market_resource(game_url: str) -> str:
    client = get_client()
    result = client.analyze_market(game_url)
    return _format_market(result)


@mcp.resource(
    "funpay://account",
    description="Информация об аккаунте (требует авторизации)"
)
def account_resource() -> str:
    client = get_client()
    if not client.is_authenticated():
        return "❌ Не авторизован"
    info = client.get_account_info()
    return _format_account(info)


# =============================================================================
# ТОЧКА ВХОДА
# =============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="FunPay MCP Server")
    parser.add_argument("--transport", type=str, default="stdio",
                        choices=["stdio", "sse", "streamable-http"])
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--cookies-file", type=str,
                        default=os.environ.get("FUNPAY_COOKIES_FILE"))
    parser.add_argument("--log-level", type=str, default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--login", action="store_true",
                        help="Войти через браузер (открывает окно Chrome)")
    args = parser.parse_args()

    logging.getLogger("funpay-mcp").setLevel(getattr(logging, args.log_level))

    # Режим входа через браузер
    if args.login:
        cookies_file = args.cookies_file or "cookies.txt"
        from .client import FunPayClient
        client = FunPayClient(cookies_file=cookies_file)
        result = client.login_via_browser()
        if result.get("success"):
            print(f"✅ Успешный вход! User ID: {result.get('user_id')}")
            print(f"📁 Куки сохранены в: {cookies_file}")
        else:
            print(f"❌ Ошибка: {result.get('error')}")
        return

    # Инициализация
    global _client
    _client = FunPayClient(
        cookies_file=args.cookies_file,
        cookies_str=os.environ.get("FUNPAY_COOKIES_STR"),
    )

    if _client.is_authenticated():
        info = _client.get_account_info()
        logger.info("✅ Авторизован как: %s", info.username if info else "Unknown")
    else:
        logger.warning("❌ Не авторизован. Укажите FUNPAY_COOKIES_FILE или FUNPAY_COOKIES_STR")
        logger.warning("   Или запустите: funpay-mcp --login")

    logger.info("🚀 Запуск FunPay MCP (%s)", args.transport)
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()

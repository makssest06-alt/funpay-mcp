"""
FunPay MCP — Модели данных
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FunPayListing:
    id: str
    title: str
    price: str
    price_value: float
    seller: str
    seller_id: str
    seller_rating: int
    seller_reviews: int
    seller_years: int
    quantity: str
    server: str
    url: str


@dataclass
class FunPayOffer:
    offer_id: str
    node: str
    title: str
    price: str
    price_raw: float
    stock: str
    status: str
    description: str
    url: str
    fields: dict = field(default_factory=dict)


@dataclass
class GameCategory:
    name: str
    url: str
    listings_count: int


@dataclass
class ChatDialog:
    id: str
    user_name: str
    user_id: str
    last_message: str
    url: str
    unread: bool


@dataclass
class Order:
    id: str
    type: str
    title: str
    price: str
    status: str
    seller: str
    buyer: str
    created_at: str
    url: str


@dataclass
class Review:
    id: str
    author: str
    rating: int
    text: str
    date: str


@dataclass
class AccountInfo:
    user_id: str
    username: str
    balance: str
    balance_raw: float
    rating: str
    rating_value: float
    avatar_url: str
    csrf_token: str


@dataclass
class MarketAnalysis:
    game: str
    category: str
    total_listings: int
    price_min: float
    price_max: float
    price_avg: float
    price_median: float
    top_sellers: list[dict]
    price_distribution: dict
    recommendation: str


@dataclass
class NodeField:
    id: str
    type: int
    label: str
    conditions: list[dict]
    options: list[dict] = field(default_factory=list)

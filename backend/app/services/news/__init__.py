"""新闻接入层：采集（provider）→ 去重入库（store）→ 窗口查询（store）。"""

from app.services.news.akshare_news import (
    ClsTelegraphProvider,
    EastmoneyBreakfastProvider,
    EastmoneyGlobalProvider,
    fetch_all_news,
)
from app.services.news.base import NewsItem, NewsProvider, fingerprint
from app.services.news.store import (
    fetch_and_store_news,
    query_news_window,
    upsert_news,
)

__all__ = [
    "ClsTelegraphProvider",
    "EastmoneyBreakfastProvider",
    "EastmoneyGlobalProvider",
    "NewsItem",
    "NewsProvider",
    "fetch_all_news",
    "fetch_and_store_news",
    "fingerprint",
    "query_news_window",
    "upsert_news",
]

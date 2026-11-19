"""AkShare 新闻源（spike 验证于 2026-10-26，akshare 1.18.94）：

- 东财全球财经快讯 stock_info_global_em：实时快讯，~200 条
- 财联社电报 stock_info_global_cls：~20 条电报，无 URL（指纹走标题回退）
- 东财财经早餐 stock_info_cjzc_em：每日 06:00 发布，含历史回填

接口字段随 AkShare 版本可能变动，单源失败仅降级该源（fetch_all_news 隔离）。
"""

import logging
from datetime import datetime

from app.services.news.base import NewsItem

logger = logging.getLogger(__name__)


def _parse_dt(text: str) -> datetime | None:
    try:
        return datetime.strptime(str(text).strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


class EastmoneyGlobalProvider:
    name = "em_global"

    def fetch(self) -> list[NewsItem]:
        import akshare as ak

        df = ak.stock_info_global_em()
        items = []
        for _, row in df.iterrows():
            dt = _parse_dt(row["发布时间"])
            if dt is None:
                continue
            items.append(
                NewsItem(
                    source=self.name,
                    title=str(row["标题"]).strip(),
                    summary=str(row["摘要"]).strip() or None,
                    url=str(row["链接"]).strip() or None,
                    published_at=dt,
                )
            )
        return items


class ClsTelegraphProvider:
    name = "cls_telegraph"

    def fetch(self) -> list[NewsItem]:
        import akshare as ak

        df = ak.stock_info_global_cls(symbol="全部")
        items = []
        for _, row in df.iterrows():
            dt = _parse_dt(f"{row['发布日期']} {row['发布时间']}")
            if dt is None:
                continue
            items.append(
                NewsItem(
                    source=self.name,
                    title=str(row["标题"]).strip(),
                    summary=str(row["内容"]).strip() or None,
                    url=None,
                    published_at=dt,
                )
            )
        return items


class EastmoneyBreakfastProvider:
    name = "em_breakfast"

    def fetch(self) -> list[NewsItem]:
        import akshare as ak

        df = ak.stock_info_cjzc_em()
        items = []
        for _, row in df.iterrows():
            dt = _parse_dt(row["发布时间"])
            if dt is None:
                continue
            items.append(
                NewsItem(
                    source=self.name,
                    title=str(row["标题"]).strip(),
                    summary=str(row["摘要"]).strip() or None,
                    url=str(row["链接"]).strip() or None,
                    published_at=dt,
                )
            )
        return items


def fetch_all_news() -> list[NewsItem]:
    """同步聚合所有源（供 asyncio.to_thread 调用）；单源失败降级不中断。"""
    items: list[NewsItem] = []
    for provider in (
        EastmoneyGlobalProvider(),
        ClsTelegraphProvider(),
        EastmoneyBreakfastProvider(),
    ):
        try:
            fetched = provider.fetch()
            items.extend(fetched)
            logger.info("新闻源 %s 抓取 %s 条", provider.name, len(fetched))
        except Exception:
            logger.exception("新闻源 %s 抓取失败，跳过", provider.name)
    return items

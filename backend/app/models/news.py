from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class FactNewsArticle(Base):
    """当日新闻池（AI 内参素材）。

    全局共享（非用户隔离）：新闻是市场级事实，去重指纹 url_hash 上
    无 URL 的源（如财联社电报）回退为 source+标题+日期 的 sha256。
    """

    __tablename__ = "fact_news_articles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1024))
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

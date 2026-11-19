from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class FactChatMessage(Base):
    """AI 问答消息（每用户一条持续会话，id 升序即对话顺序）。

    清空会话即删除该用户全部行；上下文仅取最近 MAX_HISTORY_MESSAGES 条。
    """

    __tablename__ = "fact_chat_messages"
    __table_args__ = (Index("ix_fact_chat_user", "user_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

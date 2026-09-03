"""每用户清算链的回放状态：流水变更后标记快照从哪一天起失效。

06:00 / 22:00 Job 检测到标记后自动从 dirty_from 逐日重放到目标日，
成功后清除标记；回放单事务提交，中途失败标记保留、次日重试。
"""

from datetime import date

from sqlalchemy import Date, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SysSettlementState(Base):
    __tablename__ = "sys_settlement_state"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("sys_users.id"), primary_key=True
    )
    dirty_from: Mapped[date] = mapped_column(Date, nullable=False)

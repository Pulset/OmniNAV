"""通知器统一接口：飞书 / Telegram 可任选配置，未配置时 no-op。

通知渠道按用户个人化（MultiUser §5.2）：从 user_settings 读取，不再使用全局 Settings。
"""

import logging
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserSetting

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    name: str

    async def send(
        self, title: str, sections: list[str], *, alert: bool = False
    ) -> None: ...


class NullNotifier:
    name = "null"

    async def send(
        self, title: str, sections: list[str], *, alert: bool = False
    ) -> None:
        logger.info("[通知未配置] %s\n%s", title, "\n".join(sections))


def get_user_notifiers(settings: UserSetting | None) -> list[Notifier]:
    notifiers: list[Notifier] = []
    if settings is not None:
        if settings.feishu_webhook_url:
            from app.services.notify.feishu import FeishuNotifier

            notifiers.append(FeishuNotifier(settings.feishu_webhook_url))
        if settings.telegram_bot_token and settings.telegram_chat_id:
            from app.services.notify.telegram import TelegramNotifier

            notifiers.append(
                TelegramNotifier(
                    settings.telegram_bot_token, settings.telegram_chat_id
                )
            )
    if not notifiers:
        notifiers.append(NullNotifier())
    return notifiers


async def notify_user(
    session: AsyncSession,
    user_id: int,
    title: str,
    sections: list[str],
    *,
    alert: bool = False,
) -> None:
    """向指定用户配置的通知渠道推送；未配置时记录日志。"""
    settings = await session.get(UserSetting, user_id)
    for n in get_user_notifiers(settings):
        try:
            await n.send(title, sections, alert=alert)
        except Exception:
            logger.exception("通知通道 %s 发送失败 (user=%s)", n.name, user_id)

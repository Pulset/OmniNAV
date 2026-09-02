"""通知器统一接口：飞书 / Telegram 可任选配置，未配置时 no-op。"""

import logging
from typing import Protocol

from app.core.config import get_settings

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


def get_notifiers() -> list[Notifier]:
    settings = get_settings()
    notifiers: list[Notifier] = []
    if settings.feishu_webhook_url:
        from app.services.notify.feishu import FeishuNotifier

        notifiers.append(FeishuNotifier(settings.feishu_webhook_url))
    if settings.telegram_bot_token and settings.telegram_chat_id:
        from app.services.notify.telegram import TelegramNotifier

        notifiers.append(
            TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
        )
    if not notifiers:
        notifiers.append(NullNotifier())
    return notifiers


async def notify_all(
    title: str, sections: list[str], *, alert: bool = False
) -> None:
    for n in get_notifiers():
        try:
            await n.send(title, sections, alert=alert)
        except Exception:
            logger.exception("通知通道 %s 发送失败", n.name)

"""Telegram Bot 推送通道（Markdown）。"""

import httpx


class TelegramNotifier:
    name = "telegram"
    _api = "https://api.telegram.org"

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    async def send(
        self, title: str, sections: list[str], *, alert: bool = False
    ) -> None:
        prefix = "🚨 " if alert else ""
        text = f"*{prefix}{title}*\n\n" + "\n".join(sections)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self._api}/bot{self.bot_token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
            )
            resp.raise_for_status()

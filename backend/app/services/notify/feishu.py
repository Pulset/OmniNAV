"""飞书自定义机器人 Webhook：交互式 Card 富文本卡片。"""

import httpx


class FeishuNotifier:
    name = "feishu"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send(
        self, title: str, sections: list[str], *, alert: bool = False
    ) -> None:
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "red" if alert else "blue",
                "title": {"tag": "plain_text", "content": title},
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": line}}
                for line in sections
            ]
            + [{"tag": "hr"}]
            + [
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "OmniNAV · 个人全资产净值化复盘系统",
                        }
                    ],
                }
            ],
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                self.webhook_url, json={"msg_type": "interactive", "card": card}
            )
            resp.raise_for_status()

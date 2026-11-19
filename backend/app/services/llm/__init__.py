"""LLM 接入：OpenAI 兼容 chat/completions，仅依赖 httpx。"""

from app.services.llm.client import LlmError, chat_json

__all__ = ["LlmError", "chat_json"]

"""OpenAI 兼容 LLM 客户端（httpx 直连，DeepSeek/GLM/Qwen/OpenAI 一行配置切换）。

chat_json：要求 JSON 输出并解析为 dict，供 advisor 用 Pydantic 校验。
chat_text_stream：纯文本流式输出，供问答模块逐段返回。
"""

import json
import logging
from collections.abc import AsyncIterator

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class LlmError(RuntimeError):
    pass


def extract_json(content: str) -> dict:
    """解析模型输出：裸 JSON → ```json 围栏 → 首个平衡 {...} 块，逐级回退。"""
    text = content.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise LlmError(f"LLM 输出无法解析为 JSON: {content[:200]!r}")


async def chat_json(messages: list[dict]) -> tuple[dict, dict]:
    """调用 chat/completions 并返回 (parsed_json, usage)。失败抛 LlmError。"""
    s = get_settings()
    if not (s.llm_base_url and s.llm_api_key and s.llm_model):
        raise LlmError("LLM 未配置（LLM_BASE_URL/LLM_API_KEY/LLM_MODEL）")
    payload = {
        "model": s.llm_model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        "max_tokens": s.llm_max_tokens,
    }
    headers = {"Authorization": f"Bearer {s.llm_api_key}"}
    url = f"{s.llm_base_url.rstrip('/')}/chat/completions"
    async with httpx.AsyncClient(timeout=s.llm_timeout_seconds) as client:
        resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code != 200:
        raise LlmError(f"LLM HTTP {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    try:
        content = body["choices"][0]["message"]["content"] or ""
        usage = body.get("usage") or {}
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmError(f"LLM 响应结构异常: {str(body)[:300]}") from exc
    return extract_json(content), {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


async def chat_text_stream(messages: list[dict]) -> AsyncIterator[str]:
    """流式调用 chat/completions（stream=True），逐段产出文本增量。失败抛 LlmError。

    生成器惰性执行：配置缺失/HTTP 错误在首次迭代时抛出。
    """
    s = get_settings()
    if not (s.llm_base_url and s.llm_api_key and s.llm_model):
        raise LlmError("LLM 未配置（LLM_BASE_URL/LLM_API_KEY/LLM_MODEL）")
    payload = {
        "model": s.llm_model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": s.llm_max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    headers = {"Authorization": f"Bearer {s.llm_api_key}"}
    url = f"{s.llm_base_url.rstrip('/')}/chat/completions"
    async with httpx.AsyncClient(timeout=s.llm_timeout_seconds) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise LlmError(f"LLM HTTP {resp.status_code}: {body[:300]!r}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                delta = (choices[0].get("delta") or {}).get("content") if choices else None
                if delta:
                    yield delta

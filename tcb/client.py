"""OpenAI 兼容 chat/completions 客户端(纯标准库)。

配置优先级:构造参数 > TCB_* 环境变量。
任何 OpenAI 兼容 endpoint 均可;base URL 必须显式配置,不内置任何默认值。
内置 429/5xx 指数退避重试(默认 3 次)。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    """LLM 调用失败(重试耗尽或不可重试)。"""


def _env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


class Client:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 180.0,
        max_retries: int = 3,
    ) -> None:
        self.base_url = (base_url or _env("TCB_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or _env("TCB_API_KEY")
        self.model = model or _env("TCB_MODEL")
        self.timeout = timeout
        self.max_retries = max_retries
        if not self.base_url:
            raise LLMError(
                "缺少 base URL:设置 TCB_BASE_URL(任何 OpenAI 兼容 endpoint,"
                "如 https://api.example.com/v1;或在项目根 .env 里配)"
            )
        if not self.api_key:
            raise LLMError("缺少 API Key:设置 TCB_API_KEY(或在项目根 .env 里配)")
        if not self.model:
            raise LLMError("缺少模型:设置 TCB_MODEL(或在项目根 .env 里配)")

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """一轮对话。返回 {content, tool_calls:[{id,name,arguments,raw_arguments}], usage}。"""
        payload: dict = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = [
                {"type": "function", "function": tool} for tool in tools
            ]
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            request = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:500]
                last_error = LLMError(f"HTTP {exc.code}: {detail}")
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(min(60.0, 4.0 * (2 ** (attempt - 1))))
                    continue
                raise last_error
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = LLMError(f"网络错误: {exc}")
                if attempt < self.max_retries:
                    time.sleep(4.0 * attempt)
                    continue
                raise last_error
        else:  # pragma: no cover - 循环内必 break 或 raise
            raise last_error or LLMError("unreachable")

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            raw = function.get("arguments")
            if raw is None:
                raw = "{}"
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except (ValueError, TypeError):
                arguments = {"_malformed": str(raw)[:200]}
            tool_calls.append(
                {
                    "id": call.get("id") or f"call_{len(tool_calls)}",
                    "name": function.get("name"),
                    "arguments": arguments,
                    "raw_arguments": raw if isinstance(raw, str) else json.dumps(raw),
                }
            )
        return {
            "content": message.get("content"),
            "tool_calls": tool_calls,
            "finish_reason": choice.get("finish_reason"),
            "usage": data.get("usage") or {},
        }

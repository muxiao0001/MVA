from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from ..config import validate_base_url
from ..domain.models import ModelRequest, ModelResponse, ToolCall
from ..errors import (
    ConfigurationError,
    ModelAuthenticationError,
    ModelBalanceError,
    ModelProtocolError,
    ModelRateLimitError,
    ModelRequestError,
    ModelResponseTooLargeError,
    ModelServiceError,
)


class DeepSeekClient:
    """Small OpenAI-compatible HTTP adapter; it contains no Agent logic."""

    RETRYABLE_STATUS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        timeout_seconds: float = 90.0,
        max_retries: int = 2,
        retry_base_seconds: float = 1.2,
        allow_custom_base_url: bool = False,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        self.api_key = api_key
        self.base_url = validate_base_url(base_url, allow_custom_base_url)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds
        self.max_response_bytes = max_response_bytes

    def complete(self, request: ModelRequest) -> ModelResponse:
        if not self.api_key:
            raise ConfigurationError(
                "缺少 DEEPSEEK_API_KEY；请先在环境变量中配置密钥"
            )

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                *request.messages,
            ],
            "tools": list(request.tools),
            "tool_choice": "auto",
            "thinking": {
                "type": "enabled" if request.thinking_enabled else "disabled"
            },
            "max_tokens": request.max_output_tokens,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(
                    http_request,
                    timeout=self.timeout_seconds,
                ) as response:
                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        try:
                            declared_length = int(content_length)
                        except ValueError:
                            declared_length = 0
                        if declared_length > self.max_response_bytes:
                            raise ModelResponseTooLargeError(
                                "模型响应超过允许的字节上限"
                            )
                    raw = response.read(self.max_response_bytes + 1)
                    if len(raw) > self.max_response_bytes:
                        raise ModelResponseTooLargeError(
                            "模型响应超过允许的字节上限"
                        )
                return self._parse_response(raw)
            except urllib.error.HTTPError as exc:
                error = self._http_error(exc)
                if (
                    exc.code in self.RETRYABLE_STATUS
                    and attempt < self.max_retries
                ):
                    time.sleep(self.retry_base_seconds * (2**attempt))
                    continue
                raise error from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self.max_retries:
                    time.sleep(self.retry_base_seconds * (2**attempt))
                    continue
                reason = getattr(exc, "reason", exc)
                raise ModelServiceError(
                    "无法连接 DeepSeek 服务",
                    detail=str(reason),
                ) from exc

        raise ModelServiceError("DeepSeek 请求未完成")

    @staticmethod
    def _parse_response(raw: bytes) -> ModelResponse:
        try:
            data = json.loads(raw.decode("utf-8"))
            choices = data["choices"]
            choice = choices[0]
            message = choice["message"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ModelProtocolError("模型返回了无法解析的响应") from exc

        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ModelProtocolError("模型 content 字段类型非法")

        reasoning_content = message.get("reasoning_content")
        if reasoning_content is not None and not isinstance(reasoning_content, str):
            raise ModelProtocolError("模型 reasoning_content 字段类型非法")

        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raise ModelProtocolError("模型 tool_calls 字段类型非法")

        calls: list[ToolCall] = []
        for raw_call in raw_calls:
            try:
                function = raw_call["function"]
                call_id = raw_call["id"]
                name = function["name"]
                arguments = function["arguments"]
            except (KeyError, TypeError) as exc:
                raise ModelProtocolError("模型工具调用结构不完整") from exc
            if not all(isinstance(value, str) and value for value in (call_id, name)):
                raise ModelProtocolError("模型工具调用缺少有效 id 或 name")
            if not isinstance(arguments, str):
                raise ModelProtocolError("模型工具参数必须是 JSON 字符串")
            calls.append(ToolCall(id=call_id, name=name, arguments=arguments))

        if not calls and (content is None or not content.strip()):
            raise ModelProtocolError("模型既未返回答案，也未返回工具调用")

        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            finish_reason = str(finish_reason)
        return ModelResponse(
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tuple(calls),
            finish_reason=finish_reason,
            usage=usage,
        )

    @staticmethod
    def _http_error(exc: urllib.error.HTTPError) -> Exception:
        detail = ""
        try:
            raw = exc.read(4096)
            data = json.loads(raw.decode("utf-8"))
            candidate = data.get("error", {}).get("message")
            if isinstance(candidate, str):
                detail = candidate
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            detail = ""

        if exc.code == 401:
            return ModelAuthenticationError("DeepSeek API 鉴权失败", detail=detail)
        if exc.code == 402:
            return ModelBalanceError("DeepSeek API 账户余额不足", detail=detail)
        if exc.code == 429:
            return ModelRateLimitError("DeepSeek API 请求过于频繁", detail=detail)
        if 500 <= exc.code <= 599:
            return ModelServiceError(
                f"DeepSeek 服务暂时不可用（HTTP {exc.code}）",
                detail=detail,
            )
        return ModelRequestError(
            f"DeepSeek 拒绝了请求（HTTP {exc.code}）",
            detail=detail,
        )

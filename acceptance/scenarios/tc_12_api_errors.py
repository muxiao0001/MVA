import io
import json
import urllib.error
import urllib.request

from mva.domain.models import ModelRequest
from mva.errors import (
    ModelAuthenticationError,
    ModelProtocolError,
)
from mva.model.deepseek import DeepSeekClient

from acceptance.fixtures import ScenarioEnvironment

NAME = "TC-12 API 异常"


class _FakeHttpResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.deepseek.com/chat/completions",
        status,
        "injected",
        {},
        io.BytesIO(b'{"error":{"message":"injected"}}'),
    )


def run() -> str:
    env = ScenarioEnvironment()
    try:
        missing_key_app = env.app_with_real_adapter(api_key=None)
        session = missing_key_app.sessions.create("missing-key")
        missing = missing_key_app.runtime.run(session.id, "你好")
        assert missing.status == "failed"
        assert missing.error_code == "configuration_error"

        auth_app, _ = env.app(
            [ModelAuthenticationError("鉴权失败", detail="bad key")]
        )
        auth_session = auth_app.sessions.create("bad-key")
        auth = auth_app.runtime.run(auth_session.id, "你好")
        assert auth.status == "failed"
        assert auth.error_code == "model_authentication_error"

        serialized = json.dumps(
            auth_app.traces.list(
                session_id=auth_session.id,
                run_id=auth.run_id,
            ),
            ensure_ascii=False,
        )
        assert "acceptance-test-key" not in serialized
        assert "bad key" not in serialized

        parsed = DeepSeekClient._parse_response(
            json.dumps(
                {
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "content": "",
                                "reasoning_content": "internal",
                                "tool_calls": [
                                    {
                                        "id": "call_parse",
                                        "type": "function",
                                        "function": {
                                            "name": "calculator",
                                            "arguments": '{"expression":"1+1"}',
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                    "usage": {"total_tokens": 12},
                }
            ).encode()
        )
        assert parsed.tool_calls[0].name == "calculator"
        assert parsed.reasoning_content == "internal"
        try:
            DeepSeekClient._parse_response(b"{}")
        except ModelProtocolError:
            pass
        else:
            raise AssertionError("畸形模型响应未被拒绝")

        request = ModelRequest(
            model="deepseek-v4-flash",
            system_prompt="system",
            messages=({"role": "user", "content": "hello"},),
            tools=(),
        )
        response_body = json.dumps(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "ok"},
                    }
                ]
            }
        ).encode()
        original_urlopen = urllib.request.urlopen
        attempts = 0

        def retry_once(http_request, timeout):
            nonlocal attempts
            del http_request, timeout
            attempts += 1
            if attempts == 1:
                raise _http_error(503)
            return _FakeHttpResponse(response_body)

        try:
            urllib.request.urlopen = retry_once
            client = DeepSeekClient(
                api_key="acceptance-key",
                base_url="https://api.deepseek.com",
                max_retries=1,
                retry_base_seconds=0.001,
            )
            retried = client.complete(request)
            assert retried.content == "ok"
            assert attempts == 2

            attempts = 0

            def reject_auth(http_request, timeout):
                nonlocal attempts
                del http_request, timeout
                attempts += 1
                raise _http_error(401)

            urllib.request.urlopen = reject_auth
            try:
                client.complete(request)
            except ModelAuthenticationError:
                pass
            else:
                raise AssertionError("401 未被分类为鉴权失败")
            assert attempts == 1
        finally:
            urllib.request.urlopen = original_urlopen

        return "API 配置、鉴权、协议和有限重试均验证，trace 未泄露密钥。"
    finally:
        env.close()

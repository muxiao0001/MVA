import json

from mva.errors import (
    ModelAuthenticationError,
    ModelProtocolError,
)
from mva.model.deepseek import DeepSeekClient

from acceptance.fixtures import ScenarioEnvironment

NAME = "TC-12 API 异常"


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

        return "API 配置/鉴权/协议异常均分类终止，trace 未泄露密钥。"
    finally:
        env.close()

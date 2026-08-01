from mva.domain.models import ModelRequest

from acceptance.fixtures import ScenarioEnvironment, direct_response

NAME = "TC-06 普通追问"


def run() -> str:
    env = ScenarioEnvironment()
    try:
        def followup(request: ModelRequest):
            contents = [item.get("content") for item in request.messages]
            assert "我的代号是蓝鲸。" in contents
            assert "记住了，你的代号是蓝鲸。" in contents
            return direct_response("你刚才说你的代号是蓝鲸。")

        app, _ = env.app(
            [
                direct_response("记住了，你的代号是蓝鲸。"),
                followup,
            ]
        )
        session = app.sessions.create("followup")
        assert app.runtime.run(session.id, "我的代号是蓝鲸。").status == "succeeded"
        result = app.runtime.run(session.id, "我的代号是什么？")
        assert result.status == "succeeded"
        assert "蓝鲸" in (result.answer or "")
        return "第二轮请求携带了同一 session 的前文。"
    finally:
        env.close()


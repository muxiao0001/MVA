import json
import os
import subprocess
import sys
from pathlib import Path

from acceptance.fixtures import ScenarioEnvironment

NAME = "TC-04 Todo 持久化"

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_probe(database_path: Path, source: str, *arguments: str) -> dict:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(PROJECT_ROOT / "src"), str(PROJECT_ROOT))
    )
    completed = subprocess.run(
        [sys.executable, "-c", source, str(database_path), *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(completed.stdout)


CREATE_AND_ADD = r"""
import json
import sys
from pathlib import Path

from acceptance.fixtures import direct_response, tool_response
from acceptance.fixtures.fixed_model import FixedModelClient
from mva.bootstrap import build_application
from mva.config import Settings

client = FixedModelClient([
    tool_response(
        "call_add",
        "todo",
        '{"operation":"add","content":"周五提交周报"}',
    ),
    direct_response("已新增待办。"),
])
settings = Settings(
    api_key="acceptance-test-key",
    base_url="https://api.deepseek.com",
    model="deepseek-v4-flash",
    database_path=Path(sys.argv[1]),
    api_max_retries=0,
    api_retry_base_seconds=0.001,
    model_timeout_seconds=1,
)
app = build_application(settings, model_client=client)
session = app.sessions.create("todo-persist")
result = app.runtime.run(session.id, "记下周五提交周报")
print(json.dumps({"session_id": session.id, "status": result.status}))
"""


RESTART_AND_LIST = r"""
import json
import sys
from pathlib import Path

from acceptance.fixtures import direct_response, tool_response
from acceptance.fixtures.fixed_model import FixedModelClient
from mva.bootstrap import build_application
from mva.config import Settings

client = FixedModelClient([
    tool_response("call_list", "todo", '{"operation":"list"}'),
    direct_response("当前有一项待办：周五提交周报。"),
])
settings = Settings(
    api_key="acceptance-test-key",
    base_url="https://api.deepseek.com",
    model="deepseek-v4-flash",
    database_path=Path(sys.argv[1]),
    api_max_retries=0,
    api_retry_base_seconds=0.001,
    model_timeout_seconds=1,
)
app = build_application(settings, model_client=client)
session_id = sys.argv[2]
result = app.runtime.run(session_id, "查看待办")
todos = [todo.content for todo in app.todos.list(session_id)]
tool_messages = [
    message
    for message in app.messages.load_after(session_id, 0)
    if message.role == "tool" and message.tool_name == "todo"
]
latest = json.loads(tool_messages[-1].content or "{}")
print(json.dumps({
    "status": result.status,
    "todos": todos,
    "listed_count": latest["output"]["count"],
}, ensure_ascii=False))
"""


def run() -> str:
    env = ScenarioEnvironment()
    try:
        created = _run_probe(env.database_path, CREATE_AND_ADD)
        assert created["status"] == "succeeded"

        restored = _run_probe(
            env.database_path,
            RESTART_AND_LIST,
            created["session_id"],
        )
        assert restored["status"] == "succeeded"
        assert restored["todos"] == ["周五提交周报"]
        assert restored["listed_count"] == 1
        return "两个独立 Python 进程间恢复 session，并读取持久化待办。"
    finally:
        env.close()

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ..bootstrap import Application, build_application
from ..config import Settings
from ..errors import MVAError
from .presenter import (
    present_run,
    present_sessions,
    present_traces,
    sanitize_terminal_text,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mva",
        description="最小可用 Agent：原生 Tool Calls + SQLite session",
    )
    subparsers = parser.add_subparsers(dest="command")

    new_parser = subparsers.add_parser("new", help="创建 session 并进入对话")
    new_parser.add_argument("--title", help="可选 session 标题")
    new_parser.add_argument(
        "--no-chat",
        action="store_true",
        help="仅创建，不进入交互",
    )

    chat_parser = subparsers.add_parser("chat", help="恢复指定 session")
    chat_parser.add_argument("session_id")

    subparsers.add_parser("sessions", help="列出可恢复 session")

    trace_parser = subparsers.add_parser("traces", help="查看脱敏 trace")
    trace_parser.add_argument("session_id")
    trace_parser.add_argument("--run", dest="run_id", help="只查看指定 run")
    return parser


def interactive_chat(app: Application, session_id: str) -> None:
    session = app.sessions.resume(session_id)
    print(f"已进入 session {session.id}。输入 /exit 退出，/help 查看帮助。")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return
        if not text:
            continue
        if text == "/exit":
            print("已退出。")
            return
        if text == "/help":
            print("/exit 退出当前对话；每条普通文本都会启动一次 Agent run。")
            continue
        try:
            result = app.runtime.run(session.id, text)
        except MVAError as exc:
            print(
                f"错误 [{sanitize_terminal_text(exc.code)}]："
                f"{sanitize_terminal_text(exc.message)}",
                file=sys.stderr,
            )
            continue
        print(present_run(result))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        app = build_application(Settings.from_env())
        if args.command == "sessions":
            print(present_sessions(app.sessions.list()))
            return 0
        if args.command == "traces":
            app.sessions.get(args.session_id)
            print(
                present_traces(
                    app.traces.list(
                        session_id=args.session_id,
                        run_id=args.run_id,
                    )
                )
            )
            return 0
        if args.command == "chat":
            interactive_chat(app, args.session_id)
            return 0
        if args.command == "new":
            session = app.sessions.create(args.title)
            print(f"已创建 session: {session.id}")
            if not args.no_chat:
                interactive_chat(app, session.id)
            return 0

        session = app.sessions.create()
        print(f"已创建 session: {session.id}")
        interactive_chat(app, session.id)
        return 0
    except MVAError as exc:
        print(
            f"错误 [{sanitize_terminal_text(exc.code)}]："
            f"{sanitize_terminal_text(exc.message)}",
            file=sys.stderr,
        )
        return 2
    except ValueError as exc:
        print(f"错误：{sanitize_terminal_text(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

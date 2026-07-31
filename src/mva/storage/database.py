from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..errors import StorageError
from .schema import SCHEMA_SQL, SCHEMA_VERSION


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                self.path,
                timeout=10,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            return connection
        except sqlite3.Error as exc:
            raise StorageError("无法连接本地数据库", detail=str(exc)) from exc

    def initialize(self) -> None:
        try:
            missing_directories: list[Path] = []
            candidate = self.path.parent
            while not candidate.exists():
                missing_directories.append(candidate)
                candidate = candidate.parent
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            for directory in reversed(missing_directories):
                os.chmod(directory, 0o700)
            if self.path.is_symlink():
                raise StorageError("拒绝使用符号链接作为数据库文件")
            with self.transaction() as connection:
                connection.executescript(SCHEMA_SQL)
                row = connection.execute(
                    "SELECT version FROM schema_meta LIMIT 1"
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO schema_meta(version) VALUES (?)",
                        (SCHEMA_VERSION,),
                    )
                elif int(row["version"]) != SCHEMA_VERSION:
                    raise StorageError(
                        "数据库 Schema 版本不兼容",
                        detail=f"expected={SCHEMA_VERSION}, actual={row['version']}",
                    )
            os.chmod(self.path, 0o600)
        except OSError as exc:
            raise StorageError(
                "无法创建数据库或收紧文件权限",
                detail=str(exc),
            ) from exc

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        except sqlite3.Error as exc:
            raise StorageError("数据库读取失败", detail=str(exc)) from exc
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except StorageError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise StorageError("数据库事务失败", detail=str(exc)) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

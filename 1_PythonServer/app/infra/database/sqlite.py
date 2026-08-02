# SQLite 连接与事务管理
# 提供数据库连接工厂、连接上下文管理器和事务上下文管理器

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3


def connect_database(database_path: Path) -> sqlite3.Connection:
    """创建 SQLite 连接，启用外键约束和忙等待超时"""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextmanager
def database_connection(database_path: Path) -> Iterator[sqlite3.Connection]:
    """数据库连接上下文管理器：自动关闭连接"""
    connection = connect_database(database_path)
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def database_transaction(database_path: Path) -> Iterator[sqlite3.Connection]:
    """数据库事务上下文管理器：成功时 COMMIT，异常时 ROLLBACK"""
    connection = connect_database(database_path)
    try:
        connection.execute("BEGIN")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

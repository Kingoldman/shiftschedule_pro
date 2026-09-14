"""轻量数据库迁移

为什么需要它：SQLAlchemy 的 `create_all()` 只会创建**不存在**的表，
既不会给已有表补列，也不会修改已有表的约束。本项目的两处改动都触碰了这个边界：

1. 新增列：`schedule.version`、`admin.token_version`
   —— 老库没有这两列，直接查询会报 "no such column"。
2. 修改约束：`employee_state_log` 原本声明了
   `FOREIGN KEY(employee_id) REFERENCES employee(id) ON DELETE CASCADE`。
   现在该表改为「留档表」，要求删除员工时日志保留。但老库的建表语句里
   外键约束已经固化，光改 Python 模型对已有数据库无效 ——
   一旦启用 `PRAGMA foreign_keys=ON`，删除员工仍会连带删掉日志。
   SQLite 不支持 ALTER CONSTRAINT，只能重建表。

这里用最小代价处理：每次启动时检查，缺什么补什么，全部幂等（可重复执行）。
如果日后结构演进变复杂，建议换成 Alembic。
"""
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import Base, engine

logger = logging.getLogger(__name__)

# 需要补齐的列：{表名: [(列名, 列定义 SQL, 默认值)]}
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "schedule": [
        ("version", "ALTER TABLE schedule ADD COLUMN version INTEGER NOT NULL DEFAULT 1"),
    ],
    "admin": [
        (
            "token_version",
            "ALTER TABLE admin ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1",
        ),
    ],
    "employee_account": [
        (
            "feed_token",
            "ALTER TABLE employee_account ADD COLUMN feed_token VARCHAR(64)",
        ),
        (
            "feed_token_created_at",
            "ALTER TABLE employee_account ADD COLUMN feed_token_created_at DATETIME",
        ),
    ],
}


def _table_exists(db: Session, table: str) -> bool:
    row = db.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table},
    ).first()
    return row is not None


def _existing_columns(db: Session, table: str) -> set[str]:
    rows = db.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


def _add_missing_columns(db: Session) -> None:
    for table, columns in _ADDED_COLUMNS.items():
        if not _table_exists(db, table):
            continue
        existing = _existing_columns(db, table)
        for col, ddl in columns:
            if col in existing:
                continue
            db.execute(text(ddl))
            logger.info("迁移：表 %s 已补充列 %s", table, col)


def _ensure_feed_token_index(db: Session) -> None:
    """为老库的 employee_account 补上 feed_token 唯一索引

    新建表时 `unique=True` 会内联进 CREATE TABLE；但 ALTER TABLE ADD COLUMN
    无法追加唯一约束，只能补一个独立索引。SQLite 的唯一索引允许多个 NULL，
    所以"尚未开通订阅"的员工（feed_token 为空）不会互相冲突。
    """
    if not _table_exists(db, "employee_account"):
        return
    if "feed_token" not in _existing_columns(db, "employee_account"):
        return
    db.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_employee_account_feed_token "
            "ON employee_account (feed_token)"
        )
    )


def _has_foreign_key(db: Session, table: str) -> bool:
    rows = db.execute(text(f"PRAGMA foreign_key_list({table})")).fetchall()
    return len(rows) > 0


def _rebuild_state_log_without_fk(db: Session) -> None:
    """重建 employee_state_log，去掉外键约束，使其真正成为留档表

    SQLite 不支持直接删除/修改外键约束，标准做法是：
    建新表 → 拷数据 → 删旧表 → 重命名 → 重建索引。

    注意：`PRAGMA foreign_keys` 在事务内部是空操作（SQLite 明确规定），
    而 SQLAlchemy Session 默认处于事务中，所以在 Session 里关外键是无效的。
    这里改用 engine.raw_connection() 走 autocommit 连接执行，确保 PRAGMA 生效。
    """
    table = "employee_state_log"
    if not _table_exists(db, table):
        return
    if not _has_foreign_key(db, table):
        return  # 已经是新结构，跳过

    logger.info("迁移：重建 %s 以移除外键约束（改为留档表）", table)
    conn = engine.raw_connection()
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.execute(
            """
            CREATE TABLE employee_state_log__new (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER,
                employee_name VARCHAR(255) NOT NULL,
                old_state INTEGER NOT NULL,
                new_state INTEGER NOT NULL,
                changed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            INSERT INTO employee_state_log__new
                (id, employee_id, employee_name, old_state, new_state, changed_at)
            SELECT id, employee_id, employee_name, old_state, new_state, changed_at
            FROM employee_state_log
            """
        )
        cur.execute("DROP TABLE employee_state_log")
        cur.execute("ALTER TABLE employee_state_log__new RENAME TO employee_state_log")
        cur.execute(
            "CREATE INDEX ix_employee_state_log_employee_id "
            "ON employee_state_log (employee_id)"
        )
        conn.commit()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
        logger.info("迁移：%s 重建完成，历史日志已保留", table)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_migrations(db: Session) -> None:
    """启动时执行：建新表 + 补列 + 按需重建日志表。全部幂等。"""
    # 1. 创建新表（audit_log 等），已存在的表不受影响
    Base.metadata.create_all(bind=engine)

    # 2. 补齐新增列
    _add_missing_columns(db)
    _ensure_feed_token_index(db)

    # 3. 日志表去外键
    _rebuild_state_log_without_fk(db)

    db.commit()

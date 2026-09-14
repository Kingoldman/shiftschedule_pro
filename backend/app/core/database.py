"""数据库连接与 Session 管理

使用 SQLAlchemy 2.0 风格，通过 declarative_base 暴露统一的 Base 给模型继承。
每个请求使用独立的 Session，由 FastAPI 依赖注入管理生命周期。
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# SQLite 需要额外参数以支持跨线程访问
# - check_same_thread=False：允许多线程复用连接
# - timeout=30：写锁冲突时最多等待 30 秒再报错（默认 5 秒，并发下易 "database is locked"）
connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if settings.DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False,  # 设为 True 可打印 SQL 调试
)


if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_conn, conn_record):  # noqa: ANN001, ANN202
        """每个 SQLite 连接建立时执行 PRAGMA

        两点必要性：
        1. foreign_keys=ON —— SQLite 默认关闭外键约束，不显式开启则模型里声明的
           ON DELETE CASCADE / SET NULL 全部不生效（例如删除组时 employee.group_id 不会置空）。
        2. journal_mode=WAL —— 读写不互相阻塞，显著降低并发下的锁冲突。

        注意：EmployeeStateLog 是有意设计的「留档表」，已去除外键级联约束，
        因此开启 foreign_keys 不会导致删除员工时连带删除其历史日志。
        """
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI 依赖：每个请求获取独立数据库 Session，请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

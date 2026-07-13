"""数据库连接与 Session 管理

使用 SQLAlchemy 2.0 风格，通过 declarative_base 暴露统一的 Base 给模型继承。
每个请求使用独立的 Session，由 FastAPI 依赖注入管理生命周期。
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# SQLite 需要额外参数以支持跨线程访问
connect_args = (
    {"check_same_thread": False}
    if settings.DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False,  # 设为 True 可打印 SQL 调试
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI 依赖：每个请求获取独立数据库 Session，请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

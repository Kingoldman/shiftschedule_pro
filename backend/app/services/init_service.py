"""初始化服务

首次启动时自动建表，并创建默认管理员账号。
默认账号：admin / admin123，登录后请立即修改密码。
"""
from sqlalchemy.orm import Session

from app.core.database import Base, engine, SessionLocal
from app.core.security import hash_password
from app.models.admin import Admin


def init_database() -> None:
    """建表 + 初始化默认管理员"""
    # 创建所有表
    Base.metadata.create_all(bind=engine)

    # 创建默认管理员（如果不存在）
    db = SessionLocal()
    try:
        admin = db.query(Admin).filter(Admin.username == "admin").first()
        if not admin:
            admin = Admin(
                username="admin",
                hashed_password=hash_password("admin123"),
            )
            db.add(admin)
            db.commit()
            print("=" * 50)
            print("已创建默认管理员账号:")
            print("  用户名: admin")
            print("  密码: admin123")
            print("  登录后请立即修改密码！")
            print("=" * 50)
    finally:
        db.close()

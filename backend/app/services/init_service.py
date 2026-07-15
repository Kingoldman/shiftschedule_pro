"""初始化服务

首次启动时自动建表，并创建默认管理员账号。
默认账号：admin，密码通过 INIT_ADMIN_PASSWORD 环境变量指定，
未设置则随机生成并打印一次到日志。
"""
import logging

from app.core.database import Base, engine, SessionLocal
from app.core.config import settings
from app.core.security import hash_password
from app.models.admin import Admin

logger = logging.getLogger(__name__)


def init_database() -> None:
    """建表 + 初始化默认管理员"""
    # 创建所有表
    Base.metadata.create_all(bind=engine)

    # 创建默认管理员（如果不存在）
    db = SessionLocal()
    try:
        admin = db.query(Admin).filter(Admin.username == "admin").first()
        if not admin:
            # 密码来自 settings（环境变量优先，否则启动时随机生成）
            password = settings.INIT_ADMIN_PASSWORD
            admin = Admin(
                username="admin",
                hashed_password=hash_password(password),
            )
            db.add(admin)
            db.commit()
            logger.warning("=" * 60)
            logger.warning("已创建默认管理员账号:")
            logger.warning("  用户名: admin")
            logger.warning("  密码: %s", password)
            logger.warning("  请登录后立即修改密码！")
            logger.warning("  （后续可通过 INIT_ADMIN_PASSWORD 环境变量预设密码）")
            logger.warning("=" * 60)
    finally:
        db.close()

"""员工自助登录账号

设计要点：
- 与 `Employee` 分表：员工是排班业务对象（会被排班快照引用、删人后仍需留档统计），
  而账号只是访问凭据，随员工删除而失效，两者生命周期不同，不应混在一张表里。
- `token_version` 与 Admin 同款机制：改密后自增，使此前签发的所有 JWT 立即失效。
- `employee_id` 使用 ON DELETE CASCADE，删除员工时账号自动清理，不留孤儿凭据。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EmployeeAccount(Base):
    __tablename__ = "employee_account"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employee.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        comment="对应员工",
    )
    username: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    # 令牌版本号：改密/重置密码时 +1，使旧 Token 立即失效
    token_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # 停用后无法登录，但账号与历史审计保留
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 日历订阅令牌：日历客户端（iOS/Google/Outlook）无法携带 Cookie 或 Authorization 头，
    # 只能把凭据放在 URL 里，因此单独发放一个长期令牌，与登录密码解耦。
    # 为空表示未开启订阅；重新生成或注销后旧链接立即失效。
    feed_token: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    feed_token_created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # passive_deletes：删员工时交给数据库的 ON DELETE CASCADE 处理。
    # 否则 SQLAlchemy 会先把 employee_id 置 NULL，而该列是 NOT NULL，反而报错。
    employee: Mapped["Employee"] = relationship(passive_deletes=True)

"""操作审计日志

记录管理员对系统的关键写操作（组/员工的增删与调整、排班的生成与保存等），
用于事后追溯"谁在什么时间改了什么"。

与 EmployeeStateLog 的区别：
- EmployeeStateLog 记录的是「员工/组这条数据本身的变化」，是业务留档；
- AuditLog 记录的是「管理员的一次操作动作」，是操作留档。
  在此之前组相关事件被硬塞进 EmployeeStateLog（用 employee_id=0 标记），
  语义混乱且无法记录操作者，这里拆开。

注意：本表同样是留档性质，不设外键，也不参与统计。
"""
from datetime import datetime

from sqlalchemy import String, DateTime, Text, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 操作者用户名（冗余存储，管理员被删除后仍可追溯）
    actor: Mapped[str] = mapped_column(String(30), default="", comment="操作者")
    # 操作类型：create/update/delete/import/sort/lock/unlock/login/logout 等
    action: Mapped[str] = mapped_column(String(30), index=True, comment="操作类型")
    # 操作对象类型：group/employee/schedule/day_info/auth
    target_type: Mapped[str] = mapped_column(String(30), default="", comment="对象类型")
    # 操作对象标识：如 "2026-07"、"group:3"、"employee:12"
    target_id: Mapped[str] = mapped_column(String(50), default="", comment="对象标识")
    # 人类可读的描述
    detail: Mapped[str | None] = mapped_column(Text, nullable=True, comment="操作描述")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

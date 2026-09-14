"""员工状态变更日志（留档表）

记录员工值班状态、分组、排序的每次变更，用于事后追溯"某个人什么时候被怎么调整过"。

【设计约定：这是一张留档表，不是业务关联表】
- 员工被删除后其历史日志必须保留，因此 employee_id 不设外键约束。
  原先的 ondelete="CASCADE" 在启用 SQLite 外键后会被数据库连带删除，与留档目标冲突。
- employee_name 冗余存储且加长到 255：既保证员工记录消失后仍可读懂日志，
  也避免迁移到 PostgreSQL/MySQL 时因长度不足报错（原 String(10) 实际写入远超 10 字）。
- 本表仅用于查询与追溯，**不参与任何统计计算**。
"""
from datetime import datetime
from sqlalchemy import Integer, String, DateTime, Index, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class EmployeeStateLog(Base):
    __tablename__ = "employee_state_log"
    __table_args__ = (Index("ix_employee_state_log_employee_id", "employee_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 故意不设 ForeignKey：员工删除后日志需保留
    # 组级别日志（新建组/组排序/组更名/删除组）约定使用 employee_id = 0
    employee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employee_name: Mapped[str] = mapped_column(String(255))
    old_state: Mapped[int] = mapped_column(Integer, comment="变更前状态 0不值班 1值班")
    new_state: Mapped[int] = mapped_column(Integer, comment="变更后状态 0不值班 1值班")
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

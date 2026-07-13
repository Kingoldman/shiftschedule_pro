"""员工模型

员工是排班的最小单位，归属于一个值班组。
state=1 表示参与值班，state=0 表示不参与（如请假、离职）。
只保留最必要的字段。
"""
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Employee(Base):
    __tablename__ = "employee"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(10), comment="姓名")
    # 组内排序号，用于组内展示顺序
    order_id: Mapped[int] = mapped_column(Integer, default=1, comment="组内排序")
    # 是否参与值班：1=值班 0=不值班
    state: Mapped[int] = mapped_column(Integer, default=1, comment="是否参与值班")
    # 所属组：删除组时置空
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("shift_group.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    group: Mapped["ShiftGroup | None"] = relationship(back_populates="employees")

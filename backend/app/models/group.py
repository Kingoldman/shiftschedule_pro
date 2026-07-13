"""值班组模型

组的概念用于把员工编组，排班时按组轮转。
order_id 决定轮转顺序，由前端拖拽后整体更新。
"""
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ShiftGroup(Base):
    __tablename__ = "shift_group"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(20), unique=True, comment="组名称")
    # 排序号：决定轮转顺序，1 开始
    order_id: Mapped[int] = mapped_column(Integer, default=1, comment="轮转顺序")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    # 关联员工：删除组时员工外键置空（由 API 层显式处理）
    employees: Mapped[list["Employee"]] = relationship(
        back_populates="group", passive_deletes=True
    )

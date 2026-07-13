"""排班记录模型

每月一条记录，schedule_json 存储该月的完整排班数据。
JSON 结构示例：
[
  {
    "date": "2026-07-01",
    "day_type": "workday",
    "group_id": 1,
    "group_name": "一组",
    "employees": [{"id":1,"name":"张三"}, {"id":2,"name":"李四"}]
  },
  ...
]

group_snapshot: 保存时的组/员工快照，确保历史统计不受后续人员变动影响。
locked: 锁定后不可修改排班，防止误操作。
"""
from datetime import datetime

from sqlalchemy import Integer, Boolean, DateTime, UniqueConstraint, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Schedule(Base):
    __tablename__ = "schedule"
    __table_args__ = (UniqueConstraint("year", "month", name="uq_schedule_year_month"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer)
    # 月度排班 JSON 数据
    schedule_json: Mapped[list] = mapped_column(JSON, default=list)
    # 保存时的组/员工快照，用于历史统计
    # 结构: {"groups": [{"id":1, "name":"张三李四", "order_id":1, "employees": [...]}],
    #        "state_logs": [...]}
    group_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 锁定标志：True 时不允许修改排班
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

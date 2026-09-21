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
    # 生成该月排班时的起始组，保存后需原样回显
    # 早期版本没有这一列（老库为 NULL），读取时会从 schedule_json 反推
    start_group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 保存时的组/员工快照，用于历史统计
    # 结构: {"groups": [{"id":1, "name":"张三李四", "order_id":1, "employees": [...]}],
    #        "state_logs": [...]}
    group_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 锁定标志：True 时不允许修改排班
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    # 乐观锁版本号：每次保存 +1。客户端提交 expected_version，
    # 与库中不一致说明期间被他人改过，返回 409 避免静默覆盖
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

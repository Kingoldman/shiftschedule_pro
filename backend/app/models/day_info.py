"""每日信息模型

合并了原系统中的 whyDay / Holiday / VacationDay 三张表。
day_type 字段用一个枚举字符串表示日期性质，互斥设计：
  - workday: 普通工作日
  - weekend: 周末
  - holiday: 法定节假日
  - vacation: 调休日（即周末调休成工作日）

这样查询和统计都极其简单：按 day_type 分组即可。
"""
from datetime import date, datetime

from sqlalchemy import String, Date, DateTime, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# 日期性质枚举常量，前端也使用同样的值
DAY_TYPE_WORKDAY = "workday"
DAY_TYPE_WEEKEND = "weekend"
DAY_TYPE_HOLIDAY = "holiday"
DAY_TYPE_VACATION = "vacation"

ALL_DAY_TYPES = (
    DAY_TYPE_WORKDAY,
    DAY_TYPE_WEEKEND,
    DAY_TYPE_HOLIDAY,
    DAY_TYPE_VACATION,
)


class DayInfo(Base):
    __tablename__ = "day_info"
    __table_args__ = (UniqueConstraint("date", name="uq_day_info_date"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, index=True, comment="日期")
    # 日期性质：workday/weekend/holiday/vacation
    day_type: Mapped[str] = mapped_column(
        String(10), default=DAY_TYPE_WORKDAY, comment="日期性质"
    )
    # 备注：如"春节假期第1天"，方便查看
    remark: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="备注")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

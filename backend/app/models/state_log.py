"""员工状态变更日志

记录员工值班状态的每次变更，用于统计"有效值班天数"。
例如：A 在7月1-15日不值班、16-31日值班，则7月有效值班天数为16天。
"""
from datetime import datetime
from sqlalchemy import Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class EmployeeStateLog(Base):
    __tablename__ = "employee_state_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employee.id", ondelete="CASCADE"), index=True
    )
    employee_name: Mapped[str] = mapped_column(String(10))
    old_state: Mapped[int] = mapped_column(Integer, comment="变更前状态 0不值班 1值班")
    new_state: Mapped[int] = mapped_column(Integer, comment="变更后状态 0不值班 1值班")
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

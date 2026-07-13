"""排班 Schema"""
from datetime import date
from pydantic import BaseModel, Field, ConfigDict


class ScheduleItemEmployee(BaseModel):
    """排班项中的员工信息"""
    id: int
    name: str


class ScheduleItem(BaseModel):
    """单日排班"""
    date: date
    day_type: str
    holiday_name: str | None = None
    group_id: int | None = None
    group_name: str | None = None
    employees: list[ScheduleItemEmployee] = []


class ScheduleItemIn(ScheduleItem):
    """保存时的单日排班：date 用字符串，避免 datetime.date JSON 序列化报错"""
    date: str


class ScheduleSave(BaseModel):
    """保存月度排班"""
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    schedule: list[ScheduleItemIn]


class ScheduleGenerate(BaseModel):
    """生成排班请求

    start_group_id: 从哪个组开始轮转
    start_date: 轮转起始日期（含）
    days: 需要排班的天数列表（已过滤掉不值班的日子）
    """
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    start_group_id: int
    start_date: date
    days: list[date]


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    year: int
    month: int
    schedule_json: list
    group_snapshot: dict | None = None
    locked: bool = False

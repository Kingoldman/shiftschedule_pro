"""日期信息 Schema"""
from datetime import date
from pydantic import BaseModel, Field, ConfigDict

from app.models.day_info import ALL_DAY_TYPES


class DayInfoBatchItem(BaseModel):
    """批量更新中的单条"""
    date: date
    day_type: str = Field(..., pattern=f"^({'|'.join(ALL_DAY_TYPES)})$")
    remark: str | None = Field(None, max_length=50)


class DayInfoBatchUpdate(BaseModel):
    """批量更新日期性质

    用于"框选一段日期 → 设为节假日"这样的批量操作。
    """
    items: list[DayInfoBatchItem]


class DayInfoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    day_type: str
    remark: str | None = None

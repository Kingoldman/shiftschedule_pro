"""值班组 Schema"""
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class GroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=20)
    order_id: int = Field(1, ge=1)


class GroupCreate(GroupBase):
    pass


class GroupUpdate(BaseModel):
    """更新时所有字段可选"""
    name: str | None = Field(None, min_length=1, max_length=20)
    order_id: int | None = Field(None, ge=1)


class GroupBatchSort(BaseModel):
    """批量调整排序，前端拖拽后整体提交"""
    items: list[dict] = Field(..., description="[{id:1,order_id:1}, ...]")


class GroupOut(BaseModel):
    """组信息（含成员数量）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    order_id: int
    employee_count: int = 0
    created_at: datetime | None = None

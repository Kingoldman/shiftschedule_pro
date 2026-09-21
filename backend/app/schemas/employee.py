"""员工 Schema"""
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class EmployeeBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=10)
    order_id: int = Field(1, ge=1)
    state: int = Field(1, ge=0, le=1)
    group_id: int | None = None


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    """更新时所有字段可选，group_id 可显式传 null 清除分组"""
    name: str | None = Field(None, min_length=1, max_length=10)
    order_id: int | None = Field(None, ge=1)
    state: int | None = Field(None, ge=0, le=1)
    group_id: int | None = None


class EmployeeBatchSort(BaseModel):
    """批量调整排序/分组"""
    items: list[dict]


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    order_id: int
    state: int
    group_id: int | None = None
    group_name: str | None = None
    created_at: datetime | None = None


class EmployeeAccountIn(BaseModel):
    """开通/修改员工自助账号

    三个字段都可选，便于"只重置密码"或"只停用"这类局部操作。
    """
    username: str | None = Field(None, min_length=2, max_length=30)
    password: str | None = Field(None, min_length=6, max_length=64)
    is_active: bool | None = None


class EmployeeAccountOut(BaseModel):
    """员工账号状态"""
    exists: bool
    employee_id: int
    employee_name: str | None = None
    username: str | None = None
    is_active: bool | None = None
    last_login_at: datetime | None = None

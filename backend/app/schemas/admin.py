"""管理员相关 Schema"""
from pydantic import BaseModel, Field


class AdminLogin(BaseModel):
    """登录请求"""
    username: str = Field(..., min_length=1, max_length=30)
    password: str = Field(..., min_length=1, max_length=64)


class Token(BaseModel):
    """登录响应"""
    access_token: str
    token_type: str = "bearer"


class AdminOut(BaseModel):
    """管理员信息"""
    id: int
    username: str

    model_config = {"from_attributes": True}

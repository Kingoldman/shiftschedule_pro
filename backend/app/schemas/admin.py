"""管理员相关 Schema"""
from pydantic import BaseModel, Field


class AdminLogin(BaseModel):
    """登录请求"""
    username: str = Field(..., min_length=1, max_length=30)
    password: str = Field(..., min_length=1, max_length=64)


class Token(BaseModel):
    """登录响应

    role 用于前端决定跳转到管理页还是「我的值班」。
    真正的权限判定在后端，前端拿到 role 只是为了渲染正确的菜单。
    """
    access_token: str
    token_type: str = "bearer"
    role: str = "admin"
    username: str = ""


class MeOut(BaseModel):
    """当前登录者信息（管理员与员工共用）"""
    role: str
    username: str
    # 仅员工角色有值
    employee_id: int | None = None
    employee_name: str | None = None


class ChangePassword(BaseModel):
    """修改密码请求"""
    old_password: str = Field(..., min_length=1, max_length=64)
    # 上限 64：bcrypt 只取前 72 字节，超长中文密码会被静默截断
    new_password: str = Field(..., min_length=6, max_length=64)


class AdminOut(BaseModel):
    """管理员信息"""
    id: int
    username: str

    model_config = {"from_attributes": True}

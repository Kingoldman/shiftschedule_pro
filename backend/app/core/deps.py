"""FastAPI 依赖项

提供两级身份抽象：

- `get_current_user`  解析 JWT，得出「谁 + 什么角色」，不关心具体表；
- `get_current_admin` / `get_current_employee` 在其之上做角色约束。

这样新增角色（比如以后的只读审计员）只需在 CurrentUser 的 role 上做判断，
不必改动每个接口的鉴权写法。
"""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.admin import Admin
from app.models.employee_account import EmployeeAccount

ROLE_ADMIN = "admin"
ROLE_EMPLOYEE = "employee"

# tokenUrl 仅用于 OpenAPI 文档展示，实际登录走 /api/auth/login
# auto_error=False：未带 header 时不直接报错，改为回退读取 httpOnly Cookie
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


@dataclass
class CurrentUser:
    """当前登录者的身份快照（与具体表解耦）

    employee_id / employee_name 仅员工角色有效；管理员为 None。
    """

    role: str
    user_id: int          # admin.id 或 employee_account.id
    username: str
    employee_id: int | None = None
    employee_name: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """解析当前登录者身份（管理员或员工），未登录/凭证无效返回 401。

    Token 来源优先级：
    1. Authorization: Bearer <token>（便于 API 调试 / 第三方调用）
    2. httpOnly Cookie（浏览器主路径，JS 无法读取，可防 XSS 窃取）
    """
    if not token:
        token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if not token:
        raise _unauthorized("未登录或登录已过期")

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise _unauthorized("登录凭证无效")

    # sub 理论上由我们自己写入，但 Token 可能被篡改，
    # 必须容错，否则 int() 抛 ValueError 会变成 500
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise _unauthorized("登录凭证无效")

    # 旧版 Token 没有 role 声明，统一按管理员处理，避免存量会话被强制登出
    role = payload.get("role") or ROLE_ADMIN

    if role == ROLE_EMPLOYEE:
        account = db.get(EmployeeAccount, user_id)
        if not account:
            raise _unauthorized("用户不存在")
        if not account.is_active:
            raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")
        _check_token_version(payload, getattr(account, "token_version", 1))
        employee = account.employee
        return CurrentUser(
            role=ROLE_EMPLOYEE,
            user_id=account.id,
            username=account.username,
            employee_id=account.employee_id,
            employee_name=employee.name if employee else None,
        )

    admin = db.get(Admin, user_id)
    if not admin:
        raise _unauthorized("用户不存在")
    _check_token_version(payload, getattr(admin, "token_version", 1))
    return CurrentUser(role=ROLE_ADMIN, user_id=admin.id, username=admin.username)


def _check_token_version(payload: dict, expected_version: int) -> None:
    """校验令牌版本号：改密后旧 Token 立即失效。

    老 Token 没有 tv 字段时不做校验，避免存量用户被强制下线。
    """
    if payload.get("tv") is not None and payload.get("tv") != expected_version:
        raise _unauthorized("密码已修改，请重新登录")


def get_current_admin(
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Admin:
    """要求管理员身份，返回 Admin 实体。非管理员返回 403。"""
    if not current.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    admin = db.get(Admin, current.user_id)
    if not admin:  # 理论上不会走到，防御性处理
        raise _unauthorized("用户不存在")
    return admin


def get_current_employee(
    current: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """要求员工身份。非员工角色（如管理员）返回 403。"""
    if current.role != ROLE_EMPLOYEE:
        raise HTTPException(status_code=403, detail="该接口仅员工账号可访问")
    return current


def assert_admin_or_self(current: CurrentUser, employee_id: int) -> None:
    """越权防护：员工只能访问自己的数据，管理员不受限。"""
    if current.is_admin:
        return
    if current.employee_id != employee_id:
        raise HTTPException(status_code=403, detail="只能查看自己的数据")

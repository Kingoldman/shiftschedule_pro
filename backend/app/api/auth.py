"""认证相关接口"""
import time
import logging
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import ROLE_ADMIN, ROLE_EMPLOYEE, CurrentUser, get_current_user
from app.core.security import verify_password, create_access_token, hash_password
from app.models.admin import Admin
from app.models.audit_log import AuditLog
from app.models.employee_account import EmployeeAccount
from app.schemas.admin import AdminLogin, Token, MeOut, ChangePassword

router = APIRouter()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 登录失败限流（进程内简易实现，单实例部署足够）
# 策略：同一用户名连续失败达到阈值后锁定一段时间，抵御在线爆破。
# ---------------------------------------------------------------------------
_LOGIN_MAX_FAILS = 5          # 允许的最大连续失败次数
_LOGIN_LOCK_SECONDS = 300     # 触发后锁定时长（5 分钟）
_login_fails: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
_login_locked_until: dict[str, float] = {}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_login_allowed(username: str) -> None:
    """检查该用户名当前是否允许尝试登录，超出限制直接抛 429"""
    now = time.time()
    locked_until = _login_locked_until.get(username, 0)
    if locked_until > now:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"登录失败次数过多，请 {int(locked_until - now)} 秒后再试",
        )
    if locked_until and locked_until <= now:
        # 锁定已到期，清空计数
        _login_locked_until.pop(username, None)
        _login_fails[username] = (0, 0.0)


def _record_login_fail(username: str, request: Request) -> None:
    """记录一次登录失败，达到阈值则锁定"""
    now = time.time()
    fails, first_at = _login_fails[username]
    if first_at and now - first_at > _LOGIN_LOCK_SECONDS:
        # 距本轮首次失败已超过窗口期，重新计数
        fails, first_at = 0, now
    fails += 1
    _login_fails[username] = (fails, first_at or now)

    logger.warning(
        "登录失败：username=%s ip=%s 连续失败 %s 次", username, _client_ip(request), fails
    )
    if fails >= _LOGIN_MAX_FAILS:
        _login_locked_until[username] = now + _LOGIN_LOCK_SECONDS
        _login_fails[username] = (0, now)
        logger.warning("账号 %s 因连续登录失败已被锁定 %s 秒", username, _LOGIN_LOCK_SECONDS)


def _reset_login_fail(username: str) -> None:
    _login_fails.pop(username, None)
    _login_locked_until.pop(username, None)


def _set_auth_cookie(response: Response, token: str) -> None:
    """下发 httpOnly Cookie，JS 无法读取，可防 XSS 窃取令牌"""
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.AUTH_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
    )


@router.post("/login", response_model=Token)
def login(
    body: AdminLogin,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """统一登录入口：管理员与员工共用，返回的 role 决定前端可见范围

    之所以合并成一个入口，是因为两类账号的用户名全局唯一，
    合起来既省去前端让用户先选身份的麻烦，也避免暴露"哪个是管理员账号"。

    Token 写入 httpOnly Cookie；同时仍在响应体返回一份，
    仅为兼容 Bearer 调试调用，前端不应持久化它。
    """
    _check_login_allowed(body.username)

    admin = db.query(Admin).filter(Admin.username == body.username).first()
    if admin:
        if not verify_password(body.password, admin.hashed_password):
            _record_login_fail(body.username, request)
            raise _bad_credentials()
        return _login_admin(admin, request, response, db)

    account = (
        db.query(EmployeeAccount)
        .filter(EmployeeAccount.username == body.username)
        .first()
    )
    if account:
        if not verify_password(body.password, account.hashed_password):
            _record_login_fail(body.username, request)
            raise _bad_credentials()
        if not account.is_active:
            # 停用账号不消耗限流额度，但提示与"密码错误"区分开，便于用户自查
            raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")
        return _login_employee(account, request, response, db)

    _record_login_fail(body.username, request)
    raise _bad_credentials()


def _bad_credentials() -> HTTPException:
    """提示语不区分"用户不存在"与"密码错误"，避免账号枚举"""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="用户名或密码错误",
    )


def _login_admin(
    admin: Admin, request: Request, response: Response, db: Session
) -> Token:
    _reset_login_fail(admin.username)
    # sub 是 JWT 标准字段（主体）；tv 为令牌版本号，用于改密后让旧 Token 失效
    token = create_access_token(
        {
            "sub": str(admin.id),
            "tv": getattr(admin, "token_version", 1),
            "role": ROLE_ADMIN,
        }
    )
    _set_auth_cookie(response, token)
    db.add(
        AuditLog(
            actor=admin.username,
            action="login",
            target_type="auth",
            target_id=str(admin.id),
            detail=f"管理员登录成功（IP: {_client_ip(request)}）",
        )
    )
    db.commit()
    return Token(access_token=token, role=ROLE_ADMIN, username=admin.username)


def _login_employee(
    account: EmployeeAccount, request: Request, response: Response, db: Session
) -> Token:
    _reset_login_fail(account.username)
    token = create_access_token(
        {
            "sub": str(account.id),
            "tv": getattr(account, "token_version", 1),
            "role": ROLE_EMPLOYEE,
        }
    )
    _set_auth_cookie(response, token)
    account.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(
        AuditLog(
            actor=account.username,
            action="login",
            target_type="employee_account",
            target_id=str(account.id),
            detail=f"员工登录成功（IP: {_client_ip(request)}）",
        )
    )
    db.commit()
    return Token(access_token=token, role=ROLE_EMPLOYEE, username=account.username)


@router.post("/logout")
def logout(response: Response):
    """退出登录：清除认证 Cookie

    令牌已改为 httpOnly Cookie 存储，前端不再持有，退出时只需让 Cookie 失效。
    """
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
    )
    return {"msg": "已退出登录"}


@router.get("/me", response_model=MeOut)
def get_me(current: CurrentUser = Depends(get_current_user)):
    """获取当前登录者信息（管理员与员工共用）"""
    return MeOut(
        role=current.role,
        username=current.username,
        employee_id=current.employee_id,
        employee_name=current.employee_name,
    )


@router.post("/change-password")
def change_password(
    payload: ChangePassword,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改密码（管理员与员工通用）

    修改成功后自增 token_version，使此前签发的所有 Token 立即失效
    （其他设备与当前会话都会被登出，需要重新登录）。
    """
    if current.is_admin:
        user: Admin | EmployeeAccount | None = db.get(Admin, current.user_id)
        target_type = "auth"
    else:
        user = db.get(EmployeeAccount, current.user_id)
        target_type = "employee_account"
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if not verify_password(payload.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="旧密码错误")

    user.hashed_password = hash_password(payload.new_password)
    # 令牌版本号 +1：所有旧 Token 立即失效
    user.token_version = (getattr(user, "token_version", 1) or 1) + 1
    db.add(
        AuditLog(
            actor=current.username,
            action="change_password",
            target_type=target_type,
            target_id=str(current.user_id),
            detail="修改密码，历史令牌已失效",
        )
    )
    db.commit()
    return {"msg": "密码修改成功，请使用新密码重新登录"}

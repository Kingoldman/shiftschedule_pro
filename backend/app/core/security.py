"""安全相关工具：密码哈希、JWT 签发与校验

使用 bcrypt 直接做密码哈希（避免 passlib 引入 cryptography 依赖），
使用 PyJWT 做 token 签发（HS256 不需要额外加密库）。
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from jwt import InvalidTokenError

from app.core.config import settings


def hash_password(password: str) -> str:
    """对明文密码做 bcrypt 哈希处理"""
    # bcrypt 需要 bytes 输入，输出也是 bytes，转 str 存库
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(data: dict[str, Any]) -> str:
    """签发 JWT。data 中应包含 sub 字段（用户标识）。"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """解码 JWT。失败返回 None，由调用方处理 401。"""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except InvalidTokenError:
        return None

"""应用配置

使用 pydantic-settings 从环境变量读取配置，方便部署时覆盖。
默认值适合本地开发，生产环境通过 .env 文件或环境变量调整。
"""
import os
import secrets
import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# 开发环境默认密钥（仅本地使用，生产环境必须通过 .env 或环境变量覆盖）
_DEV_SECRET_KEY = "shiftschedule-dev-secret-key-do-not-use-in-prod"

# 自动生成的随机默认管理员密码（仅当数据库为空且未设置环境变量时使用）
_DEFAULT_ADMIN_PASSWORD = os.getenv("INIT_ADMIN_PASSWORD") or secrets.token_urlsafe(12)


class Settings(BaseSettings):
    # 应用基础信息
    APP_NAME: str = "隔壁小王爱值班"
    VERSION: str = "1.0.0"

    # 调试模式：开发时为 True，生产环境设为 False
    # 关闭后：禁用 /docs 和 /redoc 文档、收紧 CORS、隐藏错误详情
    DEBUG: bool = True

    # 数据库配置：默认使用 SQLite，文件位于项目根目录
    DATABASE_URL: str = "sqlite:///./shiftschedule.db"

    # JWT 配置：用于管理员登录后的 token 签发
    # 本地开发时使用固定默认值便于调试；生产环境（DEBUG=False）必须通过 .env 覆盖
    SECRET_KEY: str = _DEV_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天

    # 跨域配置：开发环境允许前端端口访问
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # 初始管理员密码（首次启动创建管理员时使用）
    INIT_ADMIN_PASSWORD: str = _DEFAULT_ADMIN_PASSWORD

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


settings = Settings()

# 生产环境安全检查：DEBUG=False 时若 SECRET_KEY 仍为开发默认值，拒绝启动
if not settings.DEBUG and settings.SECRET_KEY == _DEV_SECRET_KEY:
    raise RuntimeError(
        "生产环境（DEBUG=False）必须通过环境变量或 .env 设置 SECRET_KEY，"
        "不能使用开发默认值。请生成随机密钥，例如："
        "python -c \"import secrets; print(secrets.token_urlsafe(32))\""
    )

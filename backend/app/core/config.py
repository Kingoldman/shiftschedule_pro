"""应用配置

使用 pydantic-settings 从环境变量读取配置，方便部署时覆盖。
默认值适合本地开发，生产环境通过 .env 文件或环境变量调整。
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    SECRET_KEY: str = "shiftschedule-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天

    # 跨域配置：开发环境允许前端端口访问
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


settings = Settings()

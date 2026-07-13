"""FastAPI 应用入口

启动方式：
    uvicorn app.main:app --reload --port 8000

访问 /docs 可查看自动生成的 OpenAPI 文档。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.services.init_service import init_database
from app.api import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库和默认管理员"""
    init_database()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# CORS：允许前端开发端口访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 所有业务路由统一挂在 /api 下
app.include_router(api_router, prefix="/api")


@app.get("/", tags=["健康检查"])
def health():
    """健康检查接口"""
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.VERSION}

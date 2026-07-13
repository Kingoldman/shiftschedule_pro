"""API 路由汇总"""
from fastapi import APIRouter

from app.api import auth, groups, employees, day_info, schedule, stats

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(groups.router, prefix="/groups", tags=["值班组"])
api_router.include_router(employees.router, prefix="/employees", tags=["员工"])
api_router.include_router(day_info.router, prefix="/days", tags=["日期管理"])
api_router.include_router(schedule.router, prefix="/schedule", tags=["排班"])
api_router.include_router(stats.router, prefix="/stats", tags=["统计"])

"""Pydantic Schema 汇总"""
from app.schemas.admin import AdminLogin, Token, AdminOut
from app.schemas.group import GroupCreate, GroupUpdate, GroupOut, GroupBatchSort
from app.schemas.employee import (
    EmployeeCreate, EmployeeUpdate, EmployeeOut, EmployeeBatchSort
)
from app.schemas.day_info import DayInfoBatchUpdate, DayInfoOut
from app.schemas.schedule import ScheduleSave, ScheduleOut, ScheduleGenerate

__all__ = [
    "AdminLogin", "Token", "AdminOut",
    "GroupCreate", "GroupUpdate", "GroupOut", "GroupBatchSort",
    "EmployeeCreate", "EmployeeUpdate", "EmployeeOut", "EmployeeBatchSort",
    "DayInfoBatchUpdate", "DayInfoOut",
    "ScheduleSave", "ScheduleOut", "ScheduleGenerate",
]

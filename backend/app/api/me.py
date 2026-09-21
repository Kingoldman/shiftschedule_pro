"""员工自助接口（只读）

设计原则：**只返回本人数据，绝不返回整月排班**。
管理员可以在排班页看到全量安排，员工账号不行——所以这里不复用
`/schedule/{year}/{month}`，而是从排班快照里把"我"的那几行挑出来单独返回。

可见性边界：只有**已保存**的月份才对员工可见。排班保存即锁定，
未保存的草稿不会出现在 `/me/months` 里，天然形成"发布"语义。
"""
import calendar
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_employee
from app.models.schedule import Schedule

router = APIRouter()

# 与统计口径一致：调休补班按工作日算
_VACATION = "vacation"
_WORKDAY = "workday"

_DAY_TYPE_LABEL = {
    "workday": "工作日",
    "weekend": "周末",
    "holiday": "节假日",
    "vacation": "调休补班",
}

_WEEKDAY_LABEL = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _normalize(day_type: str) -> str:
    """调休补班归入工作日统计"""
    return _WORKDAY if day_type == _VACATION else day_type


def _empty_summary() -> dict:
    return {"workday": 0, "weekend": 0, "holiday": 0, "total": 0}


@router.get("/months")
def list_my_months(
    current: CurrentUser = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """列出已发布（已保存）的排班月份，按时间倒序"""
    records = (
        db.query(Schedule)
        .order_by(Schedule.year.desc(), Schedule.month.desc())
        .all()
    )
    return [
        {"year": r.year, "month": r.month, "locked": bool(r.locked)}
        for r in records
    ]


@router.get("/schedule/{year}/{month}")
def get_my_schedule(
    year: int,
    month: int,
    current: CurrentUser = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """查询本人在指定月份的值班安排

    返回只包含"我值班的那些天"，附带同班同事与所属组，用于员工自助查看。
    """
    if not 2000 <= year <= 2100 or not 1 <= month <= 12:
        raise HTTPException(status_code=400, detail="年月不合法")

    record = (
        db.query(Schedule)
        .filter(Schedule.year == year, Schedule.month == month)
        .first()
    )
    if not record:
        return {
            "year": year,
            "month": month,
            "has_schedule": False,
            "locked": False,
            "days": [],
            "summary": _empty_summary(),
        }

    days = []
    summary = _empty_summary()
    for item in record.schedule_json or []:
        employees = item.get("employees") or []
        if not any(e.get("id") == current.employee_id for e in employees):
            continue
        raw_type = item.get("day_type", _WORKDAY)
        item_date = item.get("date", "")
        try:
            d = date.fromisoformat(item_date)
            weekday = _WEEKDAY_LABEL[d.weekday()]
        except ValueError:
            weekday = ""
        days.append(
            {
                "date": item_date,
                "weekday": weekday,
                "day_type": raw_type,
                "day_type_label": _DAY_TYPE_LABEL.get(raw_type, raw_type),
                "group_name": item.get("group_name") or "",
                "coworkers": [
                    e.get("name", "")
                    for e in employees
                    if e.get("id") != current.employee_id
                ],
            }
        )
        norm = _normalize(raw_type)
        if norm in summary:
            summary[norm] += 1
        summary["total"] += 1

    days.sort(key=lambda x: x["date"])
    return {
        "year": year,
        "month": month,
        "has_schedule": True,
        "locked": bool(record.locked),
        "days_in_month": calendar.monthrange(year, month)[1],
        "days": days,
        "summary": summary,
    }

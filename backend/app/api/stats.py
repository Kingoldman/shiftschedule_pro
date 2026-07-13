"""统计接口

支持按月、按年、累计、自定义区间统计。
调休日（vacation）视为工作日一并统计。
"""
import time
import calendar
from datetime import date
from copy import deepcopy
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.schedule import Schedule
from app.services.schedule_service import compute_statistics, compute_eligible_days

router = APIRouter()

# 调休日视为工作日统计
STAT_DAY_TYPES = ["workday", "weekend", "holiday", "vacation"]

# 简易进程内缓存：key -> (result, timestamp)
_stats_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 30  # 30秒缓存有效期


def clear_stats_cache(year: int | None = None, month: int | None = None):
    """清除统计缓存。指定年月则只清对应 key，否则清全部。"""
    if year is not None and month is not None:
        key = f"monthly_{year}_{month}"
        _stats_cache.pop(key, None)
    else:
        _stats_cache.clear()


def _normalize_day_type(item: dict) -> dict:
    """把调休日统一视为工作日"""
    item = deepcopy(item)
    if item.get("day_type") == "vacation":
        item["day_type"] = "workday"
    return item


def _collect_schedule_data(db: Session, start: date, end: date) -> list[dict]:
    """收集时间范围内的排班数据，调休日合并到工作日"""
    records = (
        db.query(Schedule)
        .filter(
            (Schedule.year * 100 + Schedule.month) >= (start.year * 100 + start.month),
            (Schedule.year * 100 + Schedule.month) <= (end.year * 100 + end.month),
        )
        .all()
    )
    all_items = []
    for record in records:
        for item in record.schedule_json:
            item_date = item.get("date", "")
            if item_date < start.isoformat() or item_date > end.isoformat():
                continue
            if item.get("day_type") not in STAT_DAY_TYPES:
                continue
            all_items.append(_normalize_day_type(item))
    return all_items


def _collect_schedule_records(db: Session, start: date, end: date) -> list[Schedule]:
    """收集时间范围内的排班记录（含 group_snapshot）"""
    return (
        db.query(Schedule)
        .filter(
            (Schedule.year * 100 + Schedule.month) >= (start.year * 100 + start.month),
            (Schedule.year * 100 + Schedule.month) <= (end.year * 100 + end.month),
        )
        .all()
    )


def _enrich_with_eligible(db: Session, result: dict, schedule_items: list[dict], group_snapshot: dict | None = None) -> dict:
    """为 by_employee 中的每个员工添加 eligible_days 字段

    eligible 天数的计算范围仅限于已保存排班的日期，而非整个月/年。
    """
    emp_ids = [e["id"] for e in result.get("by_employee", [])]
    if not emp_ids:
        return result
    # 从排班数据中提取实际日期范围
    dates = [item.get("date") for item in schedule_items if item.get("date")]
    if not dates:
        return result
    start = date.fromisoformat(min(dates))
    end = date.fromisoformat(max(dates))
    eligible = compute_eligible_days(db, emp_ids, start, end, group_snapshot=group_snapshot)
    for emp in result["by_employee"]:
        eid = emp["id"]
        e = eligible.get(eid, {"workday": 0, "weekend": 0, "holiday": 0, "total": 0})
        emp["eligible_workday"] = e["workday"]
        emp["eligible_weekend"] = e["weekend"]
        emp["eligible_holiday"] = e["holiday"]
        emp["eligible_total"] = e["total"]
    return result


def _enrich_with_eligible_multi(
    db: Session,
    result: dict,
    records: list[Schedule],
    range_start: date | None = None,
    range_end: date | None = None,
) -> dict:
    """跨多月统计：逐月使用各自保存时的快照计算 eligible 天数后累加。

    每条 Schedule 记录都有保存时的 group_snapshot，用它来还原当时的值班状态，
    确保历史统计不受后续人员/日期变动影响。

    range_start/range_end: 自定义区间边界，会过滤每月参与计算的排班日期。
    """
    emp_ids = [e["id"] for e in result.get("by_employee", [])]
    if not emp_ids:
        return result

    total_eligible: dict[int, dict[str, int]] = {
        eid: {"workday": 0, "weekend": 0, "holiday": 0, "total": 0}
        for eid in emp_ids
    }

    start_iso = range_start.isoformat() if range_start else None
    end_iso = range_end.isoformat() if range_end else None

    for record in records:
        items = [
            _normalize_day_type(item)
            for item in record.schedule_json
            if item.get("day_type") in STAT_DAY_TYPES
        ]
        # 自定义区间过滤：只保留区间内的日期
        if start_iso:
            items = [item for item in items if item.get("date", "") >= start_iso]
        if end_iso:
            items = [item for item in items if item.get("date", "") <= end_iso]
        if not items:
            continue
        dates = [item.get("date") for item in items if item.get("date")]
        if not dates:
            continue
        start = date.fromisoformat(min(dates))
        end = date.fromisoformat(max(dates))
        eligible = compute_eligible_days(
            db, emp_ids, start, end, group_snapshot=record.group_snapshot
        )
        for eid, e in eligible.items():
            if eid in total_eligible:
                total_eligible[eid]["workday"] += e.get("workday", 0)
                total_eligible[eid]["weekend"] += e.get("weekend", 0)
                total_eligible[eid]["holiday"] += e.get("holiday", 0)
                total_eligible[eid]["total"] += e.get("total", 0)

    for emp in result["by_employee"]:
        eid = emp["id"]
        e = total_eligible.get(eid, {"workday": 0, "weekend": 0, "holiday": 0, "total": 0})
        emp["eligible_workday"] = e["workday"]
        emp["eligible_weekend"] = e["weekend"]
        emp["eligible_holiday"] = e["holiday"]
        emp["eligible_total"] = e["total"]
    return result


@router.get("/monthly/{year}/{month}")
def get_monthly_stats(year: int, month: int, db: Session = Depends(get_db)):
    """获取某月排班统计"""
    cache_key = f"monthly_{year}_{month}"
    if cache_key in _stats_cache:
        cached_result, cached_at = _stats_cache[cache_key]
        if time.time() - cached_at < _CACHE_TTL:
            return cached_result

    record = (
        db.query(Schedule)
        .filter(Schedule.year == year, Schedule.month == month)
        .first()
    )
    if not record:
        return {"by_employee": [], "by_day_type": {
            "workday": 0, "weekend": 0, "holiday": 0,
        }, "total_days": 0, "period_label": f"{year}年{month}月"}
    filtered = [_normalize_day_type(item) for item in record.schedule_json if item.get("day_type") in STAT_DAY_TYPES]
    result = compute_statistics(filtered)
    result["total_days"] = len(filtered)
    result["period_label"] = f"{year}年{month}月"

    # 优先使用该月保存时的快照
    result = _enrich_with_eligible(db, result, filtered, group_snapshot=record.group_snapshot)
    _stats_cache[cache_key] = (result, time.time())
    return result


@router.get("/yearly/{year}")
def get_yearly_stats(year: int, db: Session = Depends(get_db)):
    """获取某年排班统计"""
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    records = _collect_schedule_records(db, start, end)
    all_items = []
    for record in records:
        for item in record.schedule_json:
            item_date = item.get("date", "")
            if item_date < start.isoformat() or item_date > end.isoformat():
                continue
            if item.get("day_type") not in STAT_DAY_TYPES:
                continue
            all_items.append(_normalize_day_type(item))
    if not all_items:
        return {"by_employee": [], "by_day_type": {
            "workday": 0, "weekend": 0, "holiday": 0,
        }, "total_days": 0, "period_label": f"{year}年"}
    result = compute_statistics(all_items)
    result["total_days"] = len(all_items)
    result["period_label"] = f"{year}年"
    result = _enrich_with_eligible_multi(db, result, records)
    return result


@router.get("/custom")
def get_custom_stats(
    start_date: date = Query(..., description="起始日期"),
    end_date: date = Query(..., description="结束日期"),
    db: Session = Depends(get_db),
):
    """自定义区间统计"""
    if end_date < start_date:
        return {"by_employee": [], "by_day_type": {
            "workday": 0, "weekend": 0, "holiday": 0,
        }, "total_days": 0, "period_label": "无效区间"}
    records = _collect_schedule_records(db, start_date, end_date)
    all_items = []
    for record in records:
        for item in record.schedule_json:
            item_date = item.get("date", "")
            if item_date < start_date.isoformat() or item_date > end_date.isoformat():
                continue
            if item.get("day_type") not in STAT_DAY_TYPES:
                continue
            all_items.append(_normalize_day_type(item))
    if not all_items:
        return {"by_employee": [], "by_day_type": {
            "workday": 0, "weekend": 0, "holiday": 0,
        }, "total_days": 0, "period_label": f"{start_date} ~ {end_date}"}
    result = compute_statistics(all_items)
    result["total_days"] = len(all_items)
    result["period_label"] = f"{start_date} ~ {end_date}"
    result = _enrich_with_eligible_multi(db, result, records, range_start=start_date, range_end=end_date)
    return result


@router.get("/cumulative")
def get_cumulative_stats(db: Session = Depends(get_db)):
    """累计统计（所有已保存的排班）"""
    records = db.query(Schedule).all()
    all_items = []
    for record in records:
        for item in record.schedule_json:
            if item.get("day_type") in STAT_DAY_TYPES:
                all_items.append(_normalize_day_type(item))

    if not all_items:
        return {"by_employee": [], "by_day_type": {
            "workday": 0, "weekend": 0, "holiday": 0,
        }, "total_days": 0, "period_label": "累计"}
    result = compute_statistics(all_items)
    result["total_days"] = len(all_items)
    result["period_label"] = "累计"
    result = _enrich_with_eligible_multi(db, result, records)
    return result


@router.get("/employees-with-history")
def get_employees_with_history(db: Session = Depends(get_db)):
    """获取所有曾参与值班的人员列表（包括已删除的）

    合并当前员工表和排班历史记录中的员工信息。
    用于个人查询页的人员选择器，确保已删除但有过值班记录的人员也能查询。
    """
    from app.models.employee import Employee
    from app.models.group import ShiftGroup

    result: dict[int, dict] = {}

    # 当前员工
    current_emps = db.query(Employee).order_by(Employee.id.asc()).all()
    for emp in current_emps:
        group_name = None
        if emp.group_id:
            g = db.get(ShiftGroup, emp.group_id)
            if g:
                group_name = g.name
        result[emp.id] = {
            "id": emp.id,
            "name": emp.name,
            "state": emp.state,
            "group_id": emp.group_id,
            "group_name": group_name,
            "deleted": False,
        }

    # 从排班历史中找已删除的员工
    records = db.query(Schedule).order_by(Schedule.year.asc(), Schedule.month.asc()).all()
    for record in records:
        for item in record.schedule_json:
            for emp in item.get("employees", []):
                eid = emp.get("id")
                if eid is not None and eid not in result:
                    result[eid] = {
                        "id": eid,
                        "name": emp.get("name", f"员工{eid}"),
                        "state": None,
                        "group_id": None,
                        "group_name": None,
                        "deleted": True,
                    }

    return list(result.values())


@router.get("/employee/{employee_id}")
def get_employee_stats(
    employee_id: int,
    mode: str = Query("cumulative", description="统计模式: monthly/yearly/cumulative"),
    year: int | None = Query(None, description="年份"),
    month: int | None = Query(None, description="月份(1-12)"),
    db: Session = Depends(get_db),
):
    """单个员工的值班统计分析

    返回该员工在指定统计模式下的：
    - 概览（累计值班天数、应值班天数、频率）
    - 按月趋势（折线图数据）
    - 日期性质分布（饼图数据）
    - 月度频率明细表（含可值班天数、频率，支持排序）
    - 所有值班记录（明细表）
    - 所有值班日期列表

    mode 支持 monthly(需year+month)/yearly(需year)/cumulative(全部)。
    每月数据使用该记录的 group_snapshot 计算 eligible_days，
    确保历史统计不受后续人员/组变动影响。
    """
    from app.models.employee import Employee
    from app.models.group import ShiftGroup

    # 转换模式为日期范围
    if mode == "monthly":
        if not year or not month:
            return {"error": "monthly 模式需要 year 和 month 参数"}
        last_day = calendar.monthrange(year, month)[1]
        start_date = date(year, month, 1)
        end_date = date(year, month, last_day)
    elif mode == "yearly":
        if not year:
            return {"error": "yearly 模式需要 year 参数"}
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
    else:  # cumulative
        start_date = None
        end_date = None

    # 员工基本信息（可能已被删除，从历史快照中查找）
    emp = db.get(Employee, employee_id)
    employee_info = None
    if emp:
        group_name = None
        if emp.group_id:
            g = db.get(ShiftGroup, emp.group_id)
            if g:
                group_name = g.name
        employee_info = {
            "id": emp.id,
            "name": emp.name,
            "state": emp.state,
            "group_id": emp.group_id,
            "group_name": group_name,
        }

    # 查询所有已保存排班记录，按时间升序
    records = (
        db.query(Schedule)
        .order_by(Schedule.year.asc(), Schedule.month.asc())
        .all()
    )

    # 区间筛选：将 start_date/end_date 转为字符串比较
    start_str = start_date.isoformat() if start_date else None
    end_str = end_date.isoformat() if end_date else None

    monthly_trend = []      # 按月趋势
    recent_duties = []      # 所有值班记录
    duty_days = []           # 所有值班日期
    total_workday = 0
    total_weekend = 0
    total_holiday = 0
    total_eligible = 0
    total_eligible_workday = 0
    total_eligible_weekend = 0
    total_eligible_holiday = 0

    # 若员工不在数据库中，从第一个含该员工的快照中找名字
    fallback_name = employee_info["name"] if employee_info else None

    for record in records:
        # 该月内该员工参与的排班条目
        month_items = []
        for item in record.schedule_json:
            employees = item.get("employees", []) or []
            if not any(e.get("id") == employee_id for e in employees):
                continue
            item_date = item.get("date", "")
            if not item_date:
                continue
            # 区间筛选
            if start_str and item_date < start_str:
                continue
            if end_str and item_date > end_str:
                continue
            day_type = item.get("day_type", "workday")
            if day_type == "vacation":
                day_type = "workday"
            group_name = item.get("group_name", "")
            coworkers = [e.get("name", "") for e in employees if e.get("id") != employee_id]
            if fallback_name is None:
                me = next((e for e in employees if e.get("id") == employee_id), None)
                if me and me.get("name"):
                    fallback_name = me.get("name")

            month_items.append({
                "date": item_date,
                "day_type": day_type,
                "group_name": group_name,
                "coworkers": coworkers,
            })
            duty_days.append(item_date)
            recent_duties.append({
                "date": item_date,
                "day_type": day_type,
                "group_name": group_name,
                "coworkers": coworkers,
            })

        if not month_items:
            continue

        # 按日期性质统计当月
        m_workday = sum(1 for x in month_items if x["day_type"] == "workday")
        m_weekend = sum(1 for x in month_items if x["day_type"] == "weekend")
        m_holiday = sum(1 for x in month_items if x["day_type"] == "holiday")
        m_total = len(month_items)

        # 该月 eligible 天数：用整月排班日期范围，不是该员工参与的范围
        # 与原统计功能一致（_enrich_with_eligible 使用所有排班条目的日期范围）
        all_month_dates = [
            item.get("date") for item in record.schedule_json
            if item.get("date") and item.get("day_type") in STAT_DAY_TYPES
        ]
        if all_month_dates:
            start = date.fromisoformat(min(all_month_dates))
            end = date.fromisoformat(max(all_month_dates))
        else:
            dates = [x["date"] for x in month_items]
            start = date.fromisoformat(min(dates))
            end = date.fromisoformat(max(dates))
        eligible = compute_eligible_days(
            db, [employee_id], start, end, group_snapshot=record.group_snapshot
        )
        e = eligible.get(employee_id, {"workday": 0, "weekend": 0, "holiday": 0, "total": 0})
        m_eligible = e.get("total", 0)
        m_eligible_workday = e.get("workday", 0)
        m_eligible_weekend = e.get("weekend", 0)
        m_eligible_holiday = e.get("holiday", 0)
        m_freq = round(m_eligible / m_total, 2) if m_total > 0 and m_eligible > 0 else 0

        monthly_trend.append({
            "month": f"{record.year}-{str(record.month).zfill(2)}",
            "workday": m_workday,
            "weekend": m_weekend,
            "holiday": m_holiday,
            "total": m_total,
            "eligible": m_eligible,
            "eligible_workday": m_eligible_workday,
            "eligible_weekend": m_eligible_weekend,
            "eligible_holiday": m_eligible_holiday,
            "frequency": m_freq,
        })

        total_workday += m_workday
        total_weekend += m_weekend
        total_holiday += m_holiday
        total_eligible += m_eligible
        total_eligible_workday += m_eligible_workday
        total_eligible_weekend += m_eligible_weekend
        total_eligible_holiday += m_eligible_holiday

    total_duty = total_workday + total_weekend + total_holiday
    overall_freq = round(total_eligible / total_duty, 2) if total_duty > 0 and total_eligible > 0 else 0
    freq_workday = round(total_eligible_workday / total_workday, 2) if total_workday > 0 and total_eligible_workday > 0 else 0
    freq_weekend = round(total_eligible_weekend / total_weekend, 2) if total_weekend > 0 and total_eligible_weekend > 0 else 0
    freq_holiday = round(total_eligible_holiday / total_holiday, 2) if total_holiday > 0 and total_eligible_holiday > 0 else 0

    overview = {
        "total_duty_days": total_duty,
        "workday": total_workday,
        "weekend": total_weekend,
        "holiday": total_holiday,
        "eligible_total": total_eligible,
        "eligible_workday": total_eligible_workday,
        "eligible_weekend": total_eligible_weekend,
        "eligible_holiday": total_eligible_holiday,
        "frequency": overall_freq,
        "freq_workday": freq_workday,
        "freq_weekend": freq_weekend,
        "freq_holiday": freq_holiday,
    }

    day_type_distribution = [
        {"name": "工作日", "value": total_workday},
        {"name": "周末", "value": total_weekend},
        {"name": "节假日", "value": total_holiday},
    ]

    # 所有值班记录（按日期降序）
    recent_duties.sort(key=lambda x: x["date"], reverse=True)

    # 员工已删除但出现在历史排班中，用 fallback_name 构造 employee_info
    if employee_info is None and fallback_name is not None:
        employee_info = {
            "id": employee_id,
            "name": fallback_name,
            "state": None,
            "group_id": None,
            "group_name": None,
        }

    return {
        "employee": employee_info,
        "overview": overview,
        "monthly_trend": monthly_trend,
        "day_type_distribution": day_type_distribution,
        "all_duties": recent_duties,
        "duty_days": duty_days,
    }

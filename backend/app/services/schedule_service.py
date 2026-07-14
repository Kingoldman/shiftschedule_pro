"""排班算法服务

核心逻辑：给定起始组、起始日期、待排日期列表，按组顺序轮转排班。
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.group import ShiftGroup
from app.models.day_info import DayInfo
from app.models.state_log import EmployeeStateLog


def generate_schedule(
    db: Session,
    year: int,
    month: int,
    start_group_id: int,
    start_date: date,
    days: list[date],
) -> list[dict]:
    """生成排班数据

    Args:
        db: 数据库 Session
        year/month: 年月，仅用于上下文
        start_group_id: 从哪个组开始轮转
        start_date: 排班起始日期
        days: 需要排班的日期列表

    Returns:
        排班结果列表，每项形如:
        {
            "date": "2026-07-01",
            "day_type": "workday",
            "group_id": 1,
            "group_name": "一组",
            "employees": [{"id":1,"name":"张三"}]
        }
    """
    # 取所有组按 order_id 排序，构造轮转序列
    all_groups = (
        db.query(ShiftGroup)
        .order_by(ShiftGroup.order_id.asc())
        .all()
    )
    if not all_groups:
        return []

    # 预加载每个组的值班员工（state=1），按 order_id 排序
    group_employees: dict[int, list[dict]] = {}
    for g in all_groups:
        emps = (
            db.query(Employee)
            .filter(Employee.group_id == g.id, Employee.state == 1)
            .order_by(Employee.order_id.asc())
            .all()
        )
        group_employees[g.id] = [{"id": e.id, "name": e.name} for e in emps]

    # 过滤掉空组（无值班人员的组不参与轮转）
    groups = [g for g in all_groups if group_employees.get(g.id)]
    if not groups:
        return []

    # 找到起始组在序列中的位置
    start_index = 0
    for i, g in enumerate(groups):
        if g.id == start_group_id:
            start_index = i
            break

    # 预加载日期性质
    day_infos = {
        d.date: d
        for d in db.query(DayInfo).filter(DayInfo.date.in_(days)).all()
    }

    # 待排日期按时间排序
    sorted_days = sorted(days)
    result = []
    for offset, day in enumerate(sorted_days):
        # 轮转取组：起始位置 + 偏移量取模
        group = groups[(start_index + offset) % len(groups)]
        di = day_infos.get(day)
        day_type = di.day_type if di else "workday"
        holiday_name = di.remark if di and di.remark else None
        result.append({
            "date": day.isoformat(),
            "day_type": day_type,
            "holiday_name": holiday_name,
            "group_id": group.id,
            "group_name": group.name,
            "employees": group_employees.get(group.id, []),
        })

    return result


def compute_statistics(schedule_json: list[dict]) -> dict:
    """统计某月排班结果

    按员工 + 日期性质分类汇总值班次数。

    Returns:
        {
            "by_employee": [
                {"id":1,"name":"张三","workday":5,"weekend":2,"holiday":1,"vacation":0,"total":8},
                ...
            ],
            "by_group": [...],
            "by_day_type": {"workday":22,"weekend":8,"holiday":1,"vacation":0}
        }
    """
    # 按员工聚合：employee_id -> {day_type -> count}
    emp_stats: dict[int, dict[str, int]] = {}
    emp_name: dict[int, str] = {}
    # 按组聚合
    group_stats: dict[int, dict[str, int]] = {}
    group_name: dict[int, str] = {}
    # 按日期性质聚合（不含调休补班，统计接口已过滤）
    day_type_stats: dict[str, int] = {
        "workday": 0, "weekend": 0, "holiday": 0,
    }

    for item in schedule_json:
        day_type = item.get("day_type", "workday")
        if day_type in day_type_stats:
            day_type_stats[day_type] += 1

        gid = item.get("group_id")
        gname = item.get("group_name", "")
        if gid is not None:
            if gid not in group_stats:
                group_stats[gid] = {
                    "workday": 0, "weekend": 0, "holiday": 0, "total": 0
                }
                group_name[gid] = gname
            group_stats[gid][day_type] = group_stats[gid].get(day_type, 0) + 1
            group_stats[gid]["total"] += 1

        for emp in item.get("employees", []):
            eid = emp.get("id")
            ename = emp.get("name", "")
            if eid is None:
                continue
            if eid not in emp_stats:
                emp_stats[eid] = {
                    "workday": 0, "weekend": 0, "holiday": 0, "total": 0
                }
                emp_name[eid] = ename
            emp_stats[eid][day_type] = emp_stats[eid].get(day_type, 0) + 1
            emp_stats[eid]["total"] += 1

    by_employee = [
        {"id": eid, "name": emp_name[eid], **stats}
        for eid, stats in emp_stats.items()
    ]
    by_employee.sort(key=lambda x: x["total"], reverse=True)

    return {
        "by_employee": by_employee,
        "by_day_type": day_type_stats,
    }


def compute_eligible_days(
    db: Session,
    employee_ids: list[int],
    start: date,
    end: date,
    group_snapshot: dict | None = None,
) -> dict[int, dict[str, int]]:
    """计算区间内每个员工的统计天数，按日期性质拆分。

    返回: {employee_id: {"workday": N, "weekend": N, "holiday": N, "total": N}}

    简化算法：排班以整月为单位，如果员工在某月有值班记录，
    则该月的统计天数 = 整月对应性质的天数。
    不再依赖 state_logs 或 group_snapshot，计算简单可靠。
    """
    # 预加载区间内每天的日期性质
    all_dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    day_infos = {
        d.date: d.day_type
        for d in db.query(DayInfo).filter(DayInfo.date.in_(all_dates)).all()
    }

    def _day_type(d: date) -> str:
        if d in day_infos:
            dt_val = day_infos[d]
            return "workday" if dt_val == "vacation" else dt_val
        return "weekend" if d.weekday() >= 5 else "workday"

    # 统计区间内各性质总天数
    total_by_type = {"workday": 0, "weekend": 0, "holiday": 0}
    for d in all_dates:
        dt_val = _day_type(d)
        if dt_val in total_by_type:
            total_by_type[dt_val] += 1

    # 所有员工都有相同的统计天数（整月天数）
    result = {}
    total = sum(total_by_type.values())
    for eid in employee_ids:
        result[eid] = {**total_by_type, "total": total}

    return result

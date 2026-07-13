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
    # 按日期性质聚合（不含调休日，统计接口已过滤）
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
    """计算区间内每个员工处于值班状态的天数，按日期性质拆分。

    返回: {employee_id: {"workday": N, "weekend": N, "holiday": N, "total": N}}

    逻辑：遍历区间内每一天，根据状态日志判断该员工当天是否值班(state=1)，
    并按日期性质累加。无状态日志的员工按当前 state 推算。

    group_snapshot: 如果提供，优先使用快照中的组/员工/状态日志数据，
    确保历史统计不受后续人员变动影响。
    """
    from datetime import datetime as dt

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

    total_by_type = {"workday": 0, "weekend": 0, "holiday": 0}
    for d in all_dates:
        dt_val = _day_type(d)
        if dt_val in total_by_type:
            total_by_type[dt_val] += 1

    result = {}
    for eid in employee_ids:
        # 获取员工当前状态
        emp_state = 0
        if group_snapshot:
            # 从快照中查找：遍历所有组的所有员工
            found = False
            for g in group_snapshot.get("groups", []):
                for emp in g.get("employees", []):
                    if emp["id"] == eid:
                        emp_state = emp.get("state", 0)
                        found = True
                        break
                if found:
                    break
            # 快照中没找到（可能员工不在任何组），从数据库获取
            if not found:
                emp = db.get(Employee, eid)
                if emp:
                    emp_state = emp.state
        else:
            emp = db.get(Employee, eid)
            if emp:
                emp_state = emp.state

        if not group_snapshot:
            # 无快照：从数据库查询状态日志
            logs = (
                db.query(EmployeeStateLog)
                .filter(EmployeeStateLog.employee_id == eid)
                .order_by(EmployeeStateLog.changed_at.asc())
                .all()
            )
        else:
            # 有快照：从快照的状态日志构建
            logs_data = group_snapshot.get("state_logs", [])
            logs = [type('Log', (), {
                'employee_id': l['employee_id'],
                'old_state': l['old_state'],
                'new_state': l['new_state'],
                'changed_at': dt.fromisoformat(l['changed_at']) if l.get('changed_at') else None,
            })() for l in logs_data if l['employee_id'] == eid]

        # 过滤掉 old_state == new_state 的日志（组变更、导入等非状态变更记录）
        # 这些日志的 new_state 不可靠，不应影响 state_at_start 计算
        logs = [log for log in logs if log.old_state != log.new_state]

        # 如果员工已不在数据库中（被删除）且无状态日志，
        # 但出现在排班记录的 by_employee 中，视为整月值班
        if not logs and emp_state == 0:
            # 只有出现在排班数据中的员工才会被传入此函数
            # 既然出现在排班中，说明在该区间内是值班的
            result[eid] = {**total_by_type, "total": sum(total_by_type.values())}
            continue

        if not logs:
            if emp_state == 1:
                result[eid] = {**total_by_type, "total": sum(total_by_type.values())}
            else:
                result[eid] = {"workday": 0, "weekend": 0, "holiday": 0, "total": 0}
            continue

        state_at_start = 0
        for log in logs:
            log_date = log.changed_at.date() if isinstance(log.changed_at, dt) else log.changed_at
            if log_date < start:
                state_at_start = log.new_state

        if all(
            (log.changed_at.date() if isinstance(log.changed_at, dt) else log.changed_at) >= start
            for log in logs
        ):
            # 所有状态变更都在排班周期之后。
            # 如果员工当前状态为值班(state=1)，说明在保存排班时该员工已是值班状态
            # （快照在保存排班时捕获，或员工出现在排班数据中说明当时在值班），
            # 因此排班周期内视为全程值班。
            if emp_state == 1:
                state_at_start = 1
            else:
                state_at_start = logs[0].old_state

        changes = []
        for log in logs:
            log_date = log.changed_at.date() if isinstance(log.changed_at, dt) else log.changed_at
            if start <= log_date <= end:
                changes.append((log_date, log.new_state))

        eligible = {"workday": 0, "weekend": 0, "holiday": 0}
        current_state = state_at_start
        segment_start = start

        for change_date, new_state in sorted(changes):
            if current_state == 1:
                d = segment_start
                while d < change_date:
                    dt_val = _day_type(d)
                    if dt_val in eligible:
                        eligible[dt_val] += 1
                    d += timedelta(days=1)
            current_state = new_state
            segment_start = change_date

        if current_state == 1:
            d = segment_start
            while d <= end:
                dt_val = _day_type(d)
                if dt_val in eligible:
                    eligible[dt_val] += 1
                d += timedelta(days=1)

        result[eid] = {**eligible, "total": sum(eligible.values())}

    return result

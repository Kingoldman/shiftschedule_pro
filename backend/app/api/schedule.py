"""排班管理接口"""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_admin
from app.models.schedule import Schedule
from app.models.group import ShiftGroup
from app.models.employee import Employee
from app.models.state_log import EmployeeStateLog
from app.services.schedule_service import generate_schedule
from app.api.stats import clear_stats_cache
from app.schemas.schedule import ScheduleSave, ScheduleOut, ScheduleGenerate

router = APIRouter()


@router.post("/generate", dependencies=[Depends(get_current_admin)])
def generate(body: ScheduleGenerate, db: Session = Depends(get_db)):
    """生成排班（不保存）

    前端调用此接口得到排班预览，用户确认后再调用 save 保存。
    """
    if not db.get(ShiftGroup, body.start_group_id):
        raise HTTPException(status_code=400, detail="起始组不存在")
    result = generate_schedule(
        db, body.year, body.month, body.start_group_id, body.start_date, body.days
    )
    return {"schedule": result}


@router.get("/auto-preview/{year}/{month}")
def auto_preview(year: int, month: int, db: Session = Depends(get_db)):
    """自动预览排班

    从最近有保存记录的月份推断起始组，生成当月预览。
    支持连续推断：如果上月无排班，继续往前找，最多回溯12个月。
    """
    groups = db.query(ShiftGroup).order_by(ShiftGroup.order_id.asc()).all()
    if not groups:
        return {"schedule": [], "start_group_id": None}

    # 获取每个组的值班人数，过滤空组
    from sqlalchemy import func
    group_counts = dict(
        db.query(Employee.group_id, func.count(Employee.id))
        .filter(Employee.state == 1, Employee.group_id.isnot(None))
        .group_by(Employee.group_id)
        .all()
    )
    non_empty_groups = [g for g in groups if group_counts.get(g.id, 0) > 0]
    if not non_empty_groups:
        return {"schedule": [], "start_group_id": None}

    # 从当月往前搜索，找到最近的有排班记录的月份
    start_group_id = non_empty_groups[0].id
    search_year, search_month = year, month
    for _ in range(12):
        if search_month == 1:
            prev_year, prev_month = search_year - 1, 12
        else:
            prev_year, prev_month = search_year, search_month - 1

        prev_record = (
            db.query(Schedule)
            .filter(Schedule.year == prev_year, Schedule.month == prev_month)
            .first()
        )
        if prev_record and prev_record.schedule_json:
            last_item = prev_record.schedule_json[-1]
            last_group_id = last_item.get("group_id")
            if last_group_id:
                group_ids = [g.id for g in non_empty_groups]
                if last_group_id in group_ids:
                    idx = group_ids.index(last_group_id)
                    next_idx = (idx + 1) % len(non_empty_groups)
                    start_group_id = non_empty_groups[next_idx].id
            break
        search_year, search_month = prev_year, prev_month

    import calendar
    from app.models.day_info import DayInfo

    last_day = calendar.monthrange(year, month)[1]
    all_dates = [date(year, month, d) for d in range(1, last_day + 1)]
    day_infos = {
        d.date: d.day_type
        for d in db.query(DayInfo).filter(DayInfo.date.in_(all_dates)).all()
    }

    to_arrange = [d.isoformat() for d in all_dates]

    if not to_arrange:
        return {"schedule": [], "start_group_id": start_group_id}

    start_date = date.fromisoformat(to_arrange[0])
    result = generate_schedule(
        db, year, month, start_group_id, start_date,
        [date.fromisoformat(d) for d in to_arrange]
    )
    return {"schedule": result, "start_group_id": start_group_id}


@router.get("/{year}/{month}", response_model=ScheduleOut | None)
def get_schedule(year: int, month: int, db: Session = Depends(get_db)):
    """获取某月排班数据。不存在返回 null，前端按 null 显示"未排班"。"""
    return (
        db.query(Schedule)
        .filter(Schedule.year == year, Schedule.month == month)
        .first()
    )


def _build_group_snapshot(db: Session, year: int = None, month: int = None) -> dict:
    """构建当前组/员工快照，保存排班时自动写入

    只保存自上次保存以来的变更日志（如果是更新已有排班），
    或首次保存时的全部日志。
    """
    groups = db.query(ShiftGroup).order_by(ShiftGroup.order_id.asc()).all()
    groups_data = []
    for g in groups:
        emps = (
            db.query(Employee)
            .filter(Employee.group_id == g.id)
            .order_by(Employee.order_id.asc())
            .all()
        )
        groups_data.append({
            "id": g.id,
            "name": g.name,
            "order_id": g.order_id,
            "employees": [
                {"id": e.id, "name": e.name, "state": e.state, "order_id": e.order_id}
                for e in emps
            ],
        })

    # 获取变更日志：只取上次保存之后的
    log_query = db.query(EmployeeStateLog).order_by(EmployeeStateLog.changed_at.asc())
    if year and month:
        # 找到上一次保存的快照时间，只取之后的日志
        prev_record = (
            db.query(Schedule)
            .filter(Schedule.year == year, Schedule.month == month)
            .first()
        )
        if prev_record and prev_record.group_snapshot:
            # 取上次快照中最后一条日志的时间
            prev_logs = prev_record.group_snapshot.get("state_logs", [])
            if prev_logs:
                last_log_time = prev_logs[-1].get("changed_at")
                if last_log_time:
                    from datetime import datetime as dt
                    log_query = log_query.filter(
                        EmployeeStateLog.changed_at > dt.fromisoformat(last_log_time)
                    )

    logs = log_query.all()
    logs_data = [
        {
            "employee_id": log.employee_id,
            "employee_name": log.employee_name,
            "old_state": log.old_state,
            "new_state": log.new_state,
            "changed_at": log.changed_at.isoformat() if log.changed_at else None,
        }
        for log in logs
    ]

    return {"groups": groups_data, "state_logs": logs_data}


def _fill_employees(schedule_data: list[dict], db: Session) -> list[dict]:
    """保存前自动填充 employees：如果某天的 employees 为空，按 group_id 查询"""
    for item in schedule_data:
        gid = item.get("group_id")
        emps = item.get("employees", [])
        if (not emps) and gid:
            db_emps = (
                db.query(Employee)
                .filter(Employee.group_id == gid, Employee.state == 1)
                .order_by(Employee.order_id.asc())
                .all()
            )
            item["employees"] = [{"id": e.id, "name": e.name} for e in db_emps]
    return schedule_data


@router.post("/save", response_model=ScheduleOut, dependencies=[Depends(get_current_admin)])
def save_schedule(body: ScheduleSave, db: Session = Depends(get_db)):
    """保存月度排班（覆盖式）

    保存前自动填充 employees 和 group_snapshot。
    已锁定的排班不允许覆盖。
    """
    record = (
        db.query(Schedule)
        .filter(Schedule.year == body.year, Schedule.month == body.month)
        .first()
    )
    if record and record.locked:
        raise HTTPException(status_code=403, detail="排班已锁定，请先解锁再修改")

    raw_data = [item.model_dump() for item in body.schedule]
    filled_data = _fill_employees(raw_data, db)
    snapshot = _build_group_snapshot(db, body.year, body.month)

    if record:
        record.schedule_json = filled_data
        record.group_snapshot = snapshot
    else:
        record = Schedule(
            year=body.year,
            month=body.month,
            schedule_json=filled_data,
            group_snapshot=snapshot,
        )
        db.add(record)
    db.commit()
    db.refresh(record)
    clear_stats_cache(body.year, body.month)
    return record


@router.post("/{year}/{month}/lock", dependencies=[Depends(get_current_admin)])
def lock_schedule(year: int, month: int, db: Session = Depends(get_db)):
    """锁定月度排班"""
    record = (
        db.query(Schedule)
        .filter(Schedule.year == year, Schedule.month == month)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="排班记录不存在")
    record.locked = True
    db.commit()
    return {"locked": True}


@router.post("/{year}/{month}/unlock", dependencies=[Depends(get_current_admin)])
def unlock_schedule(year: int, month: int, db: Session = Depends(get_db)):
    """解锁月度排班"""
    record = (
        db.query(Schedule)
        .filter(Schedule.year == year, Schedule.month == month)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="排班记录不存在")
    record.locked = False
    db.commit()
    return {"locked": False}


@router.delete("/{year}/{month}", dependencies=[Depends(get_current_admin)])
def delete_schedule(year: int, month: int, db: Session = Depends(get_db)):
    """删除已保存的排班记录，恢复为自动预览状态"""
    record = (
        db.query(Schedule)
        .filter(Schedule.year == year, Schedule.month == month)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="排班记录不存在")
    if record.locked:
        raise HTTPException(status_code=403, detail="排班已锁定，请先解锁再删除")
    db.delete(record)
    db.commit()
    clear_stats_cache(year, month)
    return {"deleted": True}

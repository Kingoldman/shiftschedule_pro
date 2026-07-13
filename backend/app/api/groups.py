"""值班组管理接口

注意：batch/sort 路由必须放在 /{group_id} 之前，
否则 "batch" 会被当作 group_id 参数匹配。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.deps import get_current_admin
from app.models.group import ShiftGroup
from app.models.employee import Employee
from app.schemas.group import (
    GroupCreate, GroupUpdate, GroupOut, GroupBatchSort,
)

router = APIRouter()


@router.get("", response_model=list[GroupOut])
def list_groups(db: Session = Depends(get_db)):
    """获取所有组（按 order_id 排序，含成员数量）"""
    groups = db.query(ShiftGroup).order_by(ShiftGroup.order_id.asc()).all()
    counts = dict(
        db.query(Employee.group_id, func.count(Employee.id))
        .filter(Employee.state == 1, Employee.group_id.isnot(None))
        .group_by(Employee.group_id)
        .all()
    )
    result = []
    for g in groups:
        item = GroupOut.model_validate(g)
        item.employee_count = counts.get(g.id, 0)
        result.append(item)
    return result


@router.post("", response_model=GroupOut, dependencies=[Depends(get_current_admin)])
def create_group(body: GroupCreate, db: Session = Depends(get_db)):
    """创建组：order_id 自动分配为最大值+1，不允许手动指定"""
    from app.models.state_log import EmployeeStateLog
    if db.query(ShiftGroup).filter(ShiftGroup.name == body.name).first():
        raise HTTPException(status_code=400, detail="组名已存在")
    # 自动分配 order_id：当前最大值 + 1
    max_order = db.query(func.max(ShiftGroup.order_id)).scalar() or 0
    g = ShiftGroup(name=body.name, order_id=max_order + 1)
    db.add(g)
    db.commit()
    db.refresh(g)
    db.add(EmployeeStateLog(
        employee_id=0,
        employee_name=f"新建组:第{g.order_id}组「{g.name}」",
        old_state=0,
        new_state=g.order_id,
    ))
    db.commit()
    out = GroupOut.model_validate(g)
    out.employee_count = 0
    return out


@router.put("/batch/sort", dependencies=[Depends(get_current_admin)])
def batch_sort_groups(body: GroupBatchSort, db: Session = Depends(get_db)):
    """批量调整组排序，前端拖拽后整体提交"""
    from app.models.state_log import EmployeeStateLog
    for item in body.items:
        g = db.get(ShiftGroup, item["id"])
        if g and g.order_id != item["order_id"]:
            db.add(EmployeeStateLog(
                employee_id=0,
                employee_name=f"组排序变更:第{g.order_id}组「{g.name}」→第{item['order_id']}组",
                old_state=g.order_id,
                new_state=item["order_id"],
            ))
            g.order_id = item["order_id"]
    db.commit()
    return {"msg": "已更新排序"}


@router.post("/import", dependencies=[Depends(get_current_admin)])
def import_groups(body: list[dict], db: Session = Depends(get_db)):
    """批量导入组和员工

    接收格式: [{"name": "甲组", "employees": ["张三", "李四"]}, ...]
    或支持员工对象格式: [{"name": "甲组", "employees": [{"name":"张三","state":1}, {"name":"李四","state":0}]}, ...]
    query参数 mode: append(默认,追加) / overwrite(覆盖,先清空再导入)
    """
    from fastapi import Query as Q
    from app.models.state_log import EmployeeStateLog
    created_groups = 0
    created_employees = 0
    skipped_groups = 0
    skipped_employees = 0

    # 获取现有组名和员工名
    existing_group_names = {g.name for g in db.query(ShiftGroup).all()}
    existing_emp_names = {e.name for e in db.query(Employee).all()}
    max_order = db.query(ShiftGroup).count()

    for idx, item in enumerate(body):
        group_name = item.get("name", f"第{idx + 1}组")
        raw_employees = item.get("employees", [])

        if group_name in existing_group_names:
            skipped_groups += 1
            continue

        max_order += 1
        g = ShiftGroup(name=group_name, order_id=max_order)
        db.add(g)
        db.flush()
        existing_group_names.add(group_name)
        created_groups += 1
        db.add(EmployeeStateLog(
            employee_id=0,
            employee_name=f"导入组:第{g.order_id}组「{g.name}」",
            old_state=0,
            new_state=g.order_id,
        ))

        for order, emp_entry in enumerate(raw_employees, 1):
            # 支持字符串和对象两种格式
            if isinstance(emp_entry, dict):
                emp_name = str(emp_entry.get("name", "")).strip()
                emp_state = int(emp_entry.get("state", 1))
            else:
                emp_name = str(emp_entry).strip()
                emp_state = 1
            if not emp_name or emp_name in existing_emp_names:
                skipped_employees += 1
                continue
            # 不值班员工 state=0，不分配组；值班员工 state=1，分配到当前组
            group_id = g.id if emp_state == 1 else None
            e = Employee(name=emp_name, order_id=order, state=emp_state, group_id=group_id)
            db.add(e)
            db.flush()  # 确保 e.id 已生成，避免 EmployeeStateLog.employee_id 为 None
            existing_emp_names.add(emp_name)
            created_employees += 1
            db.add(EmployeeStateLog(
                employee_id=e.id,
                employee_name=f"导入员工:{e.name}，分配至第{g.order_id}组「{g.name}」" if emp_state == 1 else f"导入员工:{e.name}（不值班）",
                old_state=0,
                new_state=emp_state,
            ))

    db.commit()
    return {
        "msg": f"导入完成：新建 {created_groups} 组、{created_employees} 人",
        "created_groups": created_groups,
        "created_employees": created_employees,
        "skipped_groups": skipped_groups,
        "skipped_employees": skipped_employees,
    }


@router.post("/import-overwrite", dependencies=[Depends(get_current_admin)])
def import_groups_overwrite(body: list[dict], db: Session = Depends(get_db)):
    """覆盖导入：先删除所有现有组和员工，再导入新数据

    接收格式: [{"name": "甲组", "employees": ["张三", "李四"]}, ...]
    或支持员工对象格式: [{"name": "甲组", "employees": [{"name":"张三","state":1}, {"name":"李四","state":0}]}, ...]
    """
    from app.models.state_log import EmployeeStateLog

    # 先删除所有员工（必须先删员工，因为外键依赖组）
    db.query(EmployeeStateLog).delete()
    db.query(Employee).delete()
    db.query(ShiftGroup).delete()
    db.flush()

    created_groups = 0
    created_employees = 0

    for idx, item in enumerate(body):
        group_name = item.get("name", f"第{idx + 1}组")
        raw_employees = item.get("employees", [])

        g = ShiftGroup(name=group_name, order_id=idx + 1)
        db.add(g)
        db.flush()
        created_groups += 1
        db.add(EmployeeStateLog(
            employee_id=0,
            employee_name=f"导入组:第{g.order_id}组「{g.name}」",
            old_state=0,
            new_state=g.order_id,
        ))

        for order, emp_entry in enumerate(raw_employees, 1):
            # 支持字符串和对象两种格式
            if isinstance(emp_entry, dict):
                emp_name = str(emp_entry.get("name", "")).strip()
                emp_state = int(emp_entry.get("state", 1))
            else:
                emp_name = str(emp_entry).strip()
                emp_state = 1
            if not emp_name:
                continue
            # 不值班员工 state=0，不分配组；值班员工 state=1，分配到当前组
            group_id = g.id if emp_state == 1 else None
            e = Employee(name=emp_name, order_id=order, state=emp_state, group_id=group_id)
            db.add(e)
            db.flush()
            created_employees += 1
            db.add(EmployeeStateLog(
                employee_id=e.id,
                employee_name=f"导入员工:{e.name}，分配至第{g.order_id}组「{g.name}」" if emp_state == 1 else f"导入员工:{e.name}（不值班）",
                old_state=0,
                new_state=emp_state,
            ))

    db.commit()
    return {
        "msg": f"覆盖导入完成：新建 {created_groups} 组、{created_employees} 人",
        "created_groups": created_groups,
        "created_employees": created_employees,
    }


@router.put("/{group_id}", response_model=GroupOut, dependencies=[Depends(get_current_admin)])
def update_group(group_id: int, body: GroupUpdate, db: Session = Depends(get_db)):
    """更新组信息（只更新名称，order_id 通过拖拽 batch/sort 接口调整）"""
    from app.models.state_log import EmployeeStateLog
    g = db.get(ShiftGroup, group_id)
    if not g:
        raise HTTPException(status_code=404, detail="组不存在")
    if body.name and body.name != g.name:
        if db.query(ShiftGroup).filter(ShiftGroup.name == body.name).first():
            raise HTTPException(status_code=400, detail="组名已存在")
        db.add(EmployeeStateLog(
            employee_id=0,
            employee_name=f"组更名:第{g.order_id}组「{g.name}」→「{body.name}」",
            old_state=0,
            new_state=0,
        ))
        g.name = body.name
    db.commit()
    db.refresh(g)
    out = GroupOut.model_validate(g)
    out.employee_count = db.query(func.count(Employee.id)).filter(Employee.group_id == g.id, Employee.state == 1).scalar() or 0
    return out


@router.delete("/{group_id}", dependencies=[Depends(get_current_admin)])
def delete_group(group_id: int, db: Session = Depends(get_db)):
    """删除组（员工 group_id 显式置空，移入未分组；剩余组 order_id 递补重排）"""
    from app.models.state_log import EmployeeStateLog
    g = db.get(ShiftGroup, group_id)
    if not g:
        raise HTTPException(status_code=404, detail="组不存在")
    affected = db.query(Employee).filter(Employee.group_id == group_id).all()
    for emp in affected:
        emp.group_id = None
    db.add(EmployeeStateLog(
        employee_id=0,
        employee_name=f"删除组:第{g.order_id}组「{g.name}」（{len(affected)}名组员移入未分组）",
        old_state=g.order_id,
        new_state=-1,
    ))
    db.delete(g)
    db.flush()
    # 重排剩余组的 order_id，使其从 1 开始连续递增
    remaining = db.query(ShiftGroup).order_by(ShiftGroup.order_id.asc()).all()
    for i, grp in enumerate(remaining, 1):
        grp.order_id = i
    db.commit()
    return {"msg": "已删除", "affected_count": len(affected)}

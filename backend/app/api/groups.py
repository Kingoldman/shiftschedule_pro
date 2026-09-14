"""值班组管理接口

注意：batch/sort 路由必须放在 /{group_id} 之前，
否则 "batch" 会被当作 group_id 参数匹配。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.deps import get_current_admin
from app.models.admin import Admin
from app.models.group import ShiftGroup
from app.models.employee import Employee
from app.models.state_log import EmployeeStateLog
from app.models.audit_log import AuditLog
from app.schemas.group import (
    GroupCreate, GroupUpdate, GroupOut, GroupBatchSort,
)

router = APIRouter()


def _add_audit(
    db: Session,
    current: Admin | None,
    action: str,
    target_id: str = "",
    detail: str | None = None,
) -> None:
    """记录组相关的操作审计日志

    此前组事件被写进 EmployeeStateLog 并用 employee_id=0 标记，语义混乱
    且记不下操作者。组不是员工，这里统一改走独立的审计表。
    """
    db.add(
        AuditLog(
            actor=current.username if current else "",
            action=action,
            target_type="group",
            target_id=target_id,
            detail=detail,
        )
    )


@router.get(
    "",
    response_model=list[GroupOut],
    dependencies=[Depends(get_current_admin)],
)
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


@router.post("", response_model=GroupOut)
def create_group(
    body: GroupCreate,
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """创建组：order_id 自动分配为最大值+1，不允许手动指定"""
    if db.query(ShiftGroup).filter(ShiftGroup.name == body.name).first():
        raise HTTPException(status_code=400, detail="组名已存在")
    # 自动分配 order_id：当前最大值 + 1
    max_order = db.query(func.max(ShiftGroup.order_id)).scalar() or 0
    g = ShiftGroup(name=body.name, order_id=max_order + 1)
    db.add(g)
    db.commit()
    db.refresh(g)
    _add_audit(
        db,
        current,
        "create",
        target_id=str(g.id),
        detail=f"新建组:第{g.order_id}组「{g.name}」",
    )
    db.commit()
    out = GroupOut.model_validate(g)
    out.employee_count = 0
    return out


@router.put("/batch/sort")
def batch_sort_groups(
    body: GroupBatchSort,
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """批量调整组排序，前端拖拽后整体提交"""
    changed = 0
    for item in body.items:
        g = db.get(ShiftGroup, item["id"])
        if g and g.order_id != item["order_id"]:
            _add_audit(
                db,
                current,
                "sort",
                target_id=str(g.id),
                detail=f"组排序变更:第{g.order_id}组「{g.name}」→第{item['order_id']}组",
            )
            g.order_id = item["order_id"]
            changed += 1
    if changed:
        _add_audit(
            db, current, "sort", target_id="batch", detail=f"批量调整 {changed} 个组的顺序"
        )
    db.commit()
    return {"msg": "已更新排序"}


# ---------------------------------------------------------------------------
# 导入：追加与覆盖两种模式共用同一套写入逻辑，仅前置处理不同
# ---------------------------------------------------------------------------


def _parse_employee_entry(entry) -> tuple[str, int]:
    """解析导入的员工条目，支持字符串与对象两种格式

    返回 (姓名, 状态)。姓名为空表示跳过该条。
    状态做容错：非法输入按"值班(1)"处理，避免 int() 抛 ValueError 直接 500。
    """
    if isinstance(entry, dict):
        name = str(entry.get("name", "")).strip()
        try:
            state = int(entry.get("state", 1))
        except (TypeError, ValueError):
            state = 1
        if state not in (0, 1):
            state = 1
        return name, state
    return str(entry).strip(), 1


def _create_group_with_employees(
    db: Session,
    current: Admin,
    group_name: str,
    order_id: int,
    raw_employees: list,
    existing_emp_names: set[str],
) -> tuple[ShiftGroup, int, int]:
    """创建一个组及其员工，返回 (组, 新建员工数, 跳过员工数)

    已存在的员工名会被跳过并计入 skipped（追加模式下用于提示用户重名）。
    覆盖模式调用方已做唯一性预校验，正常情况下不会触发跳过。
    """
    g = ShiftGroup(name=group_name, order_id=order_id)
    db.add(g)
    db.flush()

    _add_audit(
        db,
        current,
        "import",
        target_id=str(g.id),
        detail=f"导入组:第{g.order_id}组「{g.name}」",
    )

    created = 0
    skipped = 0
    for order, emp_entry in enumerate(raw_employees, 1):
        emp_name, emp_state = _parse_employee_entry(emp_entry)
        if not emp_name:
            continue
        if emp_name in existing_emp_names:
            skipped += 1
            continue
        # 不值班员工 state=0，不分配组；值班员工 state=1，分配到当前组
        group_id = g.id if emp_state == 1 else None
        e = Employee(name=emp_name, order_id=order, state=emp_state, group_id=group_id)
        db.add(e)
        db.flush()  # 确保 e.id 已生成，避免 EmployeeStateLog.employee_id 为 None
        existing_emp_names.add(emp_name)
        created += 1
        db.add(EmployeeStateLog(
            employee_id=e.id,
            employee_name=(
                f"导入员工:{e.name}，分配至第{g.order_id}组「{g.name}」"
                if emp_state == 1
                else f"导入员工:{e.name}（不值班）"
            ),
            old_state=0,
            new_state=emp_state,
        ))
    return g, created, skipped


@router.post("/import")
def import_groups(
    body: list[dict],
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """批量导入组和员工（追加模式）

    接收格式: [{"name": "甲组", "employees": ["张三", "李四"]}, ...]
    或员工对象格式: [{"name": "甲组", "employees": [{"name":"张三","state":1}, ...]}, ...]

    已存在的组名/员工名会被跳过，不覆盖既有数据。
    """
    created_groups = 0
    created_employees = 0
    skipped_groups = 0
    skipped_employees = 0

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
        _, created, skipped = _create_group_with_employees(
            db, current, group_name, max_order, raw_employees, existing_emp_names
        )
        existing_group_names.add(group_name)
        created_groups += 1
        created_employees += created
        skipped_employees += skipped

    db.commit()
    return {
        "msg": f"导入完成：新建 {created_groups} 组、{created_employees} 人",
        "created_groups": created_groups,
        "created_employees": created_employees,
        "skipped_groups": skipped_groups,
        "skipped_employees": skipped_employees,
    }


@router.post("/import-overwrite")
def import_groups_overwrite(
    body: list[dict],
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """覆盖导入：先删除所有现有组和员工，再导入新数据

    接收格式同 /import。组名与员工名都要求在数据内部唯一，否则直接拒绝。

    注意：这是高危操作，会清空全部人员与组。
    """
    # 预校验：组名不能重复（ShiftGroup.name 有唯一约束）
    seen_group_names: set[str] = set()
    for idx, item in enumerate(body):
        gname = item.get("name", f"第{idx + 1}组")
        if gname in seen_group_names:
            raise HTTPException(
                status_code=400,
                detail=f"导入数据中存在重复组名「{gname}」，请修改后重试"
            )
        seen_group_names.add(gname)

    # 预校验：员工名在覆盖模式下也要求内部唯一
    seen_emp_names: set[str] = set()
    for item in body:
        for emp_entry in item.get("employees", []):
            emp_name, _ = _parse_employee_entry(emp_entry)
            if not emp_name:
                continue
            if emp_name in seen_emp_names:
                raise HTTPException(
                    status_code=400,
                    detail=f"导入数据中存在重复员工名「{emp_name}」，请修改后重试"
                )
            seen_emp_names.add(emp_name)

    try:
        # 先删除所有员工（必须先删员工，因为外键依赖组）
        db.query(EmployeeStateLog).delete()
        db.query(Employee).delete()
        db.query(ShiftGroup).delete()
        db.flush()

        created_groups = 0
        created_employees = 0
        existing_emp_names: set[str] = set()

        for idx, item in enumerate(body):
            group_name = item.get("name", f"第{idx + 1}组")
            raw_employees = item.get("employees", [])

            _, created, _ = _create_group_with_employees(
                db, current, group_name, idx + 1, raw_employees, existing_emp_names
            )
            created_groups += 1
            created_employees += created

        _add_audit(
            db,
            current,
            "import_overwrite",
            target_id="all",
            detail=(
                f"覆盖导入：清空原有数据，新建 {created_groups} 组、"
                f"{created_employees} 人"
            ),
        )
        db.commit()
    except IntegrityError as e:
        # 唯一约束冲突时回滚，避免 session 处于不可用状态污染后续请求
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"导入失败（数据库约束冲突）：{e.orig}"
        )
    except Exception:
        # 其他异常也回滚，保持 session 干净
        db.rollback()
        raise

    return {
        "msg": f"覆盖导入完成：新建 {created_groups} 组、{created_employees} 人",
        "created_groups": created_groups,
        "created_employees": created_employees,
    }


@router.put("/{group_id}", response_model=GroupOut)
def update_group(
    group_id: int,
    body: GroupUpdate,
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """更新组信息（只更新名称，order_id 通过拖拽 batch/sort 接口调整）"""
    g = db.get(ShiftGroup, group_id)
    if not g:
        raise HTTPException(status_code=404, detail="组不存在")
    if body.name and body.name != g.name:
        if db.query(ShiftGroup).filter(ShiftGroup.name == body.name).first():
            raise HTTPException(status_code=400, detail="组名已存在")
        _add_audit(
            db,
            current,
            "update",
            target_id=str(g.id),
            detail=f"组更名:第{g.order_id}组「{g.name}」→「{body.name}」",
        )
        g.name = body.name
    db.commit()
    db.refresh(g)
    out = GroupOut.model_validate(g)
    out.employee_count = (
        db.query(func.count(Employee.id))
        .filter(Employee.group_id == g.id, Employee.state == 1)
        .scalar()
        or 0
    )
    return out


@router.delete("/{group_id}")
def delete_group(
    group_id: int,
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """删除组（员工 group_id 显式置空，移入未分组；剩余组 order_id 递补重排）"""
    g = db.get(ShiftGroup, group_id)
    if not g:
        raise HTTPException(status_code=404, detail="组不存在")
    affected = db.query(Employee).filter(Employee.group_id == group_id).all()
    for emp in affected:
        emp.group_id = None
    _add_audit(
        db,
        current,
        "delete",
        target_id=str(g.id),
        detail=(
            f"删除组:第{g.order_id}组「{g.name}」"
            f"（{len(affected)}名组员移入未分组）"
        ),
    )
    db.delete(g)
    db.flush()
    # 重排剩余组的 order_id，使其从 1 开始连续递增
    remaining = db.query(ShiftGroup).order_by(ShiftGroup.order_id.asc()).all()
    for i, grp in enumerate(remaining, 1):
        grp.order_id = i
    db.commit()
    return {"msg": "已删除", "affected_count": len(affected)}

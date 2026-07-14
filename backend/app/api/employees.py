"""员工管理接口

注意：batch/sort 路由必须放在 /{emp_id} 之前。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_admin
from app.models.employee import Employee
from app.models.group import ShiftGroup
from app.models.state_log import EmployeeStateLog
from app.schemas.employee import (
    EmployeeCreate, EmployeeUpdate, EmployeeOut, EmployeeBatchSort,
)

router = APIRouter()


@router.get("", response_model=list[EmployeeOut])
def list_employees(
    group_id: int | None = Query(None, description="按组筛选"),
    state: int | None = Query(None, description="按状态筛选 1值班 0不值班"),
    keyword: str | None = Query(None, description="姓名搜索"),
    db: Session = Depends(get_db),
):
    """获取员工列表，支持按组、状态、姓名筛选"""
    q = db.query(Employee)
    if group_id is not None:
        q = q.filter(Employee.group_id == group_id)
    if state is not None:
        q = q.filter(Employee.state == state)
    if keyword:
        q = q.filter(Employee.name.like(f"%{keyword}%"))
    emps = q.order_by(Employee.group_id.asc(), Employee.order_id.asc()).all()

    group_map = {g.id: g.name for g in db.query(ShiftGroup).all()}

    result = []
    for e in emps:
        out = EmployeeOut.model_validate(e)
        out.group_name = group_map.get(e.group_id) if e.group_id else None
        result.append(out)
    return result


@router.post("", response_model=EmployeeOut, dependencies=[Depends(get_current_admin)])
def create_employee(body: EmployeeCreate, db: Session = Depends(get_db)):
    """新增员工"""
    # 重名校验：同名人员不允许创建
    if db.query(Employee).filter(Employee.name == body.name).first():
        raise HTTPException(status_code=400, detail="姓名已存在，请修改后重试")
    if body.group_id and not db.get(ShiftGroup, body.group_id):
        raise HTTPException(status_code=400, detail="所选组不存在")
    # 不值班时不能分配组
    if body.state == 0 and body.group_id:
        raise HTTPException(status_code=400, detail="不值班状态无法分配组")
    e = Employee(**body.model_dump())
    if e.state == 0:
        e.group_id = None
    db.add(e)
    db.commit()
    db.refresh(e)
    # 记录新增日志
    gname = db.get(ShiftGroup, e.group_id).name if e.group_id and db.get(ShiftGroup, e.group_id) else None
    desc = f"新增员工:{e.name}" + (f"，分配至第{db.get(ShiftGroup, e.group_id).order_id}组「{gname}」" if gname else "")
    db.add(EmployeeStateLog(
        employee_id=e.id,
        employee_name=desc,
        old_state=0,
        new_state=e.state,
    ))
    db.commit()
    return EmployeeOut.model_validate(e)


# batch/sort 必须在 /{emp_id} 之前注册
@router.put("/batch/sort", dependencies=[Depends(get_current_admin)])
def batch_sort_employees(body: EmployeeBatchSort, db: Session = Depends(get_db)):
    """批量调整员工排序/分组，前端拖拽后整体提交"""
    group_map = {g.id: g for g in db.query(ShiftGroup).all()}
    for item in body.items:
        e = db.get(Employee, item["id"])
        if e:
            if "order_id" in item and item["order_id"] != e.order_id:
                db.add(EmployeeStateLog(
                    employee_id=e.id,
                    employee_name=f"排序变更:{e.name}，{e.order_id}→{item['order_id']}",
                    old_state=e.order_id,
                    new_state=item["order_id"],
                ))
                e.order_id = item["order_id"]
            if "group_id" in item and item.get("group_id") != e.group_id:
                old_g = group_map.get(e.group_id)
                new_g = group_map.get(item.get("group_id"))
                old_desc = f"第{old_g.order_id}组「{old_g.name}」" if old_g else "未分组"
                new_desc = f"第{new_g.order_id}组「{new_g.name}」" if new_g else "未分组"
                db.add(EmployeeStateLog(
                    employee_id=e.id,
                    employee_name=f"组变更:{e.name}，{old_desc}→{new_desc}",
                    old_state=0,
                    new_state=0,
                ))
                e.group_id = item["group_id"]
    db.commit()
    return {"msg": "已更新"}


@router.put("/{emp_id}", response_model=EmployeeOut, dependencies=[Depends(get_current_admin)])
def update_employee(emp_id: int, body: EmployeeUpdate, db: Session = Depends(get_db)):
    """更新员工信息"""
    e = db.get(Employee, emp_id)
    if not e:
        raise HTTPException(status_code=404, detail="员工不存在")
    data = body.model_dump(exclude_unset=True)
    # 重名校验：排除自身
    if "name" in data and data["name"] != e.name:
        if db.query(Employee).filter(Employee.name == data["name"], Employee.id != emp_id).first():
            raise HTTPException(status_code=400, detail="姓名已存在，请修改后重试")
    # 处理 group_id：前端传 null 表示清除分组
    if "group_id" in data:
        gid = data["group_id"]
        if gid is not None and not db.get(ShiftGroup, gid):
            raise HTTPException(status_code=400, detail="所选组不存在")

    # 不值班时强制清除分组
    new_state = data.get("state", e.state)
    if new_state == 0 and data.get("group_id") is not None:
        data["group_id"] = None

    # 记录变更日志
    old_state = e.state
    old_group_id = e.group_id
    old_order_id = e.order_id

    group_map = {g.id: g for g in db.query(ShiftGroup).all()}

    for k, v in data.items():
        setattr(e, k, v)

    if "state" in data and data["state"] != old_state:
        state_desc = "值班" if data["state"] == 1 else "不值班"
        old_desc = "值班" if old_state == 1 else "不值班"
        db.add(EmployeeStateLog(
            employee_id=e.id,
            employee_name=f"状态变更:{e.name}，{old_desc}→{state_desc}",
            old_state=old_state,
            new_state=data["state"],
        ))
    if "group_id" in data and data.get("group_id") != old_group_id:
        old_g = group_map.get(old_group_id)
        new_g = group_map.get(data.get("group_id"))
        old_gdesc = f"第{old_g.order_id}组「{old_g.name}」" if old_g else "未分组"
        new_gdesc = f"第{new_g.order_id}组「{new_g.name}」" if new_g else "未分组"
        db.add(EmployeeStateLog(
            employee_id=e.id,
            employee_name=f"组变更:{e.name}，{old_gdesc}→{new_gdesc}",
            old_state=0,
            new_state=0,
        ))
    if "order_id" in data and data["order_id"] != old_order_id:
        db.add(EmployeeStateLog(
            employee_id=e.id,
            employee_name=f"排序变更:{e.name}，{old_order_id}→{data['order_id']}",
            old_state=old_order_id,
            new_state=data["order_id"],
        ))

    db.commit()
    db.refresh(e)
    return EmployeeOut.model_validate(e)


@router.delete("/{emp_id}", dependencies=[Depends(get_current_admin)])
def delete_employee(emp_id: int, db: Session = Depends(get_db)):
    """删除员工"""
    e = db.get(Employee, emp_id)
    if not e:
        raise HTTPException(status_code=404, detail="员工不存在")
    # 记录删除日志
    gname = db.get(ShiftGroup, e.group_id).name if e.group_id and db.get(ShiftGroup, e.group_id) else None
    desc = f"删除员工:{e.name}" + (f"，原属第{db.get(ShiftGroup, e.group_id).order_id}组「{gname}」" if gname else "")
    db.add(EmployeeStateLog(
        employee_id=e.id,
        employee_name=desc,
        old_state=e.state,
        new_state=-1,
    ))
    db.delete(e)
    db.commit()
    return {"msg": "已删除"}

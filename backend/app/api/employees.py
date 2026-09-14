"""员工管理接口

注意：batch/sort 路由必须放在 /{emp_id} 之前。
"""
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_admin
from app.core.security import hash_password
from app.models.admin import Admin
from app.models.employee import Employee
from app.models.group import ShiftGroup
from app.models.state_log import EmployeeStateLog
from app.models.audit_log import AuditLog
from app.models.employee_account import EmployeeAccount
from app.schemas.employee import (
    EmployeeCreate, EmployeeUpdate, EmployeeOut, EmployeeBatchSort,
    EmployeeAccountIn, EmployeeAccountOut, EmployeeFeedAction,
)

router = APIRouter()


def _add_audit(
    db: Session,
    current: Admin | None,
    action: str,
    target_id: str = "",
    detail: str | None = None,
) -> None:
    """记录一条操作审计日志"""
    db.add(
        AuditLog(
            actor=current.username if current else "",
            action=action,
            target_type="employee",
            target_id=target_id,
            detail=detail,
        )
    )


@router.get(
    "",
    response_model=list[EmployeeOut],
    dependencies=[Depends(get_current_admin)],
)
def list_employees(
    response: Response,
    group_id: int | None = Query(None, description="按组筛选"),
    state: int | None = Query(None, description="按状态筛选 1值班 0不值班"),
    keyword: str | None = Query(None, description="姓名搜索"),
    page: int | None = Query(None, ge=1, description="页码，从 1 开始；不传则返回全部"),
    page_size: int | None = Query(
        None, ge=1, le=500, description="每页条数；需与 page 同时使用"
    ),
    db: Session = Depends(get_db),
):
    """获取员工列表，支持按组、状态、姓名筛选，并支持可选分页

    说明：分页是可选的。人员管理页需要一次性拿到全量数据做拖拽排序，
    因此默认不分页、保持与旧版一致的返回结构；数据量变大后可传
    page/page_size 启用分页，总条数通过响应头 X-Total-Count 返回。
    """
    q = db.query(Employee)
    if group_id is not None:
        q = q.filter(Employee.group_id == group_id)
    if state is not None:
        q = q.filter(Employee.state == state)
    if keyword:
        q = q.filter(Employee.name.like(f"%{keyword}%"))

    total = q.count()
    response.headers["X-Total-Count"] = str(total)

    q = q.order_by(Employee.group_id.asc(), Employee.order_id.asc())
    if page is not None and page_size is not None:
        q = q.offset((page - 1) * page_size).limit(page_size)

    emps = q.all()

    group_map = {g.id: g.name for g in db.query(ShiftGroup).all()}

    result = []
    for e in emps:
        out = EmployeeOut.model_validate(e)
        out.group_name = group_map.get(e.group_id) if e.group_id else None
        result.append(out)
    return result


@router.post("", response_model=EmployeeOut)
def create_employee(
    body: EmployeeCreate,
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
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
    # 记录新增日志：只查一次组，避免原实现里对 db.get 的三次重复往返
    group = db.get(ShiftGroup, e.group_id) if e.group_id else None
    desc = f"新增员工:{e.name}"
    if group:
        desc += f"，分配至第{group.order_id}组「{group.name}」"
    db.add(EmployeeStateLog(
        employee_id=e.id,
        employee_name=desc,
        old_state=0,
        new_state=e.state,
    ))
    _add_audit(db, current, "create", target_id=str(e.id), detail=desc)
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


@router.put("/{emp_id}", response_model=EmployeeOut)
def update_employee(
    emp_id: int,
    body: EmployeeUpdate,
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
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

    # 不值班时强制清除分组（无论请求中是否带 group_id，与 create 逻辑保持一致）
    new_state = data.get("state", e.state)
    if new_state == 0:
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

    changes = [k for k in ("name", "state", "group_id", "order_id") if k in data]
    if changes:
        _add_audit(
            db,
            current,
            "update",
            target_id=str(e.id),
            detail=f"更新员工:{e.name}（{'、'.join(changes)}）",
        )
    db.commit()
    db.refresh(e)
    return EmployeeOut.model_validate(e)


@router.delete("/{emp_id}")
def delete_employee(
    emp_id: int,
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """删除员工

    注意：删除员工**不会**删除其历史值班记录与统计——
    排班数据以 JSON 快照形式保存在 schedule 表中（含 id 与姓名），
    个人查询页仍能查到该员工的历史记录。
    employee_state_log 同为留档表，其日志也会保留。
    """
    e = db.get(Employee, emp_id)
    if not e:
        raise HTTPException(status_code=404, detail="员工不存在")
    # 记录删除日志：只查一次组
    group = db.get(ShiftGroup, e.group_id) if e.group_id else None
    desc = f"删除员工:{e.name}"
    if group:
        desc += f"，原属第{group.order_id}组「{group.name}」"
    db.add(EmployeeStateLog(
        employee_id=e.id,
        employee_name=desc,
        old_state=e.state,
        new_state=-1,
    ))
    _add_audit(db, current, "delete", target_id=str(e.id), detail=desc)
    db.delete(e)
    db.commit()
    return {"msg": "已删除"}


# ---------------------------------------------------------------------------
# 员工自助账号管理
# ---------------------------------------------------------------------------

def _get_employee_or_404(emp_id: int, db: Session) -> Employee:
    e = db.get(Employee, emp_id)
    if not e:
        raise HTTPException(status_code=404, detail="员工不存在")
    return e


@router.get("/accounts")
def list_employee_accounts(
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """批量查询员工账号状态

    单独提供批量接口是为了避免列表页对每个员工发一次请求（N+1）。
    """
    accounts = db.query(EmployeeAccount).all()
    return [
        {
            "employee_id": a.employee_id,
            "username": a.username,
            "is_active": a.is_active,
            "last_login_at": a.last_login_at.isoformat() if a.last_login_at else None,
        }
        for a in accounts
    ]


def _validate_username(username: str, db: Session, exclude_account_id: int | None) -> str:
    """用户名需全局唯一：员工账号之间、以及与管理员账号都不能重名

    登录是统一入口（先查 admin 再查 employee_account），
    若两边重名，admin 会永久抢占该用户名，员工将永远登不进来。
    """
    username = username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if db.query(EmployeeAccount).filter(
        EmployeeAccount.username == username,
        EmployeeAccount.id != exclude_account_id,
    ).first():
        raise HTTPException(status_code=400, detail="用户名已被占用")
    if db.query(Admin).filter(Admin.username == username).first():
        raise HTTPException(status_code=400, detail="用户名与管理员账号冲突")
    return username


def _feed_fields(acc: EmployeeAccount | None) -> dict:
    """组装订阅地址的响应字段（相对路径，前端自行拼接 origin）"""
    if not acc or not acc.feed_token:
        return {"feed_path": None, "feed_updated_at": None}
    return {
        "feed_path": f"/api/me/feed/{acc.feed_token}.ics",
        "feed_updated_at": acc.feed_token_created_at,
    }


@router.get("/{emp_id}/account", response_model=EmployeeAccountOut)
def get_employee_account(
    emp_id: int,
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """查询员工是否已开通自助账号"""
    e = _get_employee_or_404(emp_id, db)
    acc = (
        db.query(EmployeeAccount)
        .filter(EmployeeAccount.employee_id == emp_id)
        .first()
    )
    if not acc:
        return EmployeeAccountOut(exists=False, employee_id=emp_id, employee_name=e.name)
    return EmployeeAccountOut(
        exists=True,
        employee_id=emp_id,
        employee_name=e.name,
        username=acc.username,
        is_active=acc.is_active,
        last_login_at=acc.last_login_at,
        **_feed_fields(acc),
    )


@router.post("/{emp_id}/account/feed-token")
def manage_employee_feed_token(
    emp_id: int,
    body: EmployeeFeedAction,
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员代为开通 / 重发 / 停用员工的日历订阅

    员工自己也能在「我的值班」页操作，这里是为"员工还没登录过"或
    "帮同事代配手机日历"的场景准备的。
    """
    e = _get_employee_or_404(emp_id, db)
    acc = (
        db.query(EmployeeAccount)
        .filter(EmployeeAccount.employee_id == emp_id)
        .first()
    )
    if not acc:
        raise HTTPException(status_code=404, detail="该员工尚未开通账号")

    action = (body.action or "issue").strip().lower()
    if action == "revoke":
        if not acc.feed_token:
            raise HTTPException(status_code=400, detail="该员工尚未开启日历订阅")
        acc.feed_token = None
        acc.feed_token_created_at = None
        detail = f"停用员工 {e.name} 的日历订阅，旧链接已失效"
    elif action in ("issue", "rotate"):
        if action == "issue" and acc.feed_token:
            raise HTTPException(status_code=400, detail="已开启订阅，如需更换请重新生成")
        acc.feed_token = secrets.token_urlsafe(24)
        acc.feed_token_created_at = datetime.now(timezone.utc).replace(tzinfo=None)
        verb = "生成" if action == "issue" else "重新生成"
        detail = f"{verb}员工 {e.name} 的日历订阅链接"
    else:
        raise HTTPException(status_code=400, detail="不支持的操作")

    db.add(
        AuditLog(
            actor=current.username,
            action=f"feed_{action}",
            target_type="employee_account",
            target_id=str(emp_id),
            detail=detail,
        )
    )
    db.commit()
    return {"msg": detail, **_feed_fields(acc)}


@router.put("/{emp_id}/account", response_model=EmployeeAccountOut)
def upsert_employee_account(
    emp_id: int,
    body: EmployeeAccountIn,
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """开通或修改员工自助账号

    - 首次开通必须提供用户名和密码；
    - 已存在时可只重置密码、或只改启用状态；
    - 重置密码会自增 token_version，使该员工已登录的会话立即失效。
    """
    e = _get_employee_or_404(emp_id, db)
    acc = (
        db.query(EmployeeAccount)
        .filter(EmployeeAccount.employee_id == emp_id)
        .first()
    )

    if acc is None:
        if not body.username or not body.password:
            raise HTTPException(status_code=400, detail="首次开通需同时设置用户名和密码")
        username = _validate_username(body.username, db, exclude_account_id=None)
        acc = EmployeeAccount(
            employee_id=emp_id,
            username=username,
            hashed_password=hash_password(body.password),
            is_active=body.is_active if body.is_active is not None else True,
        )
        db.add(acc)
        db.flush()
        action = "创建"
        detail = f"为员工 {e.name} 开通自助账号「{username}」"
    else:
        action = "修改"
        parts = []
        if body.username and body.username.strip() != acc.username:
            acc.username = _validate_username(body.username, db, acc.id)
            parts.append(f"用户名改为「{acc.username}」")
        if body.password:
            acc.hashed_password = hash_password(body.password)
            # 重置密码即踢下线：避免旧密码持有者继续访问
            acc.token_version = (acc.token_version or 1) + 1
            parts.append("重置密码")
        if body.is_active is not None and body.is_active != acc.is_active:
            acc.is_active = body.is_active
            parts.append("启用" if body.is_active else "停用")
        if not parts:
            raise HTTPException(status_code=400, detail="没有需要更新的内容")
        detail = f"修改员工 {e.name} 的自助账号：" + "、".join(parts)

    db.add(
        AuditLog(
            actor=current.username,
            action=f"account_{action}",
            target_type="employee_account",
            target_id=str(emp_id),
            detail=detail,
        )
    )
    db.commit()
    db.refresh(acc)
    return EmployeeAccountOut(
        exists=True,
        employee_id=emp_id,
        employee_name=e.name,
        username=acc.username,
        is_active=acc.is_active,
        last_login_at=acc.last_login_at,
        **_feed_fields(acc),
    )


@router.delete("/{emp_id}/account")
def delete_employee_account(
    emp_id: int,
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """注销员工自助账号（不影响员工本人与其历史值班记录）"""
    e = _get_employee_or_404(emp_id, db)
    acc = (
        db.query(EmployeeAccount)
        .filter(EmployeeAccount.employee_id == emp_id)
        .first()
    )
    if not acc:
        raise HTTPException(status_code=404, detail="该员工尚未开通账号")
    db.delete(acc)
    db.add(
        AuditLog(
            actor=current.username,
            action="account_delete",
            target_type="employee_account",
            target_id=str(emp_id),
            detail=f"注销员工 {e.name} 的自助账号「{acc.username}」",
        )
    )
    db.commit()
    return {"msg": "账号已注销"}

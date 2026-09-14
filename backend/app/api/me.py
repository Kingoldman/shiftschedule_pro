"""员工自助接口（只读）

设计原则：**只返回本人数据，绝不返回整月排班**。
管理员可以在排班页看到全量安排，员工账号不行——所以这里不复用
`/schedule/{year}/{month}`，而是从排班快照里把"我"的那几行挑出来单独返回。

可见性边界：只有**已保存**的月份才对员工可见。排班保存即锁定，
未保存的草稿不会出现在 `/me/months` 里，天然形成"发布"语义。
"""
import calendar
import secrets
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_employee
from app.models.employee_account import EmployeeAccount
from app.models.schedule import Schedule
from app.services.ics_service import build_ics

router = APIRouter()

# 订阅链接的路径前缀，与 api/__init__.py 中的 /api + /me 前缀对应
_FEED_PATH_PREFIX = "/api/me/feed/"

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


# ---------------------------------------------------------------------------
# 日历订阅（.ics）
# ---------------------------------------------------------------------------

def _new_feed_token() -> str:
    """生成订阅令牌：32 字符 URL 安全串，不可猜测"""
    return secrets.token_urlsafe(24)


def _account_or_404(user: CurrentUser, db: Session) -> EmployeeAccount:
    acc = db.get(EmployeeAccount, user.user_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    return acc


def _feed_payload(acc: EmployeeAccount) -> dict:
    return {
        "enabled": bool(acc.feed_token),
        "path": f"{_FEED_PATH_PREFIX}{acc.feed_token}.ics" if acc.feed_token else None,
        "updated_at": (
            acc.feed_token_created_at.isoformat() if acc.feed_token_created_at else None
        ),
    }


def _collect_events(
    db: Session, employee_id: int, year: int | None = None, month: int | None = None
) -> list[dict]:
    """从排班快照中挑出"我"的值班日

    只取已保存的排班，草稿（自动预览未保存）不会进入订阅。
    """
    q = db.query(Schedule)
    if year is not None and month is not None:
        q = q.filter(Schedule.year == year, Schedule.month == month)
    records = q.order_by(Schedule.year.asc(), Schedule.month.asc()).all()

    events: list[dict] = []
    for record in records:
        for item in record.schedule_json or []:
            employees = item.get("employees") or []
            if not any(e.get("id") == employee_id for e in employees):
                continue
            raw_type = item.get("day_type", _WORKDAY)
            events.append(
                {
                    "date": item.get("date", ""),
                    "day_type": raw_type,
                    "day_type_label": _DAY_TYPE_LABEL.get(raw_type, raw_type),
                    "group_name": item.get("group_name") or "",
                    "coworkers": [
                        e.get("name", "")
                        for e in employees
                        if e.get("id") != employee_id
                    ],
                }
            )
    events.sort(key=lambda x: x["date"])
    return events


@router.get("/feed-url")
def get_feed_url(
    current: CurrentUser = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """获取本人的日历订阅地址

    返回的是相对路径（`/api/me/feed/<token>.ics`），前端拼接 `location.origin`
    得到完整地址。这样后端不需要知道自己的对外域名，部署换域名不会失效。
    """
    return _feed_payload(_account_or_404(current, db))


@router.post("/feed-url/rotate")
def rotate_feed_url(
    current: CurrentUser = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """重新生成订阅令牌：旧链接立即失效"""
    acc = _account_or_404(current, db)
    acc.feed_token = _new_feed_token()
    acc.feed_token_created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return _feed_payload(acc)


@router.post("/feed-url/revoke")
def revoke_feed_url(
    current: CurrentUser = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """停用订阅：清空令牌，所有已订阅的日历将拉取不到数据"""
    acc = _account_or_404(current, db)
    acc.feed_token = None
    acc.feed_token_created_at = None
    db.commit()
    return _feed_payload(acc)


@router.get("/ics")
def download_my_ics(
    year: int | None = Query(None, ge=2000, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    alarm: bool = Query(True, description="是否附带当天 8:00 提醒"),
    current: CurrentUser = Depends(get_current_employee),
    db: Session = Depends(get_db),
):
    """下载本人的值班日历文件（走登录态，供浏览器直接下载）

    不传 year/month 时导出全部已发布月份。
    """
    name = current.employee_name or current.username
    events = _collect_events(db, current.employee_id, year, month)
    content = build_ics(current.employee_id, name, events, alarm=alarm)
    suffix = f"{year}{month:02d}" if year and month else "all"
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": _attachment_header(f"duty-{name}-{suffix}.ics"),
            "Cache-Control": "no-cache",
        },
    )


def _render_feed(token: str, alarm: bool, db: Session) -> Response:
    """按订阅令牌输出日历内容（无需登录态）

    这是给日历客户端用的入口：它们只会 GET 一个 URL，
    既不会带 Cookie 也不会带 Authorization 头，所以凭据只能放在路径里。
    令牌等同于"只读本人班表"的钥匙，泄露范围仅限本人数据，
    且可随时重新生成使其失效。
    """
    acc = (
        db.query(EmployeeAccount)
        .filter(EmployeeAccount.feed_token == token)
        .first()
    )
    # 不区分"令牌不存在"与"账号停用"，统一 404，避免探测账号状态
    if not acc or not acc.is_active or not acc.employee:
        raise HTTPException(status_code=404, detail="订阅链接无效或已失效")

    name = acc.employee.name
    events = _collect_events(db, acc.employee_id)
    content = build_ics(acc.employee_id, name, events, alarm=alarm)
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={"Cache-Control": "no-cache, max-age=0"},
    )


@router.get("/feed/{token}.ics")
def ics_feed_with_suffix(
    token: str,
    alarm: bool = Query(True, description="是否附带当天 8:00 提醒"),
    db: Session = Depends(get_db),
):
    """日历订阅地址（带 .ics 后缀，部分客户端要求）"""
    return _render_feed(token, alarm, db)


@router.get("/feed/{token}")
def ics_feed(
    token: str,
    alarm: bool = Query(True, description="是否附带当天 8:00 提醒"),
    db: Session = Depends(get_db),
):
    """日历订阅地址"""
    return _render_feed(token, alarm, db)


def _attachment_header(filename: str) -> str:
    """构造下载响应头：中文文件名用 RFC 5987 编码，兼容各浏览器"""
    from urllib.parse import quote

    return f"attachment; filename*=UTF-8''{quote(filename)}"

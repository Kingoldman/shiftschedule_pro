"""日期管理接口

提供按月获取日期性质、批量更新日期性质的能力。
日期初始化（生成一年中所有日期）也在这个接口中。
"""
from datetime import date, timedelta
import calendar

from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_admin
from app.models.day_info import DayInfo, DAY_TYPE_WORKDAY, DAY_TYPE_WEEKEND
from app.models.schedule import Schedule
from app.schemas.day_info import DayInfoBatchUpdate, DayInfoOut

router = APIRouter()


def _locked_months(db: Session, dates: list[date]) -> list[str]:
    """找出这些日期所属的月份中，已经保存过排班的月份

    已保存排班的月份日期属性必须冻结：否则改了日期性质会让历史统计失真
    （例如把某天从工作日改成节假日，该月"工作日值班天数"的口径就变了）。
    """
    months = sorted({(d.year, d.month) for d in dates})
    locked: list[str] = []
    for y, m in months:
        rec = (
            db.query(Schedule)
            .filter(Schedule.year == y, Schedule.month == m)
            .first()
        )
        if rec and rec.schedule_json:
            locked.append(f"{y}年{m}月")
    return locked


def _default_day_type(d: date) -> str:
    """根据星期几推断默认日期性质：周末为 weekend，其余为 workday"""
    if d.weekday() >= 5:  # 5=周六, 6=周日
        return DAY_TYPE_WEEKEND
    return DAY_TYPE_WORKDAY


@router.get(
    "",
    response_model=list[DayInfoOut],
    dependencies=[Depends(get_current_admin)],
)
def list_days(
    start: date | None = Query(None, description="起始日期 YYYY-MM-DD"),
    end: date | None = Query(None, description="结束日期 YYYY-MM-DD"),
    year: int | None = Query(None, description="按年查询"),
    month: int | None = Query(None, description="按月查询（需配合 year）"),
    db: Session = Depends(get_db),
):
    """查询日期信息

    支持两种方式：
    1. 直接给 start/end 日期范围
    2. 给 year + month 查询某月

    如果查询的日期在库中不存在，会自动用默认规则初始化。
    """
    if year is not None:
        if month is not None:
            last_day = calendar.monthrange(year, month)[1]
            start = start or date(year, month, 1)
            end = end or date(year, month, last_day)
        else:
            start = start or date(year, 1, 1)
            end = end or date(year, 12, 31)
    elif start and not end:
        end = start

    if not start or not end:
        raise HTTPException(status_code=400, detail="请提供 year+month 或 start+end")

    # 确保范围内每一天都有记录
    existing = {
        d.date: d for d in db.query(DayInfo).filter(
            DayInfo.date >= start, DayInfo.date <= end
        ).all()
    }

    new_records = []
    cur = start
    while cur <= end:
        if cur not in existing:
            d = DayInfo(date=cur, day_type=_default_day_type(cur))
            db.add(d)
            new_records.append(d)
            existing[cur] = d
        cur += timedelta(days=1)
    if new_records:
        db.commit()

    return sorted(existing.values(), key=lambda x: x.date)


@router.put("/batch", dependencies=[Depends(get_current_admin)])
def batch_update_days(body: DayInfoBatchUpdate, db: Session = Depends(get_db)):
    """批量更新日期性质

    用于"框选一段日期 → 设为节假日"这样的批量操作。

    注意：已保存排班的月份会被拒绝修改（日期属性冻结）。
    前端也有同样的校验，但这里必须兜底——否则直接调 API 就能绕过，
    让历史统计失真。
    """
    dates = [item.date for item in body.items]

    locked = _locked_months(db, dates)
    if locked:
        raise HTTPException(
            status_code=400,
            detail=(
                f"以下月份已保存排班，日期属性不可修改：{'、'.join(locked)}。"
                "请先到「排班」页面取消对应月份的排班后再修改。"
            ),
        )

    existing = {
        d.date: d for d in db.query(DayInfo).filter(DayInfo.date.in_(dates)).all()
    }
    for item in body.items:
        d = existing.get(item.date)
        if not d:
            d = DayInfo(date=item.date)
            db.add(d)
            existing[item.date] = d
        d.day_type = item.day_type
        d.remark = item.remark
    db.commit()
    return {"msg": f"已更新 {len(body.items)} 条"}


@router.get("/modified", dependencies=[Depends(get_current_admin)])
def list_modified_days(db: Session = Depends(get_db)):
    """获取所有已修改的日期（与默认状态不一致的日期）

    默认状态：周六/周日=weekend，其余=workday，无备注。
    返回所有 day_type 不是默认值或有备注的日期记录。
    """
    all_days = db.query(DayInfo).order_by(DayInfo.date.asc()).all()
    modified = []
    for d in all_days:
        default_type = _default_day_type(d.date)
        if d.day_type != default_type or (d.remark and d.remark.strip()):
            modified.append({
                "date": d.date.isoformat(),
                "day_type": d.day_type,
                "remark": d.remark,
                "default_type": default_type,
            })
    return modified

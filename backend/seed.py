"""生成测试数据

28 个组：25 个 2 人组 + 3 个 3 人组，共 59 名员工。
同时生成最近 3 个月的日期信息和排班数据，方便统计/查询功能测试。
运行后自动创建组和员工，方便测试排班功能。
"""
import calendar
from datetime import date, timedelta

from app.core.database import SessionLocal, engine, Base
from app.core.security import hash_password
from app.models.admin import Admin
from app.models.group import ShiftGroup
from app.models.employee import Employee
from app.models.day_info import DayInfo, DAY_TYPE_WORKDAY, DAY_TYPE_WEEKEND, DAY_TYPE_HOLIDAY
from app.models.schedule import Schedule
from app.services.schedule_service import generate_schedule
from app.api.schedule import _build_group_snapshot, _fill_employees


def _default_day_type(d: date) -> str:
    if d.weekday() >= 5:
        return DAY_TYPE_WEEKEND
    return DAY_TYPE_WORKDAY


def _ensure_day_info(db: SessionLocal, year: int, month: int, holidays: list[date] | None = None):
    """为某月创建 DayInfo 记录，标记节假日"""
    last_day = calendar.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, last_day)
    existing = {d.date: d for d in db.query(DayInfo).filter(DayInfo.date >= start, DayInfo.date <= end).all()}
    holiday_set = set(holidays or [])
    cur = start
    while cur <= end:
        if cur not in existing:
            if cur in holiday_set:
                dt = DAY_TYPE_HOLIDAY
            else:
                dt = _default_day_type(cur)
            d = DayInfo(date=cur, day_type=dt)
            db.add(d)
            existing[cur] = d
        cur += timedelta(days=1)
    db.commit()


def _generate_and_save_schedule(db: SessionLocal, year: int, month: int):
    """为某月生成并保存排班"""
    last_day = calendar.monthrange(year, month)[1]
    all_days = [date(year, month, d) for d in range(1, last_day + 1)]

    # 确保该月有 DayInfo
    _ensure_day_info(db, year, month)

    # 取第一个组作为起始组
    first_group = db.query(ShiftGroup).order_by(ShiftGroup.order_id.asc()).first()
    if not first_group:
        return

    # 生成排班
    schedule_data = generate_schedule(
        db, year, month, first_group.id, all_days[0], all_days
    )
    # 填充 employees
    schedule_data = _fill_employees(schedule_data, db)
    # 构建快照
    snapshot = _build_group_snapshot(db, year, month)

    # 保存（覆盖式）
    record = db.query(Schedule).filter(Schedule.year == year, Schedule.month == month).first()
    if record:
        record.schedule_json = schedule_data
        record.group_snapshot = snapshot
    else:
        record = Schedule(
            year=year, month=month,
            schedule_json=schedule_data,
            group_snapshot=snapshot,
        )
        db.add(record)
    db.commit()


def seed():
    # 先创建所有表
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    # 确保管理员存在
    if not db.query(Admin).filter(Admin.username == "admin").first():
        db.add(Admin(username="admin", hashed_password=hash_password("admin123")))
        db.commit()

    # 如果已有组则跳过基础数据生成
    if db.query(ShiftGroup).count() > 0:
        print("已有组数据，跳过基础数据生成")
        db.close()
        return

    # ===== 1. 创建组和员工 =====
    surnames = list("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜")
    given_names = list("伟芳娜敏静丽强磊洋勇艳杰娟涛明超秀霞平刚桂英华")

    name_idx = 0
    for i in range(1, 29):
        member_count = 3 if i > 25 else 2
        group = ShiftGroup(name=f"第{i}组", order_id=i)
        db.add(group)
        db.flush()
        for j in range(member_count):
            name_idx += 1
            sn = surnames[(name_idx - 1) % len(surnames)]
            gn = given_names[((name_idx - 1) * 3 + j) % len(given_names)]
            emp = Employee(
                name=f"{sn}{gn}",
                order_id=j + 1,
                state=1,
                group_id=group.id,
            )
            db.add(emp)
    db.commit()
    print("已生成 28 组、59 名员工")

    # ===== 2. 生成最近 3 个月的日期和排班数据 =====
    today = date.today()
    months_to_generate = []
    for offset in range(2, -1, -1):  # 前2月、前1月、当月
        y = today.year
        m = today.month - offset
        while m <= 0:
            m += 12
            y -= 1
        months_to_generate.append((y, m))

    # 标记一些节假日（方便统计测试）
    holiday_map = {}
    for y, m in months_to_generate:
        holidays = []
        if m == 1:
            holidays = [date(y, 1, 1)]  # 元旦
        elif m == 5:
            holidays = [date(y, 5, 1)]  # 劳动节
        elif m == 6:
            holidays = [date(y, 6, 19), date(y, 6, 20), date(y, 6, 21)]  # 端午节附近
        elif m == 7:
            holidays = []  # 7月无固定节假日
        elif m == 10:
            holidays = [date(y, 10, 1), date(y, 10, 2), date(y, 10, 3)]  # 国庆
        holiday_map[(y, m)] = holidays

    for y, m in months_to_generate:
        _ensure_day_info(db, y, m, holiday_map.get((y, m), []))
        _generate_and_save_schedule(db, y, m)
        print(f"已生成 {y}年{m}月 排班数据")

    # ===== 3. 随机让 2 名员工"不值班"，方便测试状态变更 =====
    some_emps = db.query(Employee).limit(3).all()
    for emp in some_emps[:2]:
        emp.state = 0
    db.commit()
    if some_emps:
        print(f"已将 {len(some_emps[:2])} 名员工设为不值班状态（测试用）")

    db.close()
    print("数据生成完成！可访问 http://localhost:5173 开始测试")


if __name__ == "__main__":
    seed()

"""排班 Schema"""
from datetime import date
from pydantic import BaseModel, Field, ConfigDict


class ScheduleItemEmployee(BaseModel):
    """排班项中的员工信息"""
    id: int
    name: str


class ScheduleItem(BaseModel):
    """单日排班"""
    date: date
    day_type: str
    holiday_name: str | None = None
    group_id: int | None = None
    group_name: str | None = None
    employees: list[ScheduleItemEmployee] = []


class ScheduleItemIn(ScheduleItem):
    """保存时的单日排班

    date 用 date 类型接收，由 Pydantic 保证格式必须是 YYYY-MM-DD。
    此前用裸 str，传入 "2026/07/01" 之类也能入库，而统计逻辑大量依赖
    日期字符串比较做过滤与排序，会静默出错且难以排查。
    落库前由 API 层统一转成 isoformat 字符串。
    """
    date: date


class ScheduleSave(BaseModel):
    """保存月度排班"""
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    schedule: list[ScheduleItemIn]
    # 乐观锁：客户端提交时带上读到的版本号，服务端不一致则拒绝（409）
    expected_version: int | None = Field(
        None, description="期望的当前版本号，用于并发冲突检测"
    )


class ScheduleGenerate(BaseModel):
    """生成排班请求

    start_group_id: 从哪个组开始轮转
    start_date: 轮转起始日期（含）
    days: 需要排班的天数列表（已过滤掉不值班的日子）
    """
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    start_group_id: int
    start_date: date
    days: list[date]


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    year: int
    month: int
    schedule_json: list
    group_snapshot: dict | None = None
    locked: bool = False
    version: int = 1

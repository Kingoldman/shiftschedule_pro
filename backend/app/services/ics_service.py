"""生成 iCalendar（RFC 5545）内容

为什么手写而不引第三方库：需求很轻（只有全天事件 + 一个提醒），
引入 ics/icalendar 会多一层依赖与维护成本。但这个格式有几个坑必须处理对，
否则日历客户端会静默丢弃整个文件或重复建事件：

1. **换行必须是 CRLF**，LF 结尾的文件部分客户端不认。
2. **长行要按 75 字节折叠**，续行以单个空格开头；折叠时不能截断 UTF-8 多字节字符，
   否则中文姓名、组名会变成乱码。
3. **文本需转义** `\\` `;` `,` 和换行，否则组名里一个分号就能破坏字段结构。
4. **UID 必须稳定**。日历客户端靠 UID 判断"这是同一条事件"，
   如果每次订阅都换 UID，客户端会不断新建事件——排班改一次，日历里就多一份重复。
   这里用 `员工ID-日期` 作为 UID，只要人和日期不变，UID 就不变。
5. **全天事件的 DTEND 是次日**（结束时间不含当天），写成当天会导致事件不显示。
"""
from datetime import datetime, timezone

_CRLF = "\r\n"
# RFC 5545 要求每行不超过 75 字节（不含 CRLF）
_MAX_OCTETS = 75

_DEFAULT_ALARM = "PT8H"  # 当天上午 8:00（全天事件从 00:00 起算，8 小时后）

_DAY_TYPE_LABEL = {
    "workday": "工作日",
    "weekend": "周末",
    "holiday": "节假日",
    "vacation": "调休补班",
}


def _escape(text: str) -> str:
    """按 RFC 5545 转义文本值"""
    if not text:
        return ""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """按 75 字节折叠长行，续行前置一个空格，且不切断多字节字符"""
    raw = line.encode("utf-8")
    if len(raw) <= _MAX_OCTETS:
        return line

    chunks: list[bytes] = []
    start = 0
    limit = _MAX_OCTETS
    while len(raw) - start > limit:
        end = start + limit
        # 回退到最近的完整字符边界，避免把一个汉字切成两半
        while end > start:
            try:
                raw[start:end].decode("utf-8")
                break
            except UnicodeDecodeError:
                end -= 1
        chunks.append(raw[start:end])
        start = end
        limit = _MAX_OCTETS - 1  # 续行开头要占一个空格
    chunks.append(raw[start:])

    first = chunks[0].decode("utf-8")
    rest = [_CRLF + " " + c.decode("utf-8") for c in chunks[1:]]
    return first + "".join(rest)


def _stamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _event(
    uid: str,
    day: str,
    summary: str,
    description: str,
    stamp: str,
    alarm: bool,
) -> list[str]:
    """构造单个 VEVENT（day 形如 2026-07-01）"""
    date_compact = day.replace("-", "")
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{date_compact}",
        # 全天事件的结束时间是"次日零点"，与开始同一天会被判定为时长 0
        f"DTEND;VALUE=DATE:{_next_day(day)}",
        f"SUMMARY:{_escape(summary)}",
        f"DESCRIPTION:{_escape(description)}",
        "STATUS:CONFIRMED",
        "TRANSP:OPAQUE",
        "SEQUENCE:0",
    ]
    if alarm:
        lines += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"TRIGGER;RELATED=START:{_DEFAULT_ALARM}",
            "DESCRIPTION:今天值班",
            "END:VALARM",
        ]
    lines.append("END:VEVENT")
    return lines


def _next_day(day: str) -> str:
    """返回次日日期（YYYYMMDD），用于全天事件的 DTEND"""
    from datetime import date, timedelta

    try:
        d = date.fromisoformat(day) + timedelta(days=1)
    except ValueError:
        return day.replace("-", "")
    return d.strftime("%Y%m%d")


def build_ics(
    employee_id: int,
    employee_name: str,
    events: list[dict],
    alarm: bool = True,
) -> str:
    """生成日历文件内容

    Args:
        employee_id: 用于构造稳定 UID
        employee_name: 日历名称与事件标题使用
        events: `[{"date": "2026-07-01", "day_type": "workday",
                  "group_name": "第1组", "coworkers": ["李四"]}, ...]`
        alarm: 是否附带当天上午 8:00 的提醒
    """
    stamp = _stamp_utc()
    cal_name = f"{employee_name} 的值班日历"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//shiftschedule//Duty Calendar//ZH",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(cal_name)}",
        "X-WR-CALDESC:值班安排（自动同步）",
        "X-PUBLISHED-TTL:PT12H",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
    ]

    for ev in events:
        day = ev.get("date", "")
        if not day:
            continue
        raw_type = ev.get("day_type", "workday")
        label = ev.get("day_type_label") or _DAY_TYPE_LABEL.get(raw_type, raw_type)
        group = ev.get("group_name") or ""
        coworkers = ev.get("coworkers") or []

        desc_parts = [f"日期性质：{label}"]
        if group:
            desc_parts.append(f"值班组：{group}")
        desc_parts.append(
            f"同班同事：{'、'.join(coworkers) if coworkers else '单独值班'}"
        )

        lines += _event(
            uid=f"duty-{employee_id}-{day}@shiftschedule",
            day=day,
            summary=f"值班（{label}）",
            description="\n".join(desc_parts),
            stamp=stamp,
            alarm=alarm,
        )

    lines.append("END:VCALENDAR")

    body = _CRLF.join(_fold(line) for line in lines)
    return body + _CRLF  # 文件以 CRLF 结尾

import dayjs from 'dayjs'

const EXCEL_SERIAL_MIN = 61
const EXCEL_SERIAL_MAX = 73415
const YEAR_MIN = 1900
const YEAR_MAX = 2100

function excelSerialToDate(serial) {
  const d = new Date((serial - 25569) * 86400000)
  const parsed = dayjs(d)
  if (!parsed.isValid()) return null
  const year = parsed.year()
  if (year < YEAR_MIN || year > YEAR_MAX) return null
  return parsed.format('YYYY-MM-DD')
}

function buildDate(y, m, d) {
  const year = parseInt(y)
  const month = parseInt(m)
  const day = parseInt(d)
  if (year < YEAR_MIN || year > YEAR_MAX) return null
  if (month < 1 || month > 12) return null
  if (day < 1 || day > 31) return null
  const parsed = dayjs(`${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`)
  if (!parsed.isValid()) return null
  return parsed.format('YYYY-MM-DD')
}

/**
 * 将各种日期格式统一转换为 YYYY-MM-DD 字符串
 * 支持：
 *   - yyyy-mm-dd, yyyy/mm/dd, yyyy.m.d, yyyy年m月d日, yyyy年m月d号
 *   - 8位紧凑格式 yyyyymmdd (如 20260101)
 *   - ISO 日期时间 2026-01-01T00:00:00 / 2026-01-01 00:00:00
 *   - 带时间的斜杠格式 2026/1/1 00:00:00 / 2026/1/1 0:00
 *   - Excel 序列号 (61-73415)
 *   - 中文带时间 2026年1月1日 00时00分
 * 严格拒绝：纯数字1-60、单独年份、无日期的字符串等
 * 返回 null 表示无法解析
 */
export function parseDateStr(val) {
  if (val == null) return null

  // 数字：Excel 序列号
  if (typeof val === 'number') {
    if (!Number.isFinite(val) || val < EXCEL_SERIAL_MIN || val > EXCEL_SERIAL_MAX) return null
    return excelSerialToDate(val)
  }

  let s = String(val).trim()
  if (!s) return null

  // 纯数字字符串：8位紧凑日期 yyyyymmdd 或 Excel 序列号
  if (/^\d+$/.test(s)) {
    // 8位紧凑日期：yyyyymmdd (如 20260101)
    if (s.length === 8) {
      const y = s.slice(0, 4)
      const m = s.slice(4, 6)
      const d = s.slice(6, 8)
      const result = buildDate(y, m, d)
      if (result) return result
    }
    // Excel 序列号
    const num = Number(s)
    if (num < EXCEL_SERIAL_MIN || num > EXCEL_SERIAL_MAX) return null
    return excelSerialToDate(num)
  }

  // 带日期的 ISO 格式（如 2026-01-01T00:00:00 或 2026-01-01 00:00:00）
  const isoFullMatch = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})[T\s]/)
  if (isoFullMatch) {
    const [, y, m, d] = isoFullMatch
    const result = buildDate(y, m, d)
    if (result) return result
  }

  // 带时间的斜杠格式（如 2026/1/1 00:00:00 或 2026/1/1 0:00）
  const slashTimeMatch = s.match(/^(\d{4})\/(\d{1,2})\/(\d{1,2})\s+/)
  if (slashTimeMatch) {
    const [, y, m, d] = slashTimeMatch
    const result = buildDate(y, m, d)
    if (result) return result
  }

  // 带时间的点格式（如 2026.1.1 00:00:00）
  const dotTimeMatch = s.match(/^(\d{4})\.(\d{1,2})\.(\d{1,2})\s+/)
  if (dotTimeMatch) {
    const [, y, m, d] = dotTimeMatch
    const result = buildDate(y, m, d)
    if (result) return result
  }

  // 标准格式：yyyy-mm-dd, yyyy/mm/dd, yyyy.m.d, yyyy年m月d日, yyyy年m月d号
  const isoMatch = s.match(/^(\d{4})[-/\.年](\d{1,2})[-/\.月](\d{1,2})[日号]?$/)
  if (isoMatch) {
    const [, y, m, d] = isoMatch
    const result = buildDate(y, m, d)
    if (result) return result
  }

  // 中文带时间格式（如 2026年1月1日 00时00分 或 2026年1月1日 00:00）
  const cnTimeMatch = s.match(/^(\d{4})年(\d{1,2})月(\d{1,2})[日号]\s+/)
  if (cnTimeMatch) {
    const [, y, m, d] = cnTimeMatch
    const result = buildDate(y, m, d)
    if (result) return result
  }

  return null
}

/** 中国法定节假日列表 */
export const CHINESE_HOLIDAYS = [
  '元旦', '春节', '清明节', '劳动节', '端午节',
  '中秋节', '国庆节', '除夕',
]

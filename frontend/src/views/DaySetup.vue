<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import * as XLSX from 'xlsx'
import { dayApi } from '@/api/day'
import { scheduleApi } from '@/api/schedule'
import { useAuthStore } from '@/stores/auth'
import { parseDateStr, CHINESE_HOLIDAYS } from '@/utils/format'

const authStore = useAuthStore()
const canEdit = computed(() => authStore.isLoggedIn)

const currentMonth = ref(dayjs())
const days = ref([])
const loading = ref(false)
const monthHasSchedule = ref(false)
const canEditDays = computed(() => canEdit.value && !monthHasSchedule.value)

const selectedDates = ref(new Set())

// localStorage 缓存
const DAY_CACHE_KEY = 'day_info_cache'
function getDayCacheMap() {
  try {
    return new Map(JSON.parse(localStorage.getItem(DAY_CACHE_KEY) || '[]'))
  } catch { return new Map() }
}
function saveDayCacheMap(map) {
  try {
    const entries = [...map.entries()]
    if (entries.length > 12) entries.splice(0, entries.length - 12)
    localStorage.setItem(DAY_CACHE_KEY, JSON.stringify(entries))
  } catch {}
}

// 当前选中的日期性质
const activeDayType = ref('holiday')
const holidayRemark = ref('')
const dayTypeOptions = [
  { value: 'workday', label: '工作日', color: 'bg-gray-100 text-gray-600' },
  { value: 'weekend', label: '周末', color: 'bg-blue-100 text-blue-700' },
  { value: 'holiday', label: '节假日', color: 'bg-red-100 text-red-600' },
  { value: 'vacation', label: '调休日', color: 'bg-orange-100 text-orange-600' },
]

// 节假日名称下拉选项：中国法定节假日 + 自定义输入
const holidayOptions = CHINESE_HOLIDAYS.map(h => ({ value: h, label: h }))
const customHolidayInput = ref('')

function onHolidaySelect(val) {
  holidayRemark.value = val
}

async function loadDays(forceRefresh = false) {
  loading.value = true
  selectedDates.value.clear()
  try {
    const y = currentMonth.value.year()
    const m = currentMonth.value.month() + 1
    const cacheKey = `${y}-${m}`

    // 排班状态始终实时检查（不缓存），因为决定了日期属性是否可编辑
    try {
      const schedule = await scheduleApi.get(y, m)
      monthHasSchedule.value = !!schedule
    } catch {
      monthHasSchedule.value = false
    }

    if (!forceRefresh) {
      const cacheMap = getDayCacheMap()
      if (cacheMap.has(cacheKey)) {
        days.value = cacheMap.get(cacheKey)
        return
      }
    }

    const data = await dayApi.listByMonth(y, m)
    days.value = data
    const cacheMap = getDayCacheMap()
    cacheMap.set(cacheKey, data)
    saveDayCacheMap(cacheMap)
  } finally {
    loading.value = false
  }
}

onMounted(loadDays)
watch(currentMonth, loadDays)

// 日历表格数据
const calendarCells = computed(() => {
  const start = currentMonth.value.startOf('month')
  const startDay = start.day()
  const leadingDays = startDay === 0 ? 6 : startDay - 1
  const daysInMonth = currentMonth.value.daysInMonth()
  const cells = []
  for (let i = 0; i < leadingDays; i++) {
    const d = start.subtract(leadingDays - i, 'day')
    cells.push({ date: d, inMonth: false, info: null })
  }
  for (let i = 1; i <= daysInMonth; i++) {
    const d = currentMonth.value.date(i)
    const info = days.value.find((x) => dayjs(x.date).isSame(d, 'day'))
    cells.push({ date: d, inMonth: true, info })
  }
  const remaining = 42 - cells.length
  for (let i = 1; i <= remaining; i++) {
    const d = start.add(daysInMonth + i - 1, 'day')
    cells.push({ date: d, inMonth: false, info: null })
  }
  return cells
})

const weekDays = ['一', '二', '三', '四', '五', '六', '日']

function weekdayName(dateStr) {
  const d = dayjs(dateStr).day()
  return ['日', '一', '二', '三', '四', '五', '六'][d]
}

function dayTypeClass(dayType) {
  return dayTypeOptions.find((o) => o.value === dayType)?.color || ''
}

function dayTypeLabel(dayType) {
  return dayTypeOptions.find((o) => o.value === dayType)?.label || ''
}

/** 日历格子和导出中的显示：节假日只显示名称，其他显示性质标签 */
function dayDisplay(info) {
  if (!info) return ''
  if (info.day_type === 'holiday' && info.remark) return info.remark
  return dayTypeLabel(info.day_type)
}

/** 判断某日期是否被修改过（与默认状态不一致）
 *  默认状态：周六/周日=weekend，其余=workday，无备注
 */
function isModified(info) {
  if (!info) return false
  const d = dayjs(info.date)
  const defaultType = (d.day() === 0 || d.day() === 6) ? 'weekend' : 'workday'
  if (info.day_type !== defaultType) return true
  if (info.remark && info.remark.trim()) return true
  return false
}

// 仅查看已修改日期
const showModifiedOnly = ref(false)

// 当月已修改日期列表
const modifiedDays = computed(() => {
  return days.value.filter(d => isModified(d))
})

// 过滤后的日历高亮：是否高亮显示已修改日期
const highlightModified = ref(true)

function toggleSelect(dateStr) {
  if (!canEditDays.value) return
  if (selectedDates.value.has(dateStr)) {
    selectedDates.value.delete(dateStr)
  } else {
    selectedDates.value.add(dateStr)
  }
}

async function batchSetDayType() {
  if (!canEditDays.value) return
  if (selectedDates.value.size === 0) {
    ElMessage.warning('请先选择日期')
    return
  }
  // 节假日必须输入名称
  if (activeDayType.value === 'holiday' && !holidayRemark.value.trim()) {
    ElMessage.warning('请输入节假日名称（如：劳动节、中秋节），或从下拉选项中选择')
    return
  }
  const remark = activeDayType.value === 'holiday' ? holidayRemark.value.trim() : null
  const items = Array.from(selectedDates.value).map((d) => ({
    date: d,
    day_type: activeDayType.value,
    remark,
  }))
  try {
    await dayApi.batchUpdate(items)
    ElMessage.success(`已将 ${items.length} 天设为「${remark || dayTypeLabel(activeDayType.value)}」`)
    const y = currentMonth.value.year()
    const m = currentMonth.value.month() + 1
    const cacheMap = getDayCacheMap()
    cacheMap.delete(`${y}-${m}`)
    saveDayCacheMap(cacheMap)
    await loadDays(true)
  } catch (e) {}
}

/** 计算某日期的默认性质：周六/周日=weekend，其余=workday */
function defaultDayType(dateStr) {
  const d = dayjs(dateStr)
  return (d.day() === 0 || d.day() === 6) ? 'weekend' : 'workday'
}

/** 重置选中的日期为默认状态（工作日/周末，无备注） */
async function resetSelectedToDefault() {
  if (!canEditDays.value) return
  if (selectedDates.value.size === 0) {
    ElMessage.warning('请先选择日期')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认将选中的 ${selectedDates.value.size} 天重置为默认状态（工作日/周末，清除节假日和调休）？`,
      '重置确认',
      { type: 'warning', confirmButtonText: '确认重置', cancelButtonText: '取消' }
    )
  } catch { return }
  const items = Array.from(selectedDates.value).map((d) => ({
    date: d,
    day_type: defaultDayType(d),
    remark: null,
  }))
  try {
    await dayApi.batchUpdate(items)
    ElMessage.success(`已重置 ${items.length} 天为默认状态`)
    const y = currentMonth.value.year()
    const m = currentMonth.value.month() + 1
    const cacheMap = getDayCacheMap()
    cacheMap.delete(`${y}-${m}`)
    saveDayCacheMap(cacheMap)
    await loadDays(true)
  } catch (e) {}
}

/** 重置当月所有日期为默认状态 */
async function resetMonthToDefault() {
  if (!canEditDays.value) return
  try {
    await ElMessageBox.confirm(
      `确认将 ${currentMonth.value.format('YYYY年M月')} 所有日期重置为默认状态？此操作将清除该月所有节假日、调休日设置。`,
      '重置当月',
      { type: 'warning', confirmButtonText: '确认重置', cancelButtonText: '取消' }
    )
  } catch { return }
  const daysInMonth = currentMonth.value.daysInMonth()
  const items = []
  for (let i = 1; i <= daysInMonth; i++) {
    const d = currentMonth.value.date(i)
    items.push({
      date: d.format('YYYY-MM-DD'),
      day_type: defaultDayType(d.format('YYYY-MM-DD')),
      remark: null,
    })
  }
  try {
    await dayApi.batchUpdate(items)
    ElMessage.success(`已重置 ${items.length} 天为默认状态`)
    const y = currentMonth.value.year()
    const m = currentMonth.value.month() + 1
    const cacheMap = getDayCacheMap()
    cacheMap.delete(`${y}-${m}`)
    saveDayCacheMap(cacheMap)
    await loadDays(true)
  } catch (e) {}
}

function prevMonth() {
  currentMonth.value = currentMonth.value.subtract(1, 'month')
}
function nextMonth() {
  currentMonth.value = currentMonth.value.add(1, 'month')
}
function goToday() {
  currentMonth.value = dayjs()
}

const monthStats = computed(() => {
  const stats = { workday: 0, weekend: 0, holiday: 0, vacation: 0 }
  days.value.forEach((d) => {
    if (d.day_type in stats) stats[d.day_type]++
  })
  return stats
})

// ===== 导入日期 Excel =====
const importDayVisible = ref(false)
const importDayPreview = ref([])
const importDayLoading = ref(false)
const importDayErrors = ref([])
const importDayParsing = ref(false)

// 导入预览涉及的月份
const importPreviewMonths = computed(() => {
  const months = new Set()
  for (const item of importDayPreview.value) {
    const d = dayjs(item.date)
    months.add(`${d.year()}年${d.month() + 1}月`)
  }
  return [...months].sort()
})
// 当前月是否在导入数据中
const importIncludesCurrentMonth = computed(() => {
  const currentKey = `${currentMonth.value.year()}年${currentMonth.value.month() + 1}月`
  return importPreviewMonths.value.includes(currentKey)
})

function openDayImportDialog() {
  importDayErrors.value = []
  importDayPreview.value = []
  importDayParsing.value = false
  importDayVisible.value = true
}

function downloadDayTemplate() {
  const y = currentMonth.value.year()
  const m = currentMonth.value.month() + 1
  const mm = String(m).padStart(2, '0')
  const title = '日期设置导入模板（可导入任意月份的日期）'
  const exampleRows = [
    { '日期': `${y}-${mm}-01`, '日期性质': '工作日', '节假日名称': '' },
    { '日期': `${y}-${mm}-02`, '日期性质': '周末', '节假日名称': '' },
    { '日期': `${y}-${mm}-03`, '日期性质': '工作日', '节假日名称': '' },
    { '日期': `${y}-${mm}-04`, '日期性质': '周末', '节假日名称': '' },
    { '日期': `${y}-${mm}-05`, '日期性质': '节假日', '节假日名称': '劳动节' },
    { '日期': `${y}-${mm}-06`, '日期性质': '调休日', '节假日名称': '' },
  ]
  const ws = XLSX.utils.json_to_sheet(exampleRows)
  XLSX.utils.sheet_add_aoa(ws, [[title]], { origin: 'A1' })
  XLSX.utils.sheet_add_aoa(ws, [Object.keys(exampleRows[0])], { origin: 'A2' })
  XLSX.utils.sheet_add_json(ws, exampleRows, { origin: 'A3', skipHeader: true })
  ws['!cols'] = [{ wch: 16 }, { wch: 10 }, { wch: 16 }]
  ws['!merges'] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 2 } }]
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, '日期设置')
  XLSX.writeFile(wb, '日期设置导入模板.xlsx')
}

function handleDayImportFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  // 清除之前的状态
  importDayErrors.value = []
  importDayPreview.value = []
  importDayParsing.value = true
  const reader = new FileReader()
  reader.onload = async (evt) => {
    try {
      const data = new Uint8Array(evt.target.result)
      const wb = XLSX.read(data, { type: 'array' })
      const ws = wb.Sheets[wb.SheetNames[0]]
      const rows = XLSX.utils.sheet_to_json(ws, { header: 1, raw: false, dateNF: 'yyyy-mm-dd' })
      const dataRows = rows.slice(2).filter(r => r[0] != null && String(r[0]).trim())
      // 校验
      const errors = []
      if (dataRows.length === 0) {
        errors.push('表格中没有数据行（请从第3行开始填写数据，前两行是标题和表头）')
      }
      const dayTypeMap = { '工作日': 'workday', '周末': 'weekend', '节假日': 'holiday', '调休日': 'vacation' }
      const parsed = []
      const seenDates = new Set()
      for (let i = 0; i < dataRows.length; i++) {
        const r = dataRows[i]
        const rowNum = i + 3
        // 日期解析
        const dateStr = parseDateStr(r[0])
        if (!dateStr) {
          errors.push(`第${rowNum}行A列：无法识别日期"${r[0]}"，支持格式：2026-01-01、2026/1/1、2026年1月1日、20260101、Excel日期序列号等`)
          continue
        }
        // 重复日期检查
        if (seenDates.has(dateStr)) {
          errors.push(`第${rowNum}行A列：日期"${dateStr}"重复`)
          continue
        }
        seenDates.add(dateStr)
        // 日期性质
        const dtVal = String(r[1] || '').trim()
        const dayType = dayTypeMap[dtVal]
        if (!dayType) {
          errors.push(`第${rowNum}行B列：日期性质应为"工作日/周末/节假日/调休日"之一，当前为"${dtVal}"`)
          continue
        }
        // 节假日必须有名称
        const remark = String(r[2] || '').trim()
        if (dayType === 'holiday' && !remark) {
          errors.push(`第${rowNum}行C列：节假日必须填写节假日名称（如：劳动节、中秋节）`)
          continue
        }
        parsed.push({
          date: dateStr,
          day_type: dayType,
          remark: dayType === 'holiday' ? remark : null,
        })
      }
      // 检查涉及的月份是否已保存排班（已保存排班的月份不允许修改日期属性）
      if (errors.length === 0 && parsed.length > 0) {
        const importMonths = new Map() // "y-m" -> [dateStr, ...]
        for (const item of parsed) {
          const d = dayjs(item.date)
          const key = `${d.year()}-${d.month() + 1}`
          if (!importMonths.has(key)) importMonths.set(key, { year: d.year(), month: d.month() + 1, dates: [] })
          importMonths.get(key).dates.push(item.date)
        }
        const lockedMonths = []
        for (const [, info] of importMonths) {
          try {
            const schedule = await scheduleApi.get(info.year, info.month)
            if (schedule) {
              lockedMonths.push(`${info.year}年${info.month}月`)
            }
          } catch {}
        }
        if (lockedMonths.length > 0) {
          errors.push(`以下月份已保存排班，日期属性不可修改：${lockedMonths.join('、')}。请先到「排班」页面取消对应月份的排班后再导入`)
        }
      }
      importDayErrors.value = errors
      importDayPreview.value = errors.length > 0 ? [] : parsed
    } catch (err) {
      ElMessage.error('文件解析失败，请检查是否为有效的 Excel 文件')
      importDayErrors.value = ['文件解析失败，请确认文件为有效的 .xlsx 或 .xls 格式']
      importDayPreview.value = []
    } finally {
      importDayParsing.value = false
    }
  }
  reader.onerror = () => {
    importDayParsing.value = false
    ElMessage.error('文件读取失败，请重试')
  }
  reader.readAsArrayBuffer(file)
  e.target.value = ''
}

async function confirmDayImport() {
  if (!importDayPreview.value.length) return
  importDayLoading.value = true
  try {
    // 转换为纯对象数组，避免 Vue 响应式代理在 axios 序列化时出问题
    const items = importDayPreview.value.map(item => ({
      date: item.date,
      day_type: item.day_type,
      remark: item.remark,
    }))
    const result = await dayApi.batchUpdate(items)

    // 分析导入数据涉及哪些月份（使用与缓存一致的 key 格式：YYYY-M）
    const importedMonths = new Set()
    for (const item of items) {
      const d = dayjs(item.date)
      importedMonths.add(`${d.year()}-${d.month() + 1}`)
    }
    const monthList = [...importedMonths].sort()
    const currentKey = `${currentMonth.value.year()}-${currentMonth.value.month() + 1}`

    // 清除所有受影响月份的缓存
    const cacheMap = getDayCacheMap()
    for (const mk of monthList) {
      cacheMap.delete(mk)
    }
    saveDayCacheMap(cacheMap)

    importDayVisible.value = false
    const importCount = items.length
    importDayPreview.value = []

    // 如果当前月在导入数据中，刷新视图；否则提示用户切换
    if (importedMonths.has(currentKey)) {
      await loadDays(true)
      ElMessage.success(result.msg || `已导入 ${importCount} 天日期设置`)
    } else {
      const monthLabels = monthList.map(mk => {
        const [y, m] = mk.split('-').map(Number)
        return `${y}年${m}月`
      })
      ElMessage.success(`已导入 ${importCount} 天日期设置（${monthLabels.join('、')}），已切换到对应月份`)
      // 自动切换到第一个导入月份
      const [y, m] = monthList[0].split('-').map(Number)
      currentMonth.value = dayjs(`${y}-${String(m).padStart(2, '0')}-01`)
    }
  } catch (e) {
    console.error('日期导入失败:', e)
    ElMessage.error('日期导入失败: ' + (e.response?.data?.detail || e.message || '未知错误'))
  } finally {
    importDayLoading.value = false
  }
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto">
    <!-- 页头 -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <div class="text-xs text-blue-600 font-mono tracking-[0.3em] uppercase mb-1">/ Calendar</div>
        <h1 class="font-display text-3xl font-semibold text-gray-800">日期设置</h1>
        <div class="flex items-center gap-3 mt-1">
          <p class="text-sm text-gray-500">点击日期选择，批量设置节假日、调休日</p>
          <template v-if="canEdit">
            <div class="h-4 w-px bg-gray-300"></div>
            <button class="px-2.5 py-1 rounded-md text-xs font-medium bg-blue-50 text-blue-600 hover:bg-blue-100 border border-blue-200 flex items-center gap-1 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="monthHasSchedule" @click="openDayImportDialog">
              <el-icon><Upload /></el-icon>导入日期
            </button>
          </template>
        </div>
      </div>

      <!-- 月份导航 -->
      <div class="flex items-center gap-3">
        <button class="btn-ghost px-3" @click="prevMonth"><el-icon><ArrowLeft /></el-icon></button>
        <div class="text-center min-w-[160px]">
          <div class="font-display text-2xl font-semibold num">{{ currentMonth.format('YYYY 年 M 月') }}</div>
        </div>
        <button class="btn-ghost px-3" @click="nextMonth"><el-icon><ArrowRight /></el-icon></button>
        <button class="btn-ghost" @click="goToday">今天</button>
      </div>
    </div>

    <!-- 工具栏 -->
    <template v-if="canEdit">
      <!-- 排班已保存提示 -->
      <div v-if="monthHasSchedule" class="card p-3 mb-4 flex items-center gap-3 bg-orange-50 border-orange-200">
        <el-icon class="text-orange-500"><Lock /></el-icon>
        <span class="text-sm text-orange-700">
          本月已保存排班，日期属性已锁定不可修改。如需调整请先到「排班」页面取消当月排班
        </span>
      </div>
      <div v-if="canEditDays" class="card p-4 mb-6 flex items-center gap-4 flex-wrap">
        <div class="text-sm text-gray-600">
          已选 <span class="num font-semibold text-blue-600">{{ selectedDates.size }}</span> 天
        </div>
        <div class="h-6 w-px bg-gray-200"></div>
        <div class="flex items-center gap-2">
          <span class="text-xs text-gray-500">设为：</span>
          <div class="flex gap-1">
            <button
              v-for="opt in dayTypeOptions"
              :key="opt.value"
              class="px-3 py-1 rounded-md text-xs font-medium transition-all"
              :class="[
                activeDayType === opt.value ? 'ring-2 ring-blue-500 ring-offset-1' : '',
                opt.color,
              ]"
              @click="activeDayType = opt.value"
            >
              {{ opt.label }}
            </button>
          </div>
          <!-- 节假日名称：下拉选择 + 自定义输入 -->
          <div v-if="activeDayType === 'holiday'" class="flex items-center gap-2">
            <span class="text-xs text-gray-500">名称：</span>
            <el-select
              :model-value="holidayOptions.some(o => o.value === holidayRemark) ? holidayRemark : ''"
              placeholder="选择节假日"
              size="small"
              class="w-28"
              clearable
              @change="onHolidaySelect"
            >
              <el-option v-for="opt in holidayOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>
            <span class="text-xs text-gray-400">或</span>
            <el-input
              v-model="holidayRemark"
              size="small"
              placeholder="自定义名称"
              class="w-28"
              clearable
            />
          </div>
        </div>
        <button class="btn-primary ml-auto" @click="batchSetDayType" :disabled="selectedDates.size === 0">
          <el-icon><Check /></el-icon>批量应用
        </button>
        <div class="h-6 w-px bg-gray-200"></div>
        <button
          class="btn-ghost text-xs"
          :disabled="selectedDates.size === 0"
          @click="resetSelectedToDefault"
        >
          <el-icon><RefreshLeft /></el-icon>重置选中
        </button>
        <button class="btn-ghost text-xs text-amber-600" @click="resetMonthToDefault">
          <el-icon><Refresh /></el-icon>重置当月
        </button>
      </div>

      <!-- 修改记录提示条 -->
      <div v-if="modifiedDays.length > 0" class="card p-3 mb-4 flex items-center gap-3 bg-amber-50 border-amber-200">
        <el-icon class="text-amber-500"><WarningFilled /></el-icon>
        <span class="text-sm text-amber-700">
          当月有 <span class="num font-semibold">{{ modifiedDays.length }}</span> 天已修改
        </span>
        <label class="ml-auto flex items-center gap-1.5 text-xs text-amber-700 cursor-pointer">
          <input type="checkbox" v-model="showModifiedOnly" />
          <span>仅查看已修改日期</span>
        </label>
      </div>
    </template>

    <div v-else class="card p-4 mb-6 text-center text-sm text-gray-400">
      登录后可编辑日期性质
    </div>

    <!-- 日历 -->
    <div class="card p-4" v-loading="loading">
      <div class="grid grid-cols-7 gap-1 mb-2">
        <div
          v-for="(w, i) in weekDays"
          :key="w"
          class="text-center text-xs font-medium py-2"
          :class="i === 5 || i === 6 ? 'text-blue-600' : 'text-gray-500'"
        >
          {{ w }}
        </div>
      </div>

      <div class="grid grid-cols-7 gap-1">
        <div
          v-for="cell in calendarCells"
          :key="cell.date.format('YYYY-MM-DD')"
          class="aspect-square border border-gray-200 rounded-md p-2 transition-all relative group"
          :class="[
            cell.inMonth ? (canEditDays ? 'cursor-pointer hover:border-blue-300 hover:shadow-sm' : '') : 'bg-gray-50 opacity-50',
            selectedDates.has(cell.date.format('YYYY-MM-DD')) ? 'ring-2 ring-blue-500 border-blue-500' : '',
            // 已修改日期加边框高亮
            (cell.inMonth && cell.info && isModified(cell.info)) ? 'border-amber-400 border-2' : '',
            // 仅查看已修改时，未修改日期变淡
            (showModifiedOnly && cell.inMonth && cell.info && !isModified(cell.info)) ? 'opacity-25' : '',
            (showModifiedOnly && cell.inMonth && !cell.info) ? 'opacity-25' : '',
          ]"
          @click="cell.inMonth && toggleSelect(cell.date.format('YYYY-MM-DD'))"
        >
          <div class="flex items-start justify-between">
            <span
              class="num text-sm font-medium"
              :class="cell.date.day() === 0 || cell.date.day() === 6 ? 'text-blue-600' : 'text-gray-700'"
            >
              {{ cell.date.date() }}
            </span>
            <span
              v-if="cell.info && cell.inMonth"
              class="day-badge text-[10px]"
              :class="dayTypeClass(cell.info.day_type)"
            >
              {{ dayDisplay(cell.info) }}
            </span>
          </div>
          <!-- 已修改日期标记点 -->
          <span
            v-if="cell.inMonth && cell.info && isModified(cell.info)"
            class="absolute bottom-1 right-1 w-1.5 h-1.5 rounded-full bg-amber-500"
            title="已修改"
          ></span>
        </div>
      </div>
    </div>

    <!-- 月份统计 -->
    <div class="grid grid-cols-4 gap-4 mt-6">
      <div v-for="opt in dayTypeOptions" :key="opt.value" class="card p-4">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-xs text-gray-500 mb-1">{{ opt.label }}</div>
            <div class="font-display text-3xl font-semibold num text-gray-800">
              {{ monthStats[opt.value] }}
            </div>
          </div>
          <div class="w-10 h-10 rounded-md flex items-center justify-center" :class="opt.color">
            <span class="num text-xs font-bold">{{ opt.value[0].toUpperCase() }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 已修改日期明细 -->
    <div v-if="canEdit && modifiedDays.length > 0" class="card mt-6">
      <div class="px-5 py-3 border-b border-gray-200 flex items-center justify-between">
        <div class="section-title flex items-center gap-2">
          <span>已修改日期明细</span>
          <span class="text-xs text-amber-500 bg-amber-50 px-2 py-0.5 rounded">{{ modifiedDays.length }} 天</span>
        </div>
        <span class="text-xs text-gray-400">默认状态：工作日/周末（按星期推算）</span>
      </div>
      <div class="p-3 max-h-48 overflow-y-auto">
        <div class="flex flex-wrap gap-2">
          <div
            v-for="d in modifiedDays"
            :key="d.date"
            class="flex items-center gap-1.5 px-2 py-1 rounded-md bg-gray-50 border border-gray-200 text-xs"
          >
            <span class="num font-medium text-gray-700">{{ d.date }}</span>
            <span class="text-gray-300">·</span>
            <span class="text-gray-400">周{{ weekdayName(d.date) }}</span>
            <span class="text-gray-300">→</span>
            <span class="font-medium" :class="dayTypeClass(d.day_type)">{{ dayDisplay(d) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 导入日期设置弹窗 -->
    <el-dialog v-model="importDayVisible" title="导入日期设置" width="560px">
      <div class="flex items-center gap-4 mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <div class="flex-1">
          <div class="text-sm font-medium text-gray-800 mb-1">第一步：下载模板</div>
          <div class="text-xs text-gray-500">按模板格式填写日期、日期性质和节假日名称，支持跨月数据</div>
        </div>
        <button class="btn-primary" @click="downloadDayTemplate">
          <el-icon><Download /></el-icon>下载模板
        </button>
      </div>
      <div class="flex items-center gap-4 mb-4 p-4 bg-gray-50 border border-gray-200 rounded-lg">
        <div class="flex-1">
          <div class="text-sm font-medium text-gray-800 mb-1">第二步：选择文件</div>
          <div class="text-xs text-gray-500">支持多种日期格式（2026-01-01、2026/1/1、2026年1月1日、20260101、Excel日期等），节假日必须填写名称。已保存排班的月份不可导入</div>
        </div>
        <label class="btn-ghost cursor-pointer">
          <el-icon><Upload /></el-icon>选择文件
          <input type="file" accept=".xlsx,.xls" class="hidden" @change="handleDayImportFile" />
        </label>
      </div>
      <!-- 解析中 -->
      <div v-if="importDayParsing" class="mb-3 p-4 text-center text-sm text-blue-600">
        <el-icon class="is-loading"><Loading /></el-icon>
        正在解析文件并验证数据...
      </div>
      <!-- 校验错误 -->
      <div v-if="importDayErrors.length > 0" class="mb-3 p-3 bg-red-50 border border-red-200 rounded-md">
        <div class="text-sm font-medium text-red-600 mb-1">数据校验失败</div>
        <div v-for="(err, i) in importDayErrors" :key="i" class="text-xs text-red-500">{{ err }}</div>
      </div>
      <div v-if="importDayPreview.length > 0">
        <div class="text-xs font-medium text-gray-600 mb-2">预览（共 {{ importDayPreview.length }} 天）</div>
        <div class="mb-2 text-xs flex items-center gap-2">
          <span class="text-gray-500">涉及月份：</span>
          <span class="px-2 py-0.5 rounded bg-blue-50 text-blue-600 font-medium">{{ importPreviewMonths.join('、') }}</span>
          <span v-if="!importIncludesCurrentMonth" class="text-amber-600">（当前月不在导入数据中，导入后将自动切换到对应月份）</span>
        </div>
        <el-table :data="importDayPreview.slice(0, 30)" size="small" max-height="280">
          <el-table-column prop="date" label="日期" width="120" />
          <el-table-column label="性质" width="80">
            <template #default="{ row }">{{ dayTypeLabel(row.day_type) }}</template>
          </el-table-column>
          <el-table-column prop="remark" label="节假日名称" />
        </el-table>
        <div v-if="importDayPreview.length > 30" class="text-xs text-gray-400 mt-2 text-center">
          仅显示前 30 条，共 {{ importDayPreview.length }} 条
        </div>
      </div>
      <template #footer>
        <button class="btn-ghost" @click="importDayVisible = false; importDayErrors = []">关闭</button>
        <button v-if="importDayPreview.length > 0" class="btn-primary ml-2" :disabled="importDayLoading" @click="confirmDayImport">
          {{ importDayLoading ? '导入中...' : '确认导入' }}
        </button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import * as XLSX from 'xlsx'
import { dayApi } from '@/api/day'
import { scheduleApi } from '@/api/schedule'
import { useAuthStore } from '@/stores/auth'
import { useStaffStore } from '@/stores/staff'
import { parseDateStr } from '@/utils/format'

const authStore = useAuthStore()
const staffStore = useStaffStore()
const canEdit = computed(() => authStore.isLoggedIn)

const currentMonth = ref(dayjs())
const groups = ref([])
const groupMembers = ref({})
const days = ref([])
const schedule = ref([])
const savedSchedule = ref(null) // 后端保存的排班记录（null=未保存）
const loading = ref(false)
const activeSelectDate = ref(null)
const isLocked = ref(false)
const snapshotVisible = ref(false)
const snapshotData = ref(null)

// 三态标记：saved / preview / dirty
// saved: 已保存到数据库  preview: 自动预览(未保存)  dirty: 有未保存改动
const scheduleState = computed(() => {
  if (hasChange.value) return 'dirty'
  if (savedSchedule.value) return 'saved'
  return 'preview'
})
const hasChange = ref(false)

const CACHE_KEY = 'shift_schedule_cache'
function getCacheMap() {
  try {
    return new Map(JSON.parse(localStorage.getItem(CACHE_KEY) || '[]'))
  } catch { return new Map() }
}
function saveCacheMap(map) {
  try {
    const entries = [...map.entries()]
    if (entries.length > 6) entries.splice(0, entries.length - 6)
    localStorage.setItem(CACHE_KEY, JSON.stringify(entries))
  } catch {}
}

const startGroupId = ref(null)
const dayTypeFilter = ref(['workday', 'weekend', 'holiday', 'vacation'])

const dayTypeOptions = [
  { value: 'workday', label: '工作日', color: 'bg-gray-100 text-gray-600' },
  { value: 'weekend', label: '周末', color: 'bg-blue-100 text-blue-700' },
  { value: 'holiday', label: '节假日', color: 'bg-red-100 text-red-600' },
  { value: 'vacation', label: '调休日', color: 'bg-orange-100 text-orange-600' },
]

const canModify = computed(() => canEdit.value && !isLocked.value)

async function loadData(forceRefresh = false) {
  loading.value = true
  hasChange.value = false
  try {
    const y = currentMonth.value.year()
    const m = currentMonth.value.month() + 1
    const cacheKey = `${y}-${m}`

    if (!forceRefresh) {
      const cacheMap = getCacheMap()
      if (cacheMap.has(cacheKey)) {
        const cached = cacheMap.get(cacheKey)
        await staffStore.loadAll()
        groups.value = staffStore.groups
        groupMembers.value = staffStore.groupMembersMap
        days.value = cached.days
        savedSchedule.value = cached.savedSchedule
        isLocked.value = cached.savedSchedule?.locked || false
        if (cached.savedSchedule) {
          schedule.value = JSON.parse(JSON.stringify(cached.savedSchedule.schedule_json))
        } else {
          await autoPreviewSchedule(y, m)
        }
        if (groups.value.length > 0 && !startGroupId.value) {
          startGroupId.value = groups.value[0].id
        }
        return
      }
    }

    await staffStore.loadAll()
    groups.value = staffStore.groups
    groupMembers.value = staffStore.groupMembersMap

    const [d, s] = await Promise.all([
      dayApi.listByMonth(y, m),
      scheduleApi.get(y, m),
    ])
    days.value = d
    savedSchedule.value = s
    isLocked.value = s?.locked || false
    if (s) {
      schedule.value = JSON.parse(JSON.stringify(s.schedule_json))
    } else {
      await autoPreviewSchedule(y, m)
    }
    if (groups.value.length > 0 && !startGroupId.value) {
      startGroupId.value = groups.value[0].id
    }

    const cacheMap = getCacheMap()
    cacheMap.set(cacheKey, { days: d, savedSchedule: s })
    saveCacheMap(cacheMap)
  } finally {
    loading.value = false
  }
}

async function autoPreviewSchedule(year, month) {
  if (groups.value.length === 0) {
    schedule.value = []
    return
  }
  try {
    const result = await scheduleApi.autoPreview(year, month)
    schedule.value = result.schedule || []
    if (result.start_group_id) {
      startGroupId.value = result.start_group_id
    }
    hasChange.value = false
  } catch {
    schedule.value = []
  }
}

onMounted(loadData)
watch(currentMonth, loadData)

// 对比当前组/人员与快照的差异
function detectSnapshotDiff() {
  if (!savedSchedule.value?.group_snapshot) return null
  const snap = savedSchedule.value.group_snapshot
  const snapGroups = snap.groups || []
  const curGroups = groups.value

  const diffs = []
  const snapGroupMap = Object.fromEntries(snapGroups.map(g => [g.id, g]))
  const curGroupMap = Object.fromEntries(curGroups.map(g => [g.id, g]))

  // 检查组变化
  for (const g of curGroups) {
    if (!snapGroupMap[g.id]) {
      diffs.push(`新增组「${g.name}」`)
    } else {
      const snapG = snapGroupMap[g.id]
      // 组名变更
      if (snapG.name !== g.name) {
        diffs.push(`「${snapG.name}」更名为「${g.name}」`)
      }
      // 组排序变更
      if (snapG.order_id !== g.order_id) {
        diffs.push(`「${g.name}」排序从 ${snapG.order_id} 变为 ${g.order_id}`)
      }
      // 人员变化
      const snapEmps = (snapG.employees || []).map(e => e.name).join(',')
      const curEmps = staffStore.employees
        .filter(e => e.group_id === g.id && e.state === 1)
        .map(e => e.name).join(',')
      if (snapEmps !== curEmps) {
        diffs.push(`「${g.name}」人员有变化`)
      }
    }
  }
  for (const g of snapGroups) {
    if (!curGroupMap[g.id]) {
      diffs.push(`删除组「${g.name}」`)
    }
  }

  // 检查不在任何组中的值班员工变化
  const snapUnassigned = (snapGroups.flatMap(g => g.employees || [])).filter(e => e.state === 1 && !e.group_id)
  const curUnassigned = staffStore.employees.filter(e => e.state === 1 && !e.group_id)
  if (snapUnassigned.length !== curUnassigned.length) {
    diffs.push(`未分组值班人员有变化`)
  }

  return diffs.length > 0 ? diffs : null
}

async function generateSchedule() {
  if (!canEdit.value) {
    ElMessage.warning('请先登录')
    return
  }
  if (isLocked.value) {
    ElMessage.warning('排班已锁定，请先解锁')
    return
  }
  if (!startGroupId.value) {
    ElMessage.warning('请选择起始组')
    return
  }
  if (groups.value.length === 0) {
    ElMessage.warning('请先到「人员管理」创建值班组')
    return
  }

  // 第一步：强制确认人员/组调整已完成
  try {
    await ElMessageBox.confirm(
      '请确认本月人员与组调整已完成，确认后开始生成排班。',
      '人员调整确认',
      { type: 'info', confirmButtonText: '已确认，生成排班', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  // 第二步：检查空组并提示（空组会自动跳过，但仍需告知用户）
  const nonEmptyGroups = groups.value.filter(g => {
    const members = groupMembers.value[g.id] || []
    return members.length > 0
  })
  const emptyGroups = groups.value.filter(g => {
    const members = groupMembers.value[g.id] || []
    return members.length === 0
  })

  if (emptyGroups.length > 0) {
    const names = emptyGroups.map(g => `第${g.order_id}组「${g.name}」`).join('、')
    try {
      await ElMessageBox.confirm(
        `以下组没有值班人员，将自动跳过：\n${names}\n\n仅对有人员的组进行排班。`,
        '空组提示',
        { type: 'warning', confirmButtonText: '继续生成', cancelButtonText: '取消' }
      )
    } catch {
      return
    }
    // 如果起始组是空组，自动切换到第一个非空组
    if (emptyGroups.some(g => g.id === startGroupId.value)) {
      if (nonEmptyGroups.length > 0) {
        startGroupId.value = nonEmptyGroups[0].id
      } else {
        ElMessage.warning('没有有人员的组，无法排班')
        return
      }
    }
  }

  if (nonEmptyGroups.length === 0) {
    ElMessage.warning('没有有人员的组，无法排班')
    return
  }

  const toArrange = days.value
    .filter((d) => dayTypeFilter.value.includes(d.day_type))
    .map((d) => dayjs(d.date).format('YYYY-MM-DD'))
  if (toArrange.length === 0) {
    ElMessage.warning('当前月份没有可排班的日期')
    return
  }
  try {
    const y = currentMonth.value.year()
    const m = currentMonth.value.month() + 1
    const result = await scheduleApi.generate({
      year: y, month: m,
      start_group_id: startGroupId.value,
      start_date: toArrange[0],
      days: toArrange,
    })
    schedule.value = result.schedule
    hasChange.value = true
    ElMessage.success(`已生成 ${result.schedule.length} 天排班预览`)
  } catch (e) {}
}

async function saveSchedule() {
  if (!canEdit.value) {
    ElMessage.warning('请先登录')
    return
  }
  if (isLocked.value) {
    ElMessage.warning('排班已锁定，请先解锁')
    return
  }
  if (schedule.value.length === 0) {
    ElMessage.warning('暂无排班数据可保存')
    return
  }
  try {
    await ElMessageBox.confirm('保存排班后将自动锁定，如需修改请先解锁。确认保存？', '保存确认', { type: 'warning' })
    const y = currentMonth.value.year()
    const m = currentMonth.value.month() + 1
    await scheduleApi.save({ year: y, month: m, schedule: schedule.value })
    // 保存后自动锁定
    await scheduleApi.lock(y, m)
    hasChange.value = false
    isLocked.value = true
    ElMessage.success('排班已保存并锁定')
    const cacheKey = `${y}-${m}`
    const cacheMap = getCacheMap()
    cacheMap.delete(cacheKey)
    saveCacheMap(cacheMap)
    await loadData(true)
  } catch (e) {}
}

// 取消当月值班：删除数据库中的保存记录，恢复为自动预览
async function cancelSchedule() {
  if (!canEdit.value) return
  if (!savedSchedule.value) {
    ElMessage.info('当前月份未保存排班，无需取消')
    return
  }
  if (isLocked.value) {
    ElMessage.warning('排班已锁定，请先解锁后再取消')
    return
  }
  try {
    await ElMessageBox.confirm(
      '取消后将删除本月已保存的排班记录，恢复为按上月自动预览。确定取消？',
      '取消排班',
      { type: 'warning' }
    )
    const y = currentMonth.value.year()
    const m = currentMonth.value.month() + 1
    await scheduleApi.delete(y, m)
    ElMessage.success('已取消当月排班，恢复为自动预览')
    const cacheKey = `${y}-${m}`
    const cacheMap = getCacheMap()
    cacheMap.delete(cacheKey)
    saveCacheMap(cacheMap)
    await loadData(true)
  } catch {}
}

async function toggleLock() {
  if (!canEdit.value) return
  const y = currentMonth.value.year()
  const m = currentMonth.value.month() + 1
  try {
    if (isLocked.value) {
      await ElMessageBox.confirm('确定要解锁排班吗？解锁后可以修改。', '解锁确认', { type: 'warning' })
      await scheduleApi.unlock(y, m)
      isLocked.value = false
      ElMessage.success('排班已解锁')
    } else {
      await ElMessageBox.confirm('锁定后不可修改排班，确定要锁定吗？', '锁定确认', { type: 'warning' })
      await scheduleApi.lock(y, m)
      isLocked.value = true
      ElMessage.success('排班已锁定')
    }
    const cacheKey = `${y}-${m}`
    const cacheMap = getCacheMap()
    cacheMap.delete(cacheKey)
    saveCacheMap(cacheMap)
  } catch {}
}

function changeGroupForDay(item, groupId) {
  if (!canModify.value) return
  const g = groups.value.find((x) => x.id === groupId)
  if (!g) return
  item.group_id = groupId
  item.group_name = g.name
  const members = staffStore.employees
    .filter(e => e.group_id === groupId && e.state === 1)
    .sort((a, b) => a.order_id - b.order_id)
  item.employees = members.map(e => ({ id: e.id, name: e.name }))
  hasChange.value = true
}

function removeDay(dateStr) {
  if (!canModify.value) return
  const idx = schedule.value.findIndex((x) => x.date === dateStr)
  if (idx >= 0) {
    schedule.value.splice(idx, 1)
    hasChange.value = true
  }
}

function dayTypeLabel(t) {
  return dayTypeOptions.find((o) => o.value === t)?.label || t
}
function dayTypeClass(t) {
  return dayTypeOptions.find((o) => o.value === t)?.color || ''
}
function groupLabel(g) {
  const members = groupMembers.value[g.id] || []
  const names = members.length > 0 ? members.join('') : '空组'
  return `${g.order_id}. ${names}`
}

function viewSnapshot() {
  if (savedSchedule.value?.group_snapshot) {
    snapshotData.value = savedSchedule.value.group_snapshot
    snapshotVisible.value = true
  } else {
    ElMessage.info('该月暂无快照记录')
  }
}

function exportSnapshot() {
  if (!canEdit.value) {
    ElMessage.warning('请先登录后再导出')
    return
  }
  if (!snapshotData.value) return
  const snap = snapshotData.value
  const y = currentMonth.value.year()
  const m = currentMonth.value.month() + 1
  const title = `${y}年${m}月排班人员快照`

  // Sheet1: 人员配置
  const empRows = []
  for (const g of snap.groups || []) {
    for (const emp of g.employees || []) {
      empRows.push({
        '组序号': g.order_id,
        '组名': g.name,
        '姓名': emp.name,
        '值班状态': emp.state === 1 ? '值班' : '不值班',
        '组内排序': emp.order_id,
      })
    }
    if ((g.employees || []).length === 0) {
      empRows.push({
        '组序号': g.order_id,
        '组名': g.name,
        '姓名': '（空组）',
        '值班状态': '-',
        '组内排序': '-',
      })
    }
  }
  const ws1 = XLSX.utils.json_to_sheet(empRows)
  // 插入标题行
  XLSX.utils.sheet_add_aoa(ws1, [[title]], { origin: 'A1' })
  XLSX.utils.sheet_add_aoa(ws1, [Object.keys(empRows[0])], { origin: 'A2' })
  XLSX.utils.sheet_add_json(ws1, empRows, { origin: 'A3', skipHeader: true })
  ws1['!cols'] = [{ wch: 8 }, { wch: 12 }, { wch: 10 }, { wch: 10 }, { wch: 10 }]
  ws1['!merges'] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 4 } }]

  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws1, '人员配置')

  // Sheet2: 变更记录
  const logs = snap.state_logs || []
  if (logs.length > 0) {
    const logTitle = `${y}年${m}月人员变更记录`
    const logRows = logs.map(log => ({
      '变更描述': log.employee_name,
      '变更前状态': log.old_state === 1 ? '值班' : '不值班',
      '变更后状态': log.new_state === 1 ? '值班' : '不值班',
      '变更时间': log.changed_at?.substring(0, 19).replace('T', ' ') || '-',
    }))
    const ws2 = XLSX.utils.json_to_sheet(logRows)
    XLSX.utils.sheet_add_aoa(ws2, [[logTitle]], { origin: 'A1' })
    XLSX.utils.sheet_add_aoa(ws2, [Object.keys(logRows[0])], { origin: 'A2' })
    XLSX.utils.sheet_add_json(ws2, logRows, { origin: 'A3', skipHeader: true })
    ws2['!cols'] = [{ wch: 30 }, { wch: 12 }, { wch: 12 }, { wch: 20 }]
    ws2['!merges'] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 3 } }]
    XLSX.utils.book_append_sheet(wb, ws2, '变更记录')
  }

  const ts = dayjs().format('YYYYMMDDHHmmss')
  XLSX.writeFile(wb, `排班快照_${y}年${m}月_${ts}.xlsx`)
  ElMessage.info('正在导出，请在下载对话框中确认保存')
}

function prevMonth() {
  if (hasChange.value) {
    ElMessageBox.confirm('当前有未保存的改动，切换月份将丢失。继续？', '提示', { type: 'warning' })
      .then(() => (currentMonth.value = currentMonth.value.subtract(1, 'month')))
      .catch(() => {})
  } else {
    currentMonth.value = currentMonth.value.subtract(1, 'month')
  }
}
function nextMonth() {
  if (hasChange.value) {
    ElMessageBox.confirm('当前有未保存的改动，切换月份将丢失。继续？', '提示', { type: 'warning' })
      .then(() => (currentMonth.value = currentMonth.value.add(1, 'month')))
      .catch(() => {})
  } else {
    currentMonth.value = currentMonth.value.add(1, 'month')
  }
}
function goToday() {
  if (hasChange.value) {
    ElMessageBox.confirm('当前有未保存的改动，切换月份将丢失。继续？', '提示', { type: 'warning' })
      .then(() => (currentMonth.value = dayjs()))
      .catch(() => {})
  } else {
    currentMonth.value = dayjs()
  }
}

const calendarCells = computed(() => {
  const start = currentMonth.value.startOf('month')
  const startDay = start.day()
  const leadingDays = startDay === 0 ? 6 : startDay - 1
  const daysInMonth = currentMonth.value.daysInMonth()
  const cells = []
  for (let i = 0; i < leadingDays; i++) {
    cells.push({ date: start.subtract(leadingDays - i, 'day'), inMonth: false, item: null })
  }
  for (let i = 1; i <= daysInMonth; i++) {
    const d = currentMonth.value.date(i)
    const dateStr = d.format('YYYY-MM-DD')
    const item = schedule.value.find((x) => x.date === dateStr)
    cells.push({ date: d, inMonth: true, item })
  }
  const remaining = 42 - cells.length
  for (let i = 1; i <= remaining; i++) {
    cells.push({ date: start.add(daysInMonth + i - 1, 'day'), inMonth: false, item: null })
  }
  return cells
})

const weekDays = ['一', '二', '三', '四', '五', '六', '日']

const stats = computed(() => {
  const byGroup = {}
  schedule.value.forEach((item) => {
    if (item.group_id) {
      byGroup[item.group_name] = (byGroup[item.group_name] || 0) + 1
    }
  })
  return byGroup
})

function exportSchedule() {
  if (!canEdit.value) {
    ElMessage.warning('请先登录后再导出')
    return
  }
  if (!schedule.value.length) {
    ElMessage.warning('暂无排班数据可导出')
    return
  }
  const y = currentMonth.value.year()
  const m = currentMonth.value.month() + 1
  const title = `${y}年${m}月值班排班表`

  const rows = schedule.value.map(item => {
    let dayLabel = dayTypeLabel(item.day_type)
    if (item.day_type === 'holiday' && item.holiday_name) dayLabel = item.holiday_name
    return {
      '日期': item.date,
      '性质': dayLabel,
      '值班组': item.group_name || '-',
      '值班人员': (item.employees || []).map(e => e.name).join('、') || '-',
    }
  })

  const ws = XLSX.utils.json_to_sheet(rows)
  // 在数据前插入标题行
  XLSX.utils.sheet_add_aoa(ws, [[title]], { origin: 'A1' })
  // 数据从第2行开始
  XLSX.utils.sheet_add_aoa(ws, [Object.keys(rows[0])], { origin: 'A2' })
  XLSX.utils.sheet_add_json(ws, rows, { origin: 'A3', skipHeader: true })
  ws['!cols'] = [{ wch: 12 }, { wch: 10 }, { wch: 12 }, { wch: 30 }]
  // 合并标题行
  ws['!merges'] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 3 } }]

  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, '排班表')

  const ts = dayjs().format('YYYYMMDDHHmmss')
  XLSX.writeFile(wb, `值班排班_${y}年${m}月_${ts}.xlsx`)
  ElMessage.info('正在导出，请在下载对话框中确认保存')
}

// ===== 导入排班 Excel =====
const importScheduleVisible = ref(false)
const importSchedulePreview = ref([])
const importScheduleLoading = ref(false)
const importScheduleErrors = ref([])
const importScheduleWarnings = ref([])
const importScheduleParsing = ref(false)

function openScheduleImportDialog() {
  importScheduleErrors.value = []
  importScheduleWarnings.value = []
  importSchedulePreview.value = []
  importScheduleVisible.value = true
}

function downloadScheduleTemplate() {
  const y = currentMonth.value.year()
  const m = currentMonth.value.month() + 1
  const title = `${y}年${m}月值班排班导入模板`
  const daysInMonth = currentMonth.value.daysInMonth()
  // 取真实组名和人员名作为示例
  const g1 = groups.value[0]
  const g2 = groups.value[1]
  const g1Name = g1?.name || '甲组'
  const g2Name = g2?.name || '乙组'
  const g1Emps = g1 ? staffStore.employees.filter(e => e.group_id === g1.id && e.state === 1).map(e => e.name).join('、') : '张三、李四'
  const g2Emps = g2 ? staffStore.employees.filter(e => e.group_id === g2.id && e.state === 1).map(e => e.name).join('、') : '王五、赵六'
  // 预填当月全部日期，前两行填示例数据
  const exampleRows = []
  for (let day = 1; day <= daysInMonth; day++) {
    const dateStr = `${y}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`
    if (day === 1) {
      exampleRows.push({ '日期': dateStr, '值班组': g1Name, '值班人员': g1Emps || '张三、李四' })
    } else if (day === 2) {
      exampleRows.push({ '日期': dateStr, '值班组': g2Name, '值班人员': g2Emps || '王五、赵六' })
    } else {
      exampleRows.push({ '日期': dateStr, '值班组': '', '值班人员': '' })
    }
  }
  const ws = XLSX.utils.json_to_sheet(exampleRows)
  XLSX.utils.sheet_add_aoa(ws, [[title]], { origin: 'A1' })
  XLSX.utils.sheet_add_aoa(ws, [Object.keys(exampleRows[0])], { origin: 'A2' })
  XLSX.utils.sheet_add_json(ws, exampleRows, { origin: 'A3', skipHeader: true })
  ws['!cols'] = [{ wch: 14 }, { wch: 14 }, { wch: 36 }]
  ws['!merges'] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 2 } }]
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, '排班表')
  XLSX.writeFile(wb, `排班导入模板_${y}年${m}月.xlsx`)
}

function handleScheduleImport(e) {
  if (!canEdit.value) {
    ElMessage.warning('请先登录')
    return
  }
  const file = e.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = async (evt) => {
    importScheduleParsing.value = true
    try {
      // 确保人员和组数据已加载
      await staffStore.loadAll()
      groups.value = staffStore.groups
      groupMembers.value = staffStore.groupMembersMap
      if (!groups.value.length) {
        ElMessage.warning('人员管理中没有值班组，无法导入。请先在人员管理中创建组和人员')
        return
      }
      const data = new Uint8Array(evt.target.result)
      const wb = XLSX.read(data, { type: 'array' })
      const ws = wb.Sheets[wb.SheetNames[0]]
      const rows = XLSX.utils.sheet_to_json(ws, { header: 1, raw: false, dateNF: 'yyyy-mm-dd' })
      const dataRows = rows.slice(2).filter(r => r[0] != null && String(r[0]).trim())
      const errors = []
      if (dataRows.length === 0) {
        errors.push('表格中没有数据行')
        importScheduleErrors.value = errors
        importSchedulePreview.value = []
        return
      }

      // 严格构建组名映射（组名 -> 组对象）
      const groupNameMap = Object.fromEntries(groups.value.map(g => [g.name, g]))
      // 严格构建人员名映射（姓名 -> 员工对象）
      const empNameMap = Object.fromEntries(staffStore.employees.map(e => [e.name, e]))

      // 第一遍：解析日期，检测重复
      const parsedDates = []
      const seenDates = new Set()
      for (let i = 0; i < dataRows.length; i++) {
        const r = dataRows[i]
        const rowNum = i + 3
        const dateStr = parseDateStr(r[0])
        if (!dateStr) {
          errors.push(`第${rowNum}行A列：无法识别日期"${r[0]}"，支持格式：2026-01-01、2026/1/1、2026年1月1日、20260101、Excel日期序列号等`)
          continue
        }
        if (seenDates.has(dateStr)) {
          errors.push(`第${rowNum}行A列：日期"${dateStr}"重复，同一日期不能出现多次`)
          continue
        }
        seenDates.add(dateStr)
        parsedDates.push({ row: r, rowNum, dateStr })
      }
      if (errors.length > 0) {
        importScheduleErrors.value = errors
        importSchedulePreview.value = []
        return
      }

      // 强验证：排班导入仅支持当前月，必须包含当月全部日期
      const curY = currentMonth.value.year()
      const curM = currentMonth.value.month() + 1
      const daysInMonth = currentMonth.value.daysInMonth()
      const outOfMonth = []
      for (const { rowNum, dateStr } of parsedDates) {
        const d = dayjs(dateStr)
        if (d.year() !== curY || d.month() + 1 !== curM) {
          outOfMonth.push(`第${rowNum}行：${dateStr}`)
        }
      }
      if (outOfMonth.length > 0) {
        errors.push(`排班导入仅支持当前月（${curY}年${curM}月），以下日期不在当月：${outOfMonth.join('、')}`)
      }
      // 检查当月每一天是否齐全
      const importedDateSet = new Set(parsedDates.map(p => p.dateStr))
      const missingDays = []
      for (let day = 1; day <= daysInMonth; day++) {
        const dateStr = dayjs(`${curY}-${String(curM).padStart(2, '0')}-${String(day).padStart(2, '0')}`).format('YYYY-MM-DD')
        if (!importedDateSet.has(dateStr)) {
          missingDays.push(dateStr)
        }
      }
      if (missingDays.length > 0) {
        errors.push(`排班导入必须包含当月全部 ${daysInMonth} 天，缺少以下日期：${missingDays.join('、')}`)
      }
      if (errors.length > 0) {
        importScheduleErrors.value = errors
        importSchedulePreview.value = []
        return
      }

      // 仅获取当前月的日期设置
      const dayInfoMap = {}
      const monthDays = await dayApi.listByMonth(curY, curM)
      for (const d of monthDays) {
        dayInfoMap[dayjs(d.date).format('YYYY-MM-DD')] = d
      }

      // 第二遍：严格验证组、人员、日期
      const parsed = []
      for (const { row: r, rowNum, dateStr } of parsedDates) {
        // 日期必须存在于日期设置中
        const dayInfo = dayInfoMap[dateStr]
        if (!dayInfo) {
          errors.push(`第${rowNum}行A列：日期"${dateStr}"在日期设置中不存在，请先在日期设置中初始化该月`)
          continue
        }
        // B列：值班组（严格验证，必须存在于人员管理中）
        const gName = String(r[1] || '').trim()
        if (!gName) {
          errors.push(`第${rowNum}行B列：值班组为空`)
          continue
        }
        if (!groupNameMap[gName]) {
          errors.push(`第${rowNum}行B列：值班组"${gName}"在人员管理中不存在，请先在人员管理中创建该组`)
          continue
        }
        // C列：值班人员（严格验证，必须存在于人员管理中）
        const empList = String(r[2] || '').split(/[、,，]/).map(n => n.trim()).filter(Boolean)
        if (empList.length === 0) {
          errors.push(`第${rowNum}行C列：值班人员为空`)
          continue
        }
        let hasEmpError = false
        for (const n of empList) {
          if (!empNameMap[n]) {
            errors.push(`第${rowNum}行C列：值班人员"${n}"在人员管理中不存在，请先在人员管理中创建该员工`)
            hasEmpError = true
          }
        }
        if (hasEmpError) continue
        // 日期性质从日期设置获取
        const dayType = dayInfo.day_type
        const holidayName = dayInfo.day_type === 'holiday' ? (dayInfo.remark || null) : null
        const groupId = groupNameMap[gName].id

        parsed.push({
          date: dateStr,
          day_type: dayType,
          holiday_name: holidayName,
          group_id: groupId,
          group_name: gName,
          employees: empList.map((name, idx) => ({ id: empNameMap[name].id, name, order_id: idx + 1 })),
        })
      }

      // 第三遍：整体验证 — 每个组的导入人员必须与人员管理中该组的当前成员完全一致
      if (errors.length === 0 && parsed.length > 0) {
        // 收集导入数据中每个组出现过的所有人员（去重）
        const importGroupPersons = new Map() // groupName -> Set(personName)
        for (const item of parsed) {
          if (!importGroupPersons.has(item.group_name)) {
            importGroupPersons.set(item.group_name, new Set())
          }
          for (const emp of item.employees) {
            importGroupPersons.get(item.group_name).add(emp.name)
          }
        }
        // 与人员管理中各组的当前成员比较：必须完全一致
        for (const [gName, importPersonSet] of importGroupPersons) {
          const group = groupNameMap[gName]
          const currentMembers = new Set(
            staffStore.employees
              .filter(e => e.group_id === group.id && e.state === 1)
              .map(e => e.name)
          )
          const importNames = [...importPersonSet]
          const missingInImport = [...currentMembers].filter(n => !importPersonSet.has(n))
          const extraInImport = importNames.filter(n => !currentMembers.has(n))
          if (missingInImport.length > 0 || extraInImport.length > 0 || importPersonSet.size !== currentMembers.size) {
            const parts = []
            if (missingInImport.length > 0) {
              parts.push(`人员管理中有但导入数据缺少：${missingInImport.join('、')}`)
            }
            if (extraInImport.length > 0) {
              parts.push(`导入数据中有但人员管理中无：${extraInImport.join('、')}`)
            }
            errors.push(`组「${gName}」的人员与人员管理不一致：${parts.join('；')}。排班导入要求该组人员与人员管理完全一致`)
          }
        }
      }

      importScheduleErrors.value = errors
      importScheduleWarnings.value = []
      importSchedulePreview.value = errors.length > 0 ? [] : parsed
    } catch (err) {
      ElMessage.error('文件解析失败，请检查是否为有效的 Excel 文件')
    } finally {
      importScheduleParsing.value = false
    }
  }
  reader.readAsArrayBuffer(file)
  e.target.value = ''
}

async function confirmScheduleImport() {
  if (!importSchedulePreview.value.length) return
  importScheduleLoading.value = true
  try {
    const y = currentMonth.value.year()
    const m = currentMonth.value.month() + 1
    const scheduleData = {
      year: y,
      month: m,
      schedule: importSchedulePreview.value.map(item => ({
        date: item.date,
        day_type: item.day_type,
        holiday_name: item.holiday_name,
        group_id: item.group_id,
        group_name: item.group_name,
        employees: item.employees.map(e => ({ id: e.id, name: e.name })),
      })),
    }

    // 检查是否已锁定
    const existing = await scheduleApi.get(y, m)
    if (existing?.locked) {
      ElMessage.warning(`${y}年${m}月排班已锁定，请先解锁后再导入`)
      return
    }

    await scheduleApi.save(scheduleData)

    // 清除当前月缓存
    const cacheKey = `${y}-${m}`
    const cacheMap = getCacheMap()
    cacheMap.delete(cacheKey)
    saveCacheMap(cacheMap)

    hasChange.value = false
    ElMessage.success(`已成功导入 ${y}年${m}月 排班数据`)

    importScheduleVisible.value = false
    importSchedulePreview.value = []
    await loadData(true)
  } catch (e) {
    ElMessage.error('导入失败: ' + (e.response?.data?.detail || e.message || '未知错误'))
  } finally {
    importScheduleLoading.value = false
  }
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto">
    <!-- 页头 -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <div class="text-xs text-blue-600 font-mono tracking-[0.3em] uppercase mb-1">/ Schedule</div>
        <h1 class="font-display text-3xl font-semibold text-gray-800">排班</h1>
        <p class="text-sm text-gray-500 mt-1">选择起始组，一键生成轮转排班，可手动微调</p>
      </div>

      <div class="flex items-center gap-3">
        <button class="btn-ghost px-3" @click="prevMonth"><el-icon><ArrowLeft /></el-icon></button>
        <div class="font-display text-2xl font-semibold num min-w-[160px] text-center">
          {{ currentMonth.format('YYYY 年 M 月') }}
        </div>
        <button class="btn-ghost px-3" @click="nextMonth"><el-icon><ArrowRight /></el-icon></button>
        <button class="btn-ghost" @click="goToday">今天</button>
      </div>
    </div>

    <!-- 排班参数（仅登录后可操作） -->
    <div v-if="canEdit" class="card p-5 mb-6">
      <!-- 锁定提示 -->
      <div v-if="isLocked" class="mb-4 px-3 py-2 bg-orange-50 border border-orange-200 rounded-md flex items-center justify-between">
        <div class="flex items-center gap-2 text-sm text-orange-700">
          <el-icon><Lock /></el-icon>
          <span class="font-medium">排班已锁定</span>
          <span class="text-orange-500">不可修改，如需调整请先解锁</span>
        </div>
        <button class="px-3 py-1 text-xs bg-orange-100 text-orange-700 rounded hover:bg-orange-200 transition-colors" @click="toggleLock">
          <el-icon><Unlock /></el-icon>解锁
        </button>
      </div>

      <!-- 已保存但解锁状态提示 -->
      <div v-if="savedSchedule && !isLocked && scheduleState === 'saved'" class="mb-4 px-3 py-2 bg-green-50 border border-green-200 rounded-md flex items-center justify-between text-sm text-green-700">
        <div class="flex items-center gap-2">
          <el-icon><CircleCheck /></el-icon>
          <span class="font-medium">排班已保存</span>
          <span class="text-green-500">（已解锁，可修改排班数据）</span>
        </div>
        <button class="px-3 py-1 text-xs bg-green-100 text-green-700 rounded hover:bg-green-200 transition-colors" @click="toggleLock">
          <el-icon><Lock /></el-icon>重新锁定
        </button>
      </div>

      <!-- 状态提示条 -->
      <div v-if="scheduleState === 'preview'" class="mb-4 px-3 py-2 bg-blue-50 border border-blue-200 rounded-md flex items-center justify-between">
        <div class="flex items-center gap-2 text-sm text-blue-700">
          <el-icon><View /></el-icon>
          <span class="font-medium">自动预览</span>
          <span class="text-blue-500">根据上月排班自动生成，保存后生效</span>
        </div>
      </div>

      <div class="flex flex-wrap items-end gap-3">
        <div class="w-40">
          <label class="block text-xs font-medium text-gray-600 mb-2">起始组</label>
          <el-select v-model="startGroupId" class="w-full" placeholder="选择起始组" :disabled="isLocked">
            <el-option v-for="g in groups" :key="g.id" :label="groupLabel(g)" :value="g.id" />
          </el-select>
        </div>
        <div class="w-52">
          <label class="block text-xs font-medium text-gray-600 mb-2">排班日期性质</label>
          <el-select v-model="dayTypeFilter" multiple class="w-full" placeholder="选择需要排班的日期类型" :disabled="isLocked">
            <el-option v-for="opt in dayTypeOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </div>
        <div class="flex flex-wrap gap-2 items-center flex-1 justify-end">
          <button class="btn-primary" @click="generateSchedule" :disabled="isLocked">
            <el-icon><MagicStick /></el-icon>生成排班
          </button>
          <div class="h-6 w-px bg-gray-200"></div>
          <button class="btn-ghost" @click="openScheduleImportDialog">
            <el-icon><Upload /></el-icon>导入
          </button>
          <button v-if="schedule.length > 0" class="btn-ghost" @click="exportSchedule">
            <el-icon><Download /></el-icon>导出
          </button>
          <div class="h-6 w-px bg-gray-200"></div>
          <!-- 保存按钮 -->
          <button class="btn-primary" @click="saveSchedule" :disabled="scheduleState !== 'dirty' || isLocked">
            <el-icon><DocumentChecked /></el-icon>
            {{
              isLocked ? '已锁定' :
              scheduleState === 'saved' ? '已保存' :
              scheduleState === 'dirty' ? '保存排班' :
              '保存排班'
            }}
          </button>
          <!-- 快照查看 -->
          <button v-if="savedSchedule" class="btn-ghost" @click="viewSnapshot" title="查看保存时的组/人员快照">
            <el-icon><Memo /></el-icon>
          </button>
          <!-- 取消排班按钮（锁定时禁用） -->
          <button v-if="savedSchedule" class="btn-ghost text-red-500 hover:text-red-700" :disabled="isLocked" @click="cancelSchedule" title="取消当月排班，恢复自动预览">
            <el-icon><Delete /></el-icon>
          </button>
        </div>
      </div>
      <div v-if="scheduleState === 'dirty'" class="mt-3 text-xs text-amber-600 flex items-center gap-1">
        <el-icon><Warning /></el-icon>有未保存的改动
      </div>
    </div>
    <div v-else class="card p-5 mb-6 text-center text-sm text-gray-400">
      登录后可生成和保存排班
    </div>

    <!-- 排班日历 -->
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
          class="min-h-[100px] border border-gray-200 rounded-md p-2 transition-all relative"
          :class="[
            cell.inMonth ? 'bg-white' : 'bg-gray-50 opacity-50',
            cell.item ? dayTypeClass(cell.item.day_type).replace('text-', 'border-l-4 border-l-').split(' ')[0] + ' border-l-4' : '',
          ]"
          :style="{
            borderLeftColor: cell.item ? (cell.item.day_type === 'holiday' ? '#f56c6c' : cell.item.day_type === 'vacation' ? '#e6a23c' : cell.item.day_type === 'weekend' ? '#409eff' : '#909399') : undefined,
            zIndex: activeSelectDate === cell.date.format('YYYY-MM-DD') ? 10 : undefined,
          }"
        >
          <div class="flex items-center justify-between mb-1">
            <span
              class="num text-sm font-medium"
              :class="cell.date.day() === 0 || cell.date.day() === 6 ? 'text-blue-600' : 'text-gray-700'"
            >
              {{ cell.date.date() }}
            </span>
            <span v-if="cell.item" class="day-badge text-[10px]" :class="dayTypeClass(cell.item.day_type)">
              {{ cell.item.holiday_name || dayTypeLabel(cell.item.day_type) }}
            </span>
          </div>

          <!-- 排班内容 -->
          <div v-if="cell.item" class="space-y-1">
            <el-select
              v-if="canModify"
              :model-value="cell.item.group_id"
              size="small"
              class="w-full schedule-day-select"
              popper-class="schedule-day-popper"
              @change="(val) => changeGroupForDay(cell.item, val)"
              @visible-change="(vis) => activeSelectDate = vis ? cell.item.date : null"
            >
              <el-option v-for="g in groups" :key="g.id" :label="`第${g.order_id}组`" :value="g.id">
                <span class="text-xs">{{ groupLabel(g) }}</span>
              </el-option>
            </el-select>
            <div v-else class="text-xs font-medium text-gray-700">
              {{ cell.item.group_name }}
            </div>
            <div class="text-[10px] text-gray-500 truncate">
              {{ cell.item.employees.map(e => e.name).join('、') || '无成员' }}
            </div>
            <button
              v-if="canModify"
              class="text-[10px] text-red-400 hover:text-red-600"
              @click="removeDay(cell.item.date)"
            >
              移除
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 排班概览 -->
    <div v-if="schedule.length > 0" class="card p-5 mt-6">
      <div class="section-title mb-4">本月排班概览</div>
      <div class="flex flex-wrap gap-3">
        <div v-for="(count, name) in stats" :key="name" class="flex items-center gap-2">
          <div class="px-3 py-1.5 bg-gray-50 rounded-md">
            <span class="text-sm text-gray-600">{{ name }}</span>
            <span class="num text-sm font-semibold text-blue-600 ml-2">{{ count }} 天</span>
          </div>
        </div>
        <div class="px-3 py-1.5 bg-blue-50 rounded-md ml-auto">
          <span class="text-sm text-gray-600">合计</span>
          <span class="num text-sm font-semibold text-blue-700 ml-2">{{ schedule.length }} 天</span>
        </div>
      </div>
    </div>

    <div v-else-if="!loading" class="card p-12 mt-6 text-center">
      <el-icon size="40" class="text-gray-300 mb-3"><Calendar /></el-icon>
      <div class="text-gray-500 mb-2">本月尚未排班</div>
      <div class="text-xs text-gray-400">系统将根据上月排班自动预览，也可手动选择起始组生成</div>
    </div>

    <!-- 快照查看弹窗 -->
    <el-dialog v-model="snapshotVisible" :title="`人员快照 — ${currentMonth.format('YYYY年M月')}`" width="640px">
      <div v-if="snapshotData">
        <div class="text-xs text-gray-400 mb-3">保存排班时的组与人员配置，用于历史统计回溯</div>
        <div v-for="g in snapshotData.groups" :key="g.id" class="mb-3 p-3 bg-gray-50 rounded-md">
          <div class="flex items-center gap-2 mb-2">
            <span class="inline-flex items-center justify-center w-5 h-5 rounded bg-blue-500 text-white text-xs font-bold">{{ g.order_id }}</span>
            <span class="font-medium text-gray-800">{{ g.name }}</span>
            <span class="text-xs text-gray-400 ml-auto">{{ g.employees.length }} 人</span>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="emp in g.employees"
              :key="emp.id"
              class="px-2 py-0.5 rounded text-xs"
              :class="emp.state === 1 ? 'bg-green-100 text-green-700' : 'bg-gray-200 text-gray-500'"
            >
              {{ emp.name }}
              <span v-if="emp.state !== 1" class="text-[10px]">(不值班)</span>
            </span>
            <span v-if="g.employees.length === 0" class="text-xs text-gray-400">空组</span>
          </div>
        </div>
        <div v-if="snapshotData.state_logs && snapshotData.state_logs.length > 0" class="mt-4">
          <div class="text-xs font-medium text-gray-500 mb-2">变更记录</div>
          <div class="max-h-40 overflow-y-auto">
            <div
              v-for="(log, i) in snapshotData.state_logs"
              :key="i"
              class="flex items-center gap-2 text-xs py-1 border-b border-gray-100"
            >
              <span class="text-gray-600">{{ log.employee_name }}</span>
              <span class="text-gray-400 ml-auto">{{ log.changed_at?.substring(0, 10) }}</span>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="py-8 text-center text-gray-400 text-sm">暂无快照数据</div>
      <template #footer>
        <div class="flex items-center gap-3">
          <button class="btn-ghost" @click="exportSnapshot">
            <el-icon><Download /></el-icon>导出 Excel
          </button>
          <button class="btn-primary" @click="snapshotVisible = false">关闭</button>
        </div>
      </template>
    </el-dialog>

    <!-- 导入排班预览弹窗 -->
    <el-dialog v-model="importScheduleVisible" title="导入排班表" width="640px">
      <div class="flex items-center gap-4 mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <div class="flex-1">
          <div class="text-sm font-medium text-gray-800 mb-1">第一步：下载模板</div>
          <div class="text-xs text-gray-500">只需填写日期、值班组、值班人员三列，日期性质自动从日期设置获取</div>
        </div>
        <button class="btn-primary" @click="downloadScheduleTemplate">
          <el-icon><Download /></el-icon>下载模板
        </button>
      </div>
      <div class="flex items-center gap-4 mb-4 p-4 bg-gray-50 border border-gray-200 rounded-lg">
        <div class="flex-1">
          <div class="text-sm font-medium text-gray-800 mb-1">第二步：选择文件</div>
          <div class="text-xs text-gray-500">仅支持导入当前月（{{ currentMonth.format('YYYY 年 M 月') }}）的排班，必须包含当月全部日期，值班组和人员必须与人员管理数据一致</div>
        </div>
        <label class="btn-ghost cursor-pointer">
          <el-icon><Upload /></el-icon>选择文件
          <input type="file" accept=".xlsx,.xls" class="hidden" @change="handleScheduleImport" />
        </label>
      </div>
      <!-- 解析中 -->
      <div v-if="importScheduleParsing" class="mb-3 p-4 text-center text-sm text-blue-600">
        <el-icon class="is-loading"><Loading /></el-icon>
        正在解析文件并验证数据...
      </div>
      <!-- 校验错误 -->
      <div v-if="importScheduleErrors.length > 0" class="mb-3 p-3 bg-red-50 border border-red-200 rounded-md">
        <div class="text-sm font-medium text-red-600 mb-1">数据校验失败</div>
        <div v-for="(err, i) in importScheduleErrors" :key="i" class="text-xs text-red-500">{{ err }}</div>
      </div>
      <!-- 警告 -->
      <div v-if="importScheduleWarnings.length > 0" class="mb-3 p-3 bg-amber-50 border border-amber-200 rounded-md">
        <div class="text-sm font-medium text-amber-600 mb-1">注意</div>
        <div v-for="(w, i) in importScheduleWarnings" :key="i" class="text-xs text-amber-600">{{ w }}</div>
      </div>
      <!-- 预览 -->
      <div v-if="importSchedulePreview.length > 0">
        <div class="text-xs font-medium text-gray-600 mb-2">预览（共 {{ importSchedulePreview.length }} 天，导入到 {{ currentMonth.format('YYYY 年 M 月') }}）</div>
        <el-table :data="importSchedulePreview.slice(0, 20)" size="small" max-height="320">
          <el-table-column prop="date" label="日期" width="120" />
          <el-table-column prop="group_name" label="值班组" width="120" />
          <el-table-column label="值班人员">
            <template #default="{ row }">
              {{ row.employees.map(e => e.name).join('、') }}
            </template>
          </el-table-column>
        </el-table>
        <div v-if="importSchedulePreview.length > 20" class="text-xs text-gray-400 mt-2 text-center">
          仅显示前 20 条，共 {{ importSchedulePreview.length }} 条
        </div>
      </div>
      <template #footer>
        <button class="btn-ghost" @click="importScheduleVisible = false; importScheduleErrors = []; importScheduleWarnings = []">关闭</button>
        <button v-if="importSchedulePreview.length > 0" class="btn-primary ml-2" :disabled="importScheduleLoading" @click="confirmScheduleImport">
          {{ importScheduleLoading ? '导入中...' : '确认导入' }}
        </button>
      </template>
    </el-dialog>
  </div>
</template>

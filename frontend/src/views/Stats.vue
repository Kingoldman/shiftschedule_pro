<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import dayjs from 'dayjs'
import * as XLSX from 'xlsx'
import { ElMessage } from 'element-plus'
import { statsApi } from '@/api/schedule'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const canEdit = computed(() => authStore.isLoggedIn)

const statMode = ref('monthly')
const currentYear = ref(dayjs().year())
const currentMonth = ref(dayjs())

const stats = ref({
  by_employee: [],
  by_group: [],
  by_day_type: { workday: 0, weekend: 0, holiday: 0 },
  total_days: 0,
  period_label: '',
})
const loading = ref(false)

const hasData = computed(() => stats.value.by_employee.length > 0)

const modeOptions = [
  { value: 'monthly', label: '按月' },
  { value: 'yearly', label: '按年' },
  { value: 'cumulative', label: '累计' },
]

const periodLabel = computed(() => {
  if (statMode.value === 'monthly') return currentMonth.value.format('YYYY 年 M 月')
  if (statMode.value === 'yearly') return `${currentYear.value} 年`
  if (statMode.value === 'cumulative') return '累计统计'
  return ''
})

// 频率计算：用户勾选参与计算的日期性质
const freqTypes = ref(['workday', 'weekend', 'holiday'])

function toggleFreqType(type) {
  const idx = freqTypes.value.indexOf(type)
  if (idx > -1) {
    if (freqTypes.value.length > 1) freqTypes.value.splice(idx, 1)
  } else {
    freqTypes.value.push(type)
  }
}

// 自定义频率：分母为勾选日期性质对应的 eligible 天数之和
// 例如：工作日+节假日频率 = (eligible_workday + eligible_holiday) / (工作日值班天数 + 节假日值班天数)
function customFreq(row) {
  let eligible = 0
  let count = 0
  const eligibleMap = { workday: 'eligible_workday', weekend: 'eligible_weekend', holiday: 'eligible_holiday' }
  for (const type of freqTypes.value) {
    eligible += row[eligibleMap[type]] || 0
    count += row[type] || 0
  }
  if (!count || !eligible) return '-'
  return (eligible / count).toFixed(1)
}

const customFreqLabel = computed(() => {
  const map = { workday: '工作日', weekend: '周末', holiday: '节假日' }
  return freqTypes.value.map(t => map[t]).join('+') + '频率'
})

// 员工明细排序
const sortKey = ref('total')
const sortOrder = ref('desc')
function toggleSort(key) {
  if (sortKey.value === key) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortOrder.value = 'desc'
  }
}
const sortedEmployeeData = computed(() => {
  const list = [...stats.value.by_employee]
  const order = sortOrder.value === 'asc' ? 1 : -1
  const getVal = (item) => {
    if (sortKey.value === 'freq') {
      const freq = customFreq(item)
      return freq === '-' ? 0 : parseFloat(freq)
    }
    return item[sortKey.value] || 0
  }
  list.sort((a, b) => (getVal(a) - getVal(b)) * order)
  return list
})

async function loadStats() {
  loading.value = true
  try {
    let result
    if (statMode.value === 'monthly') {
      const y = currentMonth.value.year()
      const m = currentMonth.value.month() + 1
      result = await statsApi.monthly(y, m)
    } else if (statMode.value === 'yearly') {
      result = await statsApi.yearly(currentYear.value)
    } else if (statMode.value === 'cumulative') {
      result = await statsApi.cumulative()
    }
    if (result) stats.value = result
  } finally {
    loading.value = false
  }
}

onMounted(loadStats)
watch(statMode, loadStats)
watch(currentMonth, loadStats)
watch(currentYear, loadStats)

function prevMonth() { currentMonth.value = currentMonth.value.subtract(1, 'month') }
function nextMonth() { currentMonth.value = currentMonth.value.add(1, 'month') }
function goThisMonth() { currentMonth.value = dayjs() }
function prevYear() { currentYear.value-- }
function nextYear() { currentYear.value++ }
function goThisYear() { currentYear.value = dayjs().year() }

function totalCount(item) { return item.total || 0 }
const sortColors = { workday: '#10b981', weekend: '#3b82f6', holiday: '#ef4444', total: '#f59e0b', freq: '#8b5cf6' }
function sortIconHtml(key) {
  if (sortKey.value !== key) return `<span style="color:#c0c4cc">⇅</span>`
  const color = sortColors[key] || '#409eff'
  return sortOrder.value === 'asc'
    ? `<span style="color:${color};font-weight:bold">↑</span>`
    : `<span style="color:${color};font-weight:bold">↓</span>`
}
function sortHeaderClass(key) {
  return sortKey.value === key ? 'font-bold' : ''
}

// 导出 Excel：分别导出四种频率（不依据前端筛选的日期性质）
async function exportExcel() {
  if (!canEdit.value) {
    ElMessage.warning('请先登录后再导出')
    return
  }
  const data = sortedEmployeeData.value
  if (!data.length) return

  // 先弹出保存对话框（必须在用户手势同步上下文中调用）
  const ts = dayjs().format('YYYYMMDDHHmmss')
  const fileName = `值班统计_${periodLabel.value}_${ts}.xlsx`
  let fileHandle = null
  if (window.showSaveFilePicker) {
    try {
      fileHandle = await window.showSaveFilePicker({
        suggestedName: fileName,
        types: [{ description: 'Excel 文件', accept: { 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'] } }],
      })
    } catch (e) {
      if (e.name === 'AbortError') return  // 用户取消
      fileHandle = null
    }
  }

  // 频率计算：可值班天数 / 实际值班天数
  const calcFreq = (emp, type) => {
    const eligibleMap = { workday: 'eligible_workday', weekend: 'eligible_weekend', holiday: 'eligible_holiday', total: 'eligible_total' }
    const countMap = { workday: 'workday', weekend: 'weekend', holiday: 'holiday', total: 'total' }
    const eligible = emp[eligibleMap[type]] || 0
    const count = emp[countMap[type]] || 0
    if (!count || !eligible) return '-'
    return `每${(eligible / count).toFixed(1)}天`
  }

  const rows = data.map((emp, i) => ({
    '排名': i + 1,
    '姓名': emp.name,
    '工作日(含调休)': emp.workday || 0,
    '工作日频率': calcFreq(emp, 'workday'),
    '周末': emp.weekend || 0,
    '周末频率': calcFreq(emp, 'weekend'),
    '节假日': emp.holiday || 0,
    '节假日频率': calcFreq(emp, 'holiday'),
    '合计': emp.total || 0,
    '合计频率': calcFreq(emp, 'total'),
  }))

  const ws = XLSX.utils.json_to_sheet(rows)
  const excelTitle = `值班统计 — ${periodLabel.value}`
  XLSX.utils.sheet_add_aoa(ws, [[excelTitle]], { origin: 'A1' })
  XLSX.utils.sheet_add_aoa(ws, [Object.keys(rows[0])], { origin: 'A2' })
  XLSX.utils.sheet_add_json(ws, rows, { origin: 'A3', skipHeader: true })
  ws['!cols'] = [
    { wch: 6 }, { wch: 10 }, { wch: 14 }, { wch: 12 }, { wch: 8 }, { wch: 12 },
    { wch: 8 }, { wch: 12 }, { wch: 8 }, { wch: 12 },
  ]
  ws['!merges'] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 9 } }]
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, '员工明细')

  // 保存：优先使用 File System Access API，否则回退到 XLSX.writeFile
  if (fileHandle) {
    const writable = await fileHandle.createWritable()
    const xlsxData = XLSX.write(wb, { type: 'array', bookType: 'xlsx' })
    await writable.write(new Blob([xlsxData], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
    await writable.close()
    ElMessage.success('Excel 已导出')
  } else {
    XLSX.writeFile(wb, fileName)
    ElMessage.info('正在导出，请在下载对话框中确认保存')
  }
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto">
    <div class="flex items-center justify-between mb-6">
      <div>
        <div class="text-xs text-blue-600 font-mono tracking-[0.3em] uppercase mb-1">/ Stats</div>
        <h1 class="font-display text-3xl font-semibold text-gray-800">值班统计</h1>
        <p class="text-sm text-gray-500 mt-1">按员工、日期性质分类汇总值班次数与频率</p>
      </div>
      <button v-if="hasData && canEdit" class="btn-ghost" @click="exportExcel">
        <el-icon><Download /></el-icon>导出
      </button>
    </div>

    <!-- 统计模式选择器 -->
    <div class="card p-4 mb-6">
      <div class="flex items-center gap-4 flex-wrap">
        <div class="flex gap-1">
          <button
            v-for="opt in modeOptions"
            :key="opt.value"
            class="px-4 py-1.5 rounded-md text-sm font-medium transition-colors"
            :class="statMode === opt.value
              ? 'bg-blue-500 text-white'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'"
            @click="statMode = opt.value"
          >
            {{ opt.label }}
          </button>
        </div>

        <template v-if="statMode === 'monthly'">
          <div class="h-6 w-px bg-gray-200"></div>
          <div class="flex items-center gap-2">
            <button class="btn-ghost px-2 py-1" @click="prevMonth"><el-icon><ArrowLeft /></el-icon></button>
            <span class="font-display text-lg font-semibold num min-w-[120px] text-center">
              {{ currentMonth.format('YYYY 年 M 月') }}
            </span>
            <button class="btn-ghost px-2 py-1" @click="nextMonth"><el-icon><ArrowRight /></el-icon></button>
            <button class="btn-ghost px-2 py-1 text-xs" @click="goThisMonth">本月</button>
          </div>
        </template>

        <template v-if="statMode === 'yearly'">
          <div class="h-6 w-px bg-gray-200"></div>
          <div class="flex items-center gap-2">
            <button class="btn-ghost px-2 py-1" @click="prevYear"><el-icon><ArrowLeft /></el-icon></button>
            <span class="font-display text-lg font-semibold num min-w-[80px] text-center">{{ currentYear }} 年</span>
            <button class="btn-ghost px-2 py-1" @click="nextYear"><el-icon><ArrowRight /></el-icon></button>
            <button class="btn-ghost px-2 py-1 text-xs" @click="goThisYear">本年</button>
          </div>
        </template>

        <div class="ml-auto text-sm text-gray-500">
          当前：<span class="font-medium text-gray-700">{{ periodLabel }}</span>
        </div>
      </div>
    </div>

    <div v-loading="loading">
      <template v-if="hasData">
        <div class="card">
          <div class="px-5 py-4 border-b border-gray-200 flex items-center justify-between flex-wrap gap-3">
            <div class="section-title">员工明细</div>
            <div class="flex items-center gap-4 flex-wrap">
              <div class="flex items-center gap-2 text-xs text-gray-500">
                <span>频率计算：</span>
                <div class="flex gap-1">
                  <button
                    v-for="opt in [
                      { value: 'workday', label: '工作日', color: '#10b981' },
                      { value: 'weekend', label: '周末', color: '#3b82f6' },
                      { value: 'holiday', label: '节假日', color: '#ef4444' },
                    ]"
                    :key="opt.value"
                    class="px-2 py-0.5 rounded text-xs font-medium transition-colors border"
                    :class="freqTypes.includes(opt.value)
                      ? 'text-white border-transparent'
                      : 'bg-white text-gray-400 border-gray-200 hover:border-gray-300'"
                    :style="freqTypes.includes(opt.value) ? { backgroundColor: opt.color, borderColor: opt.color } : {}"
                    @click="toggleFreqType(opt.value)"
                  >
                    {{ opt.label }}
                  </button>
                </div>
              </div>
              <div class="text-xs text-gray-400">
                共 <span class="num font-semibold text-gray-600">{{ stats.total_days }}</span> 天排班
              </div>
            </div>
          </div>
          <el-table :data="sortedEmployeeData" style="width: 100%" size="small" max-height="520">
            <el-table-column label="排名" type="index" width="60" align="center">
              <template #default="{ $index }">
                <span class="num font-semibold" :class="$index < 3 ? 'text-blue-600' : 'text-gray-400'">
                  {{ $index + 1 }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="姓名" prop="name" width="80">
              <template #default="{ row }">
                <span class="font-medium">{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column align="center">
              <template #header>
                <span class="cursor-pointer select-none" :class="sortHeaderClass('workday')" @click="toggleSort('workday')">工作日(含调休) <span v-html="sortIconHtml('workday')"></span></span>
              </template>
              <template #default="{ row }">
                <span class="num" :class="sortKey === 'workday' ? 'font-semibold text-green-600' : ''">{{ row.workday || 0 }}</span>
              </template>
            </el-table-column>
            <el-table-column align="center">
              <template #header>
                <span class="cursor-pointer select-none" :class="sortHeaderClass('weekend')" @click="toggleSort('weekend')">周末 <span v-html="sortIconHtml('weekend')"></span></span>
              </template>
              <template #default="{ row }">
                <span class="num" :class="sortKey === 'weekend' ? 'font-semibold text-blue-600' : ''">{{ row.weekend || 0 }}</span>
              </template>
            </el-table-column>
            <el-table-column align="center">
              <template #header>
                <span class="cursor-pointer select-none" :class="sortHeaderClass('holiday')" @click="toggleSort('holiday')">节假日 <span v-html="sortIconHtml('holiday')"></span></span>
              </template>
              <template #default="{ row }">
                <span class="num" :class="sortKey === 'holiday' ? 'font-semibold text-red-500' : ''">{{ row.holiday || 0 }}</span>
              </template>
            </el-table-column>
            <el-table-column align="center">
              <template #header>
                <span class="cursor-pointer select-none" :class="sortHeaderClass('total')" @click="toggleSort('total')">合计 <span v-html="sortIconHtml('total')"></span></span>
              </template>
              <template #default="{ row }">
                <span class="num" :class="sortKey === 'total' ? 'font-semibold text-amber-600' : 'font-semibold text-blue-600'">{{ totalCount(row) }}</span>
              </template>
            </el-table-column>
            <el-table-column align="center" min-width="120">
              <template #header>
                <span class="cursor-pointer select-none" :class="sortHeaderClass('freq')" @click="toggleSort('freq')">{{ customFreqLabel }} <span v-html="sortIconHtml('freq')"></span></span>
              </template>
              <template #default="{ row }">
                <span class="num text-sm font-semibold text-purple-600">
                  {{ customFreq(row) === '-' ? '-' : `每${customFreq(row)}天` }}
                </span>
                <div class="text-[10px] text-gray-400">
                  {{ (() => { const m={workday:'eligible_workday',weekend:'eligible_weekend',holiday:'eligible_holiday'}; let e=0,c=0; for(const t of freqTypes){e+=row[m[t]]||0;c+=row[t]||0} return e })() }}天可值 / {{ (() => { let c=0; for(const t of freqTypes) c+=row[t]||0; return c })() }}天值班
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </template>

      <div v-else-if="!loading" class="card p-16 text-center">
        <el-icon size="40" class="text-gray-300 mb-3"><DataAnalysis /></el-icon>
        <div class="text-gray-500 mb-2">当前区间暂无排班数据</div>
        <div class="text-xs text-gray-400">请先到「排班」页面生成并保存排班</div>
      </div>
    </div>
  </div>
</template>

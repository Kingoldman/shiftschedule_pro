<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import dayjs from 'dayjs'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { statsApi } from '@/api/schedule'

const loading = ref(false)
const selectedId = ref(null)
const employeeData = ref(null)
const exporting = ref(false)

// 人员列表：从当前员工 + 排班历史中获取（包括已删除的）
const allPersons = ref([])

// 统计模式：按月/按年/累计（与 Stats.vue 一致，移除自定义区间避免计算错误）
const statMode = ref('monthly')
const currentYear = ref(dayjs().year())
const currentMonth = ref(dayjs())

const modeOptions = [
  { value: 'monthly', label: '按月' },
  { value: 'yearly', label: '按年' },
  { value: 'cumulative', label: '累计' },
]

const periodLabel = computed(() => {
  if (statMode.value === 'monthly') return currentMonth.value.format('YYYY 年 M 月')
  if (statMode.value === 'yearly') return `${currentYear.value} 年`
  return '累计统计'
})

const employees = computed(() => allPersons.value)

// ===== 频率统计（与 Stats.vue 完全一致的逻辑和配色）=====
const freqTypes = ref(['workday', 'weekend', 'holiday'])
function toggleFreqType(type) {
  const idx = freqTypes.value.indexOf(type)
  if (idx > -1) {
    if (freqTypes.value.length > 1) freqTypes.value.splice(idx, 1)
  } else {
    freqTypes.value.push(type)
  }
}
const customFreqLabel = computed(() => {
  const map = { workday: '工作日', weekend: '周末', holiday: '节假日' }
  return freqTypes.value.map(t => map[t]).join('+') + '频率'
})

function customFreq(row) {
  const eligibleMap = { workday: 'eligible_workday', weekend: 'eligible_weekend', holiday: 'eligible_holiday' }
  let eligible = 0, count = 0
  for (const t of freqTypes.value) {
    eligible += row[eligibleMap[t]] || 0
    count += row[t] || 0
  }
  if (!count || !eligible) return '-'
  return (eligible / count).toFixed(1)
}

// 频率公式文本：X天可值 / Y天值班
function freqFormula(row) {
  const eligibleMap = { workday: 'eligible_workday', weekend: 'eligible_weekend', holiday: 'eligible_holiday' }
  let eligible = 0, count = 0
  for (const t of freqTypes.value) {
    eligible += row[eligibleMap[t]] || 0
    count += row[t] || 0
  }
  return `${eligible}天可值 / ${count}天值班`
}

// 概览卡片的频率公式
function overviewFreqFormula(type) {
  const o = employeeData.value?.overview
  if (!o) return ''
  const map = {
    workday: { eligible: 'eligible_workday', count: 'workday' },
    weekend: { eligible: 'eligible_weekend', count: 'weekend' },
    holiday: { eligible: 'eligible_holiday', count: 'holiday' },
    total: { eligible: 'eligible_total', count: 'total_duty_days' },
  }
  const m = map[type]
  if (!m) return ''
  return `${o[m.eligible] || 0}天可值 / ${o[m.count] || 0}天值班`
}

// 月度明细排序（与 Stats.vue 一致的配色）
const sortKey = ref('month')
const sortOrder = ref('asc')
function toggleSort(key) {
  if (sortKey.value === key) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortOrder.value = 'desc'
  }
}
const sortedMonthlyTrend = computed(() => {
  if (!employeeData.value?.monthly_trend) return []
  const list = [...employeeData.value.monthly_trend]
  const order = sortOrder.value === 'asc' ? 1 : -1
  const getVal = (item) => {
    if (sortKey.value === 'freq') {
      const f = customFreq(item)
      return f === '-' ? 0 : parseFloat(f)
    }
    return item[sortKey.value] || 0
  }
  list.sort((a, b) => (getVal(a) - getVal(b)) * order)
  return list
})
const sortColors = { workday: '#10b981', weekend: '#3b82f6', holiday: '#ef4444', total: '#f59e0b', freq: '#8b5cf6' }
function sortIconHtml(key) {
  if (sortKey.value !== key) return '<span style="color:#c0c4cc">⇅</span>'
  const color = sortColors[key] || '#409eff'
  return sortOrder.value === 'asc'
    ? `<span style="color:${color};font-weight:bold">↑</span>`
    : `<span style="color:${color};font-weight:bold">↓</span>`
}
function sortHeaderClass(key) {
  return sortKey.value === key ? 'font-bold' : ''
}

// ===== 所有值班记录：日期排序 + 性质筛选 =====
const dutiesSortOrder = ref('desc')  // 日期排序：desc=新→旧
const dayTypeFilterValues = ref([])  // 性质筛选：空数组=全部（el-table 多选过滤）

const filteredSortedDuties = computed(() => {
  let all = [...(employeeData.value?.all_duties || [])]
  if (dayTypeFilterValues.value.length > 0) {
    const set = new Set(dayTypeFilterValues.value)
    all = all.filter(d => set.has(d.day_type))
  }
  return dutiesSortOrder.value === 'asc'
    ? all.sort((a, b) => a.date.localeCompare(b.date))
    : all.sort((a, b) => b.date.localeCompare(a.date))
})

const dutiesPage = ref(1)
const dutiesPageSize = 20
const pagedDuties = computed(() => {
  const all = filteredSortedDuties.value
  const start = (dutiesPage.value - 1) * dutiesPageSize
  return all.slice(start, start + dutiesPageSize)
})
function toggleDutiesSort() {
  dutiesSortOrder.value = dutiesSortOrder.value === 'asc' ? 'desc' : 'asc'
  dutiesPage.value = 1
}
// el-table @filter-change 回调：同步外部状态
function onFilterChange(filters) {
  if (filters.day_type !== undefined) {
    dayTypeFilterValues.value = filters.day_type || []
    dutiesPage.value = 1
  }
}
const dayTypeFilters = [
  { text: '工作日', value: 'workday' },
  { text: '周末', value: 'weekend' },
  { text: '节假日', value: 'holiday' },
]

// ===== 数据加载 =====
async function loadEmployeeData() {
  if (!selectedId.value) {
    employeeData.value = null
    return
  }
  loading.value = true
  try {
    let result
    if (statMode.value === 'monthly') {
      const y = currentMonth.value.year()
      const m = currentMonth.value.month() + 1
      result = await statsApi.employee(selectedId.value, 'monthly', y, m)
    } else if (statMode.value === 'yearly') {
      result = await statsApi.employee(selectedId.value, 'yearly', currentYear.value)
    } else {
      result = await statsApi.employee(selectedId.value, 'cumulative')
    }
    employeeData.value = result
    dutiesPage.value = 1
    dayTypeFilterValues.value = []
    await nextTick()
    renderCharts()
  } finally {
    loading.value = false
  }
}

function onEmployeeChange() {
  dutiesPage.value = 1
  dayTypeFilterValues.value = []
  loadEmployeeData()
}

// 月份/年份导航
function prevMonth() { currentMonth.value = currentMonth.value.subtract(1, 'month') }
function nextMonth() { currentMonth.value = currentMonth.value.add(1, 'month') }
function goThisMonth() { currentMonth.value = dayjs() }
function prevYear() { currentYear.value-- }
function nextYear() { currentYear.value++ }
function goThisYear() { currentYear.value = dayjs().year() }

// ===== ECharts =====
const trendChartRef = ref(null)
const pieChartRef = ref(null)
let trendChart = null
let pieChart = null

function renderTrendChart() {
  if (!trendChartRef.value) return
  if (!trendChart) trendChart = echarts.init(trendChartRef.value)
  const trend = employeeData.value?.monthly_trend || []
  trendChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['工作日','周末','节假日','合计'], top: 0 },
    grid: { left: 36, right: 16, top: 40, bottom: 28 },
    xAxis: { type: 'category', data: trend.map(m => m.month), axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { fontSize: 11 } },
    series: [
      { name:'工作日', type:'line', smooth:true, symbol:'circle', symbolSize:6, data: trend.map(m=>m.workday), itemStyle:{color:'#10b981'} },
      { name:'周末', type:'line', smooth:true, symbol:'circle', symbolSize:6, data: trend.map(m=>m.weekend), itemStyle:{color:'#3b82f6'} },
      { name:'节假日', type:'line', smooth:true, symbol:'circle', symbolSize:6, data: trend.map(m=>m.holiday), itemStyle:{color:'#ef4444'} },
      { name:'合计', type:'line', smooth:true, symbol:'circle', symbolSize:7, data: trend.map(m=>m.total), itemStyle:{color:'#f59e0b'}, lineStyle:{width:3,type:'dashed'} },
    ],
  })
}

function renderPieChart() {
  if (!pieChartRef.value) return
  if (!pieChart) pieChart = echarts.init(pieChartRef.value)
  const data = employeeData.value?.day_type_distribution || []
  pieChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c}天 ({d}%)' },
    legend: { bottom: 0, left: 'center', itemWidth: 12, itemHeight: 12, textStyle: { fontSize: 12 } },
    series: [{
      type: 'pie',
      radius: ['35%','65%'],
      center: ['50%','45%'],
      avoidLabelOverlap: true,
      label: { show: true, formatter: '{b}: {c}天', fontSize: 12 },
      data,
      color: ['#10b981','#3b82f6','#ef4444'],
    }],
  })
}

function renderCharts() {
  renderTrendChart()
  renderPieChart()
}

function handleResize() {
  trendChart?.resize()
  pieChart?.resize()
}

// ===== PDF 导出 =====
const stateText = (s) => s === 1 ? '值班中' : s === 0 ? '不值班' : '已删除'

async function exportPDF() {
  if (!employeeData.value || employeeData.value.overview.total_duty_days === 0) {
    ElMessage.warning('当前无数据可导出')
    return
  }
  exporting.value = true
  const emp = employeeData.value.employee || {}
  const fileName = `${emp.name || '员工'}_值班报告_${periodLabel.value}.pdf`
  // 先弹出保存对话框（必须在用户手势同步上下文中调用）
  let fileHandle = null
  if (window.showSaveFilePicker) {
    try {
      fileHandle = await window.showSaveFilePicker({
        suggestedName: fileName,
        types: [{ description: 'PDF 文件', accept: { 'application/pdf': ['.pdf'] } }],
      })
    } catch (e) {
      if (e.name === 'AbortError') { exporting.value = false; return }
      fileHandle = null
    }
  }
  try {
    const html2canvasMod = await import('html2canvas')
    const html2canvas = html2canvasMod.default || html2canvasMod
    const { jsPDF } = await import('jspdf')
    const data = employeeData.value
    const ov = data.overview
    const now = dayjs().format('YYYY-MM-DD HH:mm')
    const genDate = now.split(' ')[0]

    const ovFreqFormula = (type) => {
      const map = { workday: { eligible: 'eligible_workday', count: 'workday' }, weekend: { eligible: 'eligible_weekend', count: 'weekend' }, holiday: { eligible: 'eligible_holiday', count: 'holiday' }, total: { eligible: 'eligible_total', count: 'total_duty_days' } }
      const m = map[type]; if (!m) return ''
      return `${ov[m.eligible] || 0}天可值 / ${ov[m.count] || 0}天值班`
    }
    const calcFreqAndFormula = (row, type) => {
      const eligibleKey = { workday: 'eligible_workday', weekend: 'eligible_weekend', holiday: 'eligible_holiday', total: 'eligible' }
      const countKey = { workday: 'workday', weekend: 'weekend', holiday: 'holiday', total: 'total' }
      const eligible = row[eligibleKey[type]] || 0; const count = row[countKey[type]] || 0
      if (!count || !eligible) return { freq: '-', formula: `${eligible}天可值 / ${count}天值班` }
      return { freq: `每${(eligible / count).toFixed(1)}天`, formula: `${eligible}天可值 / ${count}天值班` }
    }

    // 捕获图表为图片
    const trendImg = trendChart?.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' }) || ''
    const pieImg = pieChart?.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' }) || ''

    // 月度明细表
    const trendRows = (data.monthly_trend || []).map(m => {
      const wf = calcFreqAndFormula(m, 'workday'), wef = calcFreqAndFormula(m, 'weekend')
      const hf = calcFreqAndFormula(m, 'holiday'), tf = calcFreqAndFormula(m, 'total')
      return `<tr>
        <td style="padding:4px 3px;border:1px solid #e5e7eb;text-align:center">${m.month}</td><td style="padding:4px 3px;border:1px solid #e5e7eb;text-align:center">${m.workday || 0}</td>
        <td style="padding:4px 3px;border:1px solid #e5e7eb;text-align:center;color:#059669;font-weight:bold">${wf.freq}<br/><span style="font-size:10px;color:#9ca3af;font-weight:normal">${wf.formula}</span></td>
        <td style="padding:4px 3px;border:1px solid #e5e7eb;text-align:center">${m.weekend || 0}</td>
        <td style="padding:4px 3px;border:1px solid #e5e7eb;text-align:center;color:#2563eb;font-weight:bold">${wef.freq}<br/><span style="font-size:10px;color:#9ca3af;font-weight:normal">${wef.formula}</span></td>
        <td style="padding:4px 3px;border:1px solid #e5e7eb;text-align:center">${m.holiday || 0}</td>
        <td style="padding:4px 3px;border:1px solid #e5e7eb;text-align:center;color:#dc2626;font-weight:bold">${hf.freq}<br/><span style="font-size:10px;color:#9ca3af;font-weight:normal">${hf.formula}</span></td>
        <td style="padding:4px 3px;border:1px solid #e5e7eb;text-align:center;font-weight:bold">${m.total}</td>
        <td style="padding:4px 3px;border:1px solid #e5e7eb;text-align:center;color:#d97706;font-weight:bold">${tf.freq}<br/><span style="font-size:10px;color:#9ca3af;font-weight:normal">${tf.formula}</span></td>
      </tr>`
    }).join('')

    const allDuties = data.all_duties || []
    const renderDutyRow = (d) => `<tr>
      <td style="padding:3px 6px;border:1px solid #e5e7eb;text-align:center">${d.date}</td>
      <td style="padding:3px 6px;border:1px solid #e5e7eb;text-align:center">${dayTypeMap[d.day_type] || d.day_type}</td>
      <td style="padding:3px 6px;border:1px solid #e5e7eb">${d.group_name || '-'}</td>
      <td style="padding:3px 6px;border:1px solid #e5e7eb">${d.coworkers?.length ? d.coworkers.join('、') : '单独值班'}</td>
    </tr>`
    const dutyHeaderHtml = `<thead><tr style="background:#f9fafb">
      <th style="padding:4px 6px;border:1px solid #e5e7eb;text-align:center">日期</th>
      <th style="padding:4px 6px;border:1px solid #e5e7eb;text-align:center">性质</th>
      <th style="padding:4px 6px;border:1px solid #e5e7eb;text-align:center">值班组</th>
      <th style="padding:4px 6px;border:1px solid #e5e7eb;text-align:center">同班人员</th>
    </tr></thead>`

    const wrapperStyle = 'font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:#1f2937;padding:16px 20px 28px 20px;width:750px'

    // 各 section 独立 HTML
    const sections = [
      // 1. 报告头 + 基本信息
      `<div style="${wrapperStyle}">
        <div style="text-align:center;border-bottom:2px solid #3b82f6;padding-bottom:10px;margin-bottom:12px">
          <div style="font-size:11px;color:#6b7280;letter-spacing:2px">SHIFT SCHEDULE SYSTEM</div>
          <div style="font-size:20px;font-weight:bold;color:#1e40af;margin:3px 0">个人值班数据报告</div>
          <div style="font-size:11px;color:#6b7280">统计区间：${periodLabel.value} · 生成时间：${now}</div>
        </div>
        <table style="width:100%;font-size:13px;margin-bottom:0;border-collapse:collapse">
          <tr><td style="background:#f3f4f6;padding:5px 10px;width:90px;font-weight:bold">姓名</td><td style="padding:5px 10px">${emp.name || '-'}</td><td style="background:#f3f4f6;padding:5px 10px;width:90px;font-weight:bold">状态</td><td style="padding:5px 10px">${stateText(emp.state)}</td></tr>
          <tr><td style="background:#f3f4f6;padding:5px 10px;font-weight:bold">所属组</td><td style="padding:5px 10px">${emp.group_name || '未分组'}</td><td style="background:#f3f4f6;padding:5px 10px;font-weight:bold">统计区间</td><td style="padding:5px 10px">${periodLabel.value}</td></tr>
        </table>
      </div>`,
      // 2. 概览统计卡片
      `<div style="${wrapperStyle}">
        <div style="font-size:14px;font-weight:bold;margin-bottom:8px;border-left:3px solid #3b82f6;padding-left:8px">概览统计</div>
        <table style="width:100%;font-size:12px;border-collapse:collapse">
          <tr>
            <td style="background:#eff6ff;padding:8px;text-align:center;border:1px solid #dbeafe"><div style="font-size:10px;color:#6b7280">累计值班</div><div style="font-size:20px;font-weight:bold;color:#1e40af">${ov.total_duty_days}<span style="font-size:11px">天</span></div></td>
            <td style="background:#eff6ff;padding:8px;text-align:center;border:1px solid #dbeafe"><div style="font-size:10px;color:#6b7280">可值班天数</div><div style="font-size:20px;font-weight:bold;color:#1e40af">${ov.eligible_total}<span style="font-size:11px">天</span></div></td>
            <td style="background:#ecfdf5;padding:8px;text-align:center;border:1px solid #d1fae5"><div style="font-size:10px;color:#6b7280">工作日频率</div><div style="font-size:15px;font-weight:bold;color:#059669">${ov.freq_workday ? '每' + ov.freq_workday + '天' : '-'}</div><div style="font-size:9px;color:#9ca3af">${ovFreqFormula('workday')}</div></td>
          </tr>
          <tr>
            <td style="background:#eff6ff;padding:8px;text-align:center;border:1px solid #dbeafe"><div style="font-size:10px;color:#6b7280">周末频率</div><div style="font-size:15px;font-weight:bold;color:#2563eb">${ov.freq_weekend ? '每' + ov.freq_weekend + '天' : '-'}</div><div style="font-size:9px;color:#9ca3af">${ovFreqFormula('weekend')}</div></td>
            <td style="background:#fef2f2;padding:8px;text-align:center;border:1px solid #fecaca"><div style="font-size:10px;color:#6b7280">节假日频率</div><div style="font-size:15px;font-weight:bold;color:#dc2626">${ov.freq_holiday ? '每' + ov.freq_holiday + '天' : '-'}</div><div style="font-size:9px;color:#9ca3af">${ovFreqFormula('holiday')}</div></td>
            <td style="background:#fffbeb;padding:8px;text-align:center;border:1px solid #fde68a"><div style="font-size:10px;color:#6b7280">综合频率</div><div style="font-size:15px;font-weight:bold;color:#d97706">${ov.frequency ? '每' + ov.frequency + '天' : '-'}</div><div style="font-size:9px;color:#9ca3af">${ovFreqFormula('total')}</div></td>
          </tr>
        </table>
      </div>`,
    ]

    // 3. 趋势图（如果有）
    if (trendImg) {
      sections.push(`<div style="${wrapperStyle}">
        <div style="font-size:14px;font-weight:bold;margin-bottom:8px;border-left:3px solid #10b981;padding-left:8px">月度值班趋势</div>
        <div style="text-align:center"><img src="${trendImg}" style="max-width:100%;border:1px solid #e5e7eb;border-radius:4px"/></div>
      </div>`)
    }
    // 4. 饼图（如果有）
    if (pieImg) {
      sections.push(`<div style="${wrapperStyle}">
        <div style="font-size:14px;font-weight:bold;margin-bottom:8px;border-left:3px solid #f59e0b;padding-left:8px">日期性质分布</div>
        <div style="text-align:center"><img src="${pieImg}" style="max-width:100%;border:1px solid #e5e7eb;border-radius:4px"/></div>
      </div>`)
    }
    // 5. 月度明细表
    sections.push(`<div style="${wrapperStyle}">
      <div style="font-size:14px;font-weight:bold;margin-bottom:8px;border-left:3px solid #8b5cf6;padding-left:8px">月度频率明细</div>
      <table style="width:100%;font-size:11px;border-collapse:collapse">
        <thead><tr style="background:#f9fafb">
          <th style="padding:5px 3px;border:1px solid #e5e7eb;text-align:center">月份</th><th style="padding:5px 3px;border:1px solid #e5e7eb;text-align:center">工作日</th><th style="padding:5px 3px;border:1px solid #e5e7eb;text-align:center">工作日频率</th>
          <th style="padding:5px 3px;border:1px solid #e5e7eb;text-align:center">周末</th><th style="padding:5px 3px;border:1px solid #e5e7eb;text-align:center">周末频率</th>
          <th style="padding:5px 3px;border:1px solid #e5e7eb;text-align:center">节假日</th><th style="padding:5px 3px;border:1px solid #e5e7eb;text-align:center">节假日频率</th>
          <th style="padding:5px 3px;border:1px solid #e5e7eb;text-align:center">合计</th><th style="padding:5px 3px;border:1px solid #e5e7eb;text-align:center">合计频率</th>
        </tr></thead>
        <tbody>${trendRows}</tbody>
      </table>
    </div>`)
    // 6. 值班记录（分块渲染，每块独立 section 避免 canvas 切片导致文字截断）
    const DUTY_CHUNK_SIZE = 30
    const dutyTotalPages = Math.ceil(allDuties.length / DUTY_CHUNK_SIZE)
    for (let ci = 0; ci < dutyTotalPages; ci++) {
      const chunk = allDuties.slice(ci * DUTY_CHUNK_SIZE, (ci + 1) * DUTY_CHUNK_SIZE)
      const chunkRows = chunk.map(renderDutyRow).join('')
      const pageLabel = dutyTotalPages > 1 ? `（第${ci + 1}/${dutyTotalPages}页）` : ''
      sections.push(`<div style="${wrapperStyle}">
        <div style="font-size:14px;font-weight:bold;margin-bottom:8px;border-left:3px solid #ef4444;padding-left:8px">所有值班记录（共${allDuties.length}条）${pageLabel}</div>
        <table style="width:100%;font-size:11px;border-collapse:collapse">
          ${dutyHeaderHtml}
          <tbody>${chunkRows}</tbody>
        </table>
      </div>`)
    }
    // 7. 页脚
    sections.push(`<div style="${wrapperStyle}">
      <div style="font-size:10px;color:#9ca3af;text-align:center;border-top:1px solid #e5e7eb;padding-top:8px">隔壁小王爱值班系统 · 报告生成于 ${genDate}</div>
    </div>`)

    // 遮罩层
    const overlay = document.createElement('div')
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(255,255,255,0.97);z-index:99998;display:flex;align-items:center;justify-content:center;font-size:15px;color:#666;'
    overlay.textContent = '正在生成 PDF 报告，请稍候...'
    document.body.appendChild(overlay)

    const html2canvasOpts = { scale: 2, useCORS: true, backgroundColor: '#ffffff', width: 750, windowWidth: 800, logging: false }

    // 逐个 section 渲染：每个 section 独立 canvas，加到 PDF 时自动处理分页
    const pdf = new jsPDF('p', 'mm', 'a4')
    const pageW = 210, pageH = 297
    const marginX = 15, marginTop = 20, marginBottom = 20
    const contentW = pageW - marginX * 2
    const contentH = pageH - marginTop - marginBottom
    let currentY = marginTop

    for (let si = 0; si < sections.length; si++) {
      const sDiv = document.createElement('div')
      sDiv.style.cssText = 'position:fixed;top:0;left:0;width:750px;background:#ffffff;z-index:99997;'
      sDiv.innerHTML = sections[si]
      document.body.appendChild(sDiv)

      // 等待图片加载
      const imgs = Array.from(sDiv.querySelectorAll('img'))
      await Promise.all(imgs.map(img => {
        if (img.complete && img.naturalWidth > 0) return Promise.resolve()
        return new Promise(resolve => { img.onload = resolve; img.onerror = resolve; setTimeout(resolve, 2000) })
      }))
      await new Promise(r => setTimeout(r, 100))

      const sCanvas = await html2canvas(sDiv, html2canvasOpts)
      document.body.removeChild(sDiv)

      const sHeightMm = (sCanvas.height * contentW) / sCanvas.width
      const imgData = sCanvas.toDataURL('image/jpeg', 0.92)

      if (sHeightMm <= contentH) {
        // 整个 section 能放入当前页
        if (currentY + sHeightMm > pageH - marginBottom) {
          pdf.addPage(); currentY = marginTop
        }
        pdf.addImage(imgData, 'JPEG', marginX, currentY, contentW, sHeightMm)
        currentY += sHeightMm + 3
      } else {
        // section 太长，需要分页渲染
        // 核心思路：精确计算每页剩余空间对应的 canvas 像素数，确保切片不会超出页面
        // 不使用 overlap（会导致切片超出页面），不使用 renderH 压缩（会导致文字变形）
        const pxPerMm = sCanvas.width / contentW  // 每 mm 对应的 canvas 像素数
        let srcY = 0
        while (srcY < sCanvas.height) {
          // 当前页剩余可用高度（mm）
          const availMm = pageH - marginBottom - currentY
          if (availMm < 15) {
            // 剩余空间太小，换新页
            pdf.addPage(); currentY = marginTop
          }
          const usableMm = pageH - marginBottom - currentY
          // 剩余空间能容纳的 canvas 像素数（向下取整，确保不超出）
          const pxThisPage = Math.floor(usableMm * pxPerMm)
          const srcH = Math.min(pxThisPage, sCanvas.height - srcY)
          if (srcH <= 0) break
          const pageCanvas = document.createElement('canvas')
          pageCanvas.width = sCanvas.width; pageCanvas.height = srcH
          const ctx = pageCanvas.getContext('2d')
          ctx.drawImage(sCanvas, 0, srcY, sCanvas.width, srcH, 0, 0, sCanvas.width, srcH)
          // 切片的精确 mm 高度 = 像素数 / 像素每mm
          const sliceHmm = srcH / pxPerMm
          pdf.addImage(pageCanvas.toDataURL('image/jpeg', 0.92), 'JPEG', marginX, currentY, contentW, sliceHmm)
          currentY += sliceHmm + 2
          srcY += srcH
          // 如果还有更多内容，换新页
          if (srcY < sCanvas.height) {
            pdf.addPage(); currentY = marginTop
          }
        }
      }
    }

    document.body.removeChild(overlay)

    // 保存
    if (fileHandle) {
      try {
        const writable = await fileHandle.createWritable()
        await writable.write(pdf.output('blob'))
        await writable.close()
        ElMessage.success('PDF 报告已导出')
      } catch (e) {
        pdf.save(fileName)
        ElMessage.success('PDF 报告已导出')
      }
    } else {
      pdf.save(fileName)
      ElMessage.success('PDF 报告已导出')
    }
  } catch (e) {
    console.error('PDF export error:', e)
    ElMessage.error('导出失败：' + (e?.message || '未知错误'))
  } finally {
    exporting.value = false
  }
}

onMounted(async () => {
  // 加载所有人员列表（包括已删除但有值班记录的），但不自动选中——等用户手动选择
  try {
    allPersons.value = await statsApi.employeesWithHistory()
  } catch (e) {
    allPersons.value = []
  }
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  trendChart?.dispose()
  pieChart?.dispose()
})

watch(selectedId, () => {
  trendChart?.dispose()
  pieChart?.dispose()
  trendChart = null
  pieChart = null
})

watch(statMode, () => { if (selectedId.value) loadEmployeeData() })
watch(currentMonth, () => { if (statMode.value === 'monthly' && selectedId.value) loadEmployeeData() })
watch(currentYear, () => { if (statMode.value === 'yearly' && selectedId.value) loadEmployeeData() })

function freqDescription(freq) {
  if (!freq || freq === 0) return '-'
  return `每${freq.toFixed(1)}天`
}

const dayTypeMap = { workday: '工作日', weekend: '周末', holiday: '节假日' }
function dayTypeLabel(t) { return dayTypeMap[t] || t }
function dayTypeColor(t) {
  return { workday: 'bg-gray-100 text-gray-600', weekend: 'bg-blue-100 text-blue-700', holiday: 'bg-red-100 text-red-600' }[t] || ''
}
function weekdayLabel(dateStr) {
  const d = dayjs(dateStr)
  const names = ['周日','周一','周二','周三','周四','周五','周六']
  return names[d.day()]
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto">
    <!-- 头部 -->
    <div class="flex items-start justify-between mb-4">
      <div>
        <div class="text-xs text-blue-600 font-mono tracking-[0.3em] uppercase mb-1">/ Personal Query</div>
        <h1 class="font-display text-3xl font-semibold text-gray-800">个人查询</h1>
        <p class="text-sm text-gray-500 mt-1">查询单个人员的值班历史、趋势与统计分析</p>
      </div>
      <button
        v-if="employeeData && employeeData.overview && employeeData.overview.total_duty_days > 0"
        class="btn-ghost flex items-center gap-1.5"
        :disabled="exporting"
        @click="exportPDF"
      >
        <el-icon><Download /></el-icon>
        <span v-if="!exporting">导出报告</span>
        <span v-else>导出中...</span>
      </button>
    </div>

    <!-- 人员搜索 + 统计模式选择 -->
    <div class="card p-4 mb-4">
      <div class="flex items-center gap-4 flex-wrap">
        <!-- 人员选择（支持大量人员，包括已删除的） -->
        <el-select
          v-model="selectedId"
          filterable
          clearable
          placeholder="搜索选择人员"
          style="width: 240px"
          @change="onEmployeeChange"
          @clear="selectedId = null; employeeData = null"
        >
          <el-option
            v-for="emp in employees"
            :key="emp.id"
            :label="emp.deleted ? `${emp.name}（已删除）` : emp.name"
            :value="emp.id"
          >
            <div class="flex items-center gap-2">
              <span
                class="w-1.5 h-1.5 rounded-full"
                :class="emp.deleted ? 'bg-red-400' : (emp.state === 1 ? 'bg-green-400' : 'bg-gray-400')"
              ></span>
              <span :class="emp.deleted ? 'text-red-500' : ''">{{ emp.name }}</span>
              <span v-if="emp.deleted" class="text-xs text-red-400">已删除</span>
              <span v-else-if="emp.state === 0" class="text-xs text-gray-400">不值班</span>
              <span class="text-xs text-gray-400">{{ emp.group_name || '未分组' }}</span>
            </div>
          </el-option>
        </el-select>

        <!-- 模式选择 -->
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

        <!-- 月份导航 -->
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

        <!-- 年份导航 -->
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

    <!-- 数据区 -->
    <div v-loading="loading">
      <template v-if="employeeData && employeeData.overview">
        <!-- Sticky 员工信息条 -->
        <div class="card p-4 mb-4 sticky top-0 z-10 shadow-md">
          <div class="flex items-center justify-between flex-wrap gap-3">
            <div class="flex items-center gap-3">
              <div>
                <div class="flex items-center gap-2">
                  <span class="font-display text-xl font-semibold text-gray-800">{{ employeeData.employee?.name }}</span>
                  <span v-if="employeeData.employee?.state === 1" class="day-badge day-badge-workday">值班中</span>
                  <span v-else-if="employeeData.employee?.state === 0" class="day-badge bg-gray-100 text-gray-500">不值班</span>
                  <span v-else class="day-badge bg-gray-100 text-gray-400">已删除</span>
                </div>
                <div class="text-xs text-gray-500 mt-1">
                  所属组：<span class="font-medium text-gray-700">{{ employeeData.employee?.group_name || '未分组' }}</span>
                  <span class="mx-2 text-gray-300">|</span>
                  共 <span class="num font-semibold text-gray-700">{{ employeeData.duty_days?.length || 0 }}</span> 天值班
                </div>
              </div>
            </div>
            <div class="text-sm text-gray-500">
              <span class="font-medium text-gray-700">{{ periodLabel }}</span>
            </div>
          </div>
        </div>

        <template v-if="employeeData.overview.total_duty_days > 0">
          <!-- 概览数字卡片 -->
          <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
            <div class="card p-4">
              <div class="text-xs text-gray-500 mb-1">累计值班</div>
              <div class="font-display text-2xl font-semibold num text-gray-800">{{ employeeData.overview.total_duty_days }}</div>
              <div class="text-[10px] text-gray-400 mt-1">天</div>
            </div>
            <div class="card p-4">
              <div class="text-xs text-gray-500 mb-1">可值班天数</div>
              <div class="font-display text-2xl font-semibold num text-blue-600">{{ employeeData.overview.eligible_total }}</div>
              <div class="text-[10px] text-gray-400 mt-1">{{ employeeData.monthly_trend?.length || 0 }}个月累计</div>
            </div>
            <div class="card p-4">
              <div class="text-xs text-gray-500 mb-1">工作日频率</div>
              <div class="font-display text-2xl font-semibold num text-green-600">
                {{ freqDescription(employeeData.overview.freq_workday) }}
              </div>
              <div class="text-[10px] text-gray-400 mt-1">{{ overviewFreqFormula('workday') }}</div>
            </div>
            <div class="card p-4">
              <div class="text-xs text-gray-500 mb-1">周末频率</div>
              <div class="font-display text-2xl font-semibold num text-blue-600">
                {{ freqDescription(employeeData.overview.freq_weekend) }}
              </div>
              <div class="text-[10px] text-gray-400 mt-1">{{ overviewFreqFormula('weekend') }}</div>
            </div>
            <div class="card p-4">
              <div class="text-xs text-gray-500 mb-1">节假日频率</div>
              <div class="font-display text-2xl font-semibold num text-red-500">
                {{ freqDescription(employeeData.overview.freq_holiday) }}
              </div>
              <div class="text-[10px] text-gray-400 mt-1">{{ overviewFreqFormula('holiday') }}</div>
            </div>
            <div class="card p-4">
              <div class="text-xs text-gray-500 mb-1">综合频率</div>
              <div class="font-display text-2xl font-semibold num text-amber-600">
                {{ freqDescription(employeeData.overview.frequency) }}
              </div>
              <div class="text-[10px] text-gray-400 mt-1">{{ overviewFreqFormula('total') }}</div>
            </div>
          </div>

          <!-- 图表区：上下布局 -->
          <div class="grid grid-cols-1 gap-4 mb-4">
            <div class="card p-4">
              <div class="section-title mb-3">月度值班趋势</div>
              <div ref="trendChartRef" style="width: 100%; height: 280px;"></div>
            </div>
            <div class="card p-4">
              <div class="section-title mb-3">日期性质分布</div>
              <div ref="pieChartRef" style="width: 100%; height: 300px;"></div>
            </div>
          </div>

          <!-- 月度频率明细表格（配色与 Stats.vue 一致，无"可值班"列） -->
          <div class="card mb-4">
            <div class="px-5 py-4 border-b border-gray-200 flex items-center justify-between flex-wrap gap-3">
              <div class="section-title">月度频率明细</div>
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
            </div>
            <el-table :data="sortedMonthlyTrend" style="width:100%" size="small">
              <el-table-column label="月份" prop="month" width="100">
                <template #default="{ row }">
                  <span class="num font-medium">{{ row.month }}</span>
                </template>
              </el-table-column>
              <el-table-column align="center">
                <template #header>
                  <span class="cursor-pointer select-none" :class="sortHeaderClass('workday')" @click="toggleSort('workday')">工作日 <span v-html="sortIconHtml('workday')"></span></span>
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
                  <span class="num" :class="sortKey === 'total' ? 'font-semibold text-amber-600' : 'font-semibold text-gray-700'">{{ row.total }}</span>
                </template>
              </el-table-column>
              <el-table-column align="center" min-width="140">
                <template #header>
                  <span class="cursor-pointer select-none" :class="sortHeaderClass('freq')" @click="toggleSort('freq')">{{ customFreqLabel }} <span v-html="sortIconHtml('freq')"></span></span>
                </template>
                <template #default="{ row }">
                  <span class="num text-sm font-semibold text-purple-600">
                    {{ customFreq(row) === '-' ? '-' : `每${customFreq(row)}天` }}
                  </span>
                  <div class="text-[10px] text-gray-400">{{ freqFormula(row) }}</div>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <!-- 所有值班记录（日期可排序 + 性质可筛选） -->
          <div class="card">
            <div class="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
              <div class="section-title">所有值班记录</div>
              <div class="text-xs text-gray-500">
                共 <span class="num font-semibold text-gray-700">{{ filteredSortedDuties.length }}</span> 条
              </div>
            </div>
            <el-table :data="pagedDuties" style="width:100%" size="small" @filter-change="onFilterChange">
              <el-table-column label="日期" prop="date" width="120">
                <template #header>
                  <span class="cursor-pointer select-none flex items-center gap-1" @click="toggleDutiesSort">
                    日期
                    <span :style="`color:${dutiesSortOrder === 'asc' ? '#10b981' : '#3b82f6'};font-weight:bold`">
                      {{ dutiesSortOrder === 'asc' ? '↑' : '↓' }}
                    </span>
                  </span>
                </template>
                <template #default="{ row }">
                  <span class="num font-medium">{{ row.date }}</span>
                </template>
              </el-table-column>
              <el-table-column label="星期" width="80" align="center">
                <template #default="{ row }">
                  <span class="text-gray-500 text-xs">{{ weekdayLabel(row.date) }}</span>
                </template>
              </el-table-column>
              <el-table-column
                label="性质"
                prop="day_type"
                column-key="day_type"
                width="120"
                align="center"
                :filters="dayTypeFilters"
                :filter-method="(value, row) => row.day_type === value"
              >
                <template #default="{ row }">
                  <span class="day-badge" :class="dayTypeColor(row.day_type)">{{ dayTypeLabel(row.day_type) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="值班组" prop="group_name" width="140">
                <template #default="{ row }">
                  <span class="font-medium">{{ row.group_name || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="同班人员">
                <template #default="{ row }">
                  <span v-if="row.coworkers.length === 0" class="text-gray-400 text-xs">单独值班</span>
                  <span v-else class="text-gray-700">{{ row.coworkers.join('、') }}</span>
                </template>
              </el-table-column>
            </el-table>
            <div v-if="filteredSortedDuties.length > dutiesPageSize" class="px-5 py-3 flex justify-center">
              <el-pagination
                v-model:current-page="dutiesPage"
                :page-size="dutiesPageSize"
                :total="filteredSortedDuties.length"
                layout="prev, pager, next"
                small
                background
              />
            </div>
          </div>
        </template>

        <!-- 无数据 -->
        <div v-else class="card p-16 text-center">
          <el-icon size="40" class="text-gray-300 mb-3"><DataAnalysis /></el-icon>
          <div class="text-gray-500 mb-2">该区间暂无值班数据</div>
          <div class="text-xs text-gray-400">请切换其他时间段或选择其他人员</div>
        </div>
      </template>

      <!-- 未选择人员 -->
      <div v-else-if="!loading" class="card p-16 text-center">
        <el-icon size="40" class="text-gray-300 mb-3"><UserFilled /></el-icon>
        <div class="text-gray-500 mb-2">请从上方选择一位人员查看值班分析</div>
      </div>
    </div>
  </div>
</template>

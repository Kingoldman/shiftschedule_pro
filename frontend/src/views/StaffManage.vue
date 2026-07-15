<script setup>
import { ref, onMounted, computed, watch, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import draggable from 'vuedraggable'
import dayjs from 'dayjs'
import * as XLSX from 'xlsx'
import { useStaffStore } from '@/stores/staff'
import { groupApi, employeeApi } from '@/api/staff'
import { useAuthStore } from '@/stores/auth'
import { parseDateStr } from '@/utils/format'

const staffStore = useStaffStore()
const authStore = useAuthStore()

const { groups, employees } = storeToRefs(staffStore)
const selectedGroupId = ref(null) // null = 全部, -1 = 未分组/不值班
const keyword = ref('')
const loading = ref(false)

// 是否可编辑（登录后才能编辑）
const canEdit = computed(() => authStore.isLoggedIn)

// 过滤后的员工列表（按组顺序 + 组内排序）
const filteredEmployees = computed(() => {
  let list = employees.value
  if (selectedGroupId.value === -1) {
    list = list.filter((e) => !e.group_id || e.state === 0)
  } else if (selectedGroupId.value !== null) {
    list = list.filter((e) => e.group_id === selectedGroupId.value)
  }
  if (keyword.value) {
    list = list.filter((e) => e.name.includes(keyword.value))
  }
  // 按 group.order_id 排序，同组内按 employee.order_id 排序
  const groupOrderMap = new Map(groups.value.map(g => [g.id, g.order_id]))
  return [...list].sort((a, b) => {
    const ga = groupOrderMap.get(a.group_id) || 9999
    const gb = groupOrderMap.get(b.group_id) || 9999
    if (ga !== gb) return ga - gb
    return (a.order_id || 0) - (b.order_id || 0)
  })
})

// 未分组/不值班的人数
const unassignedCount = computed(() =>
  employees.value.filter((e) => !e.group_id || e.state === 0).length
)

async function loadData() {
  loading.value = true
  try {
    await staffStore.loadAll()
  } finally {
    loading.value = false
  }
}

// 写操作后强制刷新缓存
async function refreshData() {
  loading.value = true
  try {
    await staffStore.refresh()
  } finally {
    loading.value = false
  }
}

onMounted(loadData)

/* ===== 组管理 ===== */
const groupDialogVisible = ref(false)
const groupForm = ref({ id: null, name: '', order_id: 1 })
const groupDialogTitle = computed(() => (groupForm.value.id ? '编辑组' : '新建组'))

function openGroupDialog(group = null) {
  if (!canEdit.value) return
  if (group) {
    groupForm.value = { id: group.id, name: group.name, order_id: group.order_id }
  } else {
    // 新建组：序号自动分配为最大值+1（后端也会处理）
    const maxOrder = groups.value.reduce((mx, g) => Math.max(mx, g.order_id || 0), 0)
    groupForm.value = { id: null, name: '', order_id: maxOrder + 1 }
  }
  groupDialogVisible.value = true
}

async function saveGroup() {
  if (!groupForm.value.name.trim()) {
    ElMessage.warning('请输入组名')
    return
  }
  try {
    if (groupForm.value.id) {
      // 编辑组：先更新名称，再处理序号变更
      const oldOrder = groups.value.find(g => g.id === groupForm.value.id)?.order_id
      await groupApi.update(groupForm.value.id, { name: groupForm.value.name })
      // 如果序号变了，用插入逻辑重新排序
      const newOrder = groupForm.value.order_id
      if (oldOrder !== undefined && newOrder !== oldOrder) {
        const total = groups.value.length
        const clamped = Math.max(1, Math.min(newOrder, total))
        // 构建新数组：把当前组从旧位置移除，插入到新位置
        const arr = groups.value.filter(g => g.id !== groupForm.value.id)
        const target = groups.value.find(g => g.id === groupForm.value.id)
        if (target) {
          arr.splice(clamped - 1, 0, target)
          const items = arr.map((g, i) => ({ id: g.id, order_id: i + 1 }))
          arr.forEach((g, i) => (g.order_id = i + 1))
          await groupApi.batchSort(items)
        }
      }
      ElMessage.success('已更新')
    } else {
      // 新建组：先创建（后端自动分配到末尾），再用 batchSort 插入到目标位置
      const created = await groupApi.create({ name: groupForm.value.name, order_id: groupForm.value.order_id })
      const total = groups.value.length + 1 // 新建后总数+1
      const targetOrder = Math.max(1, Math.min(groupForm.value.order_id, total))
      // 如果目标位置不是末尾，需要重排
      if (targetOrder < total) {
        // 把新组插入到目标位置
        const arr = [...groups.value]
        arr.splice(targetOrder - 1, 0, created)
        const items = arr.map((g, i) => ({ id: g.id, order_id: i + 1 }))
        await groupApi.batchSort(items)
      }
      ElMessage.success('已创建')
    }
    groupDialogVisible.value = false
    await refreshData()
  } catch (e) {
    console.error('操作失败:', e)
    // 失败时同步后端真实状态（name 可能已改但 batchSort 失败，或反之）
    await refreshData()
  }
}

async function deleteGroup(group) {
  if (!canEdit.value) return
  const members = employees.value.filter(e => e.group_id === group.id)
  const memberNames = members.map(e => e.name).join('、') || '无'
  try {
    await ElMessageBox.confirm(
      `确认删除组「${group.name}」？\n\n组内 ${members.length} 名成员将移入「未分组/不值班」，不会被删除：\n${memberNames}`,
      '删除确认',
      { type: 'warning', customClass: 'whitespace-pre-line' }
    )
    await groupApi.remove(group.id)
    ElMessage.success(members.length > 0
      ? `已删除组「${group.name}」，${members.length} 名组员已移入未分组`
      : `已删除空组「${group.name}」`)
    if (selectedGroupId.value === group.id) selectedGroupId.value = null
    await refreshData()
  } catch (e) { console.error('操作失败:', e) }
}

// 拖拽组排序
async function onGroupDragEnd() {
  if (!canEdit.value) return
  const items = groups.value.map((g, i) => ({ id: g.id, order_id: i + 1 }))
  groups.value.forEach((g, i) => (g.order_id = i + 1))
  try {
    await groupApi.batchSort(items)
    ElMessage.success('排序已保存')
    // 强制刷新缓存，确保 localStorage 同步更新
    await refreshData()
  } catch (e) {
    await refreshData()
  }
}

/* ===== 员工管理 ===== */
const empDialogVisible = ref(false)
const empForm = ref({ id: null, name: '', group_id: null, state: 1, order_id: 1 })
const empDialogTitle = computed(() => (empForm.value.id ? '编辑员工' : '新增员工'))
// 防止表单初始化时 watch 误触发
let skipWatch = false

// 监听值班状态变化：关闭值班时自动清除分组
watch(() => empForm.value.state, (newState, oldState) => {
  if (skipWatch) return
  if (newState === 0 && oldState === 1 && empForm.value.group_id) {
    empForm.value.group_id = null
    ElMessage.info('关闭值班后自动移除所属组')
  }
})

// 切换组时重置组内序号到新组的末尾
watch(() => empForm.value.group_id, (newGid, oldGid) => {
  if (skipWatch) return
  if (newGid === oldGid) return
  if (!newGid) {
    empForm.value.order_id = 1
    return
  }
  // 编辑时若仍是原组，保留原序号
  if (empForm.value.id) {
    const orig = employees.value.find(e => e.id === empForm.value.id)
    if (orig && orig.group_id === newGid) return
  }
  const count = employees.value.filter(e => e.group_id === newGid && e.state === 1).length
  empForm.value.order_id = count + 1
})

// 组内序号上限：编辑时为组内现有人数，新建时为组内人数+1
const empMaxOrder = computed(() => {
  if (!empForm.value.group_id) return 1
  const count = employees.value.filter(e => e.group_id === empForm.value.group_id && e.state === 1).length
  return empForm.value.id ? count : count + 1
})

function openEmpDialog(emp = null) {
  if (!canEdit.value) return
  skipWatch = true
  if (emp) {
    empForm.value = { ...emp }
  } else {
    const targetGid = selectedGroupId.value && selectedGroupId.value > 0 ? selectedGroupId.value : null
    const count = targetGid
      ? employees.value.filter(e => e.group_id === targetGid && e.state === 1).length
      : 0
    empForm.value = {
      id: null,
      name: '',
      group_id: targetGid,
      state: 1,
      order_id: count + 1,
    }
  }
  empDialogVisible.value = true
  nextTick(() => { skipWatch = false })
}

async function saveEmp() {
  if (!empForm.value.name.trim()) {
    ElMessage.warning('请输入姓名')
    return
  }
  try {
    let groupId = empForm.value.group_id ?? null
    const state = empForm.value.state ?? 1
    if (state === 0 && groupId) {
      ElMessage.warning('不值班状态无法分配组，请先开启值班或移除所属组')
      return
    }

    // 序号夹紧到合法区间
    const newOrderId = groupId
      ? Math.max(1, Math.min(empForm.value.order_id, empMaxOrder.value))
      : 1

    if (empForm.value.id) {
      // 编辑：先更新基础字段（含 group_id、order_id）
      const oldEmp = employees.value.find(e => e.id === empForm.value.id)
      const oldGroupId = oldEmp?.group_id ?? null
      const oldOrderId = oldEmp?.order_id ?? 1

      await employeeApi.update(empForm.value.id, {
        name: empForm.value.name,
        group_id: groupId,
        state,
        order_id: newOrderId,
      })

      // 组或序号变化时重排相关组
      const groupChanged = groupId !== oldGroupId
      const orderChanged = groupId === oldGroupId && newOrderId !== oldOrderId
      if (groupChanged || orderChanged) {
        const sortItems = []
        // 旧组：移除该员工后重排为无空隙
        if (oldGroupId && groupChanged) {
          const remain = employees.value
            .filter(e => e.group_id === oldGroupId && e.id !== empForm.value.id)
            .sort((a, b) => (a.order_id || 0) - (b.order_id || 0))
          remain.forEach((e, i) => {
            if (e.order_id !== i + 1) {
              sortItems.push({ id: e.id, order_id: i + 1, group_id: oldGroupId })
            }
          })
        }
        // 新组：插入到目标位置后重排
        if (groupId) {
          const cur = employees.value
            .filter(e => e.group_id === groupId && e.id !== empForm.value.id)
            .sort((a, b) => (a.order_id || 0) - (b.order_id || 0))
          const insertAt = Math.max(0, Math.min(newOrderId - 1, cur.length))
          cur.splice(insertAt, 0, { id: empForm.value.id })
          cur.forEach((e, i) => {
            if (e.id === empForm.value.id) {
              sortItems.push({ id: empForm.value.id, order_id: i + 1, group_id: groupId })
            } else {
              const orig = employees.value.find(x => x.id === e.id)
              if (orig && orig.order_id !== i + 1) {
                sortItems.push({ id: e.id, order_id: i + 1, group_id: groupId })
              }
            }
          })
        }
        if (sortItems.length > 0) {
          await employeeApi.batchSort(sortItems)
        }
      }
      ElMessage.success('已更新')
    } else {
      // 新建：先以末位创建，再用 batchSort 调整到目标位置
      const targetEmps = groupId
        ? employees.value.filter(e => e.group_id === groupId && e.state === 1).sort((a, b) => (a.order_id || 0) - (b.order_id || 0))
        : []
      const created = await employeeApi.create({
        name: empForm.value.name,
        group_id: groupId,
        state,
        order_id: targetEmps.length + 1,
      })
      // 目标位置不在末位时重排
      if (groupId && newOrderId < targetEmps.length + 1) {
        const newOrdering = [...targetEmps]
        newOrdering.splice(Math.max(0, newOrderId - 1), 0, { id: created.id })
        const sortItems = newOrdering.map((e, i) => ({ id: e.id, order_id: i + 1, group_id: groupId }))
        await employeeApi.batchSort(sortItems)
      }
      ElMessage.success('已新增')
    }
    empDialogVisible.value = false
    await refreshData()
  } catch (e) {
    console.error('操作失败:', e)
    // 失败时同步后端真实状态，避免乐观更新导致 UI 与后端不一致
    await refreshData()
  }
}

// 重排指定组：删除/移出后保持序号连续无空隙
async function renumberGroup(groupId, excludeId = null) {
  if (!groupId) return
  const remain = employees.value
    .filter(e => e.group_id === groupId && e.id !== excludeId)
    .sort((a, b) => (a.order_id || 0) - (b.order_id || 0))
  const sortItems = []
  remain.forEach((e, i) => {
    if (e.order_id !== i + 1) {
      sortItems.push({ id: e.id, order_id: i + 1, group_id: groupId })
    }
  })
  if (sortItems.length > 0) {
    await employeeApi.batchSort(sortItems)
  }
}

async function deleteEmp(emp) {
  if (!canEdit.value) return
  try {
    await ElMessageBox.confirm(`确认删除员工「${emp.name}」？`, '删除确认', { type: 'warning' })
    const oldGroupId = emp.group_id
    await employeeApi.remove(emp.id)
    // 删除后重排原组，保持序号连续
    if (oldGroupId) await renumberGroup(oldGroupId, emp.id)
    ElMessage.success('已删除')
    await refreshData()
  } catch (e) { console.error('操作失败:', e) }
}

async function toggleState(emp) {
  if (!canEdit.value) return
  try {
    const newState = emp.state === 1 ? 0 : 1
    const updateData = { state: newState }
    const oldGroupId = emp.group_id
    // 设为不值班时，同时清除组（调入待分配）
    if (newState === 0 && emp.group_id) {
      updateData.group_id = null
    }
    await employeeApi.update(emp.id, updateData)
    // 移出组后重排原组
    if (newState === 0 && oldGroupId) await renumberGroup(oldGroupId, emp.id)
    ElMessage.success(newState === 1 ? '已设为值班' : '已设为不值班，移入待分配')
    await refreshData()
  } catch (e) {
    console.error('操作失败:', e)
    // 失败时同步后端真实状态，避免乐观更新改了 store 但后端未改成功
    await refreshData()
  }
}

function groupName(id) {
  const g = groups.value.find((x) => x.id === id)
  return g?.name || '未分组'
}

function groupOrderId(id) {
  const g = groups.value.find((x) => x.id === id)
  return g?.order_id || null
}

// 批量重命名所有组为组员姓名拼接
async function batchRenameGroups() {
  if (!canEdit.value) return
  try {
    await ElMessageBox.confirm(
      '将所有组名重命名为组内人员姓名拼接（如：张三李二），确认继续？',
      '批量重命名',
      { type: 'info' }
    )
    let count = 0
    for (const g of groups.value) {
      const emps = employees.value.filter(e => e.group_id === g.id && e.state === 1)
      const newName = emps.map(e => e.name).join('') || g.name
      if (newName !== g.name) {
        await groupApi.update(g.id, { name: newName, order_id: g.order_id })
        count++
      }
    }
    ElMessage.success(`已重命名 ${count} 个组`)
    await refreshData()
  } catch (e) { console.error('操作失败:', e) }
}

function exportStaffStatus() {
  if (!canEdit.value) {
    ElMessage.warning('请先登录后再导出')
    return
  }
  if (groups.value.length === 0 && employees.value.length === 0) {
    ElMessage.warning('暂无人员和组数据可导出')
    return
  }
  const title = '人员值班状态表'
  const headers = ['组序号', '组名', '姓名', '值班状态', '组内排序']

  // Sheet1: 人员配置（与排班快照格式一致）
  const empRows = []
  for (const g of groups.value) {
    const gEmps = employees.value.filter(e => e.group_id === g.id)
    for (const emp of gEmps) {
      empRows.push({
        '组序号': g.order_id,
        '组名': g.name,
        '姓名': emp.name,
        '值班状态': emp.state === 1 ? '值班' : '不值班',
        '组内排序': emp.order_id,
      })
    }
    if (gEmps.length === 0) {
      empRows.push({
        '组序号': g.order_id,
        '组名': g.name,
        '姓名': '（空组）',
        '值班状态': '-',
        '组内排序': '-',
      })
    }
  }
  // 如果没有任何行，添加一个空行占位以避免报错
  if (empRows.length === 0) {
    empRows.push({
      '组序号': '-',
      '组名': '-',
      '姓名': '暂无数据',
      '值班状态': '-',
      '组内排序': '-',
    })
  }
  const ws1 = XLSX.utils.json_to_sheet(empRows)
  XLSX.utils.sheet_add_aoa(ws1, [[title]], { origin: 'A1' })
  XLSX.utils.sheet_add_aoa(ws1, [headers], { origin: 'A2' })
  XLSX.utils.sheet_add_json(ws1, empRows, { origin: 'A3', skipHeader: true })
  ws1['!cols'] = [{ wch: 8 }, { wch: 12 }, { wch: 10 }, { wch: 10 }, { wch: 10 }]
  ws1['!merges'] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 4 } }]

  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws1, '人员配置')

  // Sheet2: 未分组/不值班人员
  const unassigned = employees.value.filter(e => !e.group_id || e.state === 0)
  if (unassigned.length > 0) {
    const unTitle = '未分组/不值班人员'
    const unHeaders = ['姓名', '所属组', '值班状态']
    const unRows = unassigned.map(emp => ({
      '姓名': emp.name,
      '所属组': emp.group_id ? groupName(emp.group_id) : '未分组',
      '值班状态': emp.state === 1 ? '值班' : '不值班',
    }))
    const ws2 = XLSX.utils.json_to_sheet(unRows)
    XLSX.utils.sheet_add_aoa(ws2, [[unTitle]], { origin: 'A1' })
    XLSX.utils.sheet_add_aoa(ws2, [unHeaders], { origin: 'A2' })
    XLSX.utils.sheet_add_json(ws2, unRows, { origin: 'A3', skipHeader: true })
    ws2['!cols'] = [{ wch: 10 }, { wch: 14 }, { wch: 10 }]
    ws2['!merges'] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 2 } }]
    XLSX.utils.book_append_sheet(wb, ws2, '未分组不值班')
  }

  const ts = dayjs().format('YYYYMMDDHHmmss')
  XLSX.writeFile(wb, `人员状态_${ts}.xlsx`)
  ElMessage.info('正在导出，请在下载对话框中确认保存')
}

// ===== 导入 Excel =====
const importDialogVisible = ref(false)
const importPreview = ref([])
const importLoading = ref(false)
const importErrors = ref([])
const importWarnings = ref([])
const importMode = ref('append') // 'append' | 'overwrite'
const duplicateNames = ref([]) // 重名检测

function openImportDialog() {
  importErrors.value = []
  importWarnings.value = []
  importPreview.value = []
  importMode.value = 'append'
  duplicateNames.value = []
  importDialogVisible.value = true
}

function downloadStaffTemplate() {
  const title = '人员导入模板'
  const exampleRows = [
    { '组序号': 1, '组名': '甲组', '姓名': '张三', '值班状态': '值班', '组内排序': 1 },
    { '组序号': 1, '组名': '甲组', '姓名': '李四', '值班状态': '值班', '组内排序': 2 },
    { '组序号': 2, '组名': '乙组', '姓名': '王五', '值班状态': '值班', '组内排序': 1 },
    { '组序号': 2, '组名': '乙组', '姓名': '赵六', '值班状态': '不值班', '组内排序': 2 },
  ]
  const ws = XLSX.utils.json_to_sheet(exampleRows)
  XLSX.utils.sheet_add_aoa(ws, [[title]], { origin: 'A1' })
  XLSX.utils.sheet_add_aoa(ws, [Object.keys(exampleRows[0])], { origin: 'A2' })
  XLSX.utils.sheet_add_json(ws, exampleRows, { origin: 'A3', skipHeader: true })
  ws['!cols'] = [{ wch: 8 }, { wch: 12 }, { wch: 10 }, { wch: 10 }, { wch: 10 }]
  ws['!merges'] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 4 } }]
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, '人员配置')
  XLSX.writeFile(wb, '人员导入模板.xlsx')
}

function handleImportFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (evt) => {
    try {
      const data = new Uint8Array(evt.target.result)
      const wb = XLSX.read(data, { type: 'array' })
      const ws = wb.Sheets[wb.SheetNames[0]]
      const rows = XLSX.utils.sheet_to_json(ws, { header: 1, raw: false })
      const dataRows = rows.slice(2).filter(r => r.length > 0 && r[2] && String(r[2]).trim() && String(r[2]) !== '（空组）')
      // 校验
      const errors = []
      const warnings = []
      if (dataRows.length === 0) {
        errors.push('表格中没有数据行')
      }
      const validStatuses = ['值班', '不值班']

      // 组序号/组名一致性检查
      const orderNameMap = new Map() // orderId -> groupName
      const nameOrderMap = new Map() // groupName -> orderId
      for (let i = 0; i < dataRows.length; i++) {
        const r = dataRows[i]
        const rowNum = i + 3
        const orderId = r[0] != null ? Number(r[0]) : null
        const gName = String(r[1] || '').trim()
        if (!gName) {
          errors.push(`第${rowNum}行B列：组名为空`)
          continue
        }
        if (orderId != null) {
          if (orderNameMap.has(orderId) && orderNameMap.get(orderId) !== gName) {
            errors.push(`第${rowNum}行B列：组序号${orderId}对应的组名不一致，已有"${orderNameMap.get(orderId)}"，当前为"${gName}"`)
          }
          orderNameMap.set(orderId, gName)
          if (nameOrderMap.has(gName) && nameOrderMap.get(gName) !== orderId) {
            errors.push(`第${rowNum}行A列：组名"${gName}"对应的组序号不一致，已有${nameOrderMap.get(gName)}，当前为${orderId}`)
          }
          nameOrderMap.set(gName, orderId)
        }
        const empName = String(r[2] || '').trim()
        if (!empName || empName === '（空组）') continue
        if (r[3] !== undefined && !validStatuses.includes(String(r[3]))) {
          errors.push(`第${rowNum}行D列：值班状态应为"值班"或"不值班"，当前为"${r[3]}"`)
        }
      }

      // 重名检测（导入数据内部 + 与现有数据）
      const importNames = new Map() // name -> count
      for (const r of dataRows) {
        const empName = String(r[2] || '').trim()
        if (!empName || empName === '（空组）') continue
        importNames.set(empName, (importNames.get(empName) || 0) + 1)
      }
      const internalDuplicates = [...importNames.entries()].filter(([, c]) => c > 1).map(([n]) => n)
      const existingNames = new Set(employees.value.map(e => e.name))
      const existingGroupNames = new Set(groups.value.map(g => g.name))
      const externalDuplicates = [...importNames.keys()].filter(n => existingNames.has(n))

      if (internalDuplicates.length > 0) {
        errors.push(`导入数据内部有重名：${internalDuplicates.join('、')}，请修改后重新导入`)
      }

      // 追加模式下，与现有人员/组重名均不允许导入（交给人工处理或改用覆盖模式）
      if (importMode.value === 'append') {
        if (externalDuplicates.length > 0) {
          errors.push(`以下人员名与现有人员重复，无法导入：${externalDuplicates.join('、')}（请修改后重试，或改用覆盖模式）`)
        }
        // 组名重名检测：与现有组重名
        const importGroupNames = new Set()
        for (const r of dataRows) {
          const gName = String(r[1] || '').trim()
          if (gName) importGroupNames.add(gName)
        }
        const externalGroupDuplicates = [...importGroupNames].filter(n => existingGroupNames.has(n))
        if (externalGroupDuplicates.length > 0) {
          errors.push(`以下组名与现有组重复，无法导入：${externalGroupDuplicates.join('、')}（请修改后重试，或改用覆盖模式）`)
        }
      }
      duplicateNames.value = []

      importErrors.value = errors
      importWarnings.value = warnings
      if (errors.length > 0) {
        importPreview.value = []
        return
      }

      // 按组聚合
      const groupMap = new Map()
      for (const r of dataRows) {
        const orderId = r[0] != null ? Number(r[0]) : null
        const gName = String(r[1] || '').trim() || '未命名组'
        const empName = String(r[2] || '').trim()
        if (!empName || empName === '（空组）') continue
        const state = r[3] === '不值班' ? 0 : 1
        if (!groupMap.has(gName)) groupMap.set(gName, { order_id: orderId, employees: [] })
        groupMap.get(gName).employees.push({ name: empName, state })
      }
      if (groupMap.size === 0) {
        importErrors.value = ['未解析到有效的人员数据']
        importPreview.value = []
      } else {
        importPreview.value = Array.from(groupMap.entries()).map(([name, data]) => ({ name, order_id: data.order_id, employees: data.employees }))
      }
    } catch (err) {
      ElMessage.error('文件解析失败，请检查是否为有效的 Excel 文件')
    }
  }
  reader.readAsArrayBuffer(file)
  e.target.value = ''
}

async function confirmImport() {
  if (!importPreview.value.length) return
  // 覆盖模式需二次确认
  if (importMode.value === 'overwrite') {
    try {
      await ElMessageBox.confirm(
        '覆盖模式将删除所有现有组和员工，替换为导入数据。此操作不可撤销，确认继续？',
        '覆盖警告',
        { type: 'warning', confirmButtonText: '确认覆盖', cancelButtonText: '取消' }
      )
    } catch { return }
  }
  importLoading.value = true
  try {
    // 构建导入数据：员工以对象形式携带 state，保留不值班员工
    const data = importPreview.value.map(g => ({
      name: g.name,
      employees: g.employees.map(e => ({ name: e.name, state: e.state }))
    }))
    let result
    if (importMode.value === 'overwrite') {
      result = await groupApi.importGroupsOverwrite(data)
    } else {
      result = await groupApi.importGroups(data)
    }
    ElMessage.success(result.msg)
    importDialogVisible.value = false
    importPreview.value = []
    await refreshData()
  } catch (e) { console.error('导入失败:', e) } finally {
    importLoading.value = false
  }
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto">
    <!-- 页头 -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <div class="text-xs text-blue-600 font-mono tracking-[0.3em] uppercase mb-1">/ Staff</div>
        <h1 class="font-display text-3xl font-semibold text-gray-800">人员管理</h1>
        <p class="text-sm text-gray-500 mt-1">管理值班组与员工，拖拽可调整排序</p>
      </div>
      <div v-if="canEdit" class="flex gap-2">
        <button class="btn-ghost" @click="exportStaffStatus">
          <el-icon><Download /></el-icon>导出
        </button>
        <button class="btn-ghost" @click="openImportDialog">
          <el-icon><Upload /></el-icon>导入
        </button>
        <button class="btn-ghost" @click="batchRenameGroups">
          <el-icon><EditPen /></el-icon>一键命名
        </button>
        <button class="btn-primary" @click="openGroupDialog()">
          <el-icon><Plus /></el-icon>新建组
        </button>
        <button class="btn-primary" @click="openEmpDialog()">
          <el-icon><Plus /></el-icon>新增员工
        </button>
      </div>
    </div>

    <!-- 组选择器：分层标签，含顺序号和编辑/删除 -->
    <div class="card p-4 mb-6">
      <div class="flex items-center gap-2 mb-2">
        <span class="text-xs text-gray-500 mr-1">筛选：</span>
        <button
          class="px-3 py-1 rounded-md text-sm transition-colors"
          :class="selectedGroupId === null ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'"
          @click="selectedGroupId = null"
        >
          全部 <span class="num text-xs ml-1">({{ employees.length }})</span>
        </button>
        <button
          class="px-3 py-1 rounded-md text-sm transition-colors"
          :class="selectedGroupId === -1 ? 'bg-red-500 text-white' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'"
          @click="selectedGroupId = -1"
        >
          未分组/不值班 <span class="num text-xs ml-1">({{ unassignedCount }})</span>
        </button>
      </div>
      <div v-if="groups.length > 0" class="flex items-center gap-2 flex-wrap">
        <span class="text-xs text-gray-400 mr-1">组：</span>
        <draggable
          v-model="groups"
          item-key="id"
          class="flex flex-wrap gap-2"
          :disabled="!canEdit"
          @end="onGroupDragEnd"
        >
          <template #item="{ element, index }">
            <div
              class="px-3 py-1 rounded-md text-sm transition-colors flex items-center gap-1.5 group relative"
              :class="selectedGroupId === element.id ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'"
              @click="selectedGroupId = element.id"
            >
              <!-- 顺序号 -->
              <span class="num text-[10px] opacity-50 font-semibold">{{ element.order_id }}</span>
              <!-- 拖拽手柄 -->
              <span v-if="canEdit" class="cursor-grab active:cursor-grabbing opacity-40 group-hover:opacity-70">⋮⋮</span>
              <!-- 组名 + 人数 -->
              <span>{{ element.name }}</span>
              <span class="num text-xs opacity-70">({{ element.employee_count }})</span>
              <!-- 编辑/删除按钮（hover 时显示） -->
              <template v-if="canEdit">
                <span
                  class="ml-0.5 opacity-0 group-hover:opacity-70 hover:!opacity-100 cursor-pointer"
                  @click.stop="openGroupDialog(element)"
                >✎</span>
                <span
                  class="opacity-0 group-hover:opacity-70 hover:!opacity-100 cursor-pointer text-red-400"
                  @click.stop="deleteGroup(element)"
                >×</span>
              </template>
            </div>
          </template>
        </draggable>
      </div>
    </div>

    <!-- 员工列表 -->
    <div class="card">
      <div class="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
        <div class="section-title">员工列表</div>
        <el-input
          v-model="keyword"
          placeholder="搜索姓名"
          size="small"
          class="w-48"
          clearable
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </div>

      <el-table
        :data="filteredEmployees"
        v-loading="loading"
        style="width: 100%"
        row-key="id"
        max-height="520"
        :border="false"
      >
        <el-table-column label="姓名" prop="name" min-width="100">
          <template #default="{ row }">
            <span class="font-medium">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="组序号" min-width="80" align="center">
          <template #default="{ row }">
            <span v-if="groupOrderId(row.group_id)" class="num text-sm">{{ groupOrderId(row.group_id) }}</span>
            <span v-else class="text-gray-300">-</span>
          </template>
        </el-table-column>
        <el-table-column label="所属组" min-width="140">
          <template #default="{ row }">
            <span class="text-sm">{{ groupName(row.group_id) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="组内序号" min-width="90" align="center">
          <template #default="{ row }">
            <span v-if="row.group_id && row.state === 1" class="num text-sm">{{ row.order_id }}</span>
            <span v-else class="text-gray-300">-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="100">
          <template #default="{ row }">
            <button
              v-if="canEdit"
              class="px-2 py-0.5 rounded text-xs font-medium transition-colors"
              :class="row.state === 1
                ? 'bg-green-100 text-green-700 hover:bg-green-200'
                : 'bg-gray-100 text-gray-500 hover:bg-gray-200'"
              @click="toggleState(row)"
            >
              {{ row.state === 1 ? '值班' : '不值班' }}
            </button>
            <span
              v-else
              class="px-2 py-0.5 rounded text-xs font-medium"
              :class="row.state === 1 ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'"
            >
              {{ row.state === 1 ? '值班' : '不值班' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column v-if="canEdit" label="操作" min-width="140" align="right">
          <template #default="{ row }">
            <el-button text size="small" @click="openEmpDialog(row)">
              <el-icon><Edit /></el-icon>编辑
            </el-button>
            <el-button text size="small" type="danger" @click="deleteEmp(row)">
              <el-icon><Delete /></el-icon>删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="!loading && filteredEmployees.length === 0" class="py-16 text-center text-gray-400 text-sm">
        <el-icon size="32" class="mb-2"><UserFilled /></el-icon>
        <div>暂无员工，点击右上角「新增员工」开始</div>
      </div>
    </div>

    <!-- 组编辑弹窗 -->
    <el-dialog v-model="groupDialogVisible" :title="groupDialogTitle" width="400px">
      <el-form label-width="80px">
        <el-form-item label="组名">
          <el-input v-model="groupForm.name" placeholder="如：第一组" />
        </el-form-item>
        <el-form-item label="排序号">
          <el-input-number
            v-model="groupForm.order_id"
            :min="1"
            :max="groupForm.id ? groups.length : groups.length + 1"
            controls-position="right"
            style="width: 100%"
          />
          <div class="text-xs text-gray-400 mt-1">修改序号将按插入方式调整，其他组序号依次递补</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <button class="btn-ghost" @click="groupDialogVisible = false">取消</button>
        <button class="btn-primary ml-2" @click="saveGroup">保存</button>
      </template>
    </el-dialog>

    <!-- 员工编辑弹窗 -->
    <el-dialog v-model="empDialogVisible" :title="empDialogTitle" width="440px">
      <el-form label-width="80px">
        <el-form-item label="姓名" required>
          <el-input v-model="empForm.name" placeholder="请输入姓名" />
        </el-form-item>
        <el-form-item label="所属组">
          <el-select v-model="empForm.group_id" placeholder="未分组" clearable class="w-full">
            <el-option v-for="g in groups" :key="g.id" :label="`${g.order_id}. ${g.name}`" :value="g.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="empForm.group_id && empForm.state === 1" label="组内序号">
          <el-input-number
            v-model="empForm.order_id"
            :min="1"
            :max="empMaxOrder"
            controls-position="right"
            style="width: 100%"
          />
          <div class="text-xs text-gray-400 mt-1">修改序号将按插入方式调整，组内其他成员序号依次递补</div>
        </el-form-item>
        <el-form-item label="参与值班">
          <el-switch v-model="empForm.state" :active-value="1" :inactive-value="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <button class="btn-ghost" @click="empDialogVisible = false">取消</button>
        <button class="btn-primary ml-2" @click="saveEmp">保存</button>
      </template>
    </el-dialog>

    <!-- 导入预览弹窗 -->
    <el-dialog v-model="importDialogVisible" title="导入人员与组" width="560px">
      <div class="flex items-center gap-4 mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <div class="flex-1">
          <div class="text-sm font-medium text-gray-800 mb-1">第一步：下载模板</div>
          <div class="text-xs text-gray-500">按模板格式填写组和人员信息，同一组序号的组名必须一致</div>
        </div>
        <button class="btn-primary" @click="downloadStaffTemplate">
          <el-icon><Download /></el-icon>下载模板
        </button>
      </div>
      <div class="flex items-center gap-4 mb-4 p-4 bg-gray-50 border border-gray-200 rounded-lg">
        <div class="flex-1">
          <div class="text-sm font-medium text-gray-800 mb-1">第二步：选择文件</div>
          <div class="text-xs text-gray-500">追加模式下，与现有组/人员重名将无法导入，请修改后重试或改用覆盖模式</div>
        </div>
        <label class="btn-ghost cursor-pointer">
          <el-icon><Upload /></el-icon>选择文件
          <input type="file" accept=".xlsx,.xls" class="hidden" @change="handleImportFile" />
        </label>
      </div>
      <!-- 导入模式选择 -->
      <div class="mb-4 p-3 border border-gray-200 rounded-md">
        <div class="text-xs font-medium text-gray-600 mb-2">导入模式</div>
        <div class="flex gap-3">
          <label class="flex items-center gap-1.5 text-xs cursor-pointer">
            <input type="radio" v-model="importMode" value="append" />
            <span>尾部新增</span>
            <span class="text-gray-400">— 忽略组序号，追加到现有数据末尾</span>
          </label>
          <label class="flex items-center gap-1.5 text-xs cursor-pointer">
            <input type="radio" v-model="importMode" value="overwrite" />
            <span>覆盖</span>
            <span class="text-red-400">— 清空现有数据后导入</span>
          </label>
        </div>
      </div>
      <!-- 校验错误 -->
      <div v-if="importErrors.length > 0" class="mb-3 p-3 bg-red-50 border border-red-200 rounded-md">
        <div class="text-sm font-medium text-red-600 mb-1">数据校验失败</div>
        <div v-for="(err, i) in importErrors" :key="i" class="text-xs text-red-500">{{ err }}</div>
      </div>
      <!-- 警告 -->
      <div v-if="importWarnings.length > 0" class="mb-3 p-3 bg-amber-50 border border-amber-200 rounded-md">
        <div class="text-sm font-medium text-amber-600 mb-1">注意</div>
        <div v-for="(w, i) in importWarnings" :key="i" class="text-xs text-amber-600">{{ w }}</div>
      </div>
      <!-- 预览 -->
      <div v-if="importPreview.length > 0">
        <div class="text-xs font-medium text-gray-600 mb-2">预览（共 {{ importPreview.reduce((s,g) => s + g.employees.length, 0) }} 人）</div>
        <div v-for="g in importPreview" :key="g.name" class="mb-2 p-3 bg-gray-50 rounded-md">
          <div class="flex items-center gap-2 mb-1">
            <span class="font-medium text-gray-800">{{ g.name }}</span>
            <span class="text-xs text-gray-400">{{ g.employees.length }} 人</span>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="emp in g.employees"
              :key="emp.name"
              class="px-2 py-0.5 rounded text-xs"
              :class="emp.state === 1 ? 'bg-green-100 text-green-700' : 'bg-gray-200 text-gray-500'"
            >
              {{ emp.name }}
            </span>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn-ghost" @click="importDialogVisible = false; importErrors = []; importWarnings = []">关闭</button>
        <button v-if="importPreview.length > 0" class="btn-primary ml-2" :disabled="importLoading" @click="confirmImport">
          {{ importLoading ? '导入中...' : importMode === 'overwrite' ? '确认覆盖导入' : '确认新增导入' }}
        </button>
      </template>
    </el-dialog>
  </div>
</template>

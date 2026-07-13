import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { groupApi, employeeApi } from '@/api/staff'

// 人员管理缓存：组列表和员工列表变化不频繁，缓存后避免频繁请求
const CACHE_KEY = 'staff_cache'
const CACHE_TTL = 5 * 60 * 1000 // 5 分钟有效期

function loadCache() {
  try {
    const raw = JSON.parse(localStorage.getItem(CACHE_KEY) || '{}')
    if (raw.expiredAt && Date.now() < raw.expiredAt) {
      return raw
    }
  } catch { /* ignore */ }
  return null
}

function saveCache(groups, employees) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({
      groups, employees, expiredAt: Date.now() + CACHE_TTL,
    }))
  } catch { /* localStorage 满了就算了 */ }
}

export const useStaffStore = defineStore('staff', () => {
  const cached = loadCache()
  const groups = ref(cached?.groups || [])
  const employees = ref(cached?.employees || [])
  const loaded = ref(!!cached)

  async function loadAll(force = false) {
    // 检查缓存是否仍有效（TTL 内），有效则跳过
    if (!force && loaded.value) {
      const c = loadCache()
      if (c) return  // 缓存未过期，直接使用
    }
    const [g, e] = await Promise.all([groupApi.list(), employeeApi.list()])
    groups.value = g
    employees.value = e
    loaded.value = true
    saveCache(g, e)
  }

  // 组或员工变更后调用，强制刷新缓存
  async function refresh() {
    await loadAll(true)
  }

  // 组成员映射：{ groupId: [name1, name2, ...] }
  const groupMembersMap = computed(() => {
    const map = {}
    for (const g of groups.value) {
      map[g.id] = employees.value
        .filter(e => e.group_id === g.id && e.state === 1)
        .sort((a, b) => a.order_id - b.order_id)
        .map(e => e.name)
    }
    return map
  })

  return { groups, employees, loaded, loadAll, refresh, groupMembersMap }
})

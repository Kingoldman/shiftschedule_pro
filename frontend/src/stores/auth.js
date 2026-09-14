import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'

// 认证状态
//
// 【令牌存储说明】
// JWT 改由后端通过 httpOnly Cookie 下发，浏览器自动携带，JS 读不到。
// 此前把 token 明文存进 localStorage，一旦发生 XSS（或装了恶意插件）
// 就能被直接窃取并以管理员身份操作。这里只保留用于展示的账号信息（非凭据）。
const USER_KEY = 'shift_user'

function loadUser() {
  // 必须容错：存储被改坏或跨版本结构不兼容时 JSON.parse 会抛错，
  // 而 MainLayout 始终挂载，store 初始化失败会导致整站白屏
  try {
    const parsed = JSON.parse(localStorage.getItem(USER_KEY) || 'null')
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    localStorage.removeItem(USER_KEY)
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref(loadUser())

  // 是否已登录：以本地缓存的账号信息为准。
  // 真正的鉴权在后端——Cookie 失效时接口返回 401，由 http 拦截器统一处理。
  const isLoggedIn = computed(() => !!user.value)

  // 角色：'admin' | 'employee'。未登录时按 admin 渲染，
  // 因为守卫会立刻弹出登录框，实际不会看到这个中间态。
  const role = computed(() => user.value?.role || 'admin')
  const isAdmin = computed(() => role.value === 'admin')
  const isEmployee = computed(() => role.value === 'employee')
  // 员工账号绑定的员工 id，用于拉取自己的值班数据；管理员为 null
  const employeeId = computed(() => user.value?.employee_id ?? null)

  // 登录弹窗的可见状态（供 MainLayout 绑定和 http 拦截器触发）
  const loginDialogVisible = ref(false)

  async function login(username, password) {
    await authApi.login(username, password)
    const me = await authApi.getMe()
    user.value = me
    localStorage.setItem(USER_KEY, JSON.stringify(me))
    return me
  }

  async function logout() {
    // 通知后端清除 httpOnly Cookie；即使失败也要清理前端状态
    try {
      await authApi.logout()
    } catch { /* 忽略：Cookie 可能已过期 */ }
    user.value = null
    localStorage.removeItem(USER_KEY)
  }

  async function changePassword(oldPassword, newPassword) {
    await authApi.changePassword(oldPassword, newPassword)
  }

  return {
    user, isLoggedIn, role, isAdmin, isEmployee, employeeId,
    loginDialogVisible, login, logout, changePassword,
  }
})

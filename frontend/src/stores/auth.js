import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'

// 认证状态：管理 token 和当前管理员信息
export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('shift_token') || '')
  const admin = ref(JSON.parse(localStorage.getItem('shift_admin') || 'null'))

  const isLoggedIn = computed(() => !!token.value && !!admin.value)

  // 登录弹窗的可见状态（供 MainLayout 绑定和 http 拦截器触发）
  const loginDialogVisible = ref(false)

  async function login(username, password) {
    const data = await authApi.login(username, password)
    token.value = data.access_token
    localStorage.setItem('shift_token', data.access_token)

    const me = await authApi.getMe()
    admin.value = me
    localStorage.setItem('shift_admin', JSON.stringify(me))
  }

  function logout() {
    token.value = ''
    admin.value = null
    localStorage.removeItem('shift_token')
    localStorage.removeItem('shift_admin')
  }

  async function changePassword(oldPassword, newPassword) {
    await authApi.changePassword(oldPassword, newPassword)
  }

  return { token, admin, isLoggedIn, loginDialogVisible, login, logout, changePassword }
})

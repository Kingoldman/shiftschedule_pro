import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

// Axios 实例：统一 baseURL、超时、token 注入、错误处理
const http = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

// 请求拦截：自动附加 JWT（如果有）
http.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

// 401 处理去重标志：多个并发请求同时返回 401 时，只处理一次
let isHandling401 = false

// 响应拦截：统一错误提示
http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status
    const url = error.config?.url || ''

    if (status === 401) {
      // 登录接口的 401 表示账号密码错误，由调用方自行提示
      if (url.includes('/auth/login')) {
        // 不在此提示
      } else if (!isHandling401) {
        // 多个并发请求同时 401 时，只处理第一个，避免重复弹窗和重复 logout
        isHandling401 = true
        const auth = useAuthStore()
        if (!auth.isLoggedIn) {
          auth.loginDialogVisible = true
          ElMessage.warning('此操作需要登录')
        } else {
          ElMessage.warning('登录已过期，请重新登录')
          auth.logout()
          auth.loginDialogVisible = true
        }
        // 2 秒后重置标志，允许后续 401 再次触发登录提示
        setTimeout(() => { isHandling401 = false }, 2000)
      }
    } else {
      // 网络错误等非 HTTP 响应情况提供更友好的提示
      let detail = error.response?.data?.detail
      if (!detail) {
        if (error.code === 'ECONNABORTED') detail = '请求超时，请稍后重试'
        else if (!error.response) detail = '网络连接异常，请检查网络'
        else detail = error.message || '请求失败'
      }
      ElMessage.error(detail)
    }
    return Promise.reject(error)
  }
)

export default http

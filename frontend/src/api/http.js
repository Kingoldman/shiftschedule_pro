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

// 响应拦截：统一错误提示
http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail || error.message || '请求失败'
    const url = error.config?.url || ''

    if (status === 401) {
      // 登录接口的 401 表示账号密码错误，由调用方自行提示
      if (url.includes('/auth/login')) {
        // 不在此提示
      } else {
        // 未登录或 token 过期：打开登录弹窗
        const auth = useAuthStore()
        if (!auth.isLoggedIn) {
          auth.loginDialogVisible = true
          ElMessage.warning('此操作需要登录')
        } else {
          ElMessage.warning('登录已过期，请重新登录')
          auth.logout()
          auth.loginDialogVisible = true
        }
      }
    } else {
      ElMessage.error(detail)
    }
    return Promise.reject(error)
  }
)

export default http

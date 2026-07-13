import http from './http'

// 认证相关 API
export const authApi = {
  login: (username, password) => http.post('/auth/login', { username, password }),
  getMe: () => http.get('/auth/me'),
  changePassword: (oldPassword, newPassword) =>
    http.post('/auth/change-password', { old_password: oldPassword, new_password: newPassword }),
}

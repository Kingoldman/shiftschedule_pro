import http from './http'

// 排班 API
export const scheduleApi = {
  get: (year, month) => http.get(`/schedule/${year}/${month}`),
  generate: (data) => http.post('/schedule/generate', data),
  save: (data) => http.post('/schedule/save', data),
  lock: (year, month) => http.post(`/schedule/${year}/${month}/lock`),
  unlock: (year, month) => http.post(`/schedule/${year}/${month}/unlock`),
  delete: (year, month) => http.delete(`/schedule/${year}/${month}`),
  autoPreview: (year, month) => http.get(`/schedule/auto-preview/${year}/${month}`),
}

// 统计 API
export const statsApi = {
  // 按月统计
  monthly: (year, month) => http.get(`/stats/monthly/${year}/${month}`),
  // 按年统计
  yearly: (year) => http.get(`/stats/yearly/${year}`),
  // 累计统计
  cumulative: () => http.get('/stats/cumulative'),
  // 自定义区间统计
  custom: (startDate, endDate) => http.get('/stats/custom', { params: { start_date: startDate, end_date: endDate } }),
  // 单人员值班分析（按月/按年/累计）
  employee: (employeeId, mode = 'cumulative', year = null, month = null) => {
    const params = { mode }
    if (year) params.year = year
    if (month) params.month = month
    return http.get(`/stats/employee/${employeeId}`, { params })
  },
  // 获取所有曾参与值班的人员（包括已删除的）
  employeesWithHistory: () => http.get('/stats/employees-with-history'),
}

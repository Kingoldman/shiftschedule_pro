import http from './http'

// 值班组 API
export const groupApi = {
  list: () => http.get('/groups'),
  create: (data) => http.post('/groups', data),
  update: (id, data) => http.put(`/groups/${id}`, data),
  remove: (id) => http.delete(`/groups/${id}`),
  batchSort: (items) => http.put('/groups/batch/sort', { items }),
  importGroups: (data) => http.post('/groups/import', data),
  importGroupsOverwrite: (data) => http.post('/groups/import-overwrite', data),
}

// 员工 API
export const employeeApi = {
  list: (params) => http.get('/employees', { params }),
  create: (data) => http.post('/employees', data),
  update: (id, data) => http.put(`/employees/${id}`, data),
  remove: (id) => http.delete(`/employees/${id}`),
  batchSort: (items) => http.put('/employees/batch/sort', { items }),
}

// 员工自助账号 API（管理员操作）
export const accountApi = {
  // 批量查询所有员工账号状态（避免列表页 N+1 请求）
  list: () => http.get('/employees/accounts'),
  get: (empId) => http.get(`/employees/${empId}/account`),
  upsert: (empId, data) => http.put(`/employees/${empId}/account`, data),
  remove: (empId) => http.delete(`/employees/${empId}/account`),
  // action: issue | rotate | revoke
  feedToken: (empId, action) =>
    http.post(`/employees/${empId}/account/feed-token`, { action }),
}

// 员工自助 API（仅返回本人数据）
export const meApi = {
  months: () => http.get('/me/months'),
  schedule: (year, month) => http.get(`/me/schedule/${year}/${month}`),
  // 日历订阅
  feedUrl: () => http.get('/me/feed-url'),
  rotateFeed: () => http.post('/me/feed-url/rotate'),
  revokeFeed: () => http.post('/me/feed-url/revoke'),
}

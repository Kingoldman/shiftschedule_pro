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

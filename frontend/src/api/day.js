import http from './http'

export const dayApi = {
  listByMonth: (year, month) => http.get('/days', { params: { year, month } }),
  batchUpdate: (items) => http.put('/days/batch', { items }),
  listModified: () => http.get('/days/modified'),
}

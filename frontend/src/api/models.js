import http from './http'

export default {
  list: (pid) => http.get(`/projects/${pid}/models`).then(r => r.data),
  get: (id) => http.get(`/models/${id}`).then(r => r.data),
  importModel: (data) => http.post('/models/import', data).then(r => r.data),
  markBest: (id) => http.post(`/models/${id}/best`).then(r => r.data),
  remove: (id) => http.delete(`/models/${id}`),
  result: (modelId) => http.get(`/models/${modelId}/result`).then(r => r.data),
  exportModel: (id) => http.post(`/models/${id}/export`, {}, { timeout: 300000 }).then(r => r.data),
  predict: (id, data) => http.post(`/models/${id}/predict`, data, { timeout: 120000 }).then(r => r.data),
  predictDetails: (id) => http.post(`/models/${id}/predict-details`, {}, { timeout: 300000 }).then(r => r.data),
}

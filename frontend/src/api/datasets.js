import http from './http'

export default {
  list: (pid) => http.get('/datasets', { params: { project_id: pid } }).then(r => r.data),
  get: (id) => http.get(`/datasets/${id}`).then(r => r.data),
  create: (data) => http.post('/datasets', data).then(r => r.data),
  remove: (id) => http.delete(`/datasets/${id}`),
  images: (id, params) => http.get(`/datasets/${id}/images`, { params }).then(r => r.data),
  split: (id, data) => http.post(`/datasets/${id}/split`, data).then(r => r.data),
  augment: (id, data) => http.post(`/datasets/${id}/augment`, data, { timeout: 600000 }).then(r => r.data),
}

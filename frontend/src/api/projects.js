import http from './http'

export default {
  list: () => http.get('/projects').then(r => r.data),
  get: (id) => http.get(`/projects/${id}`).then(r => r.data),
  create: (data) => http.post('/projects', data).then(r => r.data),
  update: (id, data) => http.patch(`/projects/${id}`, data).then(r => r.data),
  remove: (id) => http.delete(`/projects/${id}`),
  addCategory: (pid, data) => http.post(`/projects/${pid}/categories`, data).then(r => r.data),
  // 类别按数据集隔离：数据集维度 CRUD
  datasetCategories: (dsid) => http.get(`/datasets/${dsid}/categories`).then(r => r.data),
  addDatasetCategory: (dsid, data) => http.post(`/datasets/${dsid}/categories`, data).then(r => r.data),
  removeCategory: (cid) => http.delete(`/projects/categories/${cid}`),
  updateCategory: (cid, data) => http.patch(`/projects/categories/${cid}`, data).then(r => r.data),
}

import http from './http'

export default {
  list: (imageId) => http.get(`/images/${imageId}/annotations`).then(r => r.data),
  create: (data) => http.post('/annotations', data).then(r => r.data),
  update: (id, data) => http.put(`/annotations/${id}`, data).then(r => r.data),
  remove: (id) => http.delete(`/annotations/${id}`),
  importAnnotations: (datasetId, data) => http.post(`/datasets/${datasetId}/import-annotations`, data).then(r => r.data),
  brush: (data) => http.post('/annotations/brush', data).then(r => r.data),
  paint: (id, data) => http.post(`/annotations/${id}/paint`, data).then(r => r.data),
}

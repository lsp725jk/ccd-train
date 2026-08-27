import http from './http'

export default {
  scenes: () => http.get('/scenes').then(r => r.data),
  safeAug: () => http.get('/scenes/safe_aug').then(r => r.data),
  plan: (data) => http.post('/scenes/plan', data).then(r => r.data),
  saveCustom: (data) => http.post('/scenes/custom', data).then(r => r.data),
  removeCustom: (name) => http.delete('/scenes/custom', { params: { name } }),
}

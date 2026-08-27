import http from './http'

export default {
  create: (data) => http.post('/train', data).then(r => r.data),
  list: (pid) => http.get(`/projects/${pid}/tasks`).then(r => r.data),
  get: (id) => http.get(`/tasks/${id}`).then(r => r.data),
  log: (id, offset) => http.get(`/tasks/${id}/log`, { params: { offset }, silent: true }).then(r => r.data),
  stop: (id) => http.post(`/tasks/${id}/stop`).then(r => r.data),
  curve: (id) => http.get(`/tasks/${id}/curve`, { silent: true }).then(r => r.data),
  engines: () => http.get('/engines').then(r => r.data),
}

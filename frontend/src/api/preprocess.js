import http from './http'

export default {
  ops: {
    preprocess: () => http.get('/ops/preprocess').then(r => r.data),
    augment: () => http.get('/ops/augment').then(r => r.data),
  },
  preview: {
    preprocess: (data) => http.post('/preview/preprocess', data, { silent: true }).then(r => r.data),
    augment: (data) => http.post('/preview/augment', data, { silent: true }).then(r => r.data),
    resize: (data) => http.post('/preview/resize', data, { silent: true }).then(r => r.data),
  },
  pipelines: {
    list: (pid, type = '') => http.get(`/projects/${pid}/pipelines`, { params: { type } }).then(r => r.data),
    create: (data) => http.post('/pipelines', data).then(r => r.data),
    remove: (id) => http.delete(`/pipelines/${id}`),
  },
}

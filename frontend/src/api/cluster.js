import http from './http'

export default {
  run: (data) => http.post('/cluster/run', data).then(r => r.data),
  apply: (data) => http.post('/cluster/apply', data).then(r => r.data),
}

import http from './http'

export default {
  get: () => http.get('/dashboard').then(r => r.data),
}

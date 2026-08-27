import http from './http'

export default {
  predict: (data) => http.post('/sam/predict', data).then(r => r.data),
}

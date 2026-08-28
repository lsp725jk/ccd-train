import http from './http'

/** 评审框选：保存/读取用户在页面上框选的位置与留言 */
export default {
  list: () => http.get('/review').then(r => r.data),
  create: (data) => http.post('/review', data).then(r => r.data),
  remove: (id) => http.delete(`/review/${id}`),
}

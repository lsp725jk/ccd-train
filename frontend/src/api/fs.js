import http from './http'

/** 服务器文件系统浏览（目录选择用）。 */
export default {
  drives: () => http.get('/fs/drives').then(r => r.data),
  list: (path) => http.get('/fs/list', { params: { path } }).then(r => r.data),
}

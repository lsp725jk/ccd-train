import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({ baseURL: '/api', timeout: 60000 })

http.interceptors.response.use(
  r => r,
  err => {
    if (!err.config?.silent) {
      let detail = err.response?.data?.detail
      if (Array.isArray(detail)) detail = detail.map(d => d.msg || JSON.stringify(d)).join('; ')
      const msg = detail || err.message || '请求失败'
      ElMessage.error(String(msg).slice(0, 200))
    }
    return Promise.reject(err)
  },
)

export default http

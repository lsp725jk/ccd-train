import axios from 'axios'
import { createDiscreteApi } from 'naive-ui'

// 用 Naive UI 的离散 API（无需组件上下文），替代 element-plus 的 ElMessage
const { message } = createDiscreteApi(['message'])

const http = axios.create({ baseURL: '/api', timeout: 60000 })

http.interceptors.response.use(
  r => r,
  err => {
    if (!err.config?.silent) {
      let detail = err.response?.data?.detail
      if (Array.isArray(detail)) detail = detail.map(d => d.msg || JSON.stringify(d)).join('; ')
      const msg = detail || err.message || '请求失败'
      message.error(String(msg).slice(0, 200))
    }
    return Promise.reject(err)
  },
)

export default http

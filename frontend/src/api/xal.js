import http from './http'

/** X-AnyLabeling 几何复用接口（prefix 由 http baseURL='/api' 统一，不再重复拼 /api）。 */
export default {
  ellipse: (data) => http.post('/xal/ellipse', data).then(r => r.data),
  circle: (data) => http.post('/xal/circle', data).then(r => r.data),
  maskBbox: (data) => http.post('/xal/mask/bbox', data).then(r => r.data),
  shapeMask: (data) => http.post('/xal/shape/mask', data).then(r => r.data),
}

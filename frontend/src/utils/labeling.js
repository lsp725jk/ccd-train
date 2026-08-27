/** 标注画布纯函数工具：几何判断、颜色转换、画布标签绘制。 */

/** hex 颜色 → rgba() 字符串 */
export function hexToRGBA(hex, alpha) {
  const h = (hex || '#4E79A7').replace('#', '')
  const r = parseInt(h.substring(0, 2), 16)
  const g = parseInt(h.substring(2, 4), 16)
  const b = parseInt(h.substring(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
}

/** 点在多边形内（射线法） */
export function pointInPolygon(x, y, pts) {
  let inside = false
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const xi = pts[i][0], yi = pts[i][1]
    const xj = pts[j][0], yj = pts[j][1]
    const intersect = ((yi > y) !== (yj > y)) &&
      (x < (xj - xi) * (y - yi) / (yj - yi) + xi)
    if (intersect) inside = !inside
  }
  return inside
}

/** 在 canvas 上绘制标注标签（色块 + 白字） */
export function drawLabel(ctx, text, x, y, color, scale) {
  if (!text) return
  ctx.save()
  ctx.font = `${Math.max(10, 11 * scale)}px sans-serif`
  const m = ctx.measureText(text)
  const padX = 4, padY = 2
  ctx.fillStyle = color
  ctx.fillRect(x, y, m.width + padX * 2, 14 * scale + padY * 2)
  ctx.fillStyle = '#fff'
  ctx.fillText(text, x + padX, y + 12 * scale)
  ctx.restore()
}

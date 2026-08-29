// RLE 位图掩码编解码（与后端 app/engines/rle.py 对称，Label Studio / COCO 兼容格式）。
// 位图约定：行优先 Uint8Array（0/1），索引 = y * w + x；RLE counts 按 Fortran（列优先）展平。

/** 掩码位图（行优先 Uint8Array）→ RLE 字典 {size:[h,w], counts} */
export function maskToRle(data, h, w) {
  const counts = []
  let prev = 0, run = 0
  // Fortran 展平：按列遍历
  for (let j = 0; j < w; j++) {
    for (let i = 0; i < h; i++) {
      const v = data[i * w + j]
      if (v === prev) run++
      else { counts.push(run); prev = v; run = 1 }
    }
  }
  counts.push(run)
  return { size: [h, w], counts: counts.join(',') }
}

/** RLE 字典 → {data: 行优先 Uint8Array(0/1), h, w, bbox: [x1,y1,x2,y2] | null} */
export function rleToMask(rle) {
  const [h, w] = rle.size
  const counts = String(rle.counts).split(',').map(Number)
  // 列优先游程展开
  const col = new Uint8Array(h * w)
  let pos = 0, val = 0
  for (const c of counts) {
    col.fill(val, pos, pos + c)
    pos += c
    val ^= 1
  }
  // 列优先 → 行优先，同时算 bbox
  const data = new Uint8Array(h * w)
  let x1 = w, y1 = h, x2 = -1, y2 = -1
  for (let j = 0; j < w; j++) {
    const baseC = j * h
    for (let i = 0; i < h; i++) {
      if (col[baseC + i]) {
        data[i * w + j] = 1
        if (j < x1) x1 = j
        if (j > x2) x2 = j
        if (i < y1) y1 = i
        if (i > y2) y2 = i
      }
    }
  }
  return { data, h, w, bbox: x2 >= 0 ? [x1, y1, x2, y2] : null }
}

/** 多边形 → 行优先位图（扫描线填充，兜底旧数据渲染/命中） */
export function fillPoly(data, h, w, pts) {
  if (!pts || pts.length < 3) return
  const n = pts.length
  for (let y = 0; y < h; y++) {
    const xs = []
    for (let i = 0, j = n - 1; i < n; j = i++) {
      const [x1, y1] = pts[j], [x2, y2] = pts[i]
      if ((y1 <= y && y2 > y) || (y2 <= y && y1 > y)) {
        const t = (y - y1) / (y2 - y1)
        xs.push(x1 + t * (x2 - x1))
      }
    }
    xs.sort((a, b) => a - b)
    for (let k = 0; k + 1 < xs.length; k += 2) {
      const a = Math.max(0, Math.round(xs[k]))
      const b = Math.min(w - 1, Math.round(xs[k + 1]))
      for (let x = a; x <= b; x++) data[y * w + x] = 1
    }
  }
}

/** 标注 data → 位图（rle 优先；points 兜底扫描线填充）。返回 {data, h, w, bbox} */
export function annToBitmap(d, h, w) {
  if (d && d.rle && d.rle.size && d.rle.counts) {
    try { return rleToMask(d.rle) } catch { /* 损坏 RLE 走 points 兜底 */ }
  }
  const data = new Uint8Array(h * w)
  const pts = d && d.points
  if (pts && pts.length >= 3) {
    fillPoly(data, h, w, pts)
    // 算 bbox
    let x1 = w, y1 = h, x2 = -1, y2 = -1
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      if (data[y * w + x]) {
        if (x < x1) x1 = x
        if (x > x2) x2 = x
        if (y < y1) y1 = y
        if (y > y2) y2 = y
      }
    }
    return { data, h, w, bbox: x2 >= 0 ? [x1, y1, x2, y2] : null }
  }
  return { data: new Uint8Array(h * w), h, w, bbox: null }
}

/** 在行优先位图上画实心圆（1=涂抹 0=擦除），返回影响的 bbox [x1,y1,x2,y2] */
export function paintCircle(data, h, w, cx, cy, r, value) {
  const rr = Math.max(0.5, r)
  const r2 = rr * rr
  const x0 = Math.max(0, Math.floor(cx - rr)), x1 = Math.min(w - 1, Math.ceil(cx + rr))
  const y0 = Math.max(0, Math.floor(cy - rr)), y1 = Math.min(h - 1, Math.ceil(cy + rr))
  let minX = w, minY = h, maxX = -1, maxY = -1
  let changed = false
  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      const dx = x - cx, dy = y - cy
      if (dx * dx + dy * dy <= r2) {
        const i = y * w + x
        if (data[i] !== value) {
          data[i] = value
          changed = true
          if (x < minX) minX = x
          if (x > maxX) maxX = x
          if (y < minY) minY = y
          if (y > maxY) maxY = y
        }
      }
    }
  }
  return changed ? [minX, minY, maxX, maxY] : null
}

/** 行优先位图 → RGBA ImageData（color + alpha 预乘到像素），只填 bbox 区域 */
export function bitmapToImageData(data, h, w, bbox, color, alpha) {
  const [x1, y1, x2, y2] = bbox
  const bw = x2 - x1 + 1, bh = y2 - y1 + 1
  const img = new ImageData(bw, bh)
  const px = img.data
  const r = color[0], g = color[1], b = color[2]
  const a = Math.round(alpha * 255)
  for (let y = 0; y < bh; y++) {
    const row = (y1 + y) * w
    for (let x = 0; x < bw; x++) {
      const o = (y * bw + x) * 4
      if (data[row + x1 + x]) {
        px[o] = r; px[o + 1] = g; px[o + 2] = b; px[o + 3] = a
      }
    }
  }
  return img
}

/** 重算行优先位图的 bbox；空位图返回 null */
export function recomputeBbox(data, h, w) {
  let x1 = w, y1 = h, x2 = -1, y2 = -1
  for (let y = 0; y < h; y++) {
    const row = y * w
    for (let x = 0; x < w; x++) {
      if (data[row + x]) {
        if (x < x1) x1 = x
        if (x > x2) x2 = x
        if (y < y1) y1 = y
        if (y > y2) y2 = y
      }
    }
  }
  return x2 >= 0 ? [x1, y1, x2, y2] : null
}

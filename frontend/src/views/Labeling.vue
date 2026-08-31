<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton, NCheckbox, NColorPicker, NEmpty, NGi, NGrid, NIcon, NImage,
  NInput, NInputNumber, NRadioButton, NRadioGroup, NSelect, NSpin, NSwitch, NTag,
  useDialog, useMessage,
} from 'naive-ui'
import { api } from '../api'
import { hexToRGBA, pointInPolygon } from '../utils/labeling'
import { annToBitmap, bitmapToImageData, maskToRle, paintCircle, recomputeBbox } from '../utils/rle'
import { ArrowLeft, ArrowRight, FullScreen, ZoomIn, ZoomOut, Check, Delete, Plus, Close } from '@element-plus/icons-vue'

const route = useRoute()
const pid = Number(route.params.pid)
const message = useMessage()
const dialog = useDialog()

// ---- 数据 ----
const datasets = ref([])
const categories = ref([])
const images = ref([])
const imageIdx = ref(0)
const current = ref(null)        // 当前数据集（n-select 绑定）
const currentImage = ref(null)   // 当前图像（切换图片时只改这里）
const anns = ref([])
const loading = ref(false)

// ---- 状态 ----
const mode = ref('box')
const catId = ref(null)
const selected = ref(null)
const drawing = ref(null)
const unlabeledFirst = ref(false)
const showGrid = ref(true)          // 辅助网格叠加
const gridPos = ref(null)           // 画布内鼠标图像坐标 {x, y}
let brushRaw = []
let eraseAccum = []          // 橡皮擦增量待提交点
let eraseTimer = null        // 节流定时器
const brushing = ref(false)
const brushSize = ref(8)
const panning = ref(false)
let panStart = null  // 平移：鼠标起点 + 滚动起点

// ---- 多边形 / 椭圆工具状态 ----
const polyPts = ref([])        // 多边形顶点 [[x,y]...]（图像坐标）
const polyPreview = ref(null)  // 多边形悬停预览点
const ellipseDrag = ref(null)  // 椭圆拖拽 {start:{x,y}, cur:{x,y}}

// ---- SAM 智能标注状态（框 + 正负点 + 预览） ----
const samBox = ref(null)        // {x1,y1,x2,y2} 图像坐标
const samPoints = ref([])       // 正点 [[x,y]]
const samNegPoints = ref([])    // 负点 [[x,y]]
const samPreview = ref([])      // 预览多边形列表
const samRles = ref([])         // 与 samPreview 逐项对齐的 RLE 掩码
const samDragStart = ref(null)  // 区分单击 / 拖拽画框
const overlayCanvas = ref(null)
let overlayCtx = null
const fillMode = ref(true)
const samLoading = ref(false)
const newCatName = ref('')
const newCatColor = ref('#4E79A7')

// ---- mask 逐像素编辑 ----
const editingId = ref(null)

// ---- RLE 位图缓存（逐像素级精度）：annId -> {data, h, w, bbox} ----
// data 为行优先 Uint8Array(0/1)；rle 优先解码，旧数据（纯多边形）用扫描线填充兜底
const maskBits = new Map()
let scratchCanvas = null   // 掩码填充合成用离屏画布（原图像素尺寸）
let scratchCtx = null

function getMaskBitmap(a) {
  const cached = maskBits.get(a.id)
  if (cached) return cached
  if (!currentImage.value?.width) return null
  const d = typeof a.data === 'string' ? JSON.parse(a.data || '{}') : (a.data || {})
  const bm = annToBitmap(d, currentImage.value.height, currentImage.value.width)
  maskBits.set(a.id, bm)
  return bm
}

function clearMaskBits() { maskBits.clear() }

/** 本地像素级绘制：在标注位图上画圆（erase=true 擦除 / false 涂抹），视觉即时生效 */
function paintLocalMask(id, p, erase) {
  const a = anns.value.find(x => x.id === id)
  if (!a || !currentImage.value) return
  const bm = getMaskBitmap(a)
  if (!bm) return
  const r = Math.max(1, brushSize.value / 2)
  paintCircle(bm.data, bm.h, bm.w, p.x, p.y, r, erase ? 0 : 1)
  renderOverlay()
}

// ---- 缩放 ----
const viewScale = ref(1)
const fitScale = ref(1)
const displayScale = ref(1)
const canvasW = ref(0)
const canvasH = ref(0)
const canvasScroll = ref(null)
const canvasImg = ref(null)
const canvasBox = ref(null)
const initialized = ref(false)

const CAT_PALETTE = ['#4E79A7', '#E15759', '#59A14F', '#F28E2B', '#B07AA1', '#76B7B2', '#EDC948', '#FF9DA7']

// ---- 加载 ----
async function loadDatasets() {
  datasets.value = await api.datasets.list(pid)
  if (!current.value && datasets.value.length) current.value = datasets.value[0]
  await loadCategories()
}

async function loadCategories() {
  // 类别按数据集隔离：只加载当前数据集的类别
  if (!current.value) { categories.value = []; return }
  categories.value = await api.projects.datasetCategories(current.value.id)
  if (catId.value && !categories.value.some(c => c.id === catId.value)) catId.value = null
  if (!catId.value && categories.value.length) catId.value = categories.value[0].id
}

async function loadImages() {
  if (!current.value) return
  // 分页拉取全量图像（后端 page_size 上限 500），避免数据集超过 500 张时其余图像不可达
  const all = []
  let page = 1
  while (true) {
    const r = await api.datasets.images(current.value.id, { page, page_size: 500 })
    all.push(...r.items)
    if (r.items.length < 500 || all.length >= 10000) break
    page++
  }
  images.value = all
  if (unlabeledFirst.value) {
    images.value = [...images.value].sort((a, b) => (a.annotation_count || 0) - (b.annotation_count || 0))
  }
  imageIdx.value = 0
  await selectImage()
}

// 切图竞态防护（P1）：快速切换图像时，过期请求的响应不得覆盖当前图像状态
let annsReqSeq = 0

async function selectImage() {
  const im = images.value[imageIdx.value]
  if (!im) { currentImage.value = null; imgUrl.value = ''; anns.value = []; return }
  currentImage.value = im
  imgUrl.value = api.files.imageUrl(im.id)
  editingId.value = null
  polyPts.value = []
  polyPreview.value = null
  ellipseDrag.value = null
  clearMaskBits()
  await loadAnns()
  await nextTick()
  calcScale()
}

async function loadAnns() {
  if (!currentImage.value) { anns.value = []; return }
  const seq = ++annsReqSeq
  const imId = currentImage.value.id
  clearMaskBits()
  let list
  try {
    list = await api.annotations.list(imId)
  } catch {
    return
  }
  if (seq !== annsReqSeq || !currentImage.value || currentImage.value.id !== imId) return  // 过期响应丢弃
  anns.value = list
  selected.value = null
  editingId.value = null
  hist.value = []
  histPtr.value = -1
  pushHist()  // 基线快照（撤销回退到此）
  renderOverlay()
}

watch(current, async () => {
  await loadCategories()
  await loadImages()
}, { immediate: false })

onMounted(async () => {
  await loadDatasets()
  await loadCategories()
})

// ---- 缩放 ----
function calcScale() {
  if (!currentImage.value?.width) return
  const avail = canvasScroll.value ? canvasScroll.value.clientWidth : 600
  if (!initialized.value) {
    fitScale.value = avail / currentImage.value.width
    initialized.value = true
  } else if (canvasImg.value && canvasImg.value.clientWidth > 0) {
    fitScale.value = canvasImg.value.clientWidth / (currentImage.value.width * viewScale.value)
  }
  updateDisplay()
}

function updateDisplay() {
  displayScale.value = fitScale.value * viewScale.value
  if (currentImage.value) {
    canvasW.value = currentImage.value.width * displayScale.value
    canvasH.value = currentImage.value.height * displayScale.value
  }
  initOverlayCanvas()
}

function initOverlayCanvas() {
  if (!overlayCanvas.value) return
  const cw = Math.round(canvasW.value)
  const ch = Math.round(canvasH.value)
  if (overlayCanvas.value.width !== cw || overlayCanvas.value.height !== ch) {
    overlayCanvas.value.width = cw
    overlayCanvas.value.height = ch
    overlayCtx = overlayCanvas.value.getContext('2d')
  }
  if (cursorCanvas.value) {
    if (cursorCanvas.value.width !== cw) cursorCanvas.value.width = cw
    if (cursorCanvas.value.height !== ch) cursorCanvas.value.height = ch
  }
  renderOverlay()
  drawCursor()
}

// 浏览器 canvas 单边上限 16384px；displayScale 超限时 canvas 尺寸溢出 → 画布空白。
// 按当前图像尺寸动态计算缩放上限（留余量，滚动容器渲染开销也受控）
const MAX_CANVAS_SIDE = 8192
function zoomLimit() {
  const w = currentImage.value?.width || 1
  const h = currentImage.value?.height || 1
  const base = Math.max(w, h) * (fitScale.value || 1)
  return Math.min(64, Math.max(1, MAX_CANVAS_SIDE / base))
}

function zoomBy(factor) {
  const lim = zoomLimit()
  viewScale.value = Math.min(lim, Math.max(0.2, viewScale.value * factor))
  updateDisplay()
}

function zoomReset() {
  viewScale.value = 1
  updateDisplay()
}

/** 1:1 原始像素视图（1 图像像素 = 1 屏幕像素，像素级精修用） */
function zoomPixel1to1() {
  viewScale.value = 1 / (fitScale.value || 1)
  updateDisplay()
}

function onWheel(e) {
  // Shift+滚轮：画笔/橡皮擦模式下调节粗细
  if (e.shiftKey && (mode.value === 'brush' || mode.value === 'eraser')) {
    brushSize.value = Math.min(100, Math.max(1, brushSize.value + (e.deltaY < 0 ? 2 : -2)))
    drawCursor()
    return
  }
  zoomBy(e.deltaY < 0 ? 1.1 : 0.9)
}

// 当前类别颜色（画笔笔迹用）
const catColor = computed(() => categories.value.find(c => c.id === catId.value)?.color || '#4a6b4a')
// 「正常」为常驻整图分类，与缺陷类别分开展示
const normalCat = computed(() => categories.value.find(c => c.name === '正常') || null)
const defectCats = computed(() => categories.value.filter(c => c.name !== '正常'))

// ---- 撤销/重做（移植 X-AnyLabeling 的 undo_shape_edit 模式） ----
// 快照保存 anns 全量；undo/redo 恢复后全量重建服务端（与 xal_sync 全量回写同策略）
const hist = ref([])          // 快照栈（JSON 字符串）
const histPtr = ref(-1)
const HIST_MAX = 60
const canUndo = computed(() => histPtr.value > 0)
const canRedo = computed(() => histPtr.value < hist.value.length - 1)

function pushHist() {
  const s = JSON.stringify(anns.value)
  hist.value = hist.value.slice(0, histPtr.value + 1)
  hist.value.push(s)
  if (hist.value.length > HIST_MAX) hist.value.shift()
  histPtr.value = hist.value.length - 1
}

// P0 修复：撤销/重做恢复原子化。
// - 互斥锁 restoring：恢复期间忽略再次 undo/redo（防 Ctrl+Z 连按并发交错）
// - 先建后删：快照标注全部创建成功后才删除旧标注；创建失败则回滚已建并提示，
//   避免"先删后建"在 create 失败时服务端标注永久丢失
const restoring = ref(false)

async function restoreFromSnapshot(prevStr) {
  if (restoring.value) return
  restoring.value = true
  try {
    const prev = JSON.parse(prevStr)
    // 1) 先建：快照标注 → 服务端（任一失败即中止并回滚已创建项）
    const created = []
    let failed = false
    for (const a of prev) {
      try {
        // 快照中 data 可能是 JSON 字符串（列表接口原样返回），需解析为对象再提交
        const data = typeof a.data === 'string' ? JSON.parse(a.data || '{}') : (a.data || {})
        const r = await api.annotations.create({
          image_id: a.image_id, category_id: a.category_id,
          type: a.type, data, source: a.source,
        })
        created.push(r)
      } catch {
        failed = true
        break
      }
    }
    if (failed) {
      // 回滚已创建的标注，保留旧数据不丢失
      for (const c of created) {
        try { await api.annotations.remove(c.id) } catch { /* ignore */ }
      }
      message.error('撤销恢复失败（服务端创建标注出错），已回滚，请刷新页面')
      return
    }
    // 2) 后删：旧标注删除（尽力而为；删除失败不影响新标注）
    for (const a of anns.value) {
      try { await api.annotations.remove(a.id) } catch { /* ignore */ }
    }
    anns.value = created
    clearMaskBits()
    selected.value = null
    editingId.value = null
    refreshBadge(0)
    renderOverlay()
  } finally {
    restoring.value = false
  }
}

async function undo() {
  if (restoring.value || !canUndo.value) return
  histPtr.value--
  await restoreFromSnapshot(hist.value[histPtr.value])
}
async function redo() {
  if (restoring.value || !canRedo.value) return
  histPtr.value++
  await restoreFromSnapshot(hist.value[histPtr.value])
}

// ---- 选中标注的形状编辑（X-AnyLabeling 的 move_by / move_vertex_by / nearest_vertex） ----
const editOp = ref(null)      // {kind: move/resize/vertex/polyMove, id, start, base}

function hitTestSelected(p) {
  const a = anns.value.find(x => x.id === selected.value)
  if (!a) return null
  const d = typeof a.data === 'string' ? JSON.parse(a.data || '{}') : (a.data || {})
  if (a.type === 'box' && d.x1 != null) {
    const r = 10
    const corners = [[d.x1, d.y1], [d.x2, d.y1], [d.x1, d.y2], [d.x2, d.y2]]
    for (let i = 0; i < 4; i++) {
      if (Math.abs(p.x - corners[i][0]) <= r && Math.abs(p.y - corners[i][1]) <= r) {
        return { kind: 'resize', corner: i }
      }
    }
    if (p.x >= d.x1 && p.x <= d.x2 && p.y >= d.y1 && p.y <= d.y2) return { kind: 'move' }
    return null
  }
  if ((a.type === 'mask' || a.type === 'shield') && d.points?.length) {
    let best = -1, bestD = 12
    for (let i = 0; i < d.points.length; i++) {
      const dist = Math.hypot(p.x - d.points[i][0], p.y - d.points[i][1])
      if (dist < bestD) { bestD = dist; best = i }
    }
    if (best >= 0) return { kind: 'vertex', vi: best }
    if (pointInPolygon(p.x, p.y, d.points)) return { kind: 'polyMove' }
    return null
  }
  return null
}

function beginEdit(p) {
  const hit = hitTestSelected(p)
  if (!hit) return false
  const a = anns.value.find(x => x.id === selected.value)
  const d = typeof a.data === 'string' ? JSON.parse(a.data) : (a.data || {})
  editOp.value = { ...hit, id: a.id, start: { x: p.x, y: p.y }, base: JSON.parse(JSON.stringify(d)) }
  return true
}

function applyEdit(p) {
  if (!editOp.value) return
  const op = editOp.value
  const dx = p.x - op.start.x
  const dy = p.y - op.start.y
  const a = anns.value.find(x => x.id === op.id)
  if (!a) return
  const d = op.base
  if (op.kind === 'move') {
    if (a.type === 'box') {
      d.x1 = op.base.x1 + dx; d.y1 = op.base.y1 + dy
      d.x2 = op.base.x2 + dx; d.y2 = op.base.y2 + dy
    } else {
      d.points = op.base.points.map(([x, y]) => [x + dx, y + dy])
      // RLE 标注：位图同步平移（bbox 区域拷贝，像素级精确预览跟随）
      const bm = maskBits.get(a.id)
      if (bm && bm.bbox) {
        const src = bm.data
        const [bx1, by1, bx2, by2] = bm.bbox
        const nw = bx2 - bx1 + 1, nh = by2 - by1 + 1
        const tmp = new Uint8Array(nw * nh)
        for (let y = 0; y < nh; y++) {
          const srcRow = (by1 + y) * bm.w + bx1
          tmp.set(src.subarray(srcRow, srcRow + nw), y * nw)
        }
        for (let y = by1; y <= by2; y++) src.fill(0, y * bm.w + bx1, y * bm.w + bx1 + nw)
        const nx1 = bx1 + dx, ny1 = by1 + dy
        for (let y = 0; y < nh; y++) {
          const sy = ny1 + y
          if (sy < 0 || sy >= bm.h) continue
          for (let x = 0; x < nw; x++) {
            const sx = nx1 + x
            if (sx < 0 || sx >= bm.w) continue
            if (tmp[y * nw + x]) src[sy * bm.w + sx] = 1
          }
        }
        bm.bbox = recomputeBbox(src, bm.h, bm.w)
        a.__dirtyRle = true  // endEdit 时重编码 RLE
      }
    }
  } else if (op.kind === 'resize') {
    const c = op.corner
    if (c === 0) { d.x1 = op.base.x1 + dx; d.y1 = op.base.y1 + dy }
    else if (c === 1) { d.x2 = op.base.x2 + dx; d.y1 = op.base.y1 + dy }
    else if (c === 2) { d.x1 = op.base.x1 + dx; d.y2 = op.base.y2 + dy }
    else { d.x2 = op.base.x2 + dx; d.y2 = op.base.y2 + dy }
    if (d.x2 < d.x1) [d.x1, d.x2] = [d.x2, d.x1]
    if (d.y2 < d.y1) [d.y1, d.y2] = [d.y2, d.y1]
  } else if (op.kind === 'vertex') {
    d.points = op.base.points.map((pt, i) => i === op.vi ? [pt[0] + dx, pt[1] + dy] : pt)
  }
  a.data = d
  renderOverlay()
}

async function endEdit() {
  if (!editOp.value) return
  const { id, kind } = editOp.value
  editOp.value = null
  const a = anns.value.find(x => x.id === id)
  if (a) {
    const data = typeof a.data === 'string' ? JSON.parse(a.data || '{}') : (a.data || {})
    if (kind === 'vertex') {
      // 顶点编辑 → RLE 与多边形不再一致，降级为纯多边形（下次像素编辑由后端重建 RLE）
      if (data.rle) { data.rle = null; a.data = data }
      maskBits.delete(id)
    } else if ((a.type === 'mask' || a.type === 'shield') && a.__dirtyRle) {
      // 整体移动 → 位图已平移，重编码 RLE 保持像素级一致
      const bm = maskBits.get(id)
      if (bm) {
        data.rle = maskToRle(bm.data, bm.h, bm.w)
        bm.bbox = recomputeBbox(bm.data, bm.h, bm.w)
        a.data = data
      }
      delete a.__dirtyRle
    }
    pushHist()
    try {
      await api.annotations.update(id, { data })
    } catch { /* ignore */ }
  }
}

// 笔刷光标圈：独立覆盖层，避免全量重绘
const cursorCanvas = ref(null)
const mousePos = ref(null)
function drawCursor() {
  const cv = cursorCanvas.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  ctx.clearRect(0, 0, cv.width, cv.height)
  if (!(mode.value === 'brush' || mode.value === 'eraser') || !mousePos.value) return
  const s = displayScale.value
  const rad = Math.max(3, brushSize.value * s / 2)
  const { x, y } = mousePos.value
  ctx.beginPath()
  ctx.arc(x, y, rad, 0, Math.PI * 2)
  ctx.strokeStyle = mode.value === 'eraser' ? 'rgba(225,87,89,0.9)' : 'rgba(74,107,74,0.9)'
  ctx.lineWidth = 1.5
  ctx.setLineDash([4, 3])
  ctx.stroke()
  ctx.setLineDash([])
  ctx.beginPath()
  ctx.arc(x, y, 1.5, 0, Math.PI * 2)
  ctx.fillStyle = mode.value === 'eraser' ? '#e15759' : '#4a6b4a'
  ctx.fill()
}

const zoomLabel = computed(() => Math.round(viewScale.value * fitScale.value * 100) + '%')

// ---- Canvas 覆盖层渲染 ----
function hexToRgbArr(hex) {
  const h = hex.replace('#', '')
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]
}

function ensureScratch(w, h) {
  if (!scratchCanvas) {
    scratchCanvas = document.createElement('canvas')
    scratchCtx = scratchCanvas.getContext('2d')
  }
  if (scratchCanvas.width !== w || scratchCanvas.height !== h) {
    scratchCanvas.width = w
    scratchCanvas.height = h
  }
}

/** 位图填充合成到 overlay（RLE 像素级精确），只 drawImage bbox 区域 */
function drawMaskFill(ctx, a, color, alpha, s) {
  const bm = getMaskBitmap(a)
  if (!bm || !bm.bbox || !currentImage.value) return
  ensureScratch(currentImage.value.width, currentImage.value.height)
  const img = bitmapToImageData(bm.data, bm.h, bm.w, bm.bbox, hexToRgbArr(color), alpha)
  scratchCtx.clearRect(0, 0, scratchCanvas.width, scratchCanvas.height)
  scratchCtx.putImageData(img, bm.bbox[0], bm.bbox[1])
  const [x1, y1, x2, y2] = bm.bbox
  const bw = x2 - x1 + 1, bh = y2 - y1 + 1
  ctx.drawImage(scratchCanvas, x1, y1, bw, bh, x1 * s, y1 * s, bw * s, bh * s)
}

function renderOverlay() {
  if (!overlayCtx || !overlayCanvas.value) return
  const ctx = overlayCtx
  const cw = overlayCanvas.value.width
  const ch = overlayCanvas.value.height
  const s = displayScale.value

  ctx.clearRect(0, 0, cw, ch)

  // 辅助网格 + 坐标十字（图像坐标，随缩放）
  if (showGrid.value) {
    const imgW = currentImage.value?.width || cw / s
    const imgH = currentImage.value?.height || ch / s
    // 像素级精度：1:1 及以上显示逐像素网格，高倍率清晰可见
    const step = s >= 1 ? 1 : (s >= 0.5 ? 2 : Math.max(8, Math.ceil(24 / s)))
    ctx.save()
    ctx.strokeStyle = 'rgba(75,120,160,0.18)'
    ctx.lineWidth = 1
    ctx.setLineDash([4, 4])
    for (let gx = 0; gx <= imgW; gx += step) {
      ctx.beginPath(); ctx.moveTo(gx * s, 0); ctx.lineTo(gx * s, imgH * s); ctx.stroke()
    }
    for (let gy = 0; gy <= imgH; gy += step) {
      ctx.beginPath(); ctx.moveTo(0, gy * s); ctx.lineTo(imgW * s, gy * s); ctx.stroke()
    }
    ctx.setLineDash([])
    if (gridPos.value) {
      const mx = gridPos.value.x, my = gridPos.value.y
      ctx.strokeStyle = 'rgba(225,87,89,0.5)'
      ctx.beginPath(); ctx.moveTo(mx * s, 0); ctx.lineTo(mx * s, imgH * s); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(0, my * s); ctx.lineTo(imgW * s, my * s); ctx.stroke()
    }
    ctx.restore()
  }

  // 绘制已保存的标注
  for (const a of anns.value) {
    if (a.type === 'class') continue
    const d = typeof a.data === 'string' ? JSON.parse(a.data || '{}') : (a.data || {})
    const isSel = selected.value === a.id
    const isEdit = editingId.value === a.id
    const color = a.color || '#4E79A7'

    ctx.save()
    if (a.type === 'mask' && (d.points?.length || d.rle)) {
      if (fillMode.value) drawMaskFill(ctx, a, color, 0.25, s)
      ctx.beginPath()
      if (d.points?.length) {
        ctx.moveTo(d.points[0][0] * s, d.points[0][1] * s)
        for (let i = 1; i < d.points.length; i++) {
          ctx.lineTo(d.points[i][0] * s, d.points[i][1] * s)
        }
        ctx.closePath()
      }
      ctx.strokeStyle = isEdit ? '#e15759' : isSel ? '#1b365d' : color
      ctx.lineWidth = isSel || isEdit ? 3 : 1.5
      ctx.stroke()

      // 标签
      const bx = Math.min(...(d.points?.length ? d.points.map(p => p[0]) : [0])) * s
      const by = Math.min(...(d.points?.length ? d.points.map(p => p[1]) : [0])) * s
      _drawLabel(ctx, a.category_name, bx, by - 16, color)
    } else if (a.type === 'shield' && (d.points?.length || d.rle)) {
      // 屏蔽区：灰色半透明像素填充（不参与训练）
      if (fillMode.value) drawMaskFill(ctx, a, '#8a8175', 0.18, s)
      ctx.beginPath()
      if (d.points?.length) {
        ctx.moveTo(d.points[0][0] * s, d.points[0][1] * s)
        for (let i = 1; i < d.points.length; i++) ctx.lineTo(d.points[i][0] * s, d.points[i][1] * s)
        ctx.closePath()
      }
      ctx.strokeStyle = '#8a8175'
      ctx.lineWidth = 1.5
      ctx.setLineDash([6, 4])
      ctx.stroke()
      ctx.setLineDash([])
      const bx = Math.min(...(d.points?.length ? d.points.map(p => p[0]) : [0])) * s
      const by = Math.min(...(d.points?.length ? d.points.map(p => p[1]) : [0])) * s
      _drawLabel(ctx, '掩膜区', bx, by - 16, '#8a8175')
    } else if (a.type === 'box') {
      const x = d.x1 * s, y = d.y1 * s, w = (d.x2 - d.x1) * s, h = (d.y2 - d.y1) * s
      ctx.strokeStyle = isEdit ? '#e15759' : isSel ? '#1b365d' : color
      ctx.lineWidth = isSel || isEdit ? 3 : 1.5
      ctx.strokeRect(x, y, w, h)
      _drawLabel(ctx, a.category_name, x, y - 16, color)
    }
    ctx.restore()
  }

  // 选中标注的编辑手柄（移植 X-AnyLabeling：框四角缩放点 / 多边形顶点）
  if (selected.value != null && !editingId.value) {
    const sel = anns.value.find(a => a.id === selected.value)
    if (sel) {
      const d = typeof sel.data === 'string' ? JSON.parse(sel.data || '{}') : (sel.data || {})
      ctx.save()
      if (sel.type === 'box' && d.x1 != null) {
        const h = 8
        for (const [hx, hy] of [[d.x1, d.y1], [d.x2, d.y1], [d.x1, d.y2], [d.x2, d.y2]]) {
          ctx.fillStyle = '#ffffff'
          ctx.strokeStyle = '#1b365d'
          ctx.lineWidth = 1.5
          ctx.fillRect(hx * s - h / 2, hy * s - h / 2, h, h)
          ctx.strokeRect(hx * s - h / 2, hy * s - h / 2, h, h)
        }
      } else if ((sel.type === 'mask' || sel.type === 'shield') && d.points?.length) {
        for (const [vx, vy] of d.points) {
          ctx.fillStyle = '#ffffff'
          ctx.strokeStyle = '#1b365d'
          ctx.lineWidth = 1.5
          ctx.beginPath()
          ctx.arc(vx * s, vy * s, 4, 0, Math.PI * 2)
          ctx.fill()
          ctx.stroke()
        }
      }
      ctx.restore()
    }
  }

  // 正在拖拽的矩形框
  if (drawing.value) {
    const d = drawing.value
    const x = Math.min(d.x1, d.x2) * s
    const y = Math.min(d.y1, d.y2) * s
    const w = Math.abs(d.x2 - d.x1) * s
    const h = Math.abs(d.y2 - d.y1) * s
    ctx.save()
    ctx.strokeStyle = '#4a6b4a'
    ctx.lineWidth = 2
    ctx.setLineDash([6, 4])
    ctx.strokeRect(x, y, w, h)
    ctx.setLineDash([])
    ctx.restore()
  }

  // 多边形工具：已加点 + 边线 + 悬停预览
  if (mode.value === 'polygon' && polyPts.value.length) {
    const pts = polyPts.value
    ctx.save()
    ctx.strokeStyle = '#4a6b4a'
    ctx.lineWidth = 2
    ctx.setLineDash([6, 4])
    ctx.beginPath()
    ctx.moveTo(pts[0][0] * s, pts[0][1] * s)
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0] * s, pts[i][1] * s)
    if (polyPreview.value && polyPreview.value.length === 2) {
      ctx.lineTo(polyPreview.value[0] * s, polyPreview.value[1] * s)
    }
    ctx.stroke()
    ctx.setLineDash([])
    for (const p of pts) {
      ctx.beginPath()
      ctx.arc(p[0] * s, p[1] * s, 4, 0, Math.PI * 2)
      ctx.fillStyle = '#4a6b4a'
      ctx.fill()
      ctx.strokeStyle = '#fff'
      ctx.lineWidth = 1
      ctx.stroke()
    }
    ctx.restore()
  }

  // 椭圆工具：拖拽预览
  if (mode.value === 'ellipse' && ellipseDrag.value) {
    const d = ellipseDrag.value
    const cx = d.start.x * s, cy = d.start.y * s
    const rx = Math.abs(d.cur.x - d.start.x) * s, ry = Math.abs(d.cur.y - d.start.y) * s
    ctx.save()
    ctx.strokeStyle = '#4a6b4a'
    ctx.lineWidth = 2
    ctx.setLineDash([6, 4])
    ctx.beginPath()
    ctx.ellipse(cx, cy, Math.max(1, rx), Math.max(1, ry), 0, 0, Math.PI * 2)
    ctx.stroke()
    ctx.setLineDash([])
    ctx.restore()
  }

  // 正在画的笔刷轨迹（画画式：实心圆头笔迹，拖到哪画到哪）
  if (brushRaw.length > 1) {
    ctx.save()
    const s = displayScale.value
    const col = mode.value === 'eraser' ? 'rgba(225,87,89,0.55)' : hexToRGBA(catColor.value, 0.5)
    ctx.strokeStyle = col
    ctx.fillStyle = col
    const w = Math.max(1, brushSize.value * s)
    ctx.lineWidth = w
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.beginPath()
    ctx.moveTo(brushRaw[0].x * s, brushRaw[0].y * s)
    for (let i = 1; i < brushRaw.length; i++) ctx.lineTo(brushRaw[i].x * s, brushRaw[i].y * s)
    ctx.stroke()
    // 每步圆点：保证笔头圆润（起点与慢速移动段）
    for (const p of brushRaw) {
      ctx.beginPath()
      ctx.arc(p.x * s, p.y * s, w / 2, 0, Math.PI * 2)
      ctx.fill()
    }
    ctx.restore()
  }

  // SAM 提示与预览（框 / 正负点 / 预览多边形）
  if (mode.value === 'sam') {
    const s = displayScale.value
    if (samBox.value) {
      ctx.save()
      ctx.strokeStyle = '#5BA8D8'
      ctx.lineWidth = 2
      ctx.setLineDash([6, 4])
      ctx.strokeRect(samBox.value.x1 * s, samBox.value.y1 * s,
        (samBox.value.x2 - samBox.value.x1) * s, (samBox.value.y2 - samBox.value.y1) * s)
      ctx.setLineDash([])
      ctx.restore()
    }
    for (const [px, py] of samPoints.value) {
      ctx.beginPath()
      ctx.arc(px * s, py * s, 5, 0, Math.PI * 2)
      ctx.fillStyle = '#4a6b4a'
      ctx.fill()
      ctx.strokeStyle = '#fff'
      ctx.lineWidth = 1
      ctx.stroke()
    }
    for (const [px, py] of samNegPoints.value) {
      ctx.strokeStyle = '#e15759'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(px * s - 5, py * s - 5)
      ctx.lineTo(px * s + 5, py * s + 5)
      ctx.moveTo(px * s + 5, py * s - 5)
      ctx.lineTo(px * s - 5, py * s + 5)
      ctx.stroke()
    }
    for (const pts of samPreview.value) {
      if (pts.length < 3) continue
      ctx.beginPath()
      ctx.moveTo(pts[0][0] * s, pts[0][1] * s)
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0] * s, pts[i][1] * s)
      ctx.closePath()
      ctx.fillStyle = 'rgba(74,107,74,0.15)'
      ctx.fill()
      ctx.strokeStyle = '#4a6b4a'
      ctx.lineWidth = 2
      ctx.setLineDash([5, 3])
      ctx.stroke()
      ctx.setLineDash([])
    }
  }
}

function _drawLabel(ctx, text, x, y, color) {
  if (!text) return
  ctx.save()
  ctx.font = `${Math.max(10, 11 * displayScale.value)}px sans-serif`
  const m = ctx.measureText(text)
  const padX = 4, padY = 2
  ctx.fillStyle = color
  ctx.fillRect(x, y, m.width + padX * 2, 14 * displayScale.value + padY * 2)
  ctx.fillStyle = '#fff'
  ctx.fillText(text, x + padX, y + 12 * displayScale.value)
  ctx.restore()
}

// 在 anns/selected/editingId/displayScale 变化时重绘
// anns 用哈希串监听（覆盖增删改类别/数据），避免 deep watch 大数组
watch(() => anns.value.map(a => `${a.id}:${a.category_id}:${JSON.stringify(a.data)}`).join('|'), renderOverlay)
watch(selected, renderOverlay)
watch(editingId, renderOverlay)
watch(() => displayScale.value, renderOverlay)
watch(fillMode, renderOverlay)

// ---- 坐标 ----
function toImgCoord(e) {
  const rect = canvasBox.value.getBoundingClientRect()
  return {
    x: Math.round((e.clientX - rect.left) / displayScale.value),
    y: Math.round((e.clientY - rect.top) / displayScale.value),
  }
}

// ---- 画布交互 ----
function onMouseDown(e) {
  // 平移：中键拖拽 或 平移模式
  if (e.button === 1 || mode.value === 'pan') {
    panning.value = true
    panStart = {
      x: e.clientX, y: e.clientY,
      sx: canvasScroll.value.scrollLeft, sy: canvasScroll.value.scrollTop,
    }
    e.preventDefault()
    return
  }
  if (e.button !== 0) return
  if (mode.value === 'brush') {
    const p = toImgCoord(e)
    // 不在当前编辑掩码内 → 结束像素编辑，开始新标注
    if (editingId.value && !hitMask(p, editingId.value)) {
      editingId.value = null
    }
    brushRaw = [p]
    brushing.value = true
    renderOverlay()
    return
  }
  if (mode.value === 'eraser') {
    const p = toImgCoord(e)
    const hit = hitMask(p)
    if (!hit) return message.info('橡皮擦：按住鼠标在要擦除的掩码区域上涂抹')
    editingId.value = hit
    brushRaw = [p]
    eraseAccum = []
    brushing.value = true
    renderOverlay()
    return
  }
  if (mode.value === 'shield') {
    const p = toImgCoord(e)
    brushRaw = [p]
    brushing.value = true
    renderOverlay()
    return
  }
  if (mode.value === 'sam') {
    if (e.button === 0) samDragStart.value = toImgCoord(e)
    return
  }
  // 形状编辑：按下位置命中选中标注（框角/框内/多边形顶点/多边形内）→ 优先编辑而非新建
  if (mode.value !== 'class') {
    const hp = toImgCoord(e)
    if (beginEdit(hp)) {
      e.preventDefault()
      return
    }
  }
  if (mode.value === 'polygon') {
    const p = toImgCoord(e)
    polyPts.value.push([p.x, p.y])
    renderOverlay()
    return
  }
  if (mode.value === 'ellipse') {
    const p = toImgCoord(e)
    ellipseDrag.value = { start: { x: p.x, y: p.y }, cur: { x: p.x, y: p.y } }
    return
  }
  if (mode.value !== 'box' || e.button !== 0) return
  const p = toImgCoord(e)
  drawing.value = { x1: p.x, y1: p.y, x2: p.x, y2: p.y }
}

function onMouseMove(e) {
  // 笔刷光标跟随
  if (canvasBox.value) {
    const r = canvasBox.value.getBoundingClientRect()
    mousePos.value = { x: e.clientX - r.left, y: e.clientY - r.top }
    drawCursor()
  }
  // 十字坐标（图像坐标）：供网格叠加与状态栏显示
  if (currentImage.value) {
    try {
      const p = toImgCoord(e)
      gridPos.value = { x: Math.round(p.x), y: Math.round(p.y) }
    } catch { gridPos.value = null }
  }
  if (panning.value && panStart) {
    canvasScroll.value.scrollLeft = panStart.sx - (e.clientX - panStart.x)
    canvasScroll.value.scrollTop = panStart.sy - (e.clientY - panStart.y)
    return
  }
  if (editOp.value) {
    applyEdit(toImgCoord(e))
    return
  }
  if (brushing.value) {
    const p = toImgCoord(e)
    brushRaw.push(p)
    // 橡皮擦：本地位图即时擦除（鼠标拖到哪，掩码立刻少一块，像素级零延迟）
    // + 增量节流提交后端（服务端权威 RLE 返回后重建缓存）
    if (mode.value === 'eraser') {
      if (editingId.value) paintLocalMask(editingId.value, p, true)
      eraseAccum.push(p)
      if (!eraseTimer) {
        eraseTimer = setTimeout(() => { eraseTimer = null; flushErase() }, 60)
      }
    }
    renderOverlay()
    return
  }
  if (mode.value === 'sam' && samDragStart.value) {
    const p = toImgCoord(e)
    if (samBox.value) {
      samBox.value.x2 = p.x
      samBox.value.y2 = p.y
    } else {
      samBox.value = { x1: samDragStart.value.x, y1: samDragStart.value.y, x2: p.x, y2: p.y }
    }
    renderOverlay()
    return
  }
  if (mode.value === 'polygon') {
    const p = toImgCoord(e)
    polyPreview.value = [p.x, p.y]
    renderOverlay()
    return
  }
  if (mode.value === 'ellipse' && ellipseDrag.value) {
    const p = toImgCoord(e)
    ellipseDrag.value.cur = { x: p.x, y: p.y }
    renderOverlay()
    return
  }
  if (!drawing.value) return
  const p = toImgCoord(e)
  drawing.value.x2 = p.x
  drawing.value.y2 = p.y
  renderOverlay()
}

async function onMouseUp(e) {
  if (editOp.value) {
    await endEdit()
    return
  }
  if (panning.value) {
    panning.value = false
    panStart = null
    return
  }
  if (brushing.value) {
    brushing.value = false
    if (mode.value === 'eraser') {
      // 橡皮擦：增量已实时提交，这里只补最后一段并清理（掩码可能已被擦完，绝不新建）
      flushErase()
      brushRaw = []
      pushHist()  // 擦除后记录历史（撤销可回到擦除前）
      renderOverlay()
      return
    }
    await submitBrush()
    return
  }
  if (mode.value === 'sam') {
    const start = samDragStart.value
    samDragStart.value = null
    if (!start || !e) return
    const p = toImgCoord(e)
    if (Math.abs(p.x - start.x) < 5 && Math.abs(p.y - start.y) < 5) {
      // 单击：加正点
      samPoints.value.push([p.x, p.y])
    } else {
      // 拖拽：画框
      samBox.value = {
        x1: Math.min(start.x, p.x), y1: Math.min(start.y, p.y),
        x2: Math.max(start.x, p.x), y2: Math.max(start.y, p.y),
      }
    }
    await runSam()
    return
  }
  if (mode.value === 'ellipse' && ellipseDrag.value) {
    const d = ellipseDrag.value
    ellipseDrag.value = null
    const cx = d.start.x, cy = d.start.y
    const rx = Math.abs(d.cur.x - d.start.x), ry = Math.abs(d.cur.y - d.start.y)
    if (rx < 3 || ry < 3) { renderOverlay(); return }
    if (!catId.value) return message.warning('请先在左侧选择缺陷类别')
    // 椭圆 → 多边形（后端复用 X-AnyLabeling 几何算法）
    let pts = []
    try {
      const r = await api.xal.ellipse({ points: [[cx, cy], [d.cur.x, d.cur.y]] })
      pts = (r && r.points) || []
    } catch (err) {
      // 后端不可用时前端兜底：参数方程采样（32 边）
      for (let i = 0; i < 32; i++) {
        const a = 2 * Math.PI * i / 32
        pts.push([cx + rx * Math.cos(a), cy + ry * Math.sin(a)])
      }
    }
    if (pts.length >= 3) {
      const a = await api.annotations.create({
        image_id: currentImage.value.id, category_id: catId.value,
        type: 'mask', data: { points: pts }, source: 'manual',
      })
      anns.value.push(a)
      pushHist()
      refreshBadge(1)
    }
    renderOverlay()
    return
  }
  if (!drawing.value) return
  const d = drawing.value
  drawing.value = null
  renderOverlay()
  const x1 = Math.min(d.x1, d.x2), y1 = Math.min(d.y1, d.y2)
  const x2 = Math.max(d.x1, d.x2), y2 = Math.max(d.y1, d.y2)
  if (x2 - x1 < 3 || y2 - y1 < 3) return
  if (!catId.value) return message.warning('请先在左侧选择缺陷类别')
  const a = await api.annotations.create({
    image_id: currentImage.value.id, category_id: catId.value,
    type: 'box', data: { x1, y1, x2, y2 }, source: 'manual',
  })
  anns.value.push(a)
  pushHist()
  refreshBadge(1)
}

/** 橡皮擦增量提交：把累积的轨迹点擦除到当前编辑掩码，实时更新视图 */
function flushErase() {
  if (!eraseAccum.length) return
  const pts = eraseAccum.map(p => [p.x, p.y])  // 接口要求 [[x,y],...]
  eraseAccum = []
  if (!editingId.value) return
  api.annotations.paint(editingId.value, {
    points: pts, brush_size: brushSize.value, erase: true,
  }).then((r) => {
    const i = anns.value.findIndex(a => a.id === editingId.value)
    if (i < 0) return
    if (r.deleted) {
      anns.value.splice(i, 1)
      maskBits.delete(editingId.value)
      editingId.value = null
      refreshBadge(-1)
    } else {
      anns.value[i] = r
      maskBits.delete(r.id)  // 以服务端权威 RLE 重建缓存
    }
    renderOverlay()
  }).catch(() => { /* 网络抖动忽略，松手时最终提交兜底 */ })
}

async function submitBrush() {
  if (brushRaw.length < 2) return
  if (!catId.value) return message.warning('请先选择缺陷类别')
  const pts = brushRaw.map(p => [p.x, p.y])
  try {
    if (editingId.value) {      const r = await api.annotations.paint(editingId.value, {
        points: pts, brush_size: brushSize.value, erase: mode.value === 'eraser',
      })
      if (r.deleted) {
        anns.value = anns.value.filter(a => a.id !== editingId.value)
        maskBits.delete(editingId.value)
        editingId.value = null
        refreshBadge(-1)
      } else {
        const i = anns.value.findIndex(a => a.id === editingId.value)
        if (i >= 0) anns.value[i] = r
        maskBits.delete(editingId.value)  // 以服务端权威 RLE 重建缓存
      }
    } else {
      const isShield = mode.value === 'shield'
      const a = await api.annotations.brush({
        image_id: currentImage.value.id, category_id: catId.value,
        points: pts, brush_size: brushSize.value, type: isShield ? 'shield' : 'mask',
      })
      anns.value.push(a)
      if (isShield) {
        message.success('屏蔽区已创建（该区域不参与训练）')
      } else {
        // 创建后自动进入逐像素编辑：后续涂抹直接 paint 像素级更新
        editingId.value = a.id
        message.success('掩码已创建，继续涂抹为逐像素编辑')
      }
      refreshBadge(1)
    }
    pushHist()  // 笔刷创建/逐像素编辑后记录历史
  } finally {
    brushRaw = []
    renderOverlay()
  }
}

// ---- 掩码命中检测（RLE 位图优先 = 像素级精确；旧数据回退多边形射线法） ----

function hitMask(p, onlyId = null) {
  for (const a of anns.value) {
    if (a.type !== 'mask' && a.type !== 'shield') continue
    if (onlyId != null && a.id !== onlyId) continue
    const bm = getMaskBitmap(a)
    if (bm && currentImage.value) {
      const x = Math.round(p.x), y = Math.round(p.y)
      if (x >= 0 && y >= 0 && x < currentImage.value.width && y < currentImage.value.height
          && bm.data[y * bm.w + x]) return a.id
      continue
    }
    const d = typeof a.data === 'string' ? JSON.parse(a.data || '{}') : (a.data || {})
    const pts = d.points || []
    if (pts.length < 3) continue
    if (pointInPolygon(p.x, p.y, pts)) return a.id
  }
  return null
}

/** 画布点选：命中标注（框内 / 掩码像素内，后画的在上层优先） */
function findAnnoAt(p) {
  for (let i = anns.value.length - 1; i >= 0; i--) {
    const a = anns.value[i]
    if (a.type === 'class') continue
    const d = typeof a.data === 'string' ? JSON.parse(a.data || '{}') : (a.data || {})
    if (a.type === 'box' && d.x1 != null) {
      if (p.x >= d.x1 && p.x <= d.x2 && p.y >= d.y1 && p.y <= d.y2) return a
    } else if (a.type === 'mask' || a.type === 'shield') {
      const bm = getMaskBitmap(a)
      if (bm && currentImage.value) {
        const x = Math.round(p.x), y = Math.round(p.y)
        if (x >= 0 && y >= 0 && x < currentImage.value.width && y < currentImage.value.height
            && bm.data[y * bm.w + x]) return a
      } else if (d.points?.length >= 3) {
        if (pointInPolygon(p.x, p.y, d.points)) return a
      }
    }
  }
  return null
}

// ---- SAM 智能标注 ----
async function runSam() {
  if (!catId.value) return message.warning('请先选择缺陷类别')
  if (!samBox.value && !samPoints.value.length && !samNegPoints.value.length) {
    samPreview.value = []
    renderOverlay()
    return
  }
  samLoading.value = true
  try {
    const r = await api.sam.predict({
      image_id: currentImage.value.id,
      points: samPoints.value,
      neg_points: samNegPoints.value,
      box: samBox.value ? [samBox.value.x1, samBox.value.y1, samBox.value.x2, samBox.value.y2] : null,
    })
    samPreview.value = r.polygons || []
    samRles.value = r.rles || []   // 与 polygons 逐项对齐（像素级 RLE 存储）
  } catch (err) {
    samPreview.value = []
    samRles.value = []
  } finally {
    samLoading.value = false
    renderOverlay()
  }
}

async function confirmSam() {
  if (!catId.value) return message.warning('请先选择缺陷类别')
  if (!samPreview.value.length) return message.info('还没有预览结果，先画框或点击添加提示')
  const n = samPreview.value.length
  for (let i = 0; i < n; i++) {
    const data = { points: samPreview.value[i] }
    if (samRles.value && samRles.value[i]) data.rle = samRles.value[i]
    const a = await api.annotations.create({
      image_id: currentImage.value.id, category_id: catId.value,
      type: 'mask', data, source: 'sam',
    })
    anns.value.push(a)
  }
  refreshBadge(n)
  pushHist()
  clearSam()
  message.success(`已生成 ${n} 个掩码`)
}

function clearSam() {
  samBox.value = null
  samPoints.value = []
  samNegPoints.value = []
  samPreview.value = []
  samDragStart.value = null
  renderOverlay()
}

function onSamContext(e) {
  // 右键：加负点（抑制误检区域）
  if (mode.value !== 'sam') return
  const p = toImgCoord(e)
  samNegPoints.value.push([p.x, p.y])
  runSam()
}

async function onCanvasClick(e) {
  if (mode.value === 'class') {
    if (!catId.value) return message.warning('请先选择缺陷类别')
    const old = anns.value.find(a => a.type === 'class')
    if (old) {
      await api.annotations.update(old.id, { category_id: catId.value })
      old.category_id = catId.value
      old.category_name = categories.value.find(c => c.id === catId.value)?.name
      old.color = categories.value.find(c => c.id === catId.value)?.color
      pushHist()
    } else {
      const a = await api.annotations.create({
        image_id: currentImage.value.id, category_id: catId.value, type: 'class', data: {}, source: 'manual',
      })
      anns.value.push(a)
      pushHist()
      refreshBadge(1)
    }
    return
  }
  // 画布点选：命中标注 → 选中（随后可拖拽编辑）；空白处 → 取消选中
  const p = toImgCoord(e)
  const hit = findAnnoAt(p)
  if (hit) {
    selected.value = hit.id
  } else {
    selected.value = null
  }
  renderOverlay()
}

// ---- 多边形：完成 / 双击闭合 ----
async function finishPolygon() {
  if (mode.value !== 'polygon') return
  const pts = polyPts.value
  if (pts.length < 3) return message.info('多边形至少需要 3 个点')
  if (!catId.value) return message.warning('请先在左侧选择缺陷类别')
  const a = await api.annotations.create({
    image_id: currentImage.value.id, category_id: catId.value,
    type: 'mask', data: { points: pts.map(p => [p[0], p[1]]) }, source: 'manual',
  })
  anns.value.push(a)
  pushHist()
  polyPts.value = []
  polyPreview.value = null
  refreshBadge(1)
  renderOverlay()
}

function onCanvasDblClick() {
  if (mode.value === 'polygon' && polyPts.value.length >= 3) finishPolygon()
}

function onAnnoClick(a) {
  selected.value = a.id
  if (a.type === 'mask') {
    editingId.value = editingId.value === a.id ? null : a.id
  }
}

async function removeSelected() {
  if (selected.value == null) return
  await api.annotations.remove(selected.value)
  anns.value = anns.value.filter(a => a.id !== selected.value)
  if (editingId.value === selected.value) editingId.value = null
  selected.value = null
  pushHist()
  refreshBadge(-1)
}

async function changeCat(ann, cid) {
  const a = await api.annotations.update(ann.id, { category_id: cid })
  Object.assign(ann, a)
}

async function addNewCat() {
  if (!newCatName.value.trim()) return message.warning('请输入类别名称')
  if (!current.value) return message.warning('请先选择数据集')
  const c = await api.projects.addDatasetCategory(current.value.id, {
    name: newCatName.value, color: newCatColor.value,
  })
  categories.value.push(c)
  catId.value = c.id
  newCatName.value = ''
  newCatColor.value = CAT_PALETTE[categories.value.length % CAT_PALETTE.length]
}

function removeCat(c) {
  dialog.warning({
    title: '删除类别',
    content: `删除类别「${c.name}」后，属于它的标注将变为未分类，确定删除？`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      await api.projects.removeCategory(c.id)
      categories.value = categories.value.filter(x => x.id !== c.id)
      if (catId.value === c.id) catId.value = categories.value[0]?.id || null
      // 当前图标注类别失效，重载
      if (currentImage.value) await loadAnns()
    },
  })
}

async function updateCatColor(c, color) {
  await api.projects.updateCategory(c.id, { color })
  c.color = color
}

function refreshBadge(delta) {
  if (currentImage.value) currentImage.value.annotation_count = (currentImage.value.annotation_count || 0) + delta
}

function nextImage(dir) {
  const n = images.value.length
  if (!n) return
  imageIdx.value = (imageIdx.value + dir + n) % n
  selectImage()
}

function keyHandler(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
  // 撤销/重做（Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y）
  if (e.ctrlKey || e.metaKey) {
    const k = e.key.toLowerCase()
    if (k === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo() }
    else if (k === 'y') { e.preventDefault(); redo() }
    return
  }
  if (e.altKey) return
  if (e.key === 'ArrowRight') nextImage(1)
  else if (e.key === 'ArrowLeft') nextImage(-1)
  else if (e.key === 'Delete' || e.key === 'Backspace') removeSelected()
  else if (e.key === 'Escape') {
    editingId.value = null; selected.value = null
    if (mode.value === 'polygon') { polyPts.value = []; polyPreview.value = null; renderOverlay() }
  }
  else if (e.key === '+') zoomBy(1.2)
  else if (e.key === '-') zoomBy(0.8)
  else if (e.key.toLowerCase() === 'b') mode.value = 'box'
  else if (e.key.toLowerCase() === 'p') mode.value = 'polygon'
  else if (e.key.toLowerCase() === 'e') mode.value = 'ellipse'
  else if (e.key.toLowerCase() === 'c') mode.value = 'class'
  else if (e.key.toLowerCase() === 's') mode.value = 'sam'
  else if (e.key.toLowerCase() === 'r') mode.value = 'brush'
  else if (e.key.toLowerCase() === 'x') mode.value = 'eraser'
  else if (e.key.toLowerCase() === 'h') mode.value = 'shield'
  else if (e.key.toLowerCase() === 'm') mode.value = 'pan'
  else if (e.key.toLowerCase() === 'g') showGrid.value = !showGrid.value
}

function keyUpHandler(e) {
  if (e.key === 'Alt') { /* 预留 */ }
}

onMounted(() => {
  window.addEventListener('keydown', keyHandler)
  window.addEventListener('keyup', keyUpHandler)
})
onUnmounted(() => {
  window.removeEventListener('keydown', keyHandler)
  window.removeEventListener('keyup', keyUpHandler)
  // 清理节流定时器（P1：切页后 timer 触发访问已卸载组件状态）
  if (eraseTimer) { clearTimeout(eraseTimer); eraseTimer = null }
})

// ---- 标注列表按类别分组 ----
const classAnn = computed(() => anns.value.find(a => a.type === 'class'))

const groupedAnns = computed(() => {
  const map = new Map()
  for (const a of anns.value) {
    if (a.type === 'class') continue
    const key = a.category_id || 0
    if (!map.has(key)) {
      map.set(key, { category_name: a.category_name || '未分类', color: a.color || '#4E79A7', items: [] })
    }
    map.get(key).items.push(a)
  }
  return [...map.values()]
})

const datasetOptions = computed(() => datasets.value.map(d => ({ label: d.name, value: d })))
const categoryOptions = computed(() => categories.value.map(c => ({ label: c.name, value: c.id })))

const imgUrl = ref('')
</script>

<template>
  <div>
    <div class="page-head">
      <h2>标注工作台</h2>
      <div style="display:flex;gap:8px;align-items:center">
        <n-select v-model:value="current" :options="datasetOptions" style="width:150px"
                  @update:value="loadImages" />
        <n-checkbox v-model:checked="unlabeledFirst" @update:checked="loadImages">未标注优先</n-checkbox>
      </div>
    </div>

    <n-grid :cols="24" :x-gap="16">
      <!-- 左：类别 + 图像列表 -->
      <n-gi :span="6">
        <div class="card" style="margin-bottom:12px">
          <!-- 常驻「正常」：整图分类专用，独立于缺陷类别 -->
          <div style="font-weight:600;margin-bottom:8px;font-size:0.9rem">整图分类</div>
          <div v-if="normalCat" class="cat-row" :class="{ on: catId === normalCat.id }"
               @click="catId = normalCat.id">
            <!-- 原生取色器：纯色块、无内嵌文本、点击弹系统取色面板（统一外观） -->
            <input type="color" class="cat-color" :value="normalCat.color || '#3F9D63'"
                   @input="e => updateCatColor(normalCat, e.target.value)" @click.stop />
            <span style="flex:1;min-width:0;word-break:break-all;line-height:1.4">{{ normalCat.name }}</span>
            <n-tag size="tiny" type="success" :bordered="false">常驻</n-tag>
          </div>
          <div v-else style="color:#8a8175;font-size:0.82rem;padding:6px 0">
            「正常」为系统常驻分类，用于图像分类（选它 = 该图无缺陷）
          </div>

          <div style="font-weight:600;margin:12px 0 8px;font-size:0.9rem">缺陷类别</div>
          <div v-if="!defectCats.length" style="color:#8b2c1f;font-size:0.82rem;margin-bottom:6px">
            暂无缺陷类别，请先在数据集页添加
          </div>
          <div class="cat-row" v-for="c in defectCats" :key="c.id" @click="catId = c.id"
               :class="{ on: catId === c.id }" :title="c.name || ('类别 ' + c.id)">
            <!-- 统一外观：原生取色器纯色块 + 名字（与「正常」行一致） -->
            <input type="color" class="cat-color" :value="c.color || '#4E79A7'"
                   @input="e => updateCatColor(c, e.target.value)" @click.stop />
            <!-- 名字不截断（word-break 换行）——窄窗口下 ellipsis 会把中文名截没 -->
            <span style="flex:1;min-width:0;word-break:break-all;line-height:1.4">{{ c.name || ('类别 ' + c.id) }}</span>
            <n-button text size="small" type="error" @click.stop="removeCat(c)"><n-icon><Close /></n-icon></n-button>
          </div>
          <div style="display:flex;gap:6px;margin-top:10px;align-items:center">
            <n-color-picker v-model:value="newCatColor" size="small" :modes="['hex']" :show-alpha="false" />
            <n-input v-model:value="newCatName" placeholder="新建标签" size="small" @keyup.enter="addNewCat" />
            <n-button size="small" type="primary" @click="addNewCat"><n-icon><Plus /></n-icon></n-button>
          </div>
          <div style="color:#8a8175;font-size:0.75rem;margin-top:6px">
            缺陷类别属于当前数据集（{{ current?.name }}）；「正常」常驻、删除后标注将变为未分类
          </div>
        </div>
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span style="font-weight:600;font-size:0.9rem">图像（{{ images.length }}）</span>
            <span style="color:#8a8175;font-size:0.8rem">{{ imageIdx + 1 }}/{{ images.length }}</span>
          </div>
          <div style="max-height:520px;overflow-y:auto">
            <div v-for="(im, i) in images" :key="im.id" class="img-row" :class="{ on: i === imageIdx }"
                 @click="imageIdx = i; selectImage()">
              <n-image :src="api.files.imageUrl(im.id)" object-fit="cover" preview-disabled
                       style="width:44px;height:44px;border-radius:4px" />
              <span style="flex:1;font-size:0.8rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ im.rel_path }}</span>
              <span class="badge" :class="im.annotation_count ? 'done' : ''">{{ im.annotation_count || 0 }}</span>
            </div>
          </div>
        </div>
      </n-gi>

      <!-- 中：画布 -->
      <n-gi :span="13">
        <div class="card">
          <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap">
            <n-radio-group v-model:value="mode" size="small">
              <n-radio-button value="box">画框</n-radio-button>
              <n-radio-button value="polygon">多边形</n-radio-button>
              <n-radio-button value="ellipse">椭圆</n-radio-button>
              <n-radio-button value="class">分类</n-radio-button>
              <n-radio-button value="sam">SAM 掩码</n-radio-button>
              <n-radio-button value="brush">画笔</n-radio-button>
              <n-radio-button value="eraser">橡皮擦</n-radio-button>
              <n-radio-button value="shield">掩膜</n-radio-button>
              <n-radio-button value="pan">平移</n-radio-button>
            </n-radio-group>
            <template v-if="mode === 'sam'">
              <n-button size="small" type="primary" @click="confirmSam" :loading="samLoading"><n-icon><Check /></n-icon><span style="margin-left:3px">确认掩码</span></n-button>
              <n-button size="small" @click="clearSam"><n-icon><Delete /></n-icon><span style="margin-left:3px">清空</span></n-button>
            </template>
            <template v-if="mode === 'polygon'">
              <n-button size="small" type="primary" :disabled="polyPts.length < 3" @click="finishPolygon"><n-icon><Check /></n-icon><span style="margin-left:3px">完成多边形</span></n-button>
              <n-button size="small" @click="polyPts = []; renderOverlay()"><n-icon><Delete /></n-icon><span style="margin-left:3px">清空</span></n-button>
            </template>
            <span v-if="mode === 'brush' || mode === 'sam'" style="display:flex;align-items:center;gap:6px;margin-left:4px">
              <n-switch v-model:value="fillMode" size="small" />
              <span style="font-size:0.8rem;color:#8a8175">{{ fillMode ? '填充' : '轮廓' }}</span>
            </span>
            <span style="color:#8a8175;font-size:0.8rem">
              {{ mode === 'box' ? '拖拽画框 · 热键 B · 点击框选中，拖四角缩放/拖框移动，Delete 删除' :
                 mode === 'polygon' ? '左键单击加点 · 热键 P · 完成/双击闭合，Esc 取消；选中后拖顶点/整体移动' :
                 mode === 'ellipse' ? '拖拽画椭圆 · 热键 E · 松手生成掩码；选中后拖顶点编辑' :
                 mode === 'class' ? '点击图像设置整图类别 · 热键 C' :
                 mode === 'sam' ? '拖拽画框 · 热键 S · 左键加正点，右键加负点，确认生成掩码' :
                 mode === 'pan' ? '按住左键拖拽平移 · 热键 M · 中键平移，滚轮缩放' :
                 mode === 'eraser' ? '橡皮擦：实时擦除（鼠标拖到哪擦到哪）· 热键 X · Shift+滚轮调大小' :
                 mode === 'shield' ? '掩膜：涂抹屏蔽区 · 热键 H · 该区域不参与训练，橡皮擦可擦除' :
                 '画笔：拖到哪画到哪 · 热键 R · Shift+滚轮调粗细，松手成掩码；Ctrl+Z 撤销' }}
            </span>
            <span v-if="mode === 'brush' || mode === 'eraser'" style="display:flex;align-items:center;gap:6px">
              <span style="font-size:0.8rem;color:#4a433c">{{ mode === 'eraser' ? '橡皮' : '笔刷' }}</span>
              <n-input-number v-model:value="brushSize" :min="1" :max="100" :step="1" size="small" style="width:90px" />
            </span>
            <span v-if="editingId" style="color:#e15759;font-size:0.8rem">● 编辑中</span>
            <span v-if="samLoading" style="color:#4a6b4a;font-size:0.8rem">SAM 推理中…</span>
            <div style="flex:1"></div>
            <n-button size="small" :disabled="!canUndo" :title="'撤销 (Ctrl+Z)'" @click="undo">撤销</n-button>
            <n-button size="small" :disabled="!canRedo" :title="'重做 (Ctrl+Shift+Z)'" @click="redo">重做</n-button>
            <span style="font-size:0.8rem;color:#8a8175">
              坐标 {{ gridPos ? `(${gridPos.x}, ${gridPos.y})` : '(--, --)' }}
            </span>
            <n-button size="small" :title="showGrid ? '隐藏参考网格 (G)' : '显示参考网格 (G)'"
                       @click="showGrid = !showGrid">{{ showGrid ? '格' : '格' }}</n-button>
            <span style="font-size:0.8rem;color:#8a8175">{{ zoomLabel }}</span>
            <n-button size="small" @click="zoomBy(1.25)"><n-icon><ZoomIn /></n-icon></n-button>
            <n-button size="small" @click="zoomBy(0.8)"><n-icon><ZoomOut /></n-icon></n-button>
            <n-button size="small" @click="zoomReset"><n-icon><FullScreen /></n-icon><span style="margin-left:3px">适应</span></n-button>
            <n-button size="small" title="1:1 原始像素（像素级精修）" @click="zoomPixel1to1">1:1</n-button>
            <n-button size="small" @click="nextImage(-1)"><n-icon><ArrowLeft /></n-icon><span style="margin-left:3px">上一张</span></n-button>
            <n-button size="small" type="primary" @click="nextImage(1)">下一张<n-icon style="margin-left:3px"><ArrowRight /></n-icon></n-button>
          </div>
          <n-spin :show="loading" style="min-height:400px">
            <div v-if="currentImage" ref="canvasScroll" class="canvas-scroll" @wheel.prevent="onWheel">
              <div ref="canvasBox" class="canvas" :style="{ width: canvasW + 'px', height: canvasH + 'px' }"
                   @mousedown="onMouseDown" @mousemove="onMouseMove" @mouseup="onMouseUp" @click="onCanvasClick"
                   @contextmenu.prevent="onSamContext" @dblclick="onCanvasDblClick">
                <img ref="canvasImg" :src="imgUrl" draggable="false" @load="calcScale" />
                <canvas ref="overlayCanvas" class="overlay-canvas"></canvas>
                <canvas ref="cursorCanvas" class="cursor-canvas"></canvas>
                <div v-if="classAnn" class="class-mark" :style="{ background: classAnn.color || '#4E79A7' }">
                  {{ classAnn.category_name }}
                </div>
              </div>
            </div>
            <n-empty v-else description="选择左侧数据集和图像" size="large" />
          </n-spin>
        </div>
      </n-gi>

      <!-- 右：标注列表（按类别分组） -->
      <n-gi :span="5">
        <div class="card">
          <div style="font-weight:600;margin-bottom:8px;font-size:0.9rem">
            标注列表（{{ anns.filter(a => a.type !== 'class').length }}）
          </div>
          <div v-if="!groupedAnns.length && classAnn" style="margin-bottom:10px">
            <div class="ann-row" :class="{ on: selected === classAnn.id }"
                 @click="selected = classAnn.id">
              <span class="dot" :style="{ background: classAnn.color }"></span>
              <span>整图：{{ classAnn.category_name }}</span>
              <n-button text size="small" type="error" @click="removeSelected">×</n-button>
            </div>
          </div>
          <div v-if="groupedAnns.length" style="max-height:460px;overflow-y:auto">
            <div v-for="group in groupedAnns" :key="group.category_name" style="margin-bottom:10px">
              <div style="display:flex;align-items:center;gap:6px;padding:3px 0;margin-bottom:4px;
                          border-bottom:0.5px solid #d8cfbe;font-size:0.82rem;font-weight:600">
                <span class="dot" :style="{ background: group.color }"></span>
                <span>{{ group.category_name }}</span>
                <span style="color:#8a8175;font-weight:400">({{ group.items.length }})</span>
              </div>
              <div v-for="a in group.items" :key="a.id" class="ann-row"
                   :class="{ on: selected === a.id }" @click="onAnnoClick(a)">
                <span style="font-size:0.75rem;color:#8a8175;width:28px;flex-shrink:0">
                  {{ a.type === 'mask' ? '掩码' : '框' }}
                </span>
                <n-select :value="a.category_id" size="small" style="flex:1;min-width:0"
                          :options="categoryOptions" @update:value="cid => changeCat(a, cid)" />
                <n-button text size="small" type="error" @click="selected = a.id; removeSelected()">×</n-button>
              </div>
            </div>
          </div>
          <n-empty v-else-if="!classAnn" description="无标注" size="medium" />
        </div>
      </n-gi>
    </n-grid>
  </div>
</template>

<style scoped>
/* 原生取色器色块（类别行统一外观）：纯色矩形、无内嵌文本、点击弹系统取色面板 */
.cat-color {
  width: 56px; height: 28px;
  padding: 0; border: 1px solid #d8cfbe; border-radius: 4px;
  background: transparent; cursor: pointer; flex-shrink: 0;
}
.cat-color::-webkit-color-swatch-wrapper { padding: 0; }
.cat-color::-webkit-color-swatch { border: none; border-radius: 3px; }
.cat-color::-moz-color-swatch { border: none; border-radius: 3px; }
.cat-row {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 10px; border: 1px solid #d8cfbe; border-radius: 4px;
  margin-bottom: 6px; cursor: pointer; font-size: 0.85rem;
}
.cat-row.on { border-color: #4a6b4a; background: var(--bg-hover); }
.dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
.img-row {
  display: flex; align-items: center; gap: 8px;
  padding: 5px 8px; border-radius: 4px; cursor: pointer; margin-bottom: 4px;
}
.img-row.on { background: var(--bg-hover); }
.badge {
  min-width: 20px; text-align: center; font-size: 0.72rem; padding: 1px 5px;
  border-radius: 8px; background: #e8e6dc; color: #8a8175;
}
.badge.done { background: var(--bg-hover); color: #4a6b4a; }
.canvas-scroll {
  overflow: auto; max-height: 640px; border: 1px solid #d8cfbe; border-radius: 4px;
  background: #2a2622;
}
.canvas {
  position: relative; user-select: none; cursor: crosshair;
}
.canvas img { display: block; position: absolute; left: 0; top: 0; width: 100%; height: 100%; }
.overlay-canvas {
  position: absolute; left: 0; top: 0; pointer-events: none;
}
.cursor-canvas {
  position: absolute; left: 0; top: 0; pointer-events: none;
}
.class-mark {
  position: absolute; top: 8px; right: 8px;
  color: #fff; font-size: 0.78rem; padding: 3px 10px; border-radius: 4px;
  z-index: 2;
}
.ann-row {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 8px; border: 1px solid #d8cfbe; border-radius: 4px;
  margin-bottom: 4px; cursor: pointer;
}
.ann-row.on { border-color: #4a6b4a; background: var(--bg-hover); }
</style>

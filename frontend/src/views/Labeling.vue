<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton, NCheckbox, NColorPicker, NEmpty, NGi, NGrid, NIcon, NImage,
  NInput, NInputNumber, NRadioButton, NRadioGroup, NSelect, NSpin, NSwitch,
  useDialog, useMessage,
} from 'naive-ui'
import { api } from '../api'
import { hexToRGBA, pointInPolygon } from '../utils/labeling'
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
const samDragStart = ref(null)  // 区分单击 / 拖拽画框
const overlayCanvas = ref(null)
let overlayCtx = null
const fillMode = ref(true)
const samLoading = ref(false)
const newCatName = ref('')
const newCatColor = ref('#4E79A7')

// ---- mask 逐像素编辑 ----
const editingId = ref(null)

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

async function selectImage() {
  const im = images.value[imageIdx.value]
  if (!im) { currentImage.value = null; imgUrl.value = ''; anns.value = []; return }
  currentImage.value = im
  imgUrl.value = api.files.imageUrl(im.id)
  editingId.value = null
  polyPts.value = []
  polyPreview.value = null
  ellipseDrag.value = null
  await loadAnns()
  await nextTick()
  calcScale()
}

async function loadAnns() {
  if (!currentImage.value) { anns.value = []; return }
  anns.value = await api.annotations.list(currentImage.value.id)
  selected.value = null
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

function zoomBy(factor) {
  viewScale.value = Math.min(8, Math.max(0.2, viewScale.value * factor))
  updateDisplay()
}

function zoomReset() {
  viewScale.value = 1
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
    const step = 40  // 网格间距（图像像素），根据缩放自适应提密度
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
    if (a.type === 'mask' && d.points?.length) {
      ctx.beginPath()
      ctx.moveTo(d.points[0][0] * s, d.points[0][1] * s)
      for (let i = 1; i < d.points.length; i++) {
        ctx.lineTo(d.points[i][0] * s, d.points[i][1] * s)
      }
      ctx.closePath()
      if (fillMode.value) {
        ctx.fillStyle = hexToRGBA(color, 0.25)
        ctx.fill()
      }
      ctx.strokeStyle = isEdit ? '#e15759' : isSel ? '#1b365d' : color
      ctx.lineWidth = isSel || isEdit ? 3 : 1.5
      ctx.stroke()

      // 标签
      const bx = Math.min(...d.points.map(p => p[0])) * s
      const by = Math.min(...d.points.map(p => p[1])) * s
      _drawLabel(ctx, a.category_name, bx, by - 16, color)
    } else if (a.type === 'shield' && d.points?.length) {
      // 屏蔽区：虚线灰色区域，不参与训练
      ctx.beginPath()
      ctx.moveTo(d.points[0][0] * s, d.points[0][1] * s)
      for (let i = 1; i < d.points.length; i++) ctx.lineTo(d.points[i][0] * s, d.points[i][1] * s)
      ctx.closePath()
      ctx.fillStyle = 'rgba(138,129,117,0.18)'
      ctx.fill()
      ctx.strokeStyle = '#8a8175'
      ctx.lineWidth = 1.5
      ctx.setLineDash([6, 4])
      ctx.stroke()
      ctx.setLineDash([])
      const bx = Math.min(...d.points.map(p => p[0])) * s
      const by = Math.min(...d.points.map(p => p[1])) * s
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
  if (brushing.value) {
    const p = toImgCoord(e)
    brushRaw.push(p)
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
  if (panning.value) {
    panning.value = false
    panStart = null
    return
  }
  if (brushing.value) {
    brushing.value = false
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
  refreshBadge(1)
}

async function submitBrush() {
  if (brushRaw.length < 2) return
  if (!catId.value) return message.warning('请先选择缺陷类别')
  const pts = brushRaw.map(p => [p.x, p.y])
  try {
    if (editingId.value) {
      const r = await api.annotations.paint(editingId.value, {
        points: pts, brush_size: brushSize.value, erase: mode.value === 'eraser',
      })
      if (r.deleted) {
        anns.value = anns.value.filter(a => a.id !== editingId.value)
        editingId.value = null
        refreshBadge(-1)
      } else {
        const i = anns.value.findIndex(a => a.id === editingId.value)
        if (i >= 0) anns.value[i] = r
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
  } finally {
    brushRaw = []
    renderOverlay()
  }
}

// ---- 掩码命中检测（射线法，见 utils/labeling.js） ----

function hitMask(p, onlyId = null) {
  for (const a of anns.value) {
    if (a.type !== 'mask' && a.type !== 'shield') continue
    if (onlyId != null && a.id !== onlyId) continue
    const d = typeof a.data === 'string' ? JSON.parse(a.data || '{}') : (a.data || {})
    const pts = d.points || []
    if (pts.length < 3) continue
    if (pointInPolygon(p.x, p.y, pts)) return a.id
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
  } catch (err) {
    samPreview.value = []
  } finally {
    samLoading.value = false
    renderOverlay()
  }
}

async function confirmSam() {
  if (!catId.value) return message.warning('请先选择缺陷类别')
  if (!samPreview.value.length) return message.info('还没有预览结果，先画框或点击添加提示')
  const n = samPreview.value.length
  for (const pts of samPreview.value) {
    const a = await api.annotations.create({
      image_id: currentImage.value.id, category_id: catId.value,
      type: 'mask', data: { points: pts }, source: 'sam',
    })
    anns.value.push(a)
  }
  refreshBadge(n)
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
    } else {
      const a = await api.annotations.create({
        image_id: currentImage.value.id, category_id: catId.value, type: 'class', data: {}, source: 'manual',
      })
      anns.value.push(a)
      refreshBadge(1)
    }
  }
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
  if (e.ctrlKey || e.metaKey || e.altKey) return
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
          <div style="font-weight:600;margin-bottom:8px;font-size:0.9rem">缺陷类别</div>
          <div v-if="!categories.length" style="color:#8b2c1f;font-size:0.82rem;margin-bottom:6px">
            暂无类别，请先在数据集页添加
          </div>
          <div class="cat-row" v-for="c in categories" :key="c.id" @click="catId = c.id"
               :class="{ on: catId === c.id }">
            <n-color-picker v-model:value="c.color" size="small" :modes="['hex']" :show-alpha="false"
                            @complete="color => color && updateCatColor(c, color)" />
            <span style="flex:1;overflow:hidden;text-overflow:ellipsis">{{ c.name }}</span>
            <n-button text size="small" type="error" @click.stop="removeCat(c)"><n-icon><Close /></n-icon></n-button>
          </div>
          <div style="display:flex;gap:6px;margin-top:10px;align-items:center">
            <n-color-picker v-model:value="newCatColor" size="small" :modes="['hex']" :show-alpha="false" />
            <n-input v-model:value="newCatName" placeholder="新建标签" size="small" @keyup.enter="addNewCat" />
            <n-button size="small" type="primary" @click="addNewCat"><n-icon><Plus /></n-icon></n-button>
          </div>
          <div style="color:#8a8175;font-size:0.75rem;margin-top:6px">
            类别属于当前数据集（{{ current?.name }}），删除后标注将变为未分类
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
              {{ mode === 'box' ? '拖拽画框 · 热键 B · 点击框可选中，Delete 删除' :
                 mode === 'polygon' ? '左键单击加点 · 热键 P · 完成按钮/双击闭合，Esc 取消' :
                 mode === 'ellipse' ? '拖拽画椭圆 · 热键 E · 松手生成掩码' :
                 mode === 'class' ? '点击图像设置整图类别 · 热键 C' :
                 mode === 'sam' ? '拖拽画框 · 热键 S · 左键加正点，右键加负点，确认生成掩码' :
                 mode === 'pan' ? '按住左键拖拽平移 · 热键 M · 中键平移，滚轮缩放' :
                 mode === 'eraser' ? '橡皮擦：按住涂抹擦除 · 热键 X · Shift+滚轮调大小' :
                 mode === 'shield' ? '掩膜：涂抹屏蔽区 · 热键 H · 该区域不参与训练，橡皮擦可擦除' :
                 '画笔：拖到哪画到哪 · 热键 R · Shift+滚轮调粗细，松手成掩码' }}
            </span>
            <span v-if="mode === 'brush' || mode === 'eraser'" style="display:flex;align-items:center;gap:6px">
              <span style="font-size:0.8rem;color:#4a433c">{{ mode === 'eraser' ? '橡皮' : '笔刷' }}</span>
              <n-input-number v-model:value="brushSize" :min="1" :max="100" :step="1" size="small" style="width:90px" />
            </span>
            <span v-if="editingId" style="color:#e15759;font-size:0.8rem">● 编辑中</span>
            <span v-if="samLoading" style="color:#4a6b4a;font-size:0.8rem">SAM 推理中…</span>
            <div style="flex:1"></div>
            <span style="font-size:0.8rem;color:#8a8175">
              坐标 {{ gridPos ? `(${gridPos.x}, ${gridPos.y})` : '(--, --)' }}
            </span>
            <n-button size="small" :title="showGrid ? '隐藏参考网格 (G)' : '显示参考网格 (G)'"
                       @click="showGrid = !showGrid">{{ showGrid ? '格' : '格' }}</n-button>
            <span style="font-size:0.8rem;color:#8a8175">{{ zoomLabel }}</span>
            <n-button size="small" @click="zoomBy(1.25)"><n-icon><ZoomIn /></n-icon></n-button>
            <n-button size="small" @click="zoomBy(0.8)"><n-icon><ZoomOut /></n-icon></n-button>
            <n-button size="small" @click="zoomReset"><n-icon><FullScreen /></n-icon><span style="margin-left:3px">适应</span></n-button>
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

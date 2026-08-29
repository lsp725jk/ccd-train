<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NInput, NEmpty } from 'naive-ui'
import { api } from '../api'

const route = useRoute()
const enabled = ref(false)
const marks = ref([])
const drawing = ref(null)          // {x0,y0,x1,y1}（视口像素）
const pending = ref(null)          // {rect, comment}
const listOpen = ref(false)

// ---- 浮动按钮：可拖动 / 可隐藏（位置与隐藏状态持久化） ----
const LS_POS = 'ccd-review-pos'
const LS_HIDDEN = 'ccd-review-hidden'
const posX = ref(window.innerWidth - 180)
const posY = ref(window.innerHeight - 70)
const hidden = ref(false)
const dragState = ref(null)        // {sx, sy, ox, oy, origin}
let _moved = false

function clampPos() {
  posX.value = Math.max(4, Math.min(posX.value, window.innerWidth - 64))
  posY.value = Math.max(4, Math.min(posY.value, window.innerHeight - 44))
}
function loadPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem(LS_POS) || 'null')
    if (Array.isArray(p)) { posX.value = p[0]; posY.value = p[1] }
    hidden.value = localStorage.getItem(LS_HIDDEN) === '1'
  } catch { /* ignore */ }
  clampPos()
}
function persistPrefs() {
  try {
    localStorage.setItem(LS_POS, JSON.stringify([Math.round(posX.value), Math.round(posY.value)]))
    localStorage.setItem(LS_HIDDEN, hidden.value ? '1' : '0')
  } catch { /* ignore */ }
}

function onFabDown(e) {
  if (e.button !== 0) return
  dragState.value = {
    sx: e.clientX, sy: e.clientY,
    ox: posX.value, oy: posY.value,
    origin: e.currentTarget.dataset.origin || 'fab',
  }
  _moved = false
  window.addEventListener('mousemove', onFabMove)
  window.addEventListener('mouseup', onFabUp)
  e.preventDefault()
}
function onFabMove(e) {
  if (!dragState.value) return
  const dx = e.clientX - dragState.value.sx
  const dy = e.clientY - dragState.value.sy
  if (Math.abs(dx) > 3 || Math.abs(dy) > 3) _moved = true
  if (_moved) {
    posX.value = Math.max(4, Math.min(dragState.value.ox + dx, window.innerWidth - 64))
    posY.value = Math.max(4, Math.min(dragState.value.oy + dy, window.innerHeight - 44))
  }
}
function onFabUp() {
  window.removeEventListener('mousemove', onFabMove)
  window.removeEventListener('mouseup', onFabUp)
  const origin = dragState.value?.origin || 'fab'
  const wasDrag = _moved
  dragState.value = null
  _moved = false
  if (wasDrag) { persistPrefs(); return }   // 拖动：仅保存位置
  // 单击：主按钮切换框选；小圆点恢复显示
  if (origin === 'dot') { hidden.value = false; persistPrefs() }
  else { enabled.value = !enabled.value }
}
function hideFab() { hidden.value = true; enabled.value = false; persistPrefs() }

// 用 route.path（不含 query）作标注键：App 刷新按钮的 _t query 不影响匹配（P1 修复）
const currentRouteMarks = computed(() =>
  marks.value.filter(m => m.route === route.path))

async function load() {
  try { marks.value = await api.review.list() } catch { marks.value = [] }
}
onMounted(() => { load(); loadPrefs(); window.addEventListener('resize', clampPos) })
onUnmounted(() => window.removeEventListener('resize', clampPos))

function onDown(e) {
  if (!enabled.value || pending.value) return
  e.preventDefault()
  drawing.value = { x0: e.clientX, y0: e.clientY, x1: e.clientX, y1: e.clientY }
}
function onMove(e) {
  if (!drawing.value) return
  drawing.value.x1 = e.clientX
  drawing.value.y1 = e.clientY
}
function onUp() {
  if (!drawing.value) return
  const { x0, y0, x1, y1 } = drawing.value
  drawing.value = null
  if (Math.abs(x1 - x0) < 8 || Math.abs(y1 - y0) < 8) return
  pending.value = { rect: { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) }, comment: '' }
}

async function saveMark() {
  if (!pending.value) return
  const p = pending.value
  pending.value = null
  const vw = window.innerWidth, vh = window.innerHeight
  try {
    await api.review.create({
      route: route.path,
      project_id: route.params.pid ? Number(route.params.pid) : null,
      comment: p.comment.trim(),
      rects: [{
        x: +(p.rect.x / vw * 100).toFixed(2),
        y: +(p.rect.y / vh * 100).toFixed(2),
        w: +(p.rect.w / vw * 100).toFixed(2),
        h: +(p.rect.h / vh * 100).toFixed(2),
      }],
      viewport: [vw, vh],
    })
    await load()
    listOpen.value = true
  } catch { /* api 错误由拦截器提示 */ }
}

async function removeMark(id) {
  try { await api.review.remove(id) } catch { /* ignore */ }
  await load()
}

function fmt(m) {
  const p = m.project_id ? `项目#${m.project_id} · ` : ''
  return `${p}${m.route} · ${m.rects.length} 个框`
}

/** 把标注映射为当前页面的百分比定位（供用户在已标注页上查看） */
const overlayMarks = computed(() => {
  if (!enabled.value) return []
  return currentRouteMarks.value.map(m => ({
    id: m.id,
    comment: m.comment || '(未留言)',
    rects: m.rects || [],
  }))
})

/** 留言弹窗定位（视口内自动避让右下角） */
const pendingStyle = computed(() => {
  if (!pending.value) return {}
  const r = pending.value.rect
  const vw = window.innerWidth, vh = window.innerHeight
  return {
    left: Math.min(r.x + r.w, vw - 280) + 'px',
    top: Math.min(r.y + r.h + 8, vh - 160) + 'px',
  }
})
</script>

<template>
  <!-- 浮动开关：可拖动（按住拖到任意位置）、可隐藏（— 收起为小圆点） -->
  <div v-if="!hidden" class="fab-wrap" :style="{ left: posX + 'px', top: posY + 'px' }"
       data-origin="fab" @mousedown="onFabDown" @mouseup="onFabUp" @dblclick.prevent>
    <button class="review-fab" :class="{ on: enabled }" type="button" tabindex="0"
            :title="enabled ? '关闭框选' : '开启框选（按住左键拖拽框选区域）'"
            @keydown.enter.prevent="enabled = !enabled">
      <span class="fab-icon">▣</span>
      <span class="fab-text">{{ enabled ? '框选中…' : '框选评审' }}</span>
    </button>
    <button class="fab-hide" type="button" title="隐藏（需要时点小圆点恢复）"
            @mousedown.stop @click.stop="hideFab">—</button>
  </div>
  <!-- 隐藏后的小圆点（可拖动，单击恢复） -->
  <div v-else class="fab-dot" :style="{ left: posX + 'px', top: posY + 'px' }"
       data-origin="dot" title="显示框选评审" @mousedown="onFabDown" @mouseup="onFabUp">▣</div>

  <!-- 框选层 -->
  <div v-if="enabled" class="review-layer"
       @mousedown="onDown" @mousemove="onMove" @mouseup="onUp" @contextmenu.prevent>
    <!-- 已保存标注（当前页） -->
    <template v-for="m in overlayMarks" :key="m.id">
      <div v-for="(r, i) in m.rects" :key="i" class="review-mark" :style="{ left: r.x + '%', top: r.y + '%', width: r.w + '%', height: r.h + '%' }">
        <span class="review-mark-tag" :title="m.comment">{{ m.comment.slice(0, 24) }}</span>
      </div>
    </template>
    <!-- 正在画 -->
    <div v-if="drawing" class="review-draw"
         :style="{ left: Math.min(drawing.x0, drawing.x1) + 'px', top: Math.min(drawing.y0, drawing.y1) + 'px',
                   width: Math.abs(drawing.x1 - drawing.x0) + 'px', height: Math.abs(drawing.y1 - drawing.y0) + 'px' }"></div>
    <!-- 留言弹窗 -->
    <div v-if="pending" class="review-pop" :style="pendingStyle">
      <div class="review-pop-title">框选区域 — 填写要改什么</div>
      <n-input v-model:value="pending.comment" type="textarea" :rows="3"
               placeholder="例如：这个表格列太挤 / 按钮应改到右上角 / 布局不对，应分两列…" />
      <div class="review-pop-actions">
        <n-button size="small" @click="pending = null">取消</n-button>
        <n-button size="small" type="primary" @click="saveMark">保存标注</n-button>
      </div>
    </div>
  </div>

  <!-- 标注列表 -->
  <div v-if="listOpen && enabled" class="review-list">
    <div class="review-list-head">
      <span>评审标注</span>
      <n-button text size="tiny" @click="listOpen = false">收起</n-button>
    </div>
    <n-empty v-if="!marks.length" description="还没有标注" size="tiny" style="padding:12px 0" />
    <div v-for="m in marks" :key="m.id" class="review-item">
      <div class="review-item-info">
        <div class="review-item-comment">{{ m.comment || '(未留言)' }}</div>
        <div class="review-item-meta">{{ fmt(m) }} · {{ m.created_at }}</div>
      </div>
      <n-button text size="tiny" type="error" @click="removeMark(m.id)">删除</n-button>
    </div>
  </div>
</template>

<style scoped>
.fab-wrap {
  position: fixed; z-index: 20000;
  display: flex; align-items: center; gap: 6px;
  cursor: grab; user-select: none; touch-action: none;
}
.fab-wrap:active { cursor: grabbing; }
.review-fab {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 14px; border: 1px solid var(--border);
  border-radius: 999px; cursor: pointer;
  background: var(--bg-surface); color: var(--text-color);
  box-shadow: 0 4px 14px rgba(0,0,0,0.15);
  transition: all .15s ease;
  font-size: 0.85rem;
}
.review-fab.on { background: var(--el-color-primary); color: #fff; border-color: transparent; }
.fab-icon { font-size: 1rem; }
.fab-hide {
  width: 22px; height: 22px; border-radius: 50%;
  border: 1px solid var(--border); background: var(--bg-surface);
  color: var(--text-muted); font-size: 0.9rem; line-height: 1;
  cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 6px rgba(0,0,0,0.12);
}
.fab-hide:hover { color: var(--el-color-primary); border-color: var(--el-color-primary); }
.fab-dot {
  position: fixed; z-index: 20000;
  width: 30px; height: 30px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg-surface); border: 1px solid var(--border);
  color: var(--el-color-primary); font-size: 0.85rem;
  box-shadow: 0 4px 14px rgba(0,0,0,0.18);
  cursor: grab; user-select: none; touch-action: none;
}
.fab-dot:active { cursor: grabbing; }

.review-layer { position: fixed; inset: 0; z-index: 19999; cursor: crosshair; }
.review-draw {
  position: fixed; border: 2px dashed #4a90d9; background: rgba(74,144,217,.15); z-index: 20001;
  pointer-events: none;
}
.review-mark {
  position: fixed; border: 2px solid rgba(201,84,78,.8); z-index: 20001;
  pointer-events: none; background: rgba(201,84,78,.08);
}
.review-mark-tag {
  position: absolute; left: 0; top: -20px; max-width: 100%;
  background: rgba(201,84,78,.92); color: #fff; font-size: .72rem;
  padding: 1px 6px; border-radius: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.review-pop {
  position: fixed; z-index: 20002; width: 260px;
  background: var(--bg-surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 10px; box-shadow: 0 8px 24px rgba(0,0,0,.2);
}
.review-pop-title { font-size: .82rem; font-weight: 600; margin-bottom: 6px; }
.review-pop-actions { display: flex; justify-content: flex-end; gap: 6px; margin-top: 8px; }

.review-list {
  position: fixed; left: 16px; bottom: 16px; z-index: 20000;
  width: 320px; max-height: 40vh; overflow: auto;
  background: var(--bg-surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 10px; box-shadow: 0 8px 24px rgba(0,0,0,.2);
}
.review-list-head { display: flex; justify-content: space-between; align-items: center; font-weight: 600; font-size: .85rem; }
.review-item { display: flex; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--border); }
.review-item-info { flex: 1; min-width: 0; }
.review-item-comment { font-size: .8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.review-item-meta { font-size: .7rem; color: var(--text-muted); }
</style>

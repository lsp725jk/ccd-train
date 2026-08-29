<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import echarts from '../utils/echarts'
import { NSelect, NEmpty } from 'naive-ui'
import { api } from '../api'
import { isDark, onThemeChange } from '../utils/theme'

const route = useRoute()
const pid = Number(route.params.pid)

const tasks = ref([])
const selectedIds = ref([])
const metric = ref('mAP50')
const curves = ref({})       // task_id -> {columns, rows}
const chartEl = ref(null)
let chart = null

const METRIC_LABELS = {
  mAP50: 'mAP50', 'mAP50-95': 'mAP50-95', precision: '精度', recall: '召回',
  accuracy: '准确率', iou: 'mIoU', train_loss: '训练损失', val_loss: '验证损失',
}

// 所有选中任务可用的指标并集
const availableMetrics = computed(() => {
  const cols = new Set()
  for (const id of selectedIds.value) {
    const c = curves.value[id]
    if (c?.columns) c.columns.slice(1).forEach(col => cols.add(col))
  }
  return [...cols]
})

const taskOptions = computed(() => tasks.value.map(t => ({ label: `${t.model_name} (#${t.id})`, value: t.id })))
const metricOptions = computed(() => availableMetrics.value.map(m => ({ label: METRIC_LABELS[m] || m, value: m })))

watch(metric, (m) => {
  if (m && !availableMetrics.value.includes(m)) metric.value = availableMetrics.value[0] || 'mAP50'
})

async function loadTasks() {
  tasks.value = await api.train.list(pid)
}

async function loadCurve(id) {
  curves.value[id] = await api.train.curve(id)
}

async function onSelect() {
  // 拉取选中任务的曲线
  for (const id of selectedIds.value) {
    if (!curves.value[id]) await loadCurve(id)
  }
  // 移除未选中的缓存
  for (const id of Object.keys(curves.value)) {
    if (!selectedIds.value.includes(Number(id))) delete curves.value[id]
  }
  if (metric.value && !availableMetrics.value.includes(metric.value)) {
    metric.value = availableMetrics.value[0] || 'mAP50'
  }
  render()
}

function render() {
  if (!chart) return
  const series = []
  const allEpochs = new Set()
  const dataByTask = {}
  for (const id of selectedIds.value) {
    const c = curves.value[id]
    if (!c?.rows?.length) continue
    const ci = c.columns.indexOf('epoch')
    const mi = c.columns.indexOf(metric.value)
    if (mi < 0) continue
    const task = tasks.value.find(t => t.id === Number(id))
    const name = task ? `${task.model_name} (#${id})` : `#${id}`
    const points = []
    for (const r of c.rows) {
      const e = r[ci]
      const v = r[mi]
      allEpochs.add(e)
      if (v !== '' && v != null) points.push([e, Number(v)])
    }
    dataByTask[name] = points
  }
  for (const [name, points] of Object.entries(dataByTask)) {
    series.push({ name, type: 'line', smooth: true, showSymbol: false, lineStyle: { width: 2 }, data: points })
  }
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', bottom: 0, textStyle: { fontSize: 11 } },
    grid: { left: 50, right: 20, top: 30, bottom: 40 },
    xAxis: { type: 'value', name: 'epoch', min: 1 },
    yAxis: { type: 'value', name: METRIC_LABELS[metric.value] || metric.value, splitLine: { lineStyle: { color: isDark() ? '#3a423c' : '#e8e6dc' } } },
    series,
  }, { notMerge: true })
}

let offTheme = null
function initChart() {
  chart?.dispose()
  chart = echarts.init(chartEl.value, isDark() ? 'dark' : undefined)
  render()
}
function onResize() { chart?.resize() }

onMounted(async () => {
  await loadTasks()
  initChart()
  window.addEventListener('resize', onResize)
  offTheme = onThemeChange(() => initChart())
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  offTheme && offTheme()
  chart?.dispose()
  chart = null
})

watch(selectedIds, onSelect)
watch(metric, render)
</script>

<template>
  <div>
    <div class="page-head">
      <h2>训练曲线对比</h2>
    </div>

    <div class="card" style="margin-bottom:14px">
      <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
        <span style="font-size:0.85rem;color:#4a433c">任务</span>
        <n-select v-model:value="selectedIds" multiple :max-tag-count="1" :options="taskOptions"
                  style="width:360px" placeholder="选择要对比的训练任务" />
        <span style="font-size:0.85rem;color:#4a433c">指标</span>
        <n-select v-model:value="metric" :options="metricOptions" style="width:150px" />
        <span style="color:#8a8175;font-size:0.8rem">多选任务可同图对比，横轴为 epoch</span>
      </div>
    </div>

    <div class="card">
      <div ref="chartEl" style="width:100%;height:480px"></div>
      <n-empty v-if="!selectedIds.length" description="选择任务开始对比" :image-size="60" style="margin-top:-480px;pointer-events:none" />
    </div>
  </div>
</template>

<script setup>
import { computed, h, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton, NDataTable, NTag, NSelect, NEmpty, NImage, NImageGroup,
  useMessage, useDialog,
} from 'naive-ui'
import { api } from '../api'
import { friendlyName } from '../utils/format'

const route = useRoute()
const pid = Number(route.params.pid)
const message = useMessage()
const dialog = useDialog()

const models = ref([])
const selected = ref(null)
const result = ref(null)
const loading = ref(false)
const genLoading = ref(false)

const taskLabels = {
  detect: '检测', segment: '分割', classify: '分类',
  us_classify: '非监督分类', us_segment: '异常检测',
}

const METRIC_ORDER = ['mAP50', 'mAP50-95', 'precision', 'recall', 'top1_acc', 'mIoU', 'pixel_acc', 'auroc_image']
const METRIC_LABELS = {
  mAP50: 'mAP50', 'mAP50-95': 'mAP50-95', precision: '精度', recall: '召回',
  top1_acc: 'Top1 准确率', mIoU: 'mIoU', pixel_acc: '像素准确率', auroc_image: 'AUROC',
}

// 预测明细展开（用图像下标选中，NSelect 的 value 需为 string/number）
const expandIndex = ref(null)
const selectOptions = computed(() => (result.value?.predictions || []).map((p, i) => ({
  label: `${p.image}（${(p.boxes || p.regions || []).length} 个目标）`,
  value: i,
})))
const expandRows = computed(() => {
  const pred = expandIndex.value != null ? (result.value?.predictions || [])[expandIndex.value] : null
  if (!pred) return []
  const items = pred.boxes || pred.regions || []
  return items.map((b, i) => ({
    idx: i + 1,
    category: b.category || '-',
    confidence: b.confidence != null ? b.confidence : (b.score != null ? b.score : '-'),
    score: b.score != null ? b.score : '-',
    bbox: b.bbox ? `(${b.bbox[0]}, ${b.bbox[1]}) → (${b.bbox[2]}, ${b.bbox[3]})` : '-',
    area_px: b.area_px != null ? b.area_px : '-',
    area_ratio: b.area_ratio != null ? b.area_ratio + '%' : '-',
    center: b.center ? `(${b.center[0]}, ${b.center[1]})` : '-',
  }))
})
const predSummary = computed(() => {
  if (!result.value?.predictions?.length) return null
  const total = result.value.predictions.reduce((s, p) => s + ((p.boxes || p.regions || []).length), 0)
  return { images: result.value.predictions.length, total }
})

async function load() {
  loading.value = true
  try {
    models.value = await api.models.list(pid)
    if (!selected.value && models.value.length) {
      selected.value = models.value[0]
      await loadResult()
    }
  } finally { loading.value = false }
}

onMounted(load)

function parseMetrics(row) {
  try { return JSON.parse(row.metrics || '{}') } catch { return {} }
}

function metricOf(row, key) {
  const m = parseMetrics(row)
  return m[key] != null ? m[key] : '-'
}

async function loadResult() {
  if (!selected.value) { result.value = null; return }
  result.value = await api.models.result(selected.value.id)
}

async function pick(row) {
  selected.value = row
  await loadResult()
}

async function genDetails(row) {
  /** 用已有权重对测试集重跑推理，补生成预测明细（旧任务无 predictions.json 时用）。 */
  genLoading.value = true
  try {
    const r = await api.models.predictDetails(row.id)
    message.success(`已生成 ${r.images} 张图、${r.targets} 个目标的预测明细`)
    if (selected.value?.id === row.id) await loadResult()
  } catch (e) {
    message.error(String(e.response?.data?.detail || e.message).slice(0, 200))
  } finally {
    genLoading.value = false
  }
}

async function markBest(row) {
  await api.models.markBest(row.id)
  message.success(`「${row.name}」已标记为最佳模型`)
  load()
}

function remove(row) {
  dialog.warning({
    title: '确认删除',
    content: `删除模型「${row.name}」？`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      await api.models.remove(row.id)
      message.success('已删除')
      if (selected.value?.id === row.id) { selected.value = null; result.value = null }
      load()
    },
  })
}

const modelColumns = computed(() => {
  const gen = genLoading.value
  return [
  {
    title: '模型', key: 'name', minWidth: 160,
    render: (row) => h('div', { style: 'display:flex;align-items:center;gap:6px' }, [
      h('span', { style: 'font-weight:500' }, friendlyName(row.name)),
      row.is_best ? h(NTag, { size: 'small', type: 'success', bordered: false }, { default: () => '最佳' }) : null,
    ]),
  },
  {
    title: '任务', key: 'task_type', width: 100,
    render: (row) => taskLabels[row.task_type] || row.task_type,
  },
  {
    title: '引擎', key: 'engine', width: 110,
    render: (row) => row.architecture || row.engine,
  },
  ...METRIC_ORDER.map((mk) => ({
    title: METRIC_LABELS[mk], key: mk, width: 100,
    render: (row) => metricOf(row, mk),
  })),
  {
    title: '操作', key: 'actions', width: 180, align: 'center',
    render: (row) => h('div', { style: 'display:flex;justify-content:center;gap:2px' }, [
      !row.is_best
        ? h(NButton, { size: 'small', text: true, type: 'primary', onClick: (e) => { e.stopPropagation(); markBest(row) } }, { default: () => '设最佳' })
        : null,
      h(NButton, { size: 'small', text: true, loading: gen, onClick: (e) => { e.stopPropagation(); genDetails(row) } }, { default: () => '生成明细' }),
      h(NButton, { size: 'small', text: true, type: 'error', onClick: (e) => { e.stopPropagation(); remove(row) } }, { default: () => '删除' }),
    ]),
  },
  ]
})

const predictionColumns = [
  { title: '#', key: 'idx', width: 50 },
  { title: '类型', key: 'category', width: 110 },
  { title: '置信度', key: 'confidence', width: 90 },
  { title: '得分', key: 'score', width: 80 },
  { title: '位置 (x1,y1)→(x2,y2)', key: 'bbox', minWidth: 220 },
  { title: '中心点', key: 'center', width: 130 },
  { title: '面积(px)', key: 'area_px', width: 90 },
  { title: '面积占比', key: 'area_ratio', width: 90 },
]
</script>

<template>
  <div>
    <div class="page-head">
      <h2>训练效果</h2>
    </div>

    <n-data-table :data="models" :columns="modelColumns" :loading="loading" class="card"
                  style="margin-bottom:14px"
                  :row-props="(row) => ({ style: selected && selected.id === row.id ? 'cursor:pointer;background:var(--bg-hover)' : 'cursor:pointer', onClick: () => pick(row) })" />

    <div class="card">
      <div style="font-weight:600;margin-bottom:10px;font-size:0.95rem">
        {{ selected ? `${friendlyName(selected.name)} 可视化` : '选择模型查看可视化' }}
      </div>
      <n-image-group v-if="result?.viz?.length">
        <div class="viz-grid">
          <n-image v-for="v in result.viz" :key="v" :src="v" object-fit="contain"
                   style="width:100%;height:220px;border:1px solid var(--border);border-radius:4px" />
        </div>
      </n-image-group>
      <n-empty v-else description="选中模型后展示评估可视化（PR 曲线、混淆矩阵、预测画廊）" :image-size="70" />
    </div>

    <!-- 预测明细：类型 / 位置 / 置信度 / 得分 / 面积 -->
    <div class="card" style="margin-top:14px">
      <div style="font-weight:600;margin-bottom:10px;font-size:0.95rem">
        预测明细
        <span v-if="predSummary" style="color:var(--text-muted);font-weight:400;font-size:0.8rem;margin-left:8px">
          {{ predSummary.images }} 张图 · {{ predSummary.total }} 个目标
        </span>
      </div>
      <template v-if="result?.predictions?.length">
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
          <n-select v-model:value="expandIndex" :options="selectOptions" filterable
                    placeholder="选择图像查看预测明细" style="width:320px" />
        </div>
        <n-data-table v-if="expandRows.length" :data="expandRows" :columns="predictionColumns"
                      size="small" :bordered="true" style="width:100%" />
        <n-empty v-else description="选择图像查看该图的预测框 / 分割区域" :image-size="50" />
      </template>
      <template v-else>
        <n-empty description="评估完成后展示结构化预测明细（类型、位置、置信度、面积）" :image-size="70">
          <n-button type="primary" :loading="genLoading" @click="selected && genDetails(selected)">
            用当前模型生成预测明细
          </n-button>
        </n-empty>
      </template>
    </div>
  </div>
</template>

<style scoped>
.viz-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
</style>

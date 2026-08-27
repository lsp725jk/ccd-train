<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { friendlyName } from '../utils/format'

const route = useRoute()
const pid = Number(route.params.pid)

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

// 预测明细展开
const expandImage = ref(null)
const expandRows = computed(() => {
  if (!expandImage.value) return []
  const items = expandImage.value.boxes || expandImage.value.regions || []
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
    ElMessage.success(`已生成 ${r.images} 张图、${r.targets} 个目标的预测明细`)
    if (selected.value?.id === row.id) await loadResult()
  } catch (e) {
    ElMessage.error(String(e.response?.data?.detail || e.message).slice(0, 200))
  } finally {
    genLoading.value = false
  }
}

async function markBest(row) {
  await api.models.markBest(row.id)
  ElMessage.success(`「${row.name}」已标记为最佳模型`)
  load()
}

async function remove(row) {
  await ElMessageBox.confirm(`删除模型「${row.name}」？`, '确认删除', { type: 'warning' })
  await api.models.remove(row.id)
  if (selected.value?.id === row.id) { selected.value = null; result.value = null }
  load()
}
</script>

<template>
  <div>
    <div class="page-head">
      <h2>训练效果</h2>
    </div>

    <el-table :data="models" v-loading="loading" class="card" highlight-current-row
              @current-change="pick" style="margin-bottom:14px">
      <el-table-column label="模型" min-width="160">
        <template #default="{ row }">
          <div style="display:flex;align-items:center;gap:6px">
            <span style="font-weight:500">{{ friendlyName(row.name) }}</span>
            <el-tag v-if="row.is_best" size="small" type="success" effect="plain">最佳</el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="任务" width="100">
        <template #default="{ row }">{{ taskLabels[row.task_type] || row.task_type }}</template>
      </el-table-column>
      <el-table-column label="引擎" width="110">
        <template #default="{ row }">{{ row.architecture || row.engine }}</template>
      </el-table-column>
      <el-table-column v-for="mk in METRIC_ORDER" :key="mk" :label="METRIC_LABELS[mk]" width="100">
        <template #default="{ row }">{{ metricOf(row, mk) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180" align="center">
        <template #default="{ row }">
          <el-button v-if="!row.is_best" link type="primary" @click.stop="markBest(row)">设最佳</el-button>
          <el-button link :loading="genLoading" @click.stop="genDetails(row)">生成明细</el-button>
          <el-button link type="danger" @click.stop="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="card">
      <div style="font-weight:600;margin-bottom:10px;font-size:0.95rem">
        {{ selected ? `${selected.name} 可视化` : '选择模型查看可视化' }}
      </div>
      <template v-if="result?.viz?.length">
        <div class="viz-grid">
          <el-image v-for="v in result.viz" :key="v" :src="v" :preview-src-list="result.viz"
                    fit="contain" style="width:100%;height:220px;border:1px solid #d8cfbe;border-radius:4px" />
        </div>
      </template>
      <el-empty v-else description="选中模型后展示评估可视化（PR 曲线、混淆矩阵、预测画廊）" :image-size="70" />
    </div>

    <!-- 预测明细：类型 / 位置 / 置信度 / 得分 / 面积 -->
    <div class="card" style="margin-top:14px">
      <div style="font-weight:600;margin-bottom:10px;font-size:0.95rem">
        预测明细
        <span v-if="predSummary" style="color:#8a8175;font-weight:400;font-size:0.8rem;margin-left:8px">
          {{ predSummary.images }} 张图 · {{ predSummary.total }} 个目标
        </span>
      </div>
      <template v-if="result?.predictions?.length">
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
          <el-select v-model="expandImage" placeholder="选择图像查看预测明细" style="width:320px" filterable>
            <el-option v-for="(p, i) in result.predictions" :key="i" :value="p"
                       :label="`${p.image}（${(p.boxes || p.regions || []).length} 个目标）`" />
          </el-select>
        </div>
        <el-table v-if="expandRows.length" :data="expandRows" border size="small"
                  style="width:100%">
          <el-table-column label="#" prop="idx" width="50" />
          <el-table-column label="类型" prop="category" width="110" />
          <el-table-column label="置信度" prop="confidence" width="90" />
          <el-table-column label="得分" prop="score" width="80" />
          <el-table-column label="位置 (x1,y1)→(x2,y2)" prop="bbox" min-width="220" />
          <el-table-column label="中心点" prop="center" width="130" />
          <el-table-column label="面积(px)" prop="area_px" width="90" />
          <el-table-column label="面积占比" prop="area_ratio" width="90" />
        </el-table>
        <el-empty v-else description="选择图像查看该图的预测框 / 分割区域" :image-size="50" />
      </template>
      <template v-else>
        <el-empty description="评估完成后展示结构化预测明细（类型、位置、置信度、面积）" :image-size="70">
          <el-button type="primary" :loading="genLoading" @click="selected && genDetails(selected)">
            用当前模型生成预测明细
          </el-button>
        </el-empty>
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

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { NSelect, NInputNumber, NButton, NSwitch, NEmpty, NImage, useMessage } from 'naive-ui'
import { api } from '../api'

const route = useRoute()
const pid = Number(route.params.pid)
const message = useMessage()

const datasets = ref([])
const categories = ref([])
const datasetId = ref(null)
const k = ref(6)
const running = ref(false)
const result = ref(null)
const meta = ref({})        // cluster_id -> { category_id, ignored }
const applying = ref(false)

const datasetOptions = computed(() => datasets.value.map(d => ({ label: `${d.name}（${d.image_count} 张）`, value: d.id })))
const categoryOptions = computed(() => categories.value.map(cat => ({ label: cat.name, value: cat.id })))

async function loadBase() {
  datasets.value = await api.datasets.list(pid)
  if (!datasetId.value && datasets.value.length) datasetId.value = datasets.value[0].id
}
// 类别按数据集隔离：切换数据集时重新加载该集的缺陷类别，并清空旧的聚类结果
watch(datasetId, async () => {
  result.value = null
  try { categories.value = await api.projects.datasetCategories(datasetId.value) }
  catch { categories.value = [] }
})
onMounted(loadBase)

function resetMeta() {
  meta.value = {}
  if (result.value) {
    for (const c of result.value.clusters) meta.value[c.id] = { category_id: null, ignored: false }
  }
}

async function run() {
  if (!datasetId.value) return message.warning('请选择数据集')
  running.value = true
  try {
    result.value = await api.cluster.run({ dataset_id: datasetId.value, k: k.value })
    resetMeta()
    message.success(`聚类完成，共 ${result.value.total} 张图像`)
  } catch (e) {
    message.error(String(e.response?.data?.detail || e.message).slice(0, 200))
  } finally {
    running.value = false
  }
}

function clusterImages(c) {
  // 该聚类包含的全部图像（从 assignments 反查）
  if (!result.value) return []
  return Object.entries(result.value.assignments)
    .filter(([, cl]) => cl === c.id)
    .map(([iid]) => Number(iid))
}

async function apply() {
  const assignments = {}
  let named = 0
  for (const c of result.value.clusters) {
    const m = meta.value[c.id]
    if (!m || m.ignored || !m.category_id) continue
    for (const iid of clusterImages(c)) assignments[iid] = m.category_id
    named++
  }
  if (!named) return message.warning('请先为至少一个聚类选择类别')
  if (!Object.keys(assignments).length) return message.warning('没有可生成的标注')
  applying.value = true
  try {
    const r = await api.cluster.apply({ assignments })
    message.success(`已生成 ${r.created} 条伪标注，可在标注工作台查看修正`)
  } finally {
    applying.value = false
  }
}

const fmtSample = (iid) => api.files.imageUrl(iid)
</script>

<template>
  <div>
    <div class="page-head">
      <h2>非监督分类（聚类伪标签）</h2>
    </div>

    <div class="card" style="margin-bottom:14px">
      <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
        <span style="font-size:0.85rem;color:#4a433c">数据集</span>
        <n-select v-model:value="datasetId" :options="datasetOptions" style="width:180px" />
        <span style="font-size:0.85rem;color:#4a433c">聚类数</span>
        <n-input-number v-model:value="k" :min="2" :max="50" style="width:110px" />
        <n-button type="primary" :loading="running" @click="run">运行聚类</n-button>
        <span style="color:#8a8175;font-size:0.8rem">
          无需标注，按图像特征自动分组；为聚类命名后生成伪标注，可作为分类训练数据
        </span>
      </div>
    </div>

    <template v-if="result">
      <div class="card" style="margin-bottom:14px;display:flex;justify-content:space-between;align-items:center">
        <span style="font-size:0.9rem;color:#4a433c">
          {{ result.total }} 张图像 → {{ result.clusters.length }} 个聚类
        </span>
        <n-button type="success" :loading="applying" @click="apply">生成伪标注</n-button>
      </div>

      <div class="cluster-grid">
        <div v-for="c in result.clusters" :key="c.id" class="cluster-card card"
             :class="{ ignored: meta[c.id]?.ignored }">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span style="font-weight:600;font-size:0.9rem">聚类 {{ c.id }} <span style="color:#8a8175;font-weight:400">（{{ c.size }} 张）</span></span>
            <div style="display:flex;align-items:center;gap:6px">
              <n-switch v-model:value="meta[c.id].ignored" size="small" />
              <span style="font-size:0.78rem;color:var(--text-muted)">忽略</span>
            </div>
          </div>
          <div class="sample-grid">
            <n-image v-for="iid in c.samples" :key="iid" :src="fmtSample(iid)" object-fit="cover"
                     style="width:100%;aspect-ratio:1;border-radius:3px" />
          </div>
          <div style="margin-top:8px">
            <n-select v-model:value="meta[c.id].category_id" placeholder="选择缺陷类别" size="small"
                      style="width:100%" :disabled="meta[c.id]?.ignored" clearable :options="categoryOptions" />
          </div>
        </div>
      </div>
    </template>
    <n-empty v-else description="选择数据集并运行聚类" :image-size="80" style="margin-top:60px" />
  </div>
</template>

<style scoped>
.cluster-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 14px;
}
.cluster-card.ignored { opacity: 0.45; }
.sample-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
}
.sample-grid .n-image { width: 100%; height: 100%; display: block; }
.sample-grid .n-image :deep(img) { width: 100% !important; height: 100% !important; object-fit: cover; display: block; }
</style>

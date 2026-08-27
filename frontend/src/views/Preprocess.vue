<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import OpForm from '../components/OpForm.vue'

const route = useRoute()
const pid = Number(route.params.pid)

const tab = ref('preprocess')
const opsLib = ref({ pre: [], aug: [] })
const datasets = ref([])
const images = ref([])
const imageId = ref(null)
const pipeline = ref([])
const selected = ref(null)
const pipelines = ref([])
const saveDlg = ref(false)
const saveName = ref('')
const previewImg = ref('')
const previewing = ref(false)
const previewScroll = ref(null)
const previewScale = ref(1)
const previewBase = ref(300)
const previewMode = ref('combo')   // combo=组合预览 / solo=逐个算子单独预览
const soloImgs = ref([])           // solo 模式：每个算子单独效果 [{label, image}]
const previewW = computed(() => Math.round(previewBase.value * previewScale.value))
const previewGridW = computed(() => {
  const cols = previewMode.value === 'solo' ? 1 + pipeline.value.filter(o => o.enabled).length : 2
  return previewW.value * cols + 10 * (cols - 1)
})
const previewZoomLabel = computed(() => Math.round(previewScale.value * 100) + '%')

watch([previewImg, soloImgs], async () => {
  const any = previewImg.value || soloImgs.value.length
  if (!any) return
  await nextTick()
  if (previewScroll.value) {
    previewBase.value = Math.max(100, (previewScroll.value.clientWidth - 10) / 2)
  }
})

function previewZoomBy(factor) {
  previewScale.value = Math.min(8, Math.max(0.25, previewScale.value * factor))
}
function previewZoomReset() {
  previewScale.value = 1
}
function previewOnWheel(e) {
  previewZoomBy(e.deltaY < 0 ? 1.1 : 0.9)
}

const opsOf = computed(() => (tab.value === 'preprocess' ? opsLib.value.pre : opsLib.value.aug))
const selectedOp = computed(() => (selected.value == null ? null : pipeline.value[selected.value]))

async function loadLib() {
  const [pre, aug] = await Promise.all([api.ops.preprocess(), api.ops.augment()])
  opsLib.value = { pre, aug }
}
async function loadDatasets() { datasets.value = await api.datasets.list(pid) }
async function loadImages() {
  if (!datasets.value.length) return
  const r = await api.datasets.images(datasets.value[0].id, { page: 1, page_size: 100 })
  images.value = r.items
  if (!imageId.value && r.items.length) imageId.value = r.items[0].id
}
async function loadPipelines() {
  pipelines.value = await api.pipelines.list(pid, tab.value === 'augment' ? 'aug' : 'pre')
}

onMounted(async () => {
  await loadLib()
  await loadDatasets()
  await loadImages()
  await loadPipelines()
})

function addOp(op) {
  const params = {}
  for (const p of op.params) params[p.name] = p.default
  pipeline.value.push({ name: op.name, label: op.label, params, paramsDef: op.params, enabled: true })
  selected.value = pipeline.value.length - 1
  refresh()
}
function removeOp(i) {
  pipeline.value.splice(i, 1)
  if (selected.value === i) selected.value = null
  refresh()
}
function moveOp(i, dir) {
  const j = i + dir
  if (j < 0 || j >= pipeline.value.length) return
  const [item] = pipeline.value.splice(i, 1)
  pipeline.value.splice(j, 0, item)
  selected.value = j
}
function clearOps() {
  pipeline.value = []
  selected.value = null
  refresh()
}

function switchTab(t) {
  tab.value = t
  pipeline.value = []
  selected.value = null
  refresh()
}

let timer = null
function refresh() {
  clearTimeout(timer)
  timer = setTimeout(async () => {
    const enabled = pipeline.value.filter(o => o.enabled)
    if (!imageId.value || !enabled.length) { previewImg.value = ''; soloImgs.value = []; return }
    previewing.value = true
    try {
      if (previewMode.value === 'solo') {
        // 逐个预览：每个算子单独应用，并排展示
        const results = await Promise.all(enabled.map(async (op, i) => {
          const ops = [{ name: op.name, params: op.params }]
          const r = tab.value === 'preprocess'
            ? await api.preview.preprocess({ image_id: imageId.value, ops })
            : await api.preview.augment({ image_id: imageId.value, augs: ops, seed: 42 + i })
          return { label: op.label, image: r.image }
        }))
        soloImgs.value = results
      } else {
        const ops = enabled.map(o => ({ name: o.name, params: o.params }))
        const r = tab.value === 'preprocess'
          ? await api.preview.preprocess({ image_id: imageId.value, ops })
          : await api.preview.augment({ image_id: imageId.value, augs: ops, seed: 42 })
        previewImg.value = r.image
      }
    } catch (e) {
      previewImg.value = ''
      soloImgs.value = []
      const detail = e.response?.data?.detail || e.message || '预览失败'
      ElMessage.error(String(detail).slice(0, 200))
    } finally {
      previewing.value = false
    }
  }, 400)
}
watch([tab, imageId, pipeline], refresh, { deep: true })

function loadPipeline(p) {
  // 后端 list_pipelines 返回原始行，ops 是 JSON 字符串，需先解析为数组
  let raw = p.ops || []
  if (typeof raw === 'string') { try { raw = JSON.parse(raw || '[]') } catch { raw = [] } }
  pipeline.value = JSON.parse(JSON.stringify(raw))
  const lib = tab.value === 'preprocess' ? opsLib.value.pre : opsLib.value.aug
  for (const item of pipeline.value) {
    const spec = lib.find(o => o.name === item.name)
    item.paramsDef = spec ? spec.params : []
    item.enabled = item.enabled !== false  // 旧管线无 enabled 字段默认启用
  }
  selected.value = null
  refresh()
}
async function savePipeline() {
  if (!saveName.value.trim()) return ElMessage.warning('请输入管线名称')
  await api.pipelines.create({
    project_id: pid,
    name: saveName.value,
    ops: pipeline.value.map(o => ({ name: o.name, params: o.params, enabled: o.enabled })),
    type: tab.value === 'augment' ? 'aug' : 'pre',
  })
  ElMessage.success('管线已保存')
  saveDlg.value = false
  saveName.value = ''
  loadPipelines()
}
async function removePipeline(p) {
  await api.pipelines.remove(p.id)
  loadPipelines()
}
</script>

<template>
  <div>
    <div class="page-head">
      <h2>预处理 · 增强工作台</h2>
      <el-radio-group v-model="tab" size="small" @change="switchTab">
        <el-radio-button value="preprocess">预处理</el-radio-button>
        <el-radio-button value="augment">数据增强</el-radio-button>
      </el-radio-group>
    </div>

    <el-row :gutter="16">
      <!-- 左：图像选择 + 算子库 -->
      <el-col :span="7">
        <div class="card" style="margin-bottom:12px">
          <div style="font-weight:600;margin-bottom:8px;font-size:0.9rem">预览图像</div>
          <el-select v-model="imageId" filterable placeholder="选择图像" style="width:100%">
            <el-option v-for="img in images" :key="img.id" :value="img.id" :label="img.rel_path" />
          </el-select>
        </div>
        <div class="card">
          <div style="font-weight:600;margin-bottom:8px;font-size:0.9rem">
            {{ tab === 'preprocess' ? '预处理算子' : '增强算子' }}（点击添加）
          </div>
          <div style="max-height:480px;overflow-y:auto">
            <div v-for="op in opsOf" :key="op.name" class="op-item" @click="addOp(op)">
              {{ op.label }}
            </div>
          </div>
        </div>
      </el-col>

      <!-- 中：管线 -->
      <el-col :span="8">
        <div class="card" style="min-height:560px;display:flex;flex-direction:column">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span style="font-weight:600;font-size:0.9rem">
              当前管线（{{ pipeline.length }} 步）
            </span>
            <div>
              <el-button size="small" @click="saveDlg = true" :disabled="!pipeline.length">保存</el-button>
              <el-button size="small" @click="clearOps" :disabled="!pipeline.length">清空</el-button>
            </div>
          </div>
          <div style="display:flex;gap:8px;margin-bottom:10px;align-items:center">
            <el-select v-model="saveName" placeholder="加载已存管线" size="small" style="flex:1"
                       @change="p => { const found = pipelines.find(x => x.name === p); if (found) loadPipeline(found) }">
              <el-option v-for="p in pipelines" :key="p.id" :value="p.name" :label="p.name" />
            </el-select>
            <el-button v-if="saveName" size="small" link type="danger" @click="removePipeline(pipelines.find(x => x.name === saveName))">
              删除
            </el-button>
          </div>
          <div v-if="pipeline.length" style="flex:1;overflow-y:auto">
            <div v-for="(op, i) in pipeline" :key="i" class="pipe-item"
                 :class="{ on: selected === i, off: !op.enabled }" @click="selected = i">
              <el-checkbox :model-value="op.enabled" size="small" @click.stop="op.enabled = !op.enabled; refresh()" />
              <span style="color:#4a6b4a;font-variant-numeric:tabular-nums">{{ i + 1 }}</span>
              <span style="flex:1;padding:0 6px">{{ op.label }}</span>
              <el-button link size="small" :disabled="i === 0" @click.stop="moveOp(i, -1)">↑</el-button>
              <el-button link size="small" :disabled="i === pipeline.length - 1" @click.stop="moveOp(i, 1)">↓</el-button>
              <el-button link size="small" type="danger" @click.stop="removeOp(i)">×</el-button>
            </div>
          </div>
          <el-empty v-else description="点击左侧算子添加步骤" :image-size="70" />
        </div>
      </el-col>

      <!-- 右：参数 + 预览 -->
      <el-col :span="9">
        <div class="card" style="margin-bottom:12px">
          <div style="font-weight:600;margin-bottom:8px;font-size:0.9rem">
            {{ selectedOp ? selectedOp.label + ' 参数' : '参数' }}
          </div>
          <OpForm v-if="selectedOp" v-model="selectedOp.params" :params="selectedOp.paramsDef || []" />
          <div v-else style="color:#8a8175;font-size:0.85rem">选择管线中的步骤调整参数，拖动滑块实时预览</div>
        </div>
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span style="font-weight:600;font-size:0.9rem">效果预览</span>
            <div style="display:flex;gap:6px;align-items:center">
              <el-radio-group v-model="previewMode" size="small" @change="refresh">
                <el-radio-button value="combo">组合</el-radio-button>
                <el-radio-button value="solo">逐个</el-radio-button>
              </el-radio-group>
              <span v-if="previewing" style="color:#8a8175;font-size:0.8rem">处理中…</span>
              <span style="font-size:0.8rem;color:#8a8175">{{ previewZoomLabel }}</span>
              <el-button size="small" @click="previewZoomBy(1.25)">＋</el-button>
              <el-button size="small" @click="previewZoomBy(0.8)">－</el-button>
              <el-button size="small" @click="previewZoomReset">适应</el-button>
            </div>
          </div>
          <div v-if="previewImg || soloImgs.length" class="preview-scroll" @wheel.prevent="previewOnWheel">
            <div v-if="previewMode === 'combo'" class="preview-grid" :style="{ width: previewGridW + 'px' }">
              <div>
                <div class="preview-cap">原图</div>
                <img v-if="imageId" :src="api.files.imageUrl(imageId)" class="preview-img"
                     :style="{ width: previewW + 'px' }" />
              </div>
              <div>
                <div class="preview-cap">组合处理后</div>
                <img :src="previewImg" class="preview-img"
                     :style="{ width: previewW + 'px' }" />
              </div>
            </div>
            <div v-else class="preview-grid" :style="{ width: previewGridW + 'px' }">
              <div>
                <div class="preview-cap">原图</div>
                <img v-if="imageId" :src="api.files.imageUrl(imageId)" class="preview-img"
                     :style="{ width: previewW + 'px' }" />
              </div>
              <div v-for="s in soloImgs" :key="s.label">
                <div class="preview-cap">{{ s.label }}（单独）</div>
                <img :src="s.image" class="preview-img" :style="{ width: previewW + 'px' }" />
              </div>
            </div>
          </div>
          <el-empty v-else description="添加算子后自动预览" :image-size="70" />
        </div>
      </el-col>
    </el-row>

    <el-dialog v-model="saveDlg" title="保存管线" width="380px">
      <el-input v-model="saveName" placeholder="管线名称，如：低对比增强" @keyup.enter="savePipeline" />
      <template #footer>
        <el-button @click="saveDlg = false">取消</el-button>
        <el-button type="primary" @click="savePipeline">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.op-item {
  padding: 7px 10px;
  border: 1px solid #d8cfbe;
  border-radius: 4px;
  margin-bottom: 6px;
  cursor: pointer;
  font-size: 0.85rem;
  background: #fbf8f1;
  transition: background 0.15s;
}
.op-item:hover { background: #eef3ee; border-color: #4a6b4a; }
.pipe-item {
  display: flex;
  align-items: center;
  padding: 7px 8px;
  border: 1px solid #d8cfbe;
  border-radius: 4px;
  margin-bottom: 6px;
  cursor: pointer;
  font-size: 0.85rem;
  background: #fbf8f1;
}
.pipe-item.on { border-color: #4a6b4a; background: #eef3ee; }
.pipe-item.off { opacity: 0.45; }
.preview-scroll {
  overflow: auto;
  max-height: 480px;
  border: 1px solid #d8cfbe;
  border-radius: 4px;
  background: #2a2622;
  padding: 8px;
}
.preview-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.preview-cap { font-size: 0.78rem; color: #8a8175; margin-bottom: 4px; }
.preview-img { border-radius: 4px; border: 1px solid #d8cfbe; max-width: none; }
</style>

<script setup>
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton, NGrid, NGi, NMenu, NImage, NSelect, NInput, NInputNumber,
  NForm, NFormItem, NSlider, NEmpty, NSpin, NModal, NColorPicker, NDivider,
  NPagination,
  useMessage, useDialog,
} from 'naive-ui'
import { api } from '../api'
import DirectoryPicker from '../components/DirectoryPicker.vue'

const route = useRoute()
const pid = Number(route.params.pid)
const message = useMessage()
const dialog = useDialog()

const datasets = ref([])
const current = ref(null)
const images = ref([])
const total = ref(0)
const split = ref('')
const page = ref(1)
const pageSize = 20
const loading = ref(false)

const dlg = ref(false)
const form = ref({ name: '', root_path: '' })
const splitDlg = ref(false)
const splitForm = ref({ train_ratio: 0.8, val_ratio: 0.1, seed: 42 })
const splitStats = ref(null)
const preview = ref(null)
const previewScale = ref(1)
const previewPanX = ref(0)
const previewPanY = ref(0)
let previewDragStart = null
const previewImgRef = ref(null)
const previewViewport = ref(null)
const previewOpen = computed({
  get: () => !!preview.value,
  set: (v) => { if (!v) { preview.value = null; previewScale.value = 1; previewPanX.value = 0; previewPanY.value = 0 } },
})

const splitOptions = [
  { label: '全部', value: '' },
  { label: '训练集', value: 'train' },
  { label: '验证集', value: 'val' },
  { label: '测试集', value: 'test' },
]

const dsMenuOptions = computed(() => datasets.value.map(d => ({
  key: d.id,
  label: () => h('div', { style: 'display:flex;justify-content:space-between;width:100%' }, [
    h('span', {}, d.name),
    h('span', { style: 'color:var(--text-muted)' }, `${d.image_count} 张`),
  ]),
})))
function onDsMenuChange(key) {
  current.value = datasets.value.find(d => d.id === key) || null
}

function previewZoomBy(f) {
  previewScale.value = Math.min(8, Math.max(0.2, previewScale.value * f))
}
function previewZoomReset() {
  previewScale.value = 1; previewPanX.value = 0; previewPanY.value = 0
}
function previewFit() {
  const vp = previewViewport.value
  const img = previewImgRef.value
  if (!vp || !img || !img.naturalWidth) return
  const s = Math.min(vp.clientWidth / img.naturalWidth, vp.clientHeight / img.naturalHeight, 1)
  previewScale.value = s
  previewPanX.value = 0
  previewPanY.value = 0
}
function onPreviewWheel(e) {
  e.preventDefault()
  previewZoomBy(e.deltaY < 0 ? 1.15 : 0.85)
}
function onPreviewMouseDown(e) {
  if (e.button !== 0) return
  previewDragStart = { x: e.clientX - previewPanX.value, y: e.clientY - previewPanY.value }
  window.addEventListener('mousemove', onPreviewMouseMove)
  window.addEventListener('mouseup', onPreviewMouseUp)
}
function onPreviewMouseMove(e) {
  if (!previewDragStart) return
  previewPanX.value = e.clientX - previewDragStart.x
  previewPanY.value = e.clientY - previewDragStart.y
}
function onPreviewMouseUp() {
  previewDragStart = null
  window.removeEventListener('mousemove', onPreviewMouseMove)
  window.removeEventListener('mouseup', onPreviewMouseUp)
}
function previewNext(dir) {
  if (!images.value.length) return
  const curIdx = images.value.findIndex(im => im.id === preview.value?.id)
  const next = (curIdx + dir + images.value.length) % images.value.length
  preview.value = images.value[next]
  // 切图保留当前缩放，只重置平移
  previewPanX.value = 0; previewPanY.value = 0
}
function onPreviewKeydown(e) {
  if (e.key === 'ArrowRight') previewNext(1)
  else if (e.key === 'ArrowLeft') previewNext(-1)
  else if (e.key === '+' || e.key === '=') previewZoomBy(1.2)
  else if (e.key === '-') previewZoomBy(0.8)
  else if (e.key === '0') previewZoomReset()
}

// 弹窗打开时挂 window 键盘监听
watch(previewOpen, (open) => {
  if (open) window.addEventListener('keydown', onPreviewKeydown)
  else window.removeEventListener('keydown', onPreviewKeydown)
})

// 打开弹窗时自动适配容器（preview 从 null → 有值）；切图不重置缩放（previewNext 已处理）
watch(preview, (img, old) => {
  if (img && !old) setTimeout(previewFit, 120) // 等图片加载后适配
})

// 类别管理
const catDlg = ref(false)
const cats = ref([])
const newCat = ref('')
// 标注导入
const impDlg = ref(false)
const impForm = ref({ format: 'yolo', path: '' })
const importFormats = [
  { value: 'yolo', label: 'YOLO txt（labels 目录）' },
  { value: 'labelme', label: 'LabelMe JSON（目录或单文件）' },
  { value: 'coco', label: 'COCO JSON（annotations 文件）' },
]
// 增强扩充
const augDlg = ref(false)
const augPipelines = ref([])
const augForm = ref({ pipeline_id: null, copies: 3, name: '' })
const augRunning = ref(false)
const augPipelineOptions = computed(() => augPipelines.value.map(p => ({ label: p.name, value: p.id })))

async function openAugDlg() {
  augPipelines.value = await api.pipelines.list(pid, 'aug')
  augForm.value = { pipeline_id: augPipelines.value[0]?.id || null, copies: 3, name: '' }
  augDlg.value = true
}

async function doAugment() {
  if (!augForm.value.pipeline_id) return message.warning('请选择增强管线')
  if (!augForm.value.name.trim()) return message.warning('请输入新数据集名称')
  if (!current.value) return message.warning('请先选择数据集')
  augRunning.value = true
  try {
    const r = await api.datasets.augment(current.value.id, { ...augForm.value })
    message.success(`扩充完成：${r.images} 张图像，${r.annotations} 条标注`)
    augDlg.value = false
    await loadDatasets()
  } catch (e) {
    message.error(String(e.response?.data?.detail || e.message).slice(0, 200))
  } finally {
    augRunning.value = false
  }
}

async function loadCats() {
  if (!current.value) { cats.value = []; return }
  cats.value = await api.projects.datasetCategories(current.value.id)
}
async function addCat() {
  if (!newCat.value.trim()) return message.warning('请输入类别名称')
  if (!current.value) return message.warning('请先选择数据集')
  const colors = ['#4E79A7', '#E15759', '#59A14F', '#F28E2B', '#B07AA1', '#76B7B2', '#EDC948']
  const c = await api.projects.addDatasetCategory(current.value.id, {
    name: newCat.value, color: colors[cats.value.length % colors.length],
  })
  cats.value.push(c)
  newCat.value = ''
}
function removeCat(c) {
  dialog.warning({
    title: '删除类别',
    content: `删除类别「${c.name}」后，属于它的标注将变为未分类，确定删除？`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      await api.projects.removeCategory(c.id)
      cats.value = cats.value.filter(x => x.id !== c.id)
      message.success(`已删除类别「${c.name}」`)
    },
  })
}
async function updateCatColor(c, color) {
  await api.projects.updateCategory(c.id, { color })
  c.color = color
}
function removeDataset(d) {
  dialog.warning({
    title: '确认删除',
    content: `删除数据集「${d.name}」？其图像、标注及引用它的训练任务将一并删除。`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      await api.datasets.remove(d.id)
      message.success('数据集已删除')
      if (current.value?.id === d.id) current.value = null
      await loadDatasets()
    },
  })
}
async function doImport() {
  if (!impForm.value.path.trim()) return message.warning('请输入标注文件路径')
  if (!current.value) return message.warning('请先选择数据集')
  const r = await api.annotations.importAnnotations(current.value.id, { ...impForm.value })
  message.success(`导入完成，共 ${r.created} 条标注`)
  impDlg.value = false
  impForm.value = { format: 'yolo', path: '' }
}

async function loadDatasets() {
  datasets.value = await api.datasets.list(pid)
  splitStats.value = null
  if (!current.value && datasets.value.length) {
    current.value = datasets.value[0]
  }
}

async function loadImages() {
  if (!current.value) { images.value = []; total.value = 0; return }
  loading.value = true
  try {
    const r = await api.datasets.images(current.value.id, {
      split: split.value, page: page.value, page_size: pageSize,
    })
    images.value = r.items
    total.value = r.total
  } finally { loading.value = false }
}

watch([current, split, page], loadImages)
watch(current, () => { page.value = 1 })

onMounted(async () => {
  await loadDatasets()
  await loadImages()
})

async function create() {
  if (!form.value.name.trim() || !form.value.root_path.trim()) {
    return message.warning('请填写数据集名称和目录路径')
  }
  await api.datasets.create({ project_id: pid, ...form.value })
  message.success('数据集已导入')
  dlg.value = false
  form.value = { name: '', root_path: '' }
  await loadDatasets()
}

async function doSplit() {
  const r = await api.datasets.split(current.value.id, splitForm.value)
  message.success(r.message)
  splitDlg.value = false
  await loadDatasets()
  const ds = await api.datasets.get(current.value.id)
  splitStats.value = ds.split_stats
}
</script>

<template>
  <div>
    <div class="page-head">
      <h2>数据集</h2>
      <div>
        <n-button :disabled="!current" @click="splitDlg = true">划分训练集</n-button>
        <n-button :disabled="!current" @click="openAugDlg">增强扩充</n-button>
        <n-button :disabled="!current" @click="catDlg = true; loadCats()">缺陷类别</n-button>
        <n-button :disabled="!current" @click="impDlg = true">导入标注</n-button>
        <n-button type="primary" @click="dlg = true">导入数据集</n-button>
      </div>
    </div>

    <n-grid :cols="24" :x-gap="16">
      <n-gi :span="7">
        <div class="card" style="padding: 8px">
          <n-menu :value="current?.id" :options="dsMenuOptions" style="border:none" @update:value="onDsMenuChange" />
          <div v-if="!datasets.length" style="padding:20px;color:var(--text-muted);text-align:center">
            暂无数据集
          </div>
        </div>
        <div v-if="splitStats" class="card" style="margin-top:12px;font-size:0.85rem">
          <div style="font-weight:600;margin-bottom:8px">划分结果</div>
          <div>训练集：{{ splitStats.train || 0 }} 张</div>
          <div>验证集：{{ splitStats.val || 0 }} 张</div>
          <div>测试集：{{ splitStats.test || 0 }} 张</div>
        </div>
        <div v-if="current" class="card" style="margin-top:12px;padding:10px 14px;display:flex;justify-content:space-between;align-items:center">
          <span style="font-size:0.85rem;color:#4a433c">{{ current.name }}</span>
          <n-button text type="error" size="small" @click="removeDataset(current)">删除数据集</n-button>
        </div>
      </n-gi>

      <n-gi :span="17">
        <div class="card">
          <div style="display:flex;gap:12px;align-items:center;margin-bottom:12px">
            <n-select v-model:value="split" :options="splitOptions" style="width:130px" />
            <span style="color:var(--text-muted);font-size:0.85rem">共 {{ total }} 张</span>
          </div>
          <n-spin :show="loading" style="min-height:200px">
            <template v-if="images.length">
              <div class="img-grid">
                <div v-for="img in images" :key="img.id" class="img-cell" @click="preview = img">
                  <n-image :src="api.files.imageUrl(img.id)" object-fit="cover" preview-disabled>
                    <template #placeholder><div class="img-ph">加载中…</div></template>
                    <template #error><div class="img-ph err">加载失败</div></template>
                  </n-image>
                  <div class="img-meta">{{ img.width }}×{{ img.height }}</div>
                </div>
              </div>
            </template>
            <n-empty v-else description="选择左侧数据集查看图像" />
          </n-spin>
          <div style="display:flex;justify-content:flex-end;margin-top:12px">
            <n-pagination v-model:page="page" :page-size="pageSize" :item-count="total" size="small" />
          </div>
        </div>
      </n-gi>
    </n-grid>

    <n-modal v-model:show="dlg" preset="card" title="导入数据集" style="width:560px">
      <n-form label-placement="left" label-width="80">
        <n-form-item label="名称">
          <n-input v-model:value="form.name" placeholder="如：焊接板 A 线" />
        </n-form-item>
        <n-form-item label="目录路径">
          <n-input v-model:value="form.root_path" placeholder="服务器上的图像目录" />
        </n-form-item>
      </n-form>
      <div style="font-weight:600;margin-bottom:8px;font-size:0.9rem">从资源管理器选择</div>
      <DirectoryPicker v-model="form.root_path" @select="dlg = false" />
      <template #footer>
        <div style="display:flex;justify-content:flex-end;gap:8px">
          <n-button @click="dlg = false">取消</n-button>
          <n-button type="primary" @click="create">导入</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal v-model:show="catDlg" preset="card" :title="`缺陷类别管理：${current?.name || ''}`" style="width:440px">
      <div v-if="cats.length" style="margin-bottom:10px">
        <div v-for="c in cats" :key="c.id" class="cat-mgr-row">
          <n-color-picker v-model:value="c.color" size="small" :modes="['hex']" :show-alpha="false"
                          @complete="color => color && updateCatColor(c, color)" />
          <span style="flex:1">{{ c.name }}</span>
          <n-button text type="error" @click="removeCat(c)">删除</n-button>
        </div>
      </div>
      <n-empty v-else description="暂无类别" :image-size="50" />
      <div style="display:flex;gap:8px;margin-top:10px">
        <n-input v-model:value="newCat" placeholder="新类别名，如：脏污" @keyup.enter="addCat" />
        <n-button type="primary" @click="addCat">添加</n-button>
      </div>
    </n-modal>

    <n-modal v-model:show="augDlg" preset="card" title="增强扩充数据集" style="width:460px">
      <n-form label-placement="left" label-width="90">
        <n-form-item label="增强管线">
          <n-select v-model:value="augForm.pipeline_id" :options="augPipelineOptions" style="width:100%" />
        </n-form-item>
        <n-form-item label="每图副本数">
          <n-input-number v-model:value="augForm.copies" :min="1" :max="20" style="width:100%" />
        </n-form-item>
        <n-form-item label="新数据集名">
          <n-input v-model:value="augForm.name" placeholder="如：线体A-扩充" />
        </n-form-item>
      </n-form>
      <div style="color:var(--text-muted);font-size:0.8rem">
        每张图生成 N 个增强副本（标注同步变换），输出为新数据集，所有任务可用。
      </div>
      <template #footer>
        <div style="display:flex;justify-content:flex-end;gap:8px">
          <n-button @click="augDlg = false">取消</n-button>
          <n-button type="primary" :loading="augRunning" @click="doAugment">开始扩充</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal v-model:show="impDlg" preset="card" title="导入标注" style="width:460px">
      <n-form label-placement="left" label-width="80">
        <n-form-item label="格式">
          <n-select v-model:value="impForm.format" :options="importFormats" style="width:100%" />
        </n-form-item>
        <n-form-item label="路径">
          <n-input v-model:value="impForm.path" :placeholder="impForm.format === 'yolo' ? 'labels 目录路径，如 E:\\data\\labels' : impForm.format === 'labelme' ? 'JSON 目录或单文件路径' : 'annotations.json 路径'" />
        </n-form-item>
      </n-form>
      <template #footer>
        <div style="display:flex;justify-content:flex-end;gap:8px">
          <n-button @click="impDlg = false">取消</n-button>
          <n-button type="primary" @click="doImport">导入</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal v-model:show="splitDlg" preset="card" title="划分训练 / 验证 / 测试集" style="width:440px">
      <n-form label-placement="left" label-width="110">
        <n-form-item label="训练集比例">
          <div style="display:flex;align-items:center;gap:8px;width:100%">
            <n-slider v-model:value="splitForm.train_ratio" :min="0" :max="1" :step="0.05" style="flex:1" />
            <n-input-number v-model:value="splitForm.train_ratio" :min="0" :max="1" :step="0.05" size="small" style="width:84px" />
          </div>
        </n-form-item>
        <n-form-item label="验证集比例">
          <div style="display:flex;align-items:center;gap:8px;width:100%">
            <n-slider v-model:value="splitForm.val_ratio" :min="0" :max="1" :step="0.05" style="flex:1" />
            <n-input-number v-model:value="splitForm.val_ratio" :min="0" :max="1" :step="0.05" size="small" style="width:84px" />
          </div>
        </n-form-item>
        <n-form-item label="随机种子">
          <n-input-number v-model:value="splitForm.seed" :min="0" style="width:100%" />
        </n-form-item>
      </n-form>
      <div style="color:var(--text-muted);font-size:0.8rem">剩余部分自动归入测试集</div>
      <template #footer>
        <div style="display:flex;justify-content:flex-end;gap:8px">
          <n-button @click="splitDlg = false">取消</n-button>
          <n-button type="primary" @click="doSplit">划分</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal v-model:show="previewOpen" preset="card" :title="preview?.rel_path" style="width:78%">
      <template v-if="preview">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <n-button size="small" @click="previewZoomBy(1.25)">＋</n-button>
          <span style="font-size:0.85rem;color:var(--text-muted);min-width:48px;text-align:center">{{ Math.round(previewScale * 100) }}%</span>
          <n-button size="small" @click="previewZoomBy(0.8)">－</n-button>
          <n-button size="small" @click="previewFit">适应</n-button>
          <n-divider vertical />
          <n-button size="small" @click="previewNext(-1)">◀ 上一张</n-button>
          <n-button size="small" @click="previewNext(1)">下一张 ▶</n-button>
          <span style="font-size:0.8rem;color:var(--text-muted);margin-left:4px">
            {{ images.findIndex(im => im.id === preview.id) + 1 }} / {{ images.length }}
          </span>
        </div>
        <div ref="previewViewport" class="preview-viewport" @wheel.prevent="onPreviewWheel"
             @mousedown="onPreviewMouseDown"
             :style="{ cursor: previewScale > 1 ? 'grab' : 'default' }">
          <img ref="previewImgRef" :src="api.files.imageUrl(preview.id)"
               :style="{ transform: `translate(${previewPanX}px, ${previewPanY}px) scale(${previewScale})`, transformOrigin: '0 0' }" />
        </div>
        <div style="margin-top:6px;font-size:0.78rem;color:var(--text-muted);display:flex;gap:12px">
          <span>{{ preview.width }} × {{ preview.height }}</span>
          <span v-if="preview.split">分区：{{ preview.split }}</span>
          <span>标注：{{ preview.annotation_count || 0 }} 条</span>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.img-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 10px;
}
.img-cell {
  position: relative;
  border: 1px solid var(--border);
  border-radius: 4px;
  overflow: hidden;
  cursor: pointer;
  aspect-ratio: 1;
}
.img-cell .n-image { width: 100%; height: 100%; display: block; position: relative; }
/* n-image 内部 img 需强制填满容器（否则按原始尺寸渲染只露出角落） */
.img-cell .n-image :deep(img) { width: 100% !important; height: 100% !important; object-fit: cover; position: absolute; inset: 0; }
.img-ph {
  width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
  background: var(--bg-hover); color: var(--text-muted); font-size: 0.72rem;
}
.img-ph.err { color: #c07; }
.img-meta {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  background: rgba(0,0,0,0.55);
  color: #fff; font-size: 0.7rem;
  padding: 2px 6px;
}
.cat-mgr-row {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 4px; border-bottom: 0.5px solid var(--border);
  font-size: 0.9rem;
}
.preview-viewport {
  overflow: hidden; max-height: 64vh;
  background: #2a2622; border-radius: 4px;
  border: 1px solid var(--border);
}
.preview-viewport img {
  display: block; max-width: none;
}
</style>

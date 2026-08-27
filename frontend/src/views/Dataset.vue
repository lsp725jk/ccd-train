<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import DirectoryPicker from '../components/DirectoryPicker.vue'

const route = useRoute()
const pid = Number(route.params.pid)

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

// 弹窗打开时挂 window 键盘监听（el-dialog 的 @keydown 只在焦点在弹窗内才触发）
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

async function openAugDlg() {
  augPipelines.value = await api.pipelines.list(pid, 'aug')
  augForm.value = { pipeline_id: augPipelines.value[0]?.id || null, copies: 3, name: '' }
  augDlg.value = true
}

async function doAugment() {
  if (!augForm.value.pipeline_id) return ElMessage.warning('请选择增强管线')
  if (!augForm.value.name.trim()) return ElMessage.warning('请输入新数据集名称')
  if (!current.value) return ElMessage.warning('请先选择数据集')
  augRunning.value = true
  try {
    const r = await api.datasets.augment(current.value.id, { ...augForm.value })
    ElMessage.success(`扩充完成：${r.images} 张图像，${r.annotations} 条标注`)
    augDlg.value = false
    await loadDatasets()
  } catch (e) {
    ElMessage.error(String(e.response?.data?.detail || e.message).slice(0, 200))
  } finally {
    augRunning.value = false
  }
}

async function loadCats() {
  if (!current.value) { cats.value = []; return }
  cats.value = await api.projects.datasetCategories(current.value.id)
}
async function addCat() {
  if (!newCat.value.trim()) return ElMessage.warning('请输入类别名称')
  if (!current.value) return ElMessage.warning('请先选择数据集')
  const colors = ['#4E79A7', '#E15759', '#59A14F', '#F28E2B', '#B07AA1', '#76B7B2', '#EDC948']
  const c = await api.projects.addDatasetCategory(current.value.id, {
    name: newCat.value, color: colors[cats.value.length % colors.length],
  })
  cats.value.push(c)
  newCat.value = ''
}
async function removeCat(c) {
  try {
    await ElMessageBox.confirm(
      `删除类别「${c.name}」后，属于它的标注将变为未分类，确定删除？`,
      '删除类别', { type: 'warning' },
    )
  } catch { return }  // 用户取消
  await api.projects.removeCategory(c.id)
  cats.value = cats.value.filter(x => x.id !== c.id)
  ElMessage.success(`已删除类别「${c.name}」`)
}
async function updateCatColor(c, color) {
  await api.projects.updateCategory(c.id, { color })
  c.color = color
}
async function removeDataset(d) {
  await ElMessageBox.confirm(`删除数据集「${d.name}」？其图像、标注及引用它的训练任务将一并删除。`, '确认删除', { type: 'warning' })
  await api.datasets.remove(d.id)
  ElMessage.success('数据集已删除')
  if (current.value?.id === d.id) current.value = null
  await loadDatasets()
}
async function doImport() {
  if (!impForm.value.path.trim()) return ElMessage.warning('请输入标注文件路径')
  if (!current.value) return ElMessage.warning('请先选择数据集')
  const r = await api.annotations.importAnnotations(current.value.id, { ...impForm.value })
  ElMessage.success(`导入完成，共 ${r.created} 条标注`)
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
    return ElMessage.warning('请填写数据集名称和目录路径')
  }
  await api.datasets.create({ project_id: pid, ...form.value })
  ElMessage.success('数据集已导入')
  dlg.value = false
  form.value = { name: '', root_path: '' }
  await loadDatasets()
}

async function doSplit() {
  const r = await api.datasets.split(current.value.id, splitForm.value)
  ElMessage.success(r.message)
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
        <el-button :disabled="!current" @click="splitDlg = true">划分训练集</el-button>
        <el-button :disabled="!current" @click="openAugDlg">增强扩充</el-button>
        <el-button :disabled="!current" @click="catDlg = true; loadCats()">缺陷类别</el-button>
        <el-button :disabled="!current" @click="impDlg = true">导入标注</el-button>
        <el-button type="primary" @click="dlg = true">导入数据集</el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="7">
        <div class="card" style="padding: 8px">
          <el-menu style="border: none">
            <el-menu-item v-for="d in datasets" :key="d.id" :class="{ active: current?.id === d.id }"
                          @click="current = d">
              <div style="display:flex;justify-content:space-between;width:100%">
                <span>{{ d.name }}</span>
                <span style="color:#8a8175">{{ d.image_count }} 张</span>
              </div>
            </el-menu-item>
          </el-menu>
          <div v-if="!datasets.length" style="padding:20px;color:#8a8175;text-align:center">
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
          <el-button link type="danger" size="small" @click="removeDataset(current)">删除数据集</el-button>
        </div>
      </el-col>

      <el-col :span="17">
        <div class="card">
          <div style="display:flex;gap:12px;align-items:center;margin-bottom:12px">
            <el-select v-model="split" style="width:130px">
              <el-option label="全部" value="" />
              <el-option label="训练集" value="train" />
              <el-option label="验证集" value="val" />
              <el-option label="测试集" value="test" />
            </el-select>
            <span style="color:#8a8175;font-size:0.85rem">共 {{ total }} 张</span>
          </div>
          <div v-loading="loading" style="min-height:200px">
            <div v-if="images.length" class="img-grid">
              <div v-for="img in images" :key="img.id" class="img-cell" @click="preview = img">
                <el-image :src="api.files.imageUrl(img.id)" fit="cover" lazy />
                <div class="img-meta">{{ img.width }}×{{ img.height }}</div>
              </div>
            </div>
            <el-empty v-else description="选择左侧数据集查看图像" />
          </div>
          <div style="display:flex;justify-content:flex-end;margin-top:12px">
            <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total"
                           layout="prev, pager, next" small />
          </div>
        </div>
      </el-col>
    </el-row>

    <el-dialog v-model="dlg" title="导入数据集" width="560px">
      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如：焊接板 A 线" />
        </el-form-item>
        <el-form-item label="目录路径">
          <el-input v-model="form.root_path" placeholder="服务器上的图像目录" />
        </el-form-item>
      </el-form>
      <div style="font-weight:600;margin-bottom:8px;font-size:0.9rem">从资源管理器选择</div>
      <DirectoryPicker v-model="form.root_path" @select="dlg = false" />
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" @click="create">导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="catDlg" :title="`缺陷类别管理：${current?.name || ''}`" width="440px">
      <div v-if="cats.length" style="margin-bottom:10px">
        <div v-for="c in cats" :key="c.id" class="cat-mgr-row">
          <el-color-picker :model-value="c.color" size="small"
                           @active-change="color => color && (c.color = color)"
                           @change="color => updateCatColor(c, color)" />
          <span style="flex:1">{{ c.name }}</span>
          <el-button link type="danger" @click="removeCat(c)">删除</el-button>
        </div>
      </div>
      <el-empty v-else description="暂无类别" :image-size="50" />
      <div style="display:flex;gap:8px;margin-top:10px">
        <el-input v-model="newCat" placeholder="新类别名，如：脏污" @keyup.enter="addCat" />
        <el-button type="primary" @click="addCat">添加</el-button>
      </div>
    </el-dialog>

    <el-dialog v-model="augDlg" title="增强扩充数据集" width="460px">
      <el-form label-width="90px">
        <el-form-item label="增强管线">
          <el-select v-model="augForm.pipeline_id" style="width:100%">
            <el-option v-for="p in augPipelines" :key="p.id" :value="p.id" :label="p.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="每图副本数">
          <el-input-number v-model="augForm.copies" :min="1" :max="20" style="width:100%" />
        </el-form-item>
        <el-form-item label="新数据集名">
          <el-input v-model="augForm.name" placeholder="如：线体A-扩充" />
        </el-form-item>
      </el-form>
      <div style="color:#8a8175;font-size:0.8rem">
        每张图生成 N 个增强副本（标注同步变换），输出为新数据集，所有任务可用。
      </div>
      <template #footer>
        <el-button @click="augDlg = false">取消</el-button>
        <el-button type="primary" :loading="augRunning" @click="doAugment">开始扩充</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="impDlg" title="导入标注" width="460px">
      <el-form label-width="80px">
        <el-form-item label="格式">
          <el-select v-model="impForm.format" style="width:100%">
            <el-option v-for="f in importFormats" :key="f.value" :value="f.value" :label="f.label" />
          </el-select>
        </el-form-item>
        <el-form-item label="路径">
          <el-input v-model="impForm.path" :placeholder="impForm.format === 'yolo' ? 'labels 目录路径，如 E:\\data\\labels' : impForm.format === 'labelme' ? 'JSON 目录或单文件路径' : 'annotations.json 路径'" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="impDlg = false">取消</el-button>
        <el-button type="primary" @click="doImport">导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="splitDlg" title="划分训练 / 验证 / 测试集" width="440px">
      <el-form label-width="110px">
        <el-form-item label="训练集比例">
          <el-slider v-model="splitForm.train_ratio" :min="0" :max="1" :step="0.05" show-input />
        </el-form-item>
        <el-form-item label="验证集比例">
          <el-slider v-model="splitForm.val_ratio" :min="0" :max="1" :step="0.05" show-input />
        </el-form-item>
        <el-form-item label="随机种子">
          <el-input-number v-model="splitForm.seed" :min="0" />
        </el-form-item>
        <div style="color:#8a8175;font-size:0.8rem">剩余部分自动归入测试集</div>
      </el-form>
      <template #footer>
        <el-button @click="splitDlg = false">取消</el-button>
        <el-button type="primary" @click="doSplit">划分</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewOpen" :title="preview?.rel_path" width="78%" top="3vh">
      <template v-if="preview">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <el-button size="small" @click="previewZoomBy(1.25)">＋</el-button>
          <span style="font-size:0.85rem;color:#8a8175;min-width:48px;text-align:center">{{ Math.round(previewScale * 100) }}%</span>
          <el-button size="small" @click="previewZoomBy(0.8)">－</el-button>
          <el-button size="small" @click="previewFit">适应</el-button>
          <el-divider direction="vertical" />
          <el-button size="small" @click="previewNext(-1)">◀ 上一张</el-button>
          <el-button size="small" @click="previewNext(1)">下一张 ▶</el-button>
          <span style="font-size:0.8rem;color:#8a8175;margin-left:4px">
            {{ images.findIndex(im => im.id === preview.id) + 1 }} / {{ images.length }}
          </span>
        </div>
        <div ref="previewViewport" class="preview-viewport" @wheel.prevent="onPreviewWheel"
             @mousedown="onPreviewMouseDown"
             :style="{ cursor: previewScale > 1 ? 'grab' : 'default' }">
          <img ref="previewImgRef" :src="api.files.imageUrl(preview.id)"
               :style="{ transform: `translate(${previewPanX}px, ${previewPanY}px) scale(${previewScale})`, transformOrigin: '0 0' }" />
        </div>
        <div style="margin-top:6px;font-size:0.78rem;color:#8a8175;display:flex;gap:12px">
          <span>{{ preview.width }} × {{ preview.height }}</span>
          <span v-if="preview.split">分区：{{ preview.split }}</span>
          <span>标注：{{ preview.annotation_count || 0 }} 条</span>
        </div>
      </template>
    </el-dialog>
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
  border: 1px solid #d8cfbe;
  border-radius: 4px;
  overflow: hidden;
  cursor: pointer;
  aspect-ratio: 1;
}
.img-cell .el-image { width: 100%; height: 100%; }
.img-meta {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  background: rgba(0,0,0,0.55);
  color: #fff; font-size: 0.7rem;
  padding: 2px 6px;
}
.active { background: #eef3ee !important; }
.cat-mgr-row {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 4px; border-bottom: 0.5px solid #d8cfbe;
  font-size: 0.9rem;
}
.preview-viewport {
  overflow: hidden; max-height: 64vh;
  background: #2a2622; border-radius: 4px;
  border: 1px solid #d8cfbe;
}
.preview-viewport img {
  display: block; max-width: none;
}
</style>

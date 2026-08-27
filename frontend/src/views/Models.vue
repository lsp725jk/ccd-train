<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

const route = useRoute()
const pid = Number(route.params.pid)

const list = ref([])
const loading = ref(false)
const dlg = ref(false)
const pipelines = ref([])
const form = ref({
  name: '', task_type: 'detect', framework: 'onnx', architecture: '',
  file_path: '', input_w: 640, input_h: 640, normalize: 'none',
  categories: '', preprocess_pipeline_id: null,
})

const taskTypeLabels = {
  detect: '目标检测', segment: '语义分割', classify: '分类',
  us_classify: '非监督分类', us_segment: '非监督分割',
}

const fmtSize = (bytes) => bytes > 1048576
  ? (bytes / 1048576).toFixed(1) + ' MB'
  : Math.max(1, Math.round(bytes / 1024)) + ' KB'

const statusText = computed(() => ({
  pending: '待训练', training: '训练中', ready: '就绪', failed: '失败',
}))

// ---- ONNX 导出 / 推理预览 ----
const exporting = ref(null)
const previewDlg = ref(false)
const previewModel = ref(null)
const previewImage = ref(null)
const previewResult = ref('')
const previewLoading = ref(false)
const previewImages = ref([])

async function doExport(row) {
  exporting.value = row.id
  try {
    const r = await api.models.exportModel(row.id)
    ElMessage.success(`已导出 ONNX（${r.size_mb} MB）`)
    row.onnx_path = r.onnx_path
  } catch (e) {
    ElMessage.error(String(e.response?.data?.detail || e.message).slice(0, 200))
  } finally {
    exporting.value = null
  }
}

async function openPreview(row) {
  previewModel.value = row
  previewResult.value = ''
  previewImage.value = null
  previewDlg.value = true
  if (!previewImages.value.length) {
    const ds = await api.datasets.list(pid)
    if (ds.length) {
      const imgs = await api.datasets.images(ds[0].id, { page: 1, page_size: 200 })
      previewImages.value = imgs.items
    }
  }
}

async function doPreview() {
  if (!previewImage.value) return ElMessage.warning('请选择图像')
  previewLoading.value = true
  try {
    const r = await api.models.predict(previewModel.value.id, { image_id: previewImage.value })
    previewResult.value = r.image_url
  } catch (e) {
    ElMessage.error(String(e.response?.data?.detail || e.message).slice(0, 200))
  } finally {
    previewLoading.value = false
  }
}

async function load() {
  loading.value = true
  try { list.value = await api.models.list(pid) } finally { loading.value = false }
}
onMounted(async () => {
  await load()
  pipelines.value = await api.pipelines.list(pid)
})

async function doImport() {
  if (!form.value.name.trim() || !form.value.file_path.trim()) {
    return ElMessage.warning('请填写模型名称和文件路径')
  }
  await api.models.importModel({
    project_id: pid,
    name: form.value.name,
    task_type: form.value.task_type,
    framework: form.value.framework,
    architecture: form.value.architecture,
    file_path: form.value.file_path,
    input_size: [form.value.input_w, form.value.input_h],
    normalize: form.value.normalize,
    categories: form.value.categories.split(/[,，]/).map(s => s.trim()).filter(Boolean),
    preprocess_pipeline_id: form.value.preprocess_pipeline_id,
  })
  ElMessage.success('模型已导入模型库')
  dlg.value = false
  form.value = { name: '', task_type: 'detect', framework: 'onnx', architecture: '',
    file_path: '', input_w: 640, input_h: 640, normalize: 'none',
    categories: '', preprocess_pipeline_id: null }
  load()
}

async function markBest(row) {
  await api.models.markBest(row.id)
  ElMessage.success(`「${row.name}」已标记为最佳模型`)
  load()
}

async function remove(row) {
  await ElMessageBox.confirm(`删除模型「${row.name}」？`, '确认删除', { type: 'warning' })
  await api.models.remove(row.id)
  ElMessage.success('已删除')
  load()
}
</script>

<template>
  <div>
    <div class="page-head">
      <h2>模型库</h2>
      <el-button type="primary" @click="dlg = true">导入模型</el-button>
    </div>

    <el-table :data="list" v-loading="loading" class="card">
      <el-table-column label="模型" min-width="170">
        <template #default="{ row }">
          <div style="display:flex;align-items:center;gap:6px">
            <span style="font-weight:500">{{ row.name }}</span>
            <el-tag v-if="row.is_best" size="small" type="success" effect="plain">最佳</el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="任务" width="110">
        <template #default="{ row }">{{ taskTypeLabels[row.task_type] || row.task_type }}</template>
      </el-table-column>
      <el-table-column prop="architecture" label="架构" width="180" show-overflow-tooltip />
      <el-table-column label="规模" width="140">
        <template #default="{ row }">
          <span v-if="row.params_m">{{ row.params_m }} M</span>
          <span v-else style="color:#8a8175">-</span>
          <span style="color:#8a8175;font-size:0.8rem"> / {{ fmtSize(row.file_size) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="row.engine.startsWith('imported') ? 'warning' : 'info'" effect="plain">
            {{ row.engine.startsWith('imported') ? '导入' : '平台训练' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <span :style="{ color: row.status === 'ready' ? '#4a6b4a' : row.status === 'failed' ? '#8b2c1f' : '#8a8175' }">
            {{ statusText[row.status] || row.status }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="165" />
      <el-table-column label="操作" width="200" align="center">
        <template #default="{ row }">
          <el-button v-if="row.status === 'ready' && row.task_type !== 'us_segment'" link type="primary"
                     :loading="exporting === row.id" @click="doExport(row)">导出</el-button>
          <el-button v-if="row.status === 'ready'" link type="primary" @click="openPreview(row)">预览</el-button>
          <el-button v-if="!row.is_best && row.status === 'ready'" link type="primary" @click="markBest(row)">最佳</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="previewDlg" :title="previewModel ? `${previewModel.name} 推理预览` : '推理预览'" width="760px" top="5vh">
      <div style="display:flex;gap:12px;margin-bottom:12px;align-items:center">
        <span style="font-size:0.85rem;color:#4a433c">图像</span>
        <el-select v-model="previewImage" filterable style="width:320px" placeholder="选择图像">
          <el-option v-for="im in previewImages" :key="im.id" :value="im.id" :label="im.rel_path" />
        </el-select>
        <el-button type="primary" :loading="previewLoading" @click="doPreview">推理</el-button>
        <span style="color:#8a8175;font-size:0.8rem">检测/分类走 ONNX，异常检测走特征库热图</span>
      </div>
      <div v-loading="previewLoading" style="min-height:320px;text-align:center">
        <img v-if="previewResult" :src="previewResult" style="max-width:100%;border:1px solid #d8cfbe;border-radius:4px" />
        <el-empty v-else description="选择图像并点击推理" :image-size="70" />
      </div>
      <template #footer>
        <el-button @click="previewDlg = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dlg" title="导入外部模型" width="560px">
      <el-form label-width="100px" label-position="left">
        <el-form-item label="模型名称">
          <el-input v-model="form.name" placeholder="如：焊点检测 ONNX 版" />
        </el-form-item>
        <el-form-item label="任务类型">
          <el-select v-model="form.task_type" style="width:100%">
            <el-option v-for="(v, k) in taskTypeLabels" :key="k" :value="k" :label="v" />
          </el-select>
        </el-form-item>
        <el-form-item label="框架">
          <el-select v-model="form.framework" style="width:100%">
            <el-option value="onnx" label="ONNX（推荐，跨框架通用）" />
            <el-option value="torch" label="PyTorch (.pt/.pth)" />
            <el-option value="tensorrt" label="TensorRT (.engine)" />
          </el-select>
        </el-form-item>
        <el-form-item label="架构">
          <el-input v-model="form.architecture" placeholder="如：yolo11s / custom-cnn-v2" />
        </el-form-item>
        <el-form-item label="文件路径">
          <el-input v-model="form.file_path" placeholder="服务器上的权重文件路径" />
        </el-form-item>
        <el-form-item label="输入尺寸">
          <el-input-number v-model="form.input_w" :min="64" :step="32" style="width:110px" />
          <span style="margin:0 8px;color:#8a8175">×</span>
          <el-input-number v-model="form.input_h" :min="64" :step="32" style="width:110px" />
        </el-form-item>
        <el-form-item label="归一化">
          <el-select v-model="form.normalize" style="width:100%">
            <el-option value="none" label="无（0-255 原值）" />
            <el-option value="imagenet" label="ImageNet 均值方差" />
          </el-select>
        </el-form-item>
        <el-form-item label="类别">
          <el-input v-model="form.categories" placeholder="逗号分隔，如：脏污,划痕,裂痕" />
        </el-form-item>
        <el-form-item label="预处理管线">
          <el-select v-model="form.preprocess_pipeline_id" clearable style="width:100%">
            <el-option v-for="p in pipelines" :key="p.id" :value="p.id" :label="p.name" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" @click="doImport">导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

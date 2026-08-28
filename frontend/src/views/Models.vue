<script setup>
import { computed, h, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  NButton, NDataTable, NTag, NModal, NForm, NFormItem, NInput, NInputNumber,
  NSelect, NEmpty, NSpin, useMessage, useDialog,
} from 'naive-ui'
import { api } from '../api'
import { friendlyName } from '../utils/format'

const route = useRoute()
const pid = Number(route.params.pid)
const message = useMessage()
const dialog = useDialog()

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

const taskTypeOptions = computed(() => Object.entries(taskTypeLabels).map(([value, label]) => ({ label, value })))
const frameworkOptions = [
  { label: 'ONNX（推荐，跨框架通用）', value: 'onnx' },
  { label: 'PyTorch (.pt/.pth)', value: 'torch' },
  { label: 'TensorRT (.engine)', value: 'tensorrt' },
]
const normalizeOptions = [
  { label: '无（0-255 原值）', value: 'none' },
  { label: 'ImageNet 均值方差', value: 'imagenet' },
]
const pipelineOptions = computed(() => pipelines.value.map(p => ({ label: p.name, value: p.id })))

// ---- ONNX 导出 / 推理预览 ----
const exporting = ref(null)
const previewDlg = ref(false)
const previewModel = ref(null)
const previewImage = ref(null)
const previewResult = ref('')
const previewLoading = ref(false)
const previewImages = ref([])
const previewImageOptions = computed(() => previewImages.value.map(im => ({ label: im.rel_path, value: im.id })))

async function doExport(row) {
  exporting.value = row.id
  try {
    const r = await api.models.exportModel(row.id)
    message.success(`已导出 ONNX（${r.size_mb} MB）`)
    row.onnx_path = r.onnx_path
  } catch (e) {
    message.error(String(e.response?.data?.detail || e.message).slice(0, 200))
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
  if (!previewImage.value) return message.warning('请选择图像')
  previewLoading.value = true
  try {
    const r = await api.models.predict(previewModel.value.id, { image_id: previewImage.value })
    previewResult.value = r.image_url
  } catch (e) {
    message.error(String(e.response?.data?.detail || e.message).slice(0, 200))
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
    return message.warning('请填写模型名称和文件路径')
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
  message.success('模型已导入模型库')
  dlg.value = false
  form.value = { name: '', task_type: 'detect', framework: 'onnx', architecture: '',
    file_path: '', input_w: 640, input_h: 640, normalize: 'none',
    categories: '', preprocess_pipeline_id: null }
  load()
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
      load()
    },
  })
}

const columns = computed(() => {
  const exp = exporting.value
  return [
  {
    title: '模型', key: 'name', minWidth: 170,
    render: (row) => h('div', { style: 'display:flex;align-items:center;gap:6px' }, [
      h('span', { style: 'font-weight:500' }, friendlyName(row.name)),
      row.is_best ? h(NTag, { size: 'small', type: 'success', bordered: false }, { default: () => '最佳' }) : null,
    ]),
  },
  {
    title: '任务', key: 'task_type', width: 110,
    render: (row) => taskTypeLabels[row.task_type] || row.task_type,
  },
  {
    title: '架构', key: 'architecture', width: 180, ellipsis: { tooltip: true },
    render: (row) => row.architecture,
  },
  {
    title: '规模', key: 'scale', width: 140,
    render: (row) => h('span', {}, [
      row.params_m ? `${row.params_m} M` : h('span', { style: 'color:var(--text-muted)' }, '-'),
      h('span', { style: 'color:var(--text-muted);font-size:0.8rem' }, ` / ${fmtSize(row.file_size)}`),
    ]),
  },
  {
    title: '来源', key: 'engine', width: 110,
    render: (row) => h(NTag, {
      size: 'small',
      type: row.engine.startsWith('imported') ? 'warning' : 'info',
      bordered: false,
    }, { default: () => row.engine.startsWith('imported') ? '导入' : '平台训练' }),
  },
  {
    title: '状态', key: 'status', width: 90,
    render: (row) => h('span', {
      style: { color: row.status === 'ready' ? '#4a6b4a' : row.status === 'failed' ? '#8b2c1f' : 'var(--text-muted)' },
    }, statusText.value[row.status] || row.status),
  },
  {
    title: '创建时间', key: 'created_at', width: 165,
    render: (row) => row.created_at,
  },
  {
    title: '操作', key: 'actions', width: 200, align: 'center',
    render: (row) => h('div', { style: 'display:flex;justify-content:center;gap:2px' }, [
      row.status === 'ready' && row.task_type !== 'us_segment'
        ? h(NButton, { size: 'small', text: true, type: 'primary', loading: exp === row.id, onClick: () => doExport(row) }, { default: () => '导出' })
        : null,
      row.status === 'ready'
        ? h(NButton, { size: 'small', text: true, type: 'primary', onClick: () => openPreview(row) }, { default: () => '预览' })
        : null,
      !row.is_best && row.status === 'ready'
        ? h(NButton, { size: 'small', text: true, type: 'primary', onClick: () => markBest(row) }, { default: () => '最佳' })
        : null,
      h(NButton, { size: 'small', text: true, type: 'error', onClick: () => remove(row) }, { default: () => '删除' }),
    ]),
  },
  ]
})
</script>

<template>
  <div>
    <div class="page-head">
      <h2>模型库</h2>
      <n-button type="primary" @click="dlg = true">导入模型</n-button>
    </div>

    <n-data-table :data="list" :columns="columns" :loading="loading" class="card" />

    <n-modal v-model:show="previewDlg" preset="card"
             :title="previewModel ? `${previewModel.name} 推理预览` : '推理预览'" style="width:760px">
      <div style="display:flex;gap:12px;margin-bottom:12px;align-items:center">
        <span style="font-size:0.85rem;color:var(--text-muted)">图像</span>
        <n-select v-model:value="previewImage" filterable :options="previewImageOptions" style="width:320px" placeholder="选择图像" />
        <n-button type="primary" :loading="previewLoading" @click="doPreview">推理</n-button>
        <span style="color:var(--text-muted);font-size:0.8rem">检测/分类走 ONNX，异常检测走特征库热图</span>
      </div>
      <n-spin :show="previewLoading" style="min-height:320px;text-align:center">
        <img v-if="previewResult" :src="previewResult" style="max-width:100%;border:1px solid var(--border);border-radius:4px" />
        <n-empty v-else description="选择图像并点击推理" :image-size="70" />
      </n-spin>
      <template #footer>
        <n-button @click="previewDlg = false">关闭</n-button>
      </template>
    </n-modal>

    <n-modal v-model:show="dlg" preset="card" title="导入外部模型" style="width:560px">
      <n-form label-placement="left" label-width="100">
        <n-form-item label="模型名称">
          <n-input v-model:value="form.name" placeholder="如：焊点检测 ONNX 版" />
        </n-form-item>
        <n-form-item label="任务类型">
          <n-select v-model:value="form.task_type" :options="taskTypeOptions" style="width:100%" />
        </n-form-item>
        <n-form-item label="框架">
          <n-select v-model:value="form.framework" :options="frameworkOptions" style="width:100%" />
        </n-form-item>
        <n-form-item label="架构">
          <n-input v-model:value="form.architecture" placeholder="如：yolo11s / custom-cnn-v2" />
        </n-form-item>
        <n-form-item label="文件路径">
          <n-input v-model:value="form.file_path" placeholder="服务器上的权重文件路径" />
        </n-form-item>
        <n-form-item label="输入尺寸">
          <div style="display:flex;align-items:center">
            <n-input-number v-model:value="form.input_w" :min="64" :step="32" style="width:110px" />
            <span style="margin:0 8px;color:var(--text-muted)">×</span>
            <n-input-number v-model:value="form.input_h" :min="64" :step="32" style="width:110px" />
          </div>
        </n-form-item>
        <n-form-item label="归一化">
          <n-select v-model:value="form.normalize" :options="normalizeOptions" style="width:100%" />
        </n-form-item>
        <n-form-item label="类别">
          <n-input v-model:value="form.categories" placeholder="逗号分隔，如：脏污,划痕,裂痕" />
        </n-form-item>
        <n-form-item label="预处理管线">
          <n-select v-model:value="form.preprocess_pipeline_id" clearable :options="pipelineOptions" style="width:100%" />
        </n-form-item>
      </n-form>
      <template #footer>
        <div style="display:flex;justify-content:flex-end;gap:8px">
          <n-button @click="dlg = false">取消</n-button>
          <n-button type="primary" @click="doImport">导入</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

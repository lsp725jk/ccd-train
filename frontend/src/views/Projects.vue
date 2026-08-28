<script setup>
import { computed, h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton, NDataTable, NTag, NModal, NForm, NFormItem, NInput, NEmpty,
  NGrid, NGi, NIcon, useMessage, useDialog,
} from 'naive-ui'
import { api } from '../api'
import { friendlyName, STATUS_LABEL, STATUS_TYPE, TASK_LABEL } from '../utils/format'
import { Plus, Delete } from '@element-plus/icons-vue'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const list = ref([])
const dia = ref(null)
const loading = ref(false)
const showCreate = ref(false)
const form = ref({ name: '', description: '' })

async function load() {
  loading.value = true
  try {
    list.value = await api.projects.list()
    try { dia.value = await api.dashboard.get() } catch { dia.value = null }
  } finally { loading.value = false }
}
onMounted(load)

const statCards = computed(() => {
  const t = dia.value?.totals || {}
  return [
    { label: '项目', value: t.projects ?? 0 },
    { label: '数据集', value: t.datasets ?? 0 },
    { label: '图像', value: (t.images ?? 0) >= 1000 ? (t.images / 1000).toFixed(1) + 'k' : (t.images ?? 0) },
    { label: '类别', value: t.categories ?? 0 },
    { label: '模型', value: t.models ?? 0 },
    { label: '训练任务', value: t.tasks ?? 0 },
  ]
})
const recentTasks = computed(() => dia.value?.recent_tasks || [])
const bestModels = computed(() => dia.value?.best_models || [])
const alerts = computed(() => dia.value?.alerts || [])

function bestMetric(m) {
  try {
    const d = JSON.parse(m.metrics || '{}')
    if (d.mAP50 != null) return { k: 'mAP50', v: d.mAP50 }
    if (d.mIoU != null) return { k: 'mIoU', v: d.mIoU }
    if (d.top1_acc != null) return { k: 'Top1', v: d.top1_acc }
    if (d.auroc_image != null) return { k: 'AUROC', v: d.auroc_image }
    if (d.pixel_acc != null) return { k: '像素精度', v: d.pixel_acc }
  } catch { /* ignore */ }
  return null
}

async function create() {
  if (!form.value.name.trim()) return message.warning('请输入项目名称')
  await api.projects.create({ ...form.value })
  message.success('项目已创建')
  showCreate.value = false
  form.value = { name: '', description: '' }
  load()
}

function remove(row) {
  dialog.warning({
    title: '确认删除',
    content: `删除项目「${row.name}」？其数据集与模型将一并删除。`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      await api.projects.remove(row.id)
      message.success('已删除')
      load()
    },
  })
}
function open(row) { router.push(`/projects/${row.id}/dataset`) }
function openTask(t) { router.push(`/projects/${t.project_id}/charts`) }
function openProject(pid) { router.push(`/projects/${pid}/dataset`) }

const columns = [
  { title: '项目名称', key: 'name', minWidth: 150 },
  { title: '描述', key: 'description', minWidth: 240, ellipsis: { tooltip: true } },
  { title: '缺陷类别', key: 'category_count', width: 100, align: 'center' },
  { title: '数据集', key: 'dataset_count', width: 90, align: 'center' },
  { title: '创建时间', key: 'created_at', width: 170 },
  {
    title: '操作', key: 'actions', width: 90, align: 'center',
    render: (row) => h(NButton, {
      size: 'small', quaternary: true, type: 'error',
      onClick: (e) => { e.stopPropagation(); remove(row) },
    }, { default: () => [h(NIcon, { style: 'margin-right:2px' }, { default: () => h(Delete) }), '删除'] }),
  },
]
</script>

<template>
  <div>
    <template v-if="dia">
      <n-grid :cols="6" :x-gap="12" :y-gap="12" responsive="screen" item-responsive class="dash-stats">
        <n-gi v-for="s in statCards" :key="s.label" span="3 m:1" class="stat-cell card">
          <div class="stat-value">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </n-gi>
      </n-grid>

      <div v-if="alerts.length" class="dash-alerts card">
        <div v-for="(a, i) in alerts" :key="i" class="alert-item" :class="`alert-${a.level}`">
          <span class="alert-dot"></span>
          <span class="alert-msg">{{ a.message }}</span>
          <n-button v-if="a.model_id" text type="primary" size="tiny" @click="openProject(a.project_id)">查看</n-button>
        </div>
      </div>

      <div class="dash-cols">
        <div class="card dash-col">
          <div class="dash-title">最近训练任务</div>
          <n-empty v-if="!recentTasks.length" description="暂无训练任务" size="small" style="padding:20px 0" />
          <div v-else class="recent-list">
            <div v-for="t in recentTasks" :key="t.id" class="recent-item" @click="openTask(t)">
              <div class="recent-main">
                <span class="recent-name">{{ friendlyName(t.model_name) || '未命名任务' }}</span>
                <span class="recent-meta">#{{ t.id }} · {{ t.project_name }} · {{ TASK_LABEL[t.task_type] || t.task_type }} · {{ t.engine }}</span>
              </div>
              <n-tag :type="STATUS_TYPE[t.status] || 'default'" size="small" :bordered="false">{{ STATUS_LABEL[t.status] || t.status }}</n-tag>
              <span class="recent-time">{{ (t.created_at || '').slice(5, 16) }}</span>
            </div>
          </div>
        </div>

        <div class="card dash-col">
          <div class="dash-title">各项目最佳模型</div>
          <n-empty v-if="!bestModels.length" description="暂无就绪模型" size="small" style="padding:20px 0" />
          <div v-else class="best-list">
            <div v-for="m in bestModels" :key="m.model_id" class="best-item" @click="openProject(m.project_id)">
              <div class="best-main">
                <span class="best-name">{{ friendlyName(m.name) }}</span>
                <span class="best-meta">{{ m.project_name }} · {{ TASK_LABEL[m.task_type] || m.task_type }}</span>
              </div>
              <span v-if="bestMetric(m)" class="best-metric">{{ bestMetric(m).k }} <b>{{ bestMetric(m).v }}</b></span>
              <n-tag v-if="m.is_best" type="success" size="small" :bordered="false">最佳</n-tag>
            </div>
          </div>
        </div>
      </div>
    </template>

    <div class="page-head">
      <h2>检测项目</h2>
      <n-button type="primary" @click="showCreate = true">
        <template #icon><n-icon><Plus /></n-icon></template>
        新建项目
      </n-button>
    </div>

    <n-data-table :data="list" :columns="columns" :loading="loading" class="card"
                  :row-props="(row) => ({ style: 'cursor:pointer', onClick: () => open(row) })" />

    <n-modal v-model:show="showCreate" preset="card" title="新建检测项目" style="width:480px">
      <n-form label-placement="left" label-width="80">
        <n-form-item label="项目名称">
          <n-input v-model:value="form.name" placeholder="如：焊点检测" />
        </n-form-item>
        <n-form-item label="描述">
          <n-input v-model:value="form.description" type="textarea" :rows="3" placeholder="检测对象、缺陷类型说明（可留空）" />
        </n-form-item>
      </n-form>
      <template #footer>
        <div style="display:flex;justify-content:flex-end;gap:8px">
          <n-button @click="showCreate = false">取消</n-button>
          <n-button type="primary" @click="create">创建</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.dash-stats { margin-bottom: 14px; }
.stat-cell { text-align: center; padding: 14px 8px; }
.stat-value { font-size: 1.5rem; font-weight: 700; color: var(--el-color-primary); }
.stat-label { font-size: 0.78rem; color: var(--text-muted); margin-top: 2px; }

.dash-alerts { margin-bottom: 14px; }
.alert-item { display: flex; align-items: center; gap: 8px; padding: 6px 0; font-size: 0.85rem; }
.alert-dot { width: 8px; height: 8px; border-radius: 50%; flex: 0 0 auto; }
.alert-error .alert-dot { background: #c9544e; }
.alert-warning .alert-dot { background: #d9a43c; }
.alert-info .alert-dot { background: var(--el-color-primary); }
.alert-msg { flex: 1; color: var(--text-color); }

.dash-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 16px; }
.dash-title { font-weight: 600; font-size: 0.95rem; margin-bottom: 10px; }
.recent-item, .best-item {
  display: flex; align-items: center; gap: 10px; padding: 7px 4px;
  border-bottom: 1px solid var(--border); cursor: pointer; border-radius: 4px;
}
.recent-item:hover, .best-item:hover { background: var(--bg-hover); }
.recent-main, .best-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.recent-name, .best-name { font-weight: 500; font-size: 0.88rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.recent-meta, .best-meta { font-size: 0.75rem; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.recent-time { font-size: 0.75rem; color: var(--text-light); white-space: nowrap; }
.best-metric { font-size: 0.8rem; color: var(--text-muted); white-space: nowrap; }
.best-metric b { color: var(--el-color-primary); }

@media (max-width: 1100px) { .dash-cols { grid-template-columns: 1fr; } }
</style>

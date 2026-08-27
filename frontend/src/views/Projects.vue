<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { friendlyName } from '../utils/format'
import { Plus, Delete } from '@element-plus/icons-vue'

const router = useRouter()
const list = ref([])
const dia = ref(null)
const loading = ref(false)
const dialog = ref(false)
const form = ref({ name: '', description: '' })

const STATUS_LABEL = { running: '运行中', queued: '排队中', success: '成功', failed: '失败', stopped: '已停止' }
const STATUS_TYPE = { running: 'primary', queued: 'info', success: 'success', failed: 'danger', stopped: 'warning' }
const TASK_LABEL = { detect: '检测', segment: '分割', classify: '分类', us_classify: '非监督分类', us_segment: '异常检测' }

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
  if (!form.value.name.trim()) return ElMessage.warning('请输入项目名称')
  await api.projects.create({ ...form.value })
  ElMessage.success('项目已创建')
  dialog.value = false
  form.value = { name: '', description: '' }
  load()
}

async function remove(row) {
  await ElMessageBox.confirm(`删除项目「${row.name}」？其数据集与模型将一并删除。`, '确认删除', { type: 'warning' })
  await api.projects.remove(row.id)
  ElMessage.success('已删除')
  load()
}

function open(row) { router.push(`/projects/${row.id}/dataset`) }
function openTask(t) { router.push(`/projects/${t.project_id}/charts`) }
function openProject(pid) { router.push(`/projects/${pid}/dataset`) }
</script>

<template>
  <div>
    <!-- 仪表盘概览 -->
    <template v-if="dia">
      <div class="dash-stats">
        <div class="stat-card card" v-for="s in statCards" :key="s.label">
          <div class="stat-value">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </div>

      <div v-if="alerts.length" class="dash-alerts card">
        <div v-for="(a, i) in alerts" :key="i" class="alert-item" :class="`alert-${a.level}`">
          <span class="alert-dot"></span>
          <span class="alert-msg">{{ a.message }}</span>
          <el-button v-if="a.model_id" link size="small" type="primary" @click="openProject(a.project_id)">查看</el-button>
        </div>
      </div>

      <div class="dash-cols">
        <div class="card dash-col">
          <div class="dash-title">最近训练任务</div>
          <el-empty v-if="!recentTasks.length" :image-size="50" description="暂无训练任务" />
          <div v-else class="recent-list">
            <div v-for="t in recentTasks" :key="t.id" class="recent-item" @click="openTask(t)">
              <div class="recent-main">
                <span class="recent-name">{{ friendlyName(t.model_name) || '未命名任务' }}</span>
                <span class="recent-meta">#{{ t.id }} · {{ t.project_name }} · {{ TASK_LABEL[t.task_type] || t.task_type }} · {{ t.engine }}</span>
              </div>
              <el-tag :type="STATUS_TYPE[t.status] || 'info'" size="small" effect="plain">
                {{ STATUS_LABEL[t.status] || t.status }}
              </el-tag>
              <span class="recent-time">{{ (t.created_at || '').slice(5, 16) }}</span>
            </div>
          </div>
        </div>

        <div class="card dash-col">
          <div class="dash-title">各项目最佳模型</div>
          <el-empty v-if="!bestModels.length" :image-size="50" description="暂无就绪模型" />
          <div v-else class="best-list">
            <div v-for="m in bestModels" :key="m.model_id" class="best-item" @click="openProject(m.project_id)">
              <div class="best-main">
                <span class="best-name">{{ friendlyName(m.name) }}</span>
                <span class="best-meta">{{ m.project_name }} · {{ TASK_LABEL[m.task_type] || m.task_type }}</span>
              </div>
              <span v-if="bestMetric(m)" class="best-metric">
                {{ bestMetric(m).k }} <b>{{ bestMetric(m).v }}</b>
              </span>
              <el-tag v-if="m.is_best" size="small" type="success" effect="plain">最佳</el-tag>
            </div>
          </div>
        </div>
      </div>
    </template>

    <div class="page-head">
      <h2>检测项目</h2>
      <el-button type="primary" @click="dialog = true"><el-icon style="margin-right:4px"><Plus /></el-icon>新建项目</el-button>
    </div>

    <el-table :data="list" v-loading="loading" class="card clickable" @row-click="open">
      <el-table-column prop="name" label="项目名称" min-width="150" />
      <el-table-column prop="description" label="描述" min-width="240" show-overflow-tooltip />
      <el-table-column prop="category_count" label="缺陷类别" width="100" align="center" />
      <el-table-column prop="dataset_count" label="数据集" width="90" align="center" />
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column label="" width="80" align="center">
        <template #default="{ row }">
          <el-button link type="danger" @click.stop="remove(row)"><el-icon><Delete /></el-icon><span style="margin-left:2px">删除</span></el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" title="新建检测项目" width="480px">
      <el-form label-width="80px">
        <el-form-item label="项目名称">
          <el-input v-model="form.name" placeholder="如：焊点检测" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="检测对象、缺陷类型说明（可留空）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="create">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dash-stats {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-bottom: 14px;
}
.stat-card { text-align: center; padding: 14px 8px; }
.stat-value { font-size: 1.5rem; font-weight: 700; color: var(--el-color-primary); }
.stat-label { font-size: 0.78rem; color: var(--text-muted); margin-top: 2px; }

.dash-alerts { margin-bottom: 14px; }
.alert-item { display: flex; align-items: center; gap: 8px; padding: 6px 0; font-size: 0.85rem; }
.alert-dot { width: 8px; height: 8px; border-radius: 50%; flex: 0 0 auto; }
.alert-error .alert-dot { background: #e15759; }
.alert-warning .alert-dot { background: #e6a23c; }
.alert-info .alert-dot { background: var(--el-color-primary); }
.alert-msg { flex: 1; color: var(--el-text-color-primary); }

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

@media (max-width: 1100px) {
  .dash-stats { grid-template-columns: repeat(3, 1fr); }
  .dash-cols { grid-template-columns: 1fr; }
}
</style>

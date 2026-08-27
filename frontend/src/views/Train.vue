<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { friendlyName } from '../utils/format'
import CurveChart from '../components/CurveChart.vue'
import ResultCard from '../components/ResultCard.vue'
import TaskItem from '../components/TaskItem.vue'

const route = useRoute()
const pid = Number(route.params.pid)

// ---- 表单 ----
const datasets = ref([])
const pipelines = ref([])
const augPipelines = ref([])
const engines = ref([])   // /api/engines 动态获取
const form = ref({
  name: '', task_type: 'detect', engine: '', dataset_ids: [],
  epochs: 100, imgsz_w: 640, imgsz_h: 640, batch: 16, custom_arch: '',
  preprocess_pipeline_id: null, aug_pipeline_id: null,
  aug_flip: true, aug_mosaic: 1.0, aug_mixup: 0.0, aug_hsv: 0.015,
})
const submitting = ref(false)
const showAug = ref(false)

// 模型视角预览（letterbox）
const viewImg = ref('')
const viewLoading = ref(false)
const viewInfo = ref(null)

// 按比例缩放（锁定宽高比，滑块调比例）
const ratioLock = ref(false)
const ratioVal = ref(50)
const origSize = ref(null)

async function getFirstImage() {
  if (!datasets.value.length) return null
  const dsid = form.value.dataset_ids?.length ? form.value.dataset_ids[0] : datasets.value[0].id
  const imgs = await api.datasets.images(dsid, { page: 1, page_size: 1 })
  return imgs.items[0] || null
}

function applyRatio(v) {
  if (!origSize.value) return
  form.value.imgsz_w = Math.max(64, Math.round(origSize.value[0] * v / 100 / 32) * 32)
  form.value.imgsz_h = Math.max(64, Math.round(origSize.value[1] * v / 100 / 32) * 32)
}

watch(ratioVal, applyRatio)
watch(ratioLock, async (on) => {
  if (on) {
    const im = await getFirstImage()
    if (im) {
      origSize.value = [im.width, im.height]
      ratioVal.value = 50
      applyRatio(50)
    } else {
      ratioLock.value = false
    }
  }
})

async function previewView() {
  if (!datasets.value.length) return ElMessage.warning('请先导入数据集')
  viewLoading.value = true
  try {
    const im = await getFirstImage()
    if (!im) return ElMessage.warning('数据集无图像')
    const r = await api.preview.resize({
      image_id: im.id, width: form.value.imgsz_w, height: form.value.imgsz_h,
    })
    viewImg.value = r.image
    viewInfo.value = r.info
  } finally {
    viewLoading.value = false
  }
}

const taskTypes = [
  { value: 'detect', label: '目标检测' },
  { value: 'segment', label: '语义分割' },
  { value: 'classify', label: '分类' },
  { value: 'us_classify', label: '非监督分类（聚类伪标签）' },
  { value: 'us_segment', label: '非监督分割（异常检测）' },
]
const enginesOf = computed(() => engines.value.filter(e => e.task_type === form.value.task_type))
const engineOptionsWithCustom = computed(() => [...enginesOf.value.map(e => e.id), 'custom'])

const augName = ref('')

function isUltra(p) {
  try {
    // 后端返回的 ops 可能是 JSON 字符串或数组，统一先解析
    const ops = typeof p?.ops === 'string' ? JSON.parse(p.ops || '[]') : (p?.ops || [])
    return Array.isArray(ops) && ops[0]?.name === '__ultra__'
  } catch { return false }
}

async function saveUltraAug() {
  if (!augName.value.trim()) return ElMessage.warning('请输入增强配置名称')
  await api.pipelines.create({
    project_id: pid, name: augName.value,
    ops: [{ name: '__ultra__', params: {
      flip: form.value.aug_flip, mosaic: form.value.aug_mosaic,
      mixup: form.value.aug_mixup, hsv: form.value.aug_hsv } }],
    type: 'aug',
  })
  ElMessage.success('增强配置已保存')
  augName.value = ''
  augPipelines.value = await api.pipelines.list(pid, 'aug')
}

async function applySafeAug() {
  const d = await api.scenes.safeAug()
  form.value.aug_flip = d.flip
  form.value.aug_mosaic = d.mosaic
  form.value.aug_mixup = d.mixup
  form.value.aug_hsv = d.hsv
  ElMessage.success('已应用工业安全增强：保守光照/几何参数，仅模拟产线物理变化')
}

async function onAugPipelineChange(id) {
  if (!id) return
  const p = augPipelines.value.find(x => x.id === id)
  if (p && isUltra(p)) {
    const params = p.ops[0].params || {}
    form.value.aug_flip = params.flip ?? form.value.aug_flip
    form.value.aug_mosaic = params.mosaic ?? form.value.aug_mosaic
    form.value.aug_mixup = params.mixup ?? form.value.aug_mixup
    form.value.aug_hsv = params.hsv ?? form.value.aug_hsv
  }
}

function applyEngineDefaults(id) {
  const spec = engines.value.find(e => e.id === id)
  if (spec?.defaults) {
    form.value.epochs = spec.defaults.epochs ?? form.value.epochs
    const d = spec.defaults.imgsz
    if (Array.isArray(d)) { form.value.imgsz_w = d[0]; form.value.imgsz_h = d[1] }
    else if (d) { form.value.imgsz_w = d; form.value.imgsz_h = d }
    form.value.batch = spec.defaults.batch ?? form.value.batch
  }
}

// ---- 任务列表 ----
const tasks = ref([])
const current = ref(null)
const loadingTasks = ref(false)

async function loadTasks() {
  loadingTasks.value = true
  try { tasks.value = await api.train.list(pid) } finally { loadingTasks.value = false }
}

// ---- 选中任务的轮询（曲线/日志/结果）----
const curve = ref({ columns: [], rows: [], exists: false })
const logLines = ref([])
const logOffset = ref(0)
const result = ref(null)
let curveTimer = null
let logTimer = null
const logBox = ref(null)

function stopPolling() {
  if (curveTimer) { clearInterval(curveTimer); curveTimer = null }
  if (logTimer) { clearInterval(logTimer); logTimer = null }
}

function selectTask(task) {
  current.value = task
  curve.value = { columns: [], rows: [], exists: false }
  logLines.value = []
  logOffset.value = 0
  result.value = null
  stopPolling()
  pollCurve()
  if (task.status === 'success') loadResult()
  if (['queued', 'running'].includes(task.status)) {
    curveTimer = setInterval(pollCurve, 5000)
    logTimer = setInterval(pollLog, 2000)
  }
}

async function pollCurve() {
  if (!current.value) return
  try {
    const c = await api.train.curve(current.value.id)
    curve.value = c
    if (!c.exists) return
    const detail = await api.train.get(current.value.id)
    current.value.progress = detail.progress
    const item = tasks.value.find(x => x.id === current.value.id)
    if (item) item.progress = detail.progress
    if (detail.status !== current.value.status) {
      current.value.status = detail.status
      if (detail.status === 'success' || detail.status === 'failed' || detail.status === 'stopped') {
        stopPolling()
        loadTasks()
        if (detail.status === 'success') loadResult()
      }
    }
  } catch { /* 任务目录可能还没建 */ }
}

async function pollLog() {
  if (!current.value) return
  try {
    const r = await api.train.log(current.value.id, logOffset.value)
    if (r.lines.length) {
      logLines.value.push(...r.lines)
      logOffset.value = r.offset
      if (logLines.value.length > 500) logLines.value = logLines.value.slice(-500)
      requestAnimationFrame(() => {
        if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
      })
    }
  } catch { /* ignore */ }
}

async function loadResult() {
  if (!current.value) return
  try { result.value = await api.models.result(current.value.model_id) } catch { /* ignore */ }
}

async function submit() {
  if (!form.value.name.trim()) return ElMessage.warning('请输入模型名称')
  if (!form.value.dataset_ids?.length) return ElMessage.warning('请选择至少一个数据集')
  submitting.value = true
  try {
    const { imgsz_w, imgsz_h, ...rest } = form.value
    const r = await api.train.create({
      project_id: pid, ...rest,
      imgsz: [imgsz_w, imgsz_h],
      engine: form.value.engine === 'custom' ? 'yolo11s' : form.value.engine,
    })
    ElMessage.success('训练任务已提交')
    form.value.name = ''
    await loadTasks()
    const t = tasks.value.find(x => x.id === r.task_id)
    if (t) selectTask(t)
  } finally { submitting.value = false }
}

async function stopTask(task) {
  await api.train.stop(task.id)
  ElMessage.info('停止信号已发送')
  loadTasks()
}

async function resubmitTask(task) {
  /** 重新提交：用原任务 config 填表单并提交。 */
  const cfg = task.config
  if (!cfg) return ElMessage.warning('任务配置缺失，无法重新提交')
  await ElMessageBox.confirm(
    `用任务 #${task.id}（${task.model_name}）的配置重新提交一次训练？`,
    '重新提交', { type: 'info' },
  ).catch(() => { throw 'cancel' })
  form.value = {
    name: task.model_name + ' (重试)',
    task_type: task.task_type,
    engine: task.engine === 'custom' ? 'custom' : task.engine,
    dataset_ids: cfg.dataset_ids || (cfg.dataset_id ? [cfg.dataset_id] : []),
    epochs: cfg.epochs ?? 100,
    imgsz_w: Array.isArray(cfg.imgsz) ? cfg.imgsz[0] : (cfg.imgsz ?? 640),
    imgsz_h: Array.isArray(cfg.imgsz) ? cfg.imgsz[1] : (cfg.imgsz ?? 640),
    batch: cfg.batch ?? 16,
    custom_arch: cfg.custom_arch || '',
    preprocess_pipeline_id: cfg.preprocess_pipeline_id ?? null,
    aug_pipeline_id: cfg.aug_pipeline_id ?? null,
    aug_flip: cfg.aug_flip ?? true,
    aug_mosaic: cfg.aug_mosaic ?? 1.0,
    aug_mixup: cfg.aug_mixup ?? 0.0,
    aug_hsv: cfg.aug_hsv ?? 0.015,
  }
  // 滚动到顶部表单
  window.scrollTo({ top: 0, behavior: 'smooth' })
  ElMessage.info('已填入原任务配置，检查后点击提交训练')
}

onMounted(async () => {
  engines.value = await api.train.engines()
  // 场景方案预填：项目创建时写入的 plan 直接带入训练表单
  let planPrefill = null
  try {
    const proj = await api.projects.get(pid)
    if (proj?.plan && proj.plan !== '{}') planPrefill = JSON.parse(proj.plan)
  } catch { /* 无方案时保持默认 */ }
  if (planPrefill?.engines?.length) {
    const e = planPrefill.engines[0]
    form.value.task_type = taskTypes.some(t => t.value === e.task_type) ? e.task_type : 'detect'
    form.value.engine = e.engine
  }
  if (planPrefill?.defaults) {
    const d = planPrefill.defaults
    if (d.epochs != null) form.value.epochs = d.epochs
    if (d.imgsz != null) { form.value.imgsz_w = d.imgsz; form.value.imgsz_h = d.imgsz }
    if (d.batch != null) form.value.batch = d.batch
  }
  if (!enginesOf.value.some(e => e.id === form.value.engine)) {
    form.value.engine = enginesOf.value[0]?.id || ''
  }
  datasets.value = await api.datasets.list(pid)
  pipelines.value = await api.pipelines.list(pid, 'pre')   // 预处理管线单独加载
  // 场景推荐了预处理且项目已自动建管线时，直接选中第一条
  if (planPrefill?.pre_ops?.length && pipelines.value.length) {
    form.value.preprocess_pipeline_id = pipelines.value[0].id
  }
  augPipelines.value = await api.pipelines.list(pid, 'aug')
  await loadTasks()
  if (tasks.value.length) selectTask(tasks.value[0])
})

onUnmounted(stopPolling)
</script>

<template>
  <div>
    <div class="page-head">
      <h2>训练中心</h2>
      <div>
        <el-button @click="$router.push(`/projects/${pid}/charts`)">曲线图表</el-button>
        <el-button @click="$router.push(`/projects/${pid}/results`)">训练效果</el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <!-- 左：表单 + 任务列表 -->
      <el-col :span="10">
        <div class="card" style="margin-bottom:12px">
          <div style="font-weight:600;margin-bottom:12px;font-size:0.95rem">新建训练任务</div>
                              <el-form label-width="90px" label-position="left">
            <el-form-item label="模型名称">
              <el-input v-model="form.name" placeholder="如：焊点检测 v1" />
            </el-form-item>
            <el-form-item label="任务类型">
              <el-select v-model="form.task_type" style="width:100%">
                <el-option v-for="t in taskTypes" :key="t.value" :value="t.value" :label="t.label" />
              </el-select>
            </el-form-item>
            <el-form-item label="模型档位">
              <el-select v-model="form.engine" style="width:100%" @change="applyEngineDefaults">
                <el-option v-for="e in engineOptionsWithCustom" :key="e" :value="e"
                           :label="e === 'custom' ? '自定义规模' : (engines.find(x => x.id === e)?.label || e)" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="form.engine === 'custom'" label="架构定义">
              <el-input v-model="form.custom_arch" placeholder="如：yolo11n-custom.yaml 或 scale=0.75" />
            </el-form-item>
            <el-form-item label="数据集">
              <el-select v-model="form.dataset_ids" multiple style="width:100%" placeholder="可多选，混合训练">
                <el-option v-for="d in datasets" :key="d.id" :value="d.id" :label="`${d.name}（${d.image_count} 张）`" />
              </el-select>
            </el-form-item>
            <el-form-item label="预处理管线">
              <el-select v-model="form.preprocess_pipeline_id" clearable style="width:100%" placeholder="可选的预处理管线">
                <el-option v-for="p in pipelines" :key="p.id" :value="p.id" :label="p.name" />
              </el-select>
            </el-form-item>
            <el-form-item label="增强管线">
              <el-select v-if="form.task_type === 'segment'" v-model="form.aug_pipeline_id" clearable style="width:100%" placeholder="自定义增强管线（分割训练应用）">
                <el-option v-for="p in augPipelines.filter(x => !isUltra(x))" :key="p.id" :value="p.id" :label="p.name" />
              </el-select>
              <el-select v-else v-model="form.aug_pipeline_id" clearable style="width:100%" placeholder="加载已保存的内置增强配置" @change="onAugPipelineChange">
                <el-option v-for="p in augPipelines.filter(isUltra)" :key="p.id" :value="p.id" :label="p.name" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="form.task_type === 'detect' || form.task_type === 'classify'" label="内置增强">
              <div style="width:100%">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 18px;margin-bottom:6px">
                  <el-checkbox v-model="form.aug_flip">水平翻转</el-checkbox>
                  <div class="aug-row">
                    <span>Mosaic</span>
                    <el-slider v-model="form.aug_mosaic" :min="0" :max="1" :step="0.1" size="small" style="flex:1" />
                    <b>{{ form.aug_mosaic }}</b>
                  </div>
                  <div class="aug-row">
                    <span>MixUp</span>
                    <el-slider v-model="form.aug_mixup" :min="0" :max="1" :step="0.05" size="small" style="flex:1" />
                    <b>{{ form.aug_mixup }}</b>
                  </div>
                  <div class="aug-row">
                    <span>HSV 扰动</span>
                    <el-slider v-model="form.aug_hsv" :min="0" :max="0.1" :step="0.005" size="small" style="flex:1" />
                    <b>{{ form.aug_hsv }}</b>
                  </div>
                </div>
                <div style="display:flex;gap:8px;align-items:center">
                  <el-input v-model="augName" placeholder="增强配置名称，保存为管线" size="small" style="max-width:220px" />
                  <el-button size="small" @click="saveUltraAug">保存增强</el-button>
                  <el-button size="small" type="primary" plain @click="applySafeAug">一键工业安全增强</el-button>
                  <span style="color:#8a8175;font-size:0.78rem">内置增强在训练时在线生效（Mosaic 等），配置可保存复用</span>
                </div>
              </div>
            </el-form-item>
            <el-row :gutter="8">
              <el-col :span="12">
                <el-form-item label="Epochs" label-width="60px">
                  <el-input-number v-model="form.epochs" :min="1" :max="2000" style="width:100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Batch" label-width="52px">
                  <el-input-number v-model="form.batch" :min="1" :max="256" style="width:100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="8" style="margin-bottom:4px">
              <el-col :span="8">
                <el-form-item label="输入宽" label-width="60px">
                  <el-input-number v-model="form.imgsz_w" :min="64" :max="8192" :step="32" style="width:100%" :disabled="ratioLock" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="输入高" label-width="60px">
                  <el-input-number v-model="form.imgsz_h" :min="64" :max="8192" :step="32" style="width:100%" :disabled="ratioLock" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="按比例">
                  <div style="display:flex;align-items:center;gap:8px;width:100%">
                    <el-checkbox v-model="ratioLock" />
                    <el-slider v-if="ratioLock" v-model="ratioVal" :min="10" :max="100" :step="5" size="small" style="flex:1" />
                    <span v-if="ratioLock" style="font-size:0.8rem;color:#4a6b4a;width:38px;text-align:right">{{ ratioVal }}%</span>
                  </div>
                </el-form-item>
              </el-col>
            </el-row>
            <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
              <el-button size="small" :loading="viewLoading" @click="previewView">模型视角预览</el-button>
              <span style="color:#8a8175;font-size:0.78rem">等比缩放 + 灰边填充到输入尺寸，建议宽高比与相机图像一致</span>
            </div>
            <img v-if="viewImg" :src="viewImg" style="max-width:100%;border:1px solid #d8cfbe;border-radius:4px" />
            <div v-if="viewInfo" style="margin-top:10px;font-size:0.82rem;color:#4a433c;line-height:1.8">
              <div>原图分辨率：{{ viewInfo.orig_size[0] }} × {{ viewInfo.orig_size[1] }} ｜ 输入尺寸：{{ viewInfo.input_size[0] }} × {{ viewInfo.input_size[1] }}
                   ｜ 缩放后：{{ viewInfo.resized_size[0] }} × {{ viewInfo.resized_size[1] }}（{{ Math.round(viewInfo.scale_ratio * 100) }}%）</div>
              <div>有效像素占比：{{ viewInfo.effective_ratio }}%（灰边以外）</div>
              <template v-if="viewInfo.defect_count">
                <div>缺陷 {{ viewInfo.defect_count }} 处，共 {{ viewInfo.defect_pixels_total }} px</div>
                <div v-for="(d, i) in viewInfo.defects" :key="i">
                  {{ d.category }}：{{ d.pixels }} px（原图 {{ d.ratio }}%）→ 输入尺寸 {{ d.input_pixels }} px
                </div>
              </template>
              <div v-else style="color:#8a8175">该图无缺陷标注（或标注类型非框/掩码）</div>
            </div>
          </el-form>
          <el-button type="primary" style="width:100%" :loading="submitting" @click="submit">
            提交训练
          </el-button>
          <div style="color:#8a8175;font-size:0.8rem;margin-top:8px">
            单 GPU 串行执行，一次只跑一个任务。支持检测 / 分割 / 分类 / 异常检测 / 聚类全部任务。
          </div>
        </div>

        <div class="card">
          <div style="font-weight:600;margin-bottom:10px;font-size:0.95rem">任务列表</div>
          <div v-loading="loadingTasks" style="max-height:360px;overflow-y:auto">
            <TaskItem v-for="t in tasks" :key="t.id" :task="t" :active="current?.id === t.id"
                      @select="selectTask" @stop="stopTask" @resubmit="resubmitTask" />
            <el-empty v-if="!tasks.length" description="暂无训练任务" :image-size="60" />
          </div>
        </div>
      </el-col>

      <!-- 右：详情 -->
      <el-col :span="14">
        <template v-if="current">
          <div class="card" style="margin-bottom:12px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
              <span style="font-weight:600;font-size:0.95rem">
                {{ friendlyName(current.model_name) }}
                <span style="color:#8a8175;font-weight:400;font-size:0.8rem">#{{ current.id }}</span>
              </span>
              <div>
                <el-button v-if="['queued', 'running'].includes(current.status)" size="small" type="danger" plain
                           @click="stopTask(current)">停止</el-button>
              </div>
            </div>
            <CurveChart v-if="curve.exists" :columns="curve.columns" :rows="curve.rows" />
            <el-empty v-else description="训练开始后显示实时曲线" :image-size="60" />
          </div>

          <div class="card" style="margin-bottom:12px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
              <span style="font-weight:600;font-size:0.95rem">训练日志</span>
              <span v-if="['queued','running'].includes(current.status)" style="color:#4a6b4a;font-size:0.8rem">● 实时</span>
            </div>
            <pre ref="logBox" class="log-box">{{ logLines.join('\n') || '等待日志…' }}</pre>
          </div>

          <div class="card">
            <div style="font-weight:600;margin-bottom:10px;font-size:0.95rem">评估结果</div>
            <ResultCard :result="result" />
          </div>
        </template>
        <el-empty v-else description="选择左侧任务查看详情" :image-size="80" style="margin-top:80px" />
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.log-box {
  background: #2a2622;
  color: #e8e6dc;
  font-family: Consolas, monospace;
  font-size: 0.78rem;
  padding: 10px 12px;
  border-radius: 4px;
  max-height: 240px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
.aug-row { display: flex; align-items: center; gap: 8px; }
.aug-row span { font-size: 0.8rem; color: #4a433c; white-space: nowrap; width: 62px; }
.aug-row b { font-size: 0.8rem; color: #4a6b4a; font-variant-numeric: tabular-nums; width: 34px; text-align: right; }
</style>

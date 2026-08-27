<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

const router = useRouter()
const scenes = ref([])
const customs = ref([])
const taskLabels = ref({})
const loading = ref(false)
const planLoading = ref(false)

const activeItem = ref(null)      // 内置物品（选中时）
const activeCustom = ref(null)    // 自定义方案（选中时）
const defects = ref([])
const customDefects = ref([])     // 用户自定义缺陷名（本地）
const customDefectInput = ref('')
const plan = ref(null)
const saveDialog = ref(false)
const saveForm = ref({ name: '', note: '' })

const ENGINE_LABELS = {
  yolo11n: 'YOLO11n', yolo11s: 'YOLO11s', yolo11m: 'YOLO11m',
  'yolo11n-cls': 'YOLO11n 分类', 'yolo11s-cls': 'YOLO11s 分类',
  unet_resnet18: 'UNet-ResNet18', unet_resnet50: 'UNet-ResNet50',
  deeplabv3p_resnet50: 'DeepLabV3+', patchcore: 'PatchCore',
}

async function load() {
  loading.value = true
  try {
    const data = await api.scenes.scenes()
    scenes.value = data.scenes
    customs.value = data.customs
    taskLabels.value = data.task_type_labels || {}
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function fetchPlan() {
  if (!activeItem.value) return
  planLoading.value = true
  try {
    const r = await api.scenes.plan({
      scene_id: activeItem.value.sceneId,
      item_id: activeItem.value.id,
      defect_names: defects.value,
    })
    plan.value = r.plan
  } finally {
    planLoading.value = false
  }
}

function selectItem(scene, item) {
  activeItem.value = { ...item, sceneId: scene.id, sceneName: scene.name }
  activeCustom.value = null
  customDefects.value = []
  defects.value = item.defects.map(d => d.name)
  plan.value = null
  fetchPlan()
}

function selectCustom(c) {
  activeCustom.value = c
  activeItem.value = null
  customDefects.value = []
  defects.value = c.defects || []
  plan.value = { engines: c.recommend?.engines || [], defaults: c.recommend?.defaults || {}, notes: c.recommend?.notes || [], pre_ops: c.recommend?.pre_ops || [], aug_ops: c.recommend?.aug_ops || [] }
}

async function removeCustom(c) {
  await ElMessageBox.confirm(`删除自定义方案「${c.name}」？`, '确认删除', { type: 'warning' })
  await api.scenes.removeCustom(c.name)
  if (activeCustom.value?.name === c.name) { activeCustom.value = null; plan.value = null }
  ElMessage.success('已删除')
  load()
}

function defectSummary() {
  if (!activeItem.value && !activeCustom.value) return ''
  return defects.value.join('、') || '（未勾选缺陷）'
}

function engineSummary() {
  if (!plan.value?.engines?.length) return ''
  return plan.value.engines.map(e => ENGINE_LABELS[e.engine] || e.engine).join(' + ')
}

function paramSummary() {
  if (!plan.value?.defaults) return ''
  const d = plan.value.defaults
  return `epochs=${d.epochs ?? '-'}, imgsz=${d.imgsz ?? '-'}, batch=${d.batch ?? '-'}`
}

function addCustomDefect() {
  const name = customDefectInput.value.trim()
  if (!name) return
  if (defects.value.includes(name) || customDefects.value.includes(name)) {
    customDefectInput.value = ''
    return
  }
  customDefects.value.push(name)
  defects.value.push(name)
  customDefectInput.value = ''
  fetchPlan()
}

function removeCustomDefect(name) {
  customDefects.value = customDefects.value.filter(d => d !== name)
  defects.value = defects.value.filter(d => d !== name)
  fetchPlan()
}

async function apply() {
  if (!plan.value) return ElMessage.warning('请先选择一个场景')
  const itemName = activeCustom.value?.item_name || activeItem.value?.name || '自定义'
  const lines = [
    `场景：${activeItem.value ? `${activeItem.value.sceneName} / ${itemName}` : itemName}`,
    `缺陷：${defectSummary()}`,
    `方案：${engineSummary()}`,
    `参数：${paramSummary()}`,
  ]
  if (plan.value.notes?.length) lines.push(`提示：${plan.value.notes.join('；')}`)
  const name = `${itemName.replace(/[\/\\]/g, '')}检测`
  const proj = await api.projects.create({ name, description: lines.join('\n'), plan: JSON.stringify(plan.value) })
  // 场景推荐了预处理/增强算子时，自动创建对应管线
  if (plan.value.pre_ops?.length) {
    try {
      await api.pipelines.create({
        project_id: proj.id,
        name: '场景推荐预处理',
        ops: plan.value.pre_ops,
        type: 'pre',
      })
    } catch { /* 同名管线已存在时忽略 */ }
  }
  if (plan.value.aug_ops?.length) {
    try {
      await api.pipelines.create({
        project_id: proj.id,
        name: '场景推荐增强',
        ops: plan.value.aug_ops,
        type: 'aug',
      })
    } catch { /* 同名管线已存在时忽略 */ }
  }
  ElMessage.success(`项目「${proj.name}」已创建，训练页已预填方案`)
  router.push(`/projects/${proj.id}/dataset`)
}

async function saveCustom() {
  if (!saveForm.value.name.trim()) return ElMessage.warning('请输入方案名称')
  if (!plan.value) return ElMessage.warning('没有可保存的方案')
  await api.scenes.saveCustom({
    name: saveForm.value.name.trim(),
    item_name: activeCustom.value?.item_name || activeItem.value?.name || '自定义',
    defects: defects.value,
    recommend: plan.value,
    note: saveForm.value.note.trim(),
  })
  ElMessage.success('自定义方案已保存')
  saveDialog.value = false
  saveForm.value = { name: '', note: '' }
  load()
}
</script>

<template>
  <div>
    <div class="page-head">
      <h2>场景方案</h2>
      <span style="font-size: 0.82rem; color: var(--text-muted)">按检测物品与缺陷类型，自动推荐模型组合</span>
    </div>

    <div style="display: flex; gap: 16px; align-items: flex-start">
      <!-- 左侧：场景树 -->
      <div class="card" style="width: 250px; flex-shrink: 0; padding: 10px; max-height: 70vh; overflow: auto">
        <div v-for="scene in scenes" :key="scene.id" style="margin-bottom: 8px">
          <div style="font-size: 0.82rem; font-weight: 500; color: var(--text-muted); padding: 4px 8px">{{ scene.name }}</div>
          <div
            v-for="item in scene.items" :key="item.id"
            class="scene-item" :class="{ active: activeItem?.id === item.id && !activeCustom }"
            @click="selectItem(scene, item)"
          >{{ item.name }}</div>
        </div>
        <div v-if="customs.length" style="border-top: 1px solid var(--border); margin-top: 8px; padding-top: 8px">
          <div style="font-size: 0.82rem; font-weight: 500; color: var(--text-muted); padding: 4px 8px">自定义方案</div>
          <div
            v-for="c in customs" :key="c.name"
            class="scene-item" :class="{ active: activeCustom?.name === c.name }"
            @click="selectCustom(c)"
          >{{ c.name }}</div>
        </div>
      </div>

      <!-- 主区：缺陷勾选 + 方案 -->
      <div class="card" style="flex: 1; min-width: 0; padding: 1rem 1.25rem" v-loading="planLoading">
        <template v-if="activeItem || activeCustom">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.8rem">
            <h3 style="margin: 0">{{ activeCustom?.item_name || `${activeItem.sceneName} / ${activeItem.name}` }}</h3>
            <div>
              <el-button @click="apply()" type="primary">应用方案（创建项目）</el-button>
              <el-button @click="saveDialog = true">保存为自定义方案</el-button>
            </div>
          </div>

          <div style="margin-bottom: 1rem">
            <div style="font-size: 0.85rem; font-weight: 500; margin-bottom: 6px">待检测缺陷类型</div>
            <el-checkbox-group v-model="defects" @change="fetchPlan">
              <el-checkbox v-for="d in (activeItem?.defects || activeCustom?.defects || [])" :key="d.name" :value="d.name">{{ d.name }}</el-checkbox>
              <el-checkbox v-for="d in customDefects" :key="d" :value="d">
                {{ d }}
                <el-icon style="cursor:pointer; margin-left:2px" @click.stop="removeCustomDefect(d)"><i class="el-icon-close"></i></el-icon>
              </el-checkbox>
            </el-checkbox-group>
            <div style="display: flex; gap: 8px; margin-top: 8px">
              <el-input v-model="customDefectInput" placeholder="自定义缺陷类型，回车添加" size="small" style="max-width: 260px" @keyup.enter="addCustomDefect" />
              <el-button size="small" @click="addCustomDefect">添加</el-button>
            </div>
          </div>

          <template v-if="plan">
            <div style="font-size: 0.85rem; font-weight: 500; margin-bottom: 6px">推荐模型组合</div>
            <div v-for="e in plan.engines" :key="e.engine" style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px">
              <span style="font-weight: 500">{{ ENGINE_LABELS[e.engine] || e.engine }}</span>
              <span class="tag" style="background: rgba(83,125,150,0.08); color: #3F6179">{{ e.role }}</span>
              <span class="tag" style="background: #E4ECF5; color: #1B365D">{{ taskLabels[e.task_type] || e.task_type }}</span>
            </div>

            <div v-if="plan.pre_ops?.length" style="font-size: 0.82rem; color: var(--text-light); margin: 0.4rem 0">
              建议预处理：<span v-for="(op, i) in plan.pre_ops" :key="i" style="margin-right: 8px">{{ op.enabled ? '✓' : '○' }} {{ op.name }}</span>
              <span style="color: var(--text-muted)">（应用方案时自动创建管线，可到训练页调整）</span>
            </div>
            <div v-if="plan.aug_ops?.length" style="font-size: 0.82rem; color: var(--text-light); margin: 0.4rem 0">
              建议增强：<span v-for="(op, i) in plan.aug_ops" :key="i" style="margin-right: 8px">{{ op.enabled ? '✓' : '○' }} {{ op.name }}</span>
              <span style="color: var(--text-muted)">（应用方案时自动创建增强管线）</span>
            </div>

            <div style="display: flex; gap: 24px; margin: 0.8rem 0">
              <label style="font-size: 0.82rem; color: var(--text-light)">
                epochs
                <el-input-number v-model="plan.defaults.epochs" :min="1" :max="1000" size="small" style="margin-left: 6px" />
              </label>
              <label style="font-size: 0.82rem; color: var(--text-light)">
                imgsz
                <el-input-number v-model="plan.defaults.imgsz" :min="64" :max="4096" :step="32" size="small" style="margin-left: 6px" />
              </label>
              <label style="font-size: 0.82rem; color: var(--text-light)">
                batch
                <el-input-number v-model="plan.defaults.batch" :min="1" :max="128" size="small" style="margin-left: 6px" />
              </label>
            </div>

            <div v-if="plan.notes?.length" style="font-size: 0.82rem; color: #9D5F4D; line-height: 1.6">
              <div v-for="(n, i) in plan.notes" :key="i">· {{ n }}</div>
            </div>
          </template>
        </template>
        <el-empty v-else description="从左侧选择检测物品，或点击自定义方案" />
      </div>
    </div>

    <el-dialog v-model="saveDialog" title="保存为自定义方案" width="420px">
      <el-form label-width="80px">
        <el-form-item label="方案名称">
          <el-input v-model="saveForm.name" placeholder="如：金属小缺陷高精度方案" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="saveForm.note" type="textarea" :rows="2" placeholder="适用场景、注意事项（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="saveDialog = false">取消</el-button>
        <el-button type="primary" @click="saveCustom">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.scene-item {
  padding: 6px 10px;
  border-radius: 4px;
  font-size: 0.85rem;
  cursor: pointer;
  color: var(--text-light);
}
.scene-item:hover { background: rgba(83, 125, 150, 0.08); }
.scene-item.active { background: rgba(83, 125, 150, 0.12); color: #3F6179; font-weight: 500; }
.tag {
  display: inline-flex; padding: 2px 8px; font-size: 0.75rem;
  font-weight: 500; border-radius: 4px;
}
</style>

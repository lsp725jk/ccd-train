<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NTree, NSpin, NButton, NInput, NCheckbox, NCheckboxGroup, NInputNumber,
  NModal, NForm, NFormItem, NIcon, NEmpty, useMessage, useDialog,
} from 'naive-ui'
import { Close } from '@element-plus/icons-vue'
import { api } from '../api'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()

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

// ---- 左侧场景树：内置场景(分组) + 物品(叶子) + 自定义方案分组 ----
const sceneTree = computed(() => {
  const nodes = scenes.value.map(s => ({
    key: `scene-${s.id}`,
    label: s.name,
    selectable: false,
    children: (s.items || []).map(it => ({
      key: `item-${s.id}-${it.id}`,
      label: it.name,
    })),
  }))
  if (customs.value.length) {
    nodes.push({
      key: 'custom-group',
      label: '自定义方案',
      selectable: false,
      children: customs.value.map(c => ({ key: `custom-${c.name}`, label: c.name })),
    })
  }
  return nodes
})
const expandedKeys = ref([])
watch(sceneTree, (nodes) => { expandedKeys.value = nodes.map(n => n.key) }, { immediate: true })
const activeKeys = computed(() => {
  if (activeCustom.value) return [`custom-${activeCustom.value.name}`]
  if (activeItem.value) return [`item-${activeItem.value.sceneId}-${activeItem.value.id}`]
  return []
})
function onTreeSelect(keys) {
  const k = keys && keys[0]
  if (!k) return
  if (k.startsWith('item-')) {
    const [, sceneId, itemId] = k.split('-')
    const scene = scenes.value.find(s => s.id === Number(sceneId))
    const item = scene?.items?.find(it => it.id === Number(itemId))
    if (scene && item) selectItem(scene, item)
  } else if (k.startsWith('custom-')) {
    const name = k.slice('custom-'.length)
    const c = customs.value.find(x => x.name === name)
    if (c) selectCustom(c)
  }
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

function removeCustom(c) {
  dialog.warning({
    title: '确认删除',
    content: `删除自定义方案「${c.name}」？`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      await api.scenes.removeCustom(c.name)
      if (activeCustom.value?.name === c.name) { activeCustom.value = null; plan.value = null }
      message.success('已删除')
      load()
    },
  })
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
  if (!plan.value) return message.warning('请先选择一个场景')
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
  message.success(`项目「${proj.name}」已创建，训练页已预填方案`)
  router.push(`/projects/${proj.id}/dataset`)
}

async function saveCustom() {
  if (!saveForm.value.name.trim()) return message.warning('请输入方案名称')
  if (!plan.value) return message.warning('没有可保存的方案')
  await api.scenes.saveCustom({
    name: saveForm.value.name.trim(),
    item_name: activeCustom.value?.item_name || activeItem.value?.name || '自定义',
    defects: defects.value,
    recommend: plan.value,
    note: saveForm.value.note.trim(),
  })
  message.success('自定义方案已保存')
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
        <n-tree :data="sceneTree" :selected-keys="activeKeys" :expanded-keys="expandedKeys"
                block-line :style="{ border: 'none' }"
                @update:selected-keys="onTreeSelect" @update:expanded-keys="k => expandedKeys = k" />
      </div>

      <!-- 主区：缺陷勾选 + 方案 -->
      <div class="card" style="flex: 1; min-width: 0; padding: 1rem 1.25rem">
        <n-spin :show="planLoading">
          <template v-if="activeItem || activeCustom">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.8rem">
              <h3 style="margin: 0">{{ activeCustom?.item_name || `${activeItem.sceneName} / ${activeItem.name}` }}</h3>
              <div>
                <n-button type="primary" @click="apply()">应用方案（创建项目）</n-button>
                <n-button @click="saveDialog = true">保存为自定义方案</n-button>
              </div>
            </div>

            <div style="margin-bottom: 1rem">
              <div style="font-size: 0.85rem; font-weight: 500; margin-bottom: 6px">待检测缺陷类型</div>
              <n-checkbox-group v-model:value="defects" class="defect-checks" @update:value="fetchPlan">
                <n-checkbox v-for="d in (activeItem?.defects || activeCustom?.defects || [])" :key="d.name" :value="d.name">{{ d.name }}</n-checkbox>
                <n-checkbox v-for="d in customDefects" :key="d" :value="d">
                  {{ d }}
                  <n-icon style="cursor:pointer; margin-left:2px" @click.stop="removeCustomDefect(d)"><Close /></n-icon>
                </n-checkbox>
              </n-checkbox-group>
              <div style="display: flex; gap: 8px; margin-top: 8px">
                <n-input v-model:value="customDefectInput" placeholder="自定义缺陷类型，回车添加" size="small" style="max-width: 260px" @keyup.enter="addCustomDefect" />
                <n-button size="small" @click="addCustomDefect">添加</n-button>
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
                  <n-input-number v-model:value="plan.defaults.epochs" :min="1" :max="1000" size="small" style="margin-left: 6px" />
                </label>
                <label style="font-size: 0.82rem; color: var(--text-light)">
                  imgsz
                  <n-input-number v-model:value="plan.defaults.imgsz" :min="64" :max="4096" :step="32" size="small" style="margin-left: 6px" />
                </label>
                <label style="font-size: 0.82rem; color: var(--text-light)">
                  batch
                  <n-input-number v-model:value="plan.defaults.batch" :min="1" :max="128" size="small" style="margin-left: 6px" />
                </label>
              </div>

              <div v-if="plan.notes?.length" style="font-size: 0.82rem; color: #9D5F4D; line-height: 1.6">
                <div v-for="(n, i) in plan.notes" :key="i">· {{ n }}</div>
              </div>
            </template>
          </template>
          <n-empty v-else description="从左侧选择检测物品，或点击自定义方案" />
        </n-spin>
      </div>
    </div>

    <n-modal v-model:show="saveDialog" preset="card" title="保存为自定义方案" style="width:420px">
      <n-form label-placement="left" label-width="80">
        <n-form-item label="方案名称">
          <n-input v-model:value="saveForm.name" placeholder="如：金属小缺陷高精度方案" />
        </n-form-item>
        <n-form-item label="备注">
          <n-input v-model:value="saveForm.note" type="textarea" :rows="2" placeholder="适用场景、注意事项（可选）" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-button @click="saveDialog = false">取消</n-button>
        <n-button type="primary" @click="saveCustom">保存</n-button>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.defect-checks {
  display: flex;
  flex-wrap: wrap;
  column-gap: 20px;
  row-gap: 8px;
}
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

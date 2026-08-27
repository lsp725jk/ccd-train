<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'select'])

const drives = ref([])
const path = ref('')
const dirs = ref([])
const parent = ref('')
const loading = ref(false)
const error = ref('')

async function loadDrives() {
  drives.value = await api.fs.drives()
  if (drives.value.length && !path.value) {
    await open(drives.value[0])
  }
}

async function open(p) {
  loading.value = true
  error.value = ''
  try {
    const r = await api.fs.list(p)
    path.value = r.path
    parent.value = r.parent
    dirs.value = r.dirs
    emit('update:modelValue', r.path)
  } catch (e) {
    error.value = String(e.response?.data?.detail || e.message)
  } finally {
    loading.value = false
  }
}

function enter(name) {
  open(path.value.endsWith('\\') ? path.value + name : path.value + '\\' + name)
}

function up() {
  if (parent.value) open(parent.value)
}

function pick() {
  emit('select', path.value)
}

onMounted(loadDrives)
</script>

<template>
  <div class="dir-picker">
    <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px;flex-wrap:wrap">
      <el-select v-model="path" size="small" style="width:130px" @change="open">
        <el-option v-for="d in drives" :key="d" :value="d" :label="d" />
      </el-select>
      <el-button size="small" @click="up" :disabled="!parent">上一级</el-button>
      <el-button size="small" @click="loadDrives">刷新</el-button>
      <span style="font-size:0.8rem;color:#4a433c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;direction:rtl;text-align:left">
        {{ path }}
      </span>
    </div>
    <div v-loading="loading" class="dir-list">
      <div v-for="d in dirs" :key="d" class="dir-item" @click="enter(d)">
        <span class="dir-icon"></span>
        <span>{{ d }}</span>
      </div>
      <div v-if="!dirs.length && !loading" style="color:#8a8175;font-size:0.82rem;padding:14px">
        此目录下没有子文件夹，可直接选择当前目录
      </div>
    </div>
    <div v-if="error" style="color:#8b2c1f;font-size:0.8rem;margin-top:6px">{{ error }}</div>
    <div style="display:flex;justify-content:flex-end;margin-top:10px">
      <el-button size="small" type="primary" :disabled="!path" @click="pick">选择此文件夹</el-button>
    </div>
  </div>
</template>

<style scoped>
.dir-list {
  border: 1px solid #d8cfbe;
  border-radius: 4px;
  max-height: 240px;
  overflow-y: auto;
  background: #fbf8f1;
}
.dir-item {
  display: flex;
  gap: 8px;
  padding: 7px 12px;
  cursor: pointer;
  font-size: 0.85rem;
  border-bottom: 0.5px solid rgba(0, 0, 0, 0.05);
  align-items: center;
}
.dir-item:hover { background: #eef3ee; }
.dir-icon {
  width: 12px; height: 10px;
  border: 1.5px solid #4a6b4a;
  border-radius: 2px;
  position: relative;
  flex-shrink: 0;
}
.dir-icon::before {
  content: '';
  position: absolute;
  top: -4px; left: 1px;
  width: 5px; height: 3px;
  background: #4a6b4a;
  border-radius: 1px 1px 0 0;
}
</style>

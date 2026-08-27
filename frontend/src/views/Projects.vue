<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

const router = useRouter()
const list = ref([])
const loading = ref(false)
const dialog = ref(false)
const form = ref({ name: '', description: '' })

async function load() {
  loading.value = true
  try { list.value = await api.projects.list() } finally { loading.value = false }
}
onMounted(load)

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
</script>

<template>
  <div>
    <div class="page-head">
      <h2>检测项目</h2>
      <el-button type="primary" @click="dialog = true">新建项目</el-button>
    </div>

    <el-table :data="list" v-loading="loading" class="card clickable" @row-click="open">
      <el-table-column prop="name" label="项目名称" min-width="150" />
      <el-table-column prop="description" label="描述" min-width="240" show-overflow-tooltip />
      <el-table-column prop="category_count" label="缺陷类别" width="100" align="center" />
      <el-table-column prop="dataset_count" label="数据集" width="90" align="center" />
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column label="" width="80" align="center">
        <template #default="{ row }">
          <el-button link type="danger" @click.stop="remove(row)">删除</el-button>
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

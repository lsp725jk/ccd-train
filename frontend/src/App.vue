<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { routes } from './router'
import { api } from './api'

const route = useRoute()
const pid = computed(() => (route.params.pid ? Number(route.params.pid) : null))
const project = ref(null)

watch(pid, async (id) => {
  project.value = null
  if (id) {
    try { project.value = await api.projects.get(id) } catch { /* 项目可能已删除 */ }
  }
}, { immediate: true })

const activeMenu = computed(() => {
  if (route.name === 'projects') return '/'
  return `/projects/${route.params.pid}/${route.name}`
})

/** 菜单由路由声明生成：meta.menu 出现即显示；meta.project 表示项目内页面。 */
const projectMenus = computed(() => {
  if (!pid.value) return []
  return routes
    .filter(r => r.meta?.menu && r.meta?.project)
    .map(r => ({ path: `/projects/${pid.value}/${r.name}`, label: r.meta.menu }))
})
</script>

<template>
  <el-container class="app">
    <el-aside width="200px" class="aside">
      <div class="logo">CCD Train</div>
      <el-menu :default-active="activeMenu" router>
        <el-menu-item index="/">项目管理</el-menu-item>
        <el-menu-item index="/scenes">场景方案</el-menu-item>
        <template v-if="pid">
          <div class="menu-divider">{{ project?.name || '项目' }}</div>
          <el-menu-item v-for="item in projectMenus" :key="item.path" :index="item.path">
            {{ item.label }}
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header" height="48px">
        <span v-if="pid" class="project-name">{{ project?.name || '…' }}</span>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

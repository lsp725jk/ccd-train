<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { routes } from './router'
import { api } from './api'
import {
  Grid, Compass, FolderOpened, EditPen, MagicStick, DataAnalysis,
  VideoPlay, TrendCharts, PieChart, Box, Monitor, Fold, Expand, Refresh,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const pid = computed(() => (route.params.pid ? Number(route.params.pid) : null))
const project = ref(null)
const collapsed = ref(false)

// 主题：浅/深切换，localStorage 持久化
const dark = ref(false)
function applyTheme() {
  document.documentElement.classList.toggle('dark', dark.value)
}
function toggleTheme() {
  dark.value = !dark.value
  applyTheme()
  try { localStorage.setItem('ccd-theme', dark.value ? 'dark' : 'light') } catch { /* ignore */ }
  window.dispatchEvent(new CustomEvent('ccd-theme', { detail: dark.value }))
}
onMounted(() => {
  try { dark.value = localStorage.getItem('ccd-theme') === 'dark' } catch { /* ignore */ }
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches && !localStorage.getItem('ccd-theme')) {
    dark.value = true
  }
  applyTheme()
})

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

const projectMenus = computed(() => {
  if (!pid.value) return []
  return routes
    .filter(r => r.meta?.menu && r.meta?.project)
    .map(r => ({ path: `/projects/${pid.value}/${r.name}`, label: r.meta.menu, icon: r.meta.icon }))
})

// 面包屑
const crumbs = computed(() => {
  const c = []
  if (pid.value && project.value) c.push({ label: project.value.name })
  if (route.meta?.menu) c.push({ label: route.meta.menu })
  return c
})

function goHome() { router.push('/') }
function refresh() { router.replace({ path: route.path, query: { ...route.query, _t: Date.now() } }) }
</script>

<template>
  <div class="app">
    <!-- 顶栏 -->
    <header class="navbar">
      <div class="nav-left">
        <el-button circle text size="small" class="collapse-btn" @click="collapsed = !collapsed">
          <el-icon :size="18"><component :is="collapsed ? Expand : Fold" /></el-icon>
        </el-button>
        <div class="logo" @click="goHome">
          <span class="logo-mark"><el-icon><Monitor /></el-icon></span>
          <span class="logo-text">CCD Train</span>
        </div>
      </div>
      <nav class="crumbs">
        <span class="crumb crumb-home" @click="goHome">模型训练平台</span>
        <template v-for="c in crumbs" :key="c.label">
          <span class="crumb-sep">/</span>
          <span class="crumb">{{ c.label }}</span>
        </template>
      </nav>
      <div class="nav-right">
        <el-tooltip content="刷新" placement="bottom">
          <el-button circle text size="small" @click="refresh"><el-icon><Refresh /></el-icon></el-button>
        </el-tooltip>
        <el-tooltip :content="dark ? '切换到浅色' : '切换到深色'" placement="bottom">
          <el-button circle text size="small" @click="toggleTheme">
            <span style="font-size:1.05rem">{{ dark ? '☀️' : '🌙' }}</span>
          </el-button>
        </el-tooltip>
      </div>
    </header>

    <div class="body">
      <!-- 侧栏 -->
      <aside class="aside" :class="{ collapsed }" :style="{ width: collapsed ? '64px' : '210px' }">
        <el-menu :default-active="activeMenu" router :collapse="collapsed" :collapse-transition="false">
          <el-menu-item index="/">
            <el-icon><Grid /></el-icon><template #title>项目管理</template>
          </el-menu-item>
          <el-menu-item index="/scenes">
            <el-icon><Compass /></el-icon><template #title>场景方案</template>
          </el-menu-item>

          <template v-if="pid">
            <div class="menu-divider">{{ project?.name || '项目' }}</div>
            <el-menu-item v-for="item in projectMenus" :key="item.path" :index="item.path">
              <el-icon><component :is="item.icon" /></el-icon><template #title>{{ item.label }}</template>
            </el-menu-item>
          </template>
        </el-menu>
      </aside>

      <!-- 主内容 -->
      <main class="main">
        <router-view />
      </main>
    </div>
  </div>
</template>

<style scoped>
.app { height: 100%; display: flex; flex-direction: column; }

.navbar {
  height: 56px; flex: 0 0 auto;
  display: flex; align-items: center; gap: 12px;
  padding: 0 16px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.nav-left { display: flex; align-items: center; gap: 6px; }
.collapse-btn { color: var(--el-text-color-regular); }
.logo { display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; }
.logo-mark {
  width: 28px; height: 28px; border-radius: 7px; display: inline-flex;
  align-items: center; justify-content: center; color: #fff;
  background: linear-gradient(135deg, #4a6b4a, #3b563b);
}
.logo-text { font-weight: 700; letter-spacing: 1px; color: var(--el-color-primary); font-size: 1rem; }

.crumbs { display: flex; align-items: center; gap: 6px; font-size: 0.85rem; color: var(--text-muted); flex: 1; min-width: 0; }
.crumb-home { cursor: pointer; color: var(--el-color-primary); font-weight: 500; }
.crumb { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.crumb-sep { color: var(--text-light); }

.nav-right { display: flex; align-items: center; gap: 4px; }

.body { flex: 1; min-height: 0; display: flex; }
.aside {
  flex: 0 0 auto; overflow-y: auto;
  background: var(--bg-accent);
  border-right: 1px solid var(--border);
  transition: width 0.15s ease;
}
.aside .el-menu { border-right: none; background: transparent; }
.aside.collapsed .el-menu { width: 64px; }
.menu-divider {
  margin: 10px 14px 4px; font-size: 0.72rem; color: var(--text-muted);
  border-bottom: 1px solid var(--border); padding-bottom: 6px;
  padding-left: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.main { flex: 1; min-width: 0; overflow-y: auto; padding: 20px; }
</style>

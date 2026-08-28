<script setup>
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NLayout, NLayoutSider, NLayoutContent, NConfigProvider, NMessageProvider,
  NDialogProvider, NMenu, NButton, NTooltip, NIcon, NBreadcrumb, NBreadcrumbItem,
} from 'naive-ui'
import { routes } from './router'
import { api } from './api'
import { naiveThemeOverrides, darkTheme } from './theme'
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
function applyTheme() { document.documentElement.classList.toggle('dark', dark.value) }
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

const projectMenus = computed(() => {
  if (!pid.value) return []
  return routes
    .filter(r => r.meta?.menu && r.meta?.project)
    .map(r => ({ path: `/projects/${pid.value}/${r.name}`, label: r.meta.menu, icon: r.meta.icon }))
})

const activeMenu = computed(() => {
  if (route.name === 'projects') return '/'
  return `/projects/${route.params.pid}/${route.name}`
})

const renderIcon = (icon) => () => h(NIcon, { size: 18 }, { default: () => h(icon) })
const menuOptions = computed(() => {
  const opts = [
    { label: '项目管理', key: '/', icon: renderIcon(Grid) },
    { label: '场景方案', key: '/scenes', icon: renderIcon(Compass) },
  ]
  if (pid.value) {
    opts.push({
      type: 'group', key: 'project', label: project.value?.name || '项目',
      children: projectMenus.value.map(m => ({ label: m.label, key: m.path, icon: renderIcon(m.icon) })),
    })
  }
  return opts
})

const crumbs = computed(() => {
  const c = []
  if (pid.value && project.value) c.push({ label: project.value.name })
  if (route.meta?.menu) c.push({ label: route.meta.menu })
  return c
})

function onMenuSelect(key) { router.push(key) }
function goHome() { router.push('/') }
function refresh() { router.replace({ path: route.path, query: { ...route.query, _t: Date.now() } }) }
</script>

<template>
  <n-config-provider :theme="dark ? darkTheme : null" :theme-overrides="naiveThemeOverrides">
    <n-message-provider>
      <n-dialog-provider>
        <div class="app">
          <header class="navbar">
            <div class="nav-left">
              <n-button quaternary circle size="small" @click="collapsed = !collapsed" class="collapse-btn">
                <template #icon><n-icon :size="18"><component :is="collapsed ? Expand : Fold" /></n-icon></template>
              </n-button>
              <div class="logo" @click="goHome">
                <span class="logo-mark"><n-icon><Monitor /></n-icon></span>
                <span class="logo-text">CCD Train</span>
              </div>
            </div>
            <n-breadcrumb class="crumbs">
              <n-breadcrumb-item><a class="crumb-home" @click.prevent="goHome">模型训练平台</a></n-breadcrumb-item>
              <n-breadcrumb-item v-for="c in crumbs" :key="c.label">{{ c.label }}</n-breadcrumb-item>
            </n-breadcrumb>
            <div class="nav-right">
              <n-tooltip><template #trigger><n-button quaternary circle size="small" @click="refresh"><template #icon><n-icon><Refresh /></n-icon></template></n-button></template>刷新</n-tooltip>
              <n-tooltip><template #trigger><n-button quaternary circle size="small" @click="toggleTheme"><span style="font-size:1.05rem">{{ dark ? '☀️' : '🌙' }}</span></n-button></template>{{ dark ? '切换到浅色' : '切换到深色' }}</n-tooltip>
            </div>
          </header>

          <n-layout has-sider class="body">
            <n-layout-sider
              bordered :width="210" :collapsed-width="64"
              :collapsed="collapsed" collapse-mode="width"
              :native-scrollbar="false" class="aside">
              <n-menu
                :value="activeMenu" :options="menuOptions"
                :collapsed="collapsed" :collapsed-width="64" :collapsed-icon-size="18"
                :indent="16" @update:value="onMenuSelect" />
            </n-layout-sider>
            <n-layout-content class="main" :native-scrollbar="false">
              <router-view />
            </n-layout-content>
          </n-layout>
        </div>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<style scoped>
.app { height: 100%; display: flex; flex-direction: column; }
.navbar {
  height: 56px; flex: 0 0 auto;
  display: flex; align-items: center; gap: 12px; padding: 0 16px;
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
.crumbs { flex: 1; min-width: 0; }
.crumb-home { color: var(--el-color-primary); font-weight: 500; cursor: pointer; }
.nav-right { display: flex; align-items: center; gap: 4px; }
.body { flex: 1; min-height: 0; }
.aside { transition: width 0.15s ease; }
.main { padding: 20px; overflow-y: auto; }
</style>

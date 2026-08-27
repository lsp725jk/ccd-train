import { createRouter, createWebHistory } from 'vue-router'

/** 路由声明：加页面 = 加一条记录。meta.menu 出现即显示在侧边栏菜单。 */
export const routes = [
  { path: '/', name: 'projects', component: () => import('./views/Projects.vue'), meta: { menu: '项目管理' } },
  { path: '/scenes', name: 'scenes', component: () => import('./views/Scenes.vue'), meta: { menu: '场景方案' } },
  { path: '/projects/:pid/dataset', name: 'dataset', component: () => import('./views/Dataset.vue'), meta: { menu: '数据集', project: true } },
  { path: '/projects/:pid/labeling', name: 'labeling', component: () => import('./views/Labeling.vue'), meta: { menu: '标注', project: true } },
  { path: '/projects/:pid/preprocess', name: 'preprocess', component: () => import('./views/Preprocess.vue'), meta: { menu: '预处理 · 增强', project: true } },
  { path: '/projects/:pid/cluster', name: 'cluster', component: () => import('./views/Cluster.vue'), meta: { menu: '聚类', project: true } },
  { path: '/projects/:pid/train', name: 'train', component: () => import('./views/Train.vue'), meta: { menu: '训练中心', project: true } },
  { path: '/projects/:pid/charts', name: 'charts', component: () => import('./views/Charts.vue'), meta: { menu: '图表', project: true } },
  { path: '/projects/:pid/results', name: 'results', component: () => import('./views/Results.vue'), meta: { menu: '训练效果', project: true } },
  { path: '/projects/:pid/models', name: 'models', component: () => import('./views/Models.vue'), meta: { menu: '模型库', project: true } },
]

export default createRouter({ history: createWebHistory(), routes })

# 前端（Vue 3）开发指南

Vue 3 `<script setup>` + Vite + **Naive UI**（已从 Element Plus 全量迁移）+ ECharts（按需引入）+ axios。

## 目录结构

```
frontend/src/
├── main.js            # 入口（createApp + router）
├── App.vue            # 外壳：主题切换、侧栏（四阶段工作流分组）、面包屑、router-view（pid 级 key 隔离）
├── router.js          # 路由表（每路由 meta.menu/meta.icon，项目页 /projects/:pid/xxx）
├── theme.js           # NaiveUI 主题覆盖（绿色工业风）+ 暗色主题
├── style.css          # 全局 CSS 变量（--el-* 兼容变量 / --bg-surface / --border 等）
├── api/               # axios 封装（http.js：Naive createDiscreteApi 报错提示）+ 各模块 API
├── utils/
│   ├── labeling.js    # 几何：点在线段/多边形射线法
│   ├── rle.js         # RLE 位图编解码（与后端 rle.py 对称：maskToRle/rleToMask/位图工具）
│   ├── echarts.js     # echarts 按需注册（LineChart + 基础组件）
│   └── format.js      # 状态/任务文案格式化（含 " (重试)×N" 折叠）
├── components/        # DirectoryPicker（目录选择器）/ ReviewBox（框选评审 FAB）/ 图表卡片等
└── views/             # 页面（见路由表）
```

## 页面与路由

| 路由 | 页面 | 说明 |
|---|---|---|
| `/` | Projects.vue | 项目管理（新建/删除/描述编辑） |
| `/scenes` | Scenes.vue | 场景方案 |
| `/projects/:pid/dataset` | Dataset.vue | 数据集：导入/图像网格/类别管理/**标注傻瓜式导入**/划分/增强 |
| `/projects/:pid/labeling` | Labeling.vue | **标注工作台**（最复杂，~1600 行） |
| `/projects/:pid/preprocess` | Preprocess.vue | 预处理/增强管线 + 实时预览 |
| `/projects/:pid/cluster` | Cluster.vue | 聚类分析 |
| `/projects/:pid/train` | Train.vue | 训练中心（提交/队列/日志实时滚动） |
| `/projects/:pid/charts` | Charts.vue | 训练曲线（ECharts） |
| `/projects/:pid/results` | Results.vue | 训练效果（指标对比） |
| `/projects/:pid/models` | Models.vue | 模型库 + 导出 + 推理预览 |

> 跨项目跳转：App.vue 的 `<router-view :key="pid:name">` 强制重建组件，避免 setup 一次性捕获的 `pid` 陈旧；
> 新页面必须遵循此约定（不要缓存 `route.params.pid` 为裸值）。

## 标注工作台（Labeling.vue）要点

- **Canvas 分层**：图像 `<img>` + overlay（标注/网格）+ cursor（笔刷光标），容器可滚动/平移/缩放
- **缩放**：`displayScale = fitScale × viewScale`；缩放上限按图像尺寸动态计算（canvas ≤ 8192，防浏览器 16384 上限画布空白）；工具栏「1:1」按钮 = 原始像素视图；像素网格随缩放自适应步长
- **掩码编辑**：本地位图缓存 `maskBits`（RLE 解码懒加载）→ 橡皮擦/笔刷**本地先行**（视觉零延迟）+ 60ms 节流提交后端；渲染走 bbox 区域位图合成（`drawMaskFill`）
- **撤销/重做**：`hist` 快照栈（≤60）→ 恢复采用**先建后删 + 互斥锁**（防连按交错/标准丢失）
- **形状编辑**：参考 X-AnyLabeling 模式——选中后拖动整体/顶点；位图标注移动时同步平移位图并重编码 RLE
- **竞态防护**：切图请求序号（annsReqSeq）、预览序号（refreshSeq）、eraseTimer 卸载清理

## 开发命令

```bat
:: 开发（代理 /api → 127.0.0.1:8000，需先起后端）
npm run dev

:: 构建（产物 frontend/dist，后端自动托管为单端口应用）
npm run build
```

## 约定

- 组件库一律用 Naive UI（禁止 Element Plus；图标可用 `@element-plus/icons-vue`）
- API 错误提示：`api/http.js` 拦截器统一 Naive message；组件内 `message.error(String(e.response?.data?.detail || e.message))`
- 主题：CSS 变量在 `style.css`，主题对象在 `theme.js`；暗色切换派发 `ccd-theme` 事件（图表等监听重绘）
- 大组件（Labeling.vue 1600+ 行）拆分时优先提取到 `utils/` 或 `composables/`，避免跨文件共享状态

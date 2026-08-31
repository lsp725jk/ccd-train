# CCD Train 模型训练平台

面向工业缺陷检测的**一站式标注 + 训练 + 评估 + 部署**平台。支持 YOLO 检测/分类、语义分割（SMP）、无监督异常检测（PatchCore）、数据增强与预处理管线，提供独立可交付的 Windows 安装版（exe + Inno Setup 安装包）。

## 功能总览

| 阶段 | 功能 |
|---|---|
| **数据准备** | 数据集导入（文件夹扫描）、YOLO/LabelMe/COCO 标注**傻瓜式导入**（选文件夹自动识别）、划分训练/验证/测试集、离线增强扩充（albumentations 全算子） |
| **标注** | Canvas 标注工作台：框/多边形/椭圆/掩码/整图分类、SAM 智能标注（点/框提示）、多像素橡皮擦、**RLE 位图掩码存储**（逐像素精确）、撤销/重做、形状编辑、1:1 像素视图 + 逐像素网格、无标签图像优先 |
| **模型训练** | YOLO11 检测/分类、SMP 分割（DeepLabV3+/U-Net 等）、PatchCore 异常检测、多数据集混合训练、预处理/增强管线、单 GPU 串行队列 + 子进程隔离 |
| **评估分析** | 训练曲线（损失/mAP/mIoU/精度/召回）、最佳模型、训练效果对比、聚类分析 |
| **部署** | 模型库管理、ONNX 导出、推理预览（预测明细/可视化）、导入外部模型 |

## 技术栈

- **后端**：Python 3.11 · FastAPI · SQLite（零额外依赖，标准库驱动）· ultralytics 8.4 · segmentation-models-pytorch · albumentations 2.0.8 · torch 2.13 (CUDA)
- **前端**：Vue 3 · Vite · Naive UI · ECharts（按需引入）· axios
- **交付**：PyInstaller onedir + Inno Setup 安装程序（自带 CUDA 运行时，目标机免装 Python/CUDA）

## 快速开始

### 源码运行（开发）
```bat
install.bat      :: 首次部署：创建 venv + 安装 torch(CUDA) + 依赖
start.bat        :: 一键启动：uvicorn 127.0.0.1:8000（浏览器访问 http://localhost:8000）
```

### 安装版（交付用户）
```bat
CCDTrain-Setup-0.2.0.exe   :: 静默/向导安装；安装后桌面/开始菜单快捷方式启动
```
安装目录 `%LOCALAPPDATA%\Programs\CCDTrain`；数据（数据库/训练产物）存应用目录 `data/`；卸载时可选择是否删除数据。

> 配套工具：安装目录内附 **X-AnyLabeling-CPU.exe**（独立标注工作台，双击即用，支持 SAM 自动标注）。

## 目录结构

```
ccd-train/
├── backend/
│   ├── app/                 # FastAPI 应用
│   │   ├── routers/         # API 路由（annotations/训练/数据集/导出/预测…）
│   │   ├── engines/         # 训练引擎（YOLO/SMP/PatchCore）+ RLE 编解码 + 数据工具
│   │   ├── services/        # 训练任务队列
│   │   ├── xal/             # X-AnyLabeling 移植几何算法
│   │   ├── ops.py           # 预处理/增强算子注册表
│   │   ├── db.py            # SQLite schema + 迁移
│   │   ├── config.py        # 路径/环境变量配置
│   │   └── main.py          # 应用入口 + SPA 托管
│   ├── pack/                # 打包（launcher/spec/iss/pack.bat/VERSION）
│   ├── tests/               # pytest（34 项，隔离临时库）
│   └── data/                # 运行时数据（ccd.db/runs/，gitignore）
├── frontend/                # Vue 3 前端
├── demo_data/               # 演示数据集
└── DEPLOY.md / ENGINES.md   # 部署 / 引擎扩展文档
```

## 常用命令

```bat
:: 后端测试（隔离临时库，不污染生产数据）
cd backend && .venv\Scripts\python -m pytest tests -q

:: 前端构建
cd frontend && npm run build

:: 一键打包（前端构建 → PyInstaller → 安装包，版本取自 pack\VERSION）
cd backend\pack && pack.bat
```

## 文档索引

| 文档 | 内容 |
|---|---|
| [backend/README.md](backend/README.md) | 后端架构、数据流、API 概览 |
| [frontend/README.md](frontend/README.md) | 前端架构、页面/路由、开发指南 |
| [pack/README.md](backend/pack/README.md) | 打包/交付指南 |
| [DEPLOY.md](DEPLOY.md) | 部署说明 |
| [ENGINES.md](ENGINES.md) | 自定义训练引擎扩展 |

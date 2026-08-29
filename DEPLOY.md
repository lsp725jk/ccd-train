# CCD Train 部署指南

## 交付物结构

```
ccd-train/
├── start.bat            一键启动（运行前先 install.bat）
├── install.bat          首次部署：建 venv + 装依赖（torch CUDA 版专用源）
├── backend/
│   ├── app/             平台后端源码
│   ├── requirements.txt 依赖清单（torch 由 install.bat 单独处理）
│   └── data/            数据目录（数据库 + 训练产物 + runs 可视化）
├── frontend/
│   ├── dist/            前端生产构建产物（后端托管，无需 Node.js）
│   └── src/             前端源码（开发用）
└── demo_data/           （演示数据，可删除）
```

## 目标机要求

- **Windows 10/11**（开发机为 Win11）
- **Python 3.10+** 已安装并加入 PATH
- **NVIDIA GPU + 驱动**（CUDA 12.x 兼容驱动，如 522+ 版本）
  - 推理走 onnxruntime-gpu + torch 自带 CUDA 运行时，**无需单独安装 CUDA Toolkit**
- 磁盘 ≥ 15GB（torch 2.5GB + 依赖 + 数据）
- 内存 ≥ 16GB（推荐 32GB）

## 部署步骤

### 1. 安装环境（一次性）

双击 `install.bat`，自动完成：
1. 创建虚拟环境 `backend\.venv`
2. 从官方源安装 torch 2.13.0+cu126（失败自动切阿里云镜像）
3. 从清华源安装其余依赖

### 2. 启动平台

双击 `start.bat`：
- 自动打开浏览器 http://localhost:8000
- 服务监听 0.0.0.0:8000（局域网内其他机器可访问 `http://<本机IP>:8000`）
- Ctrl+C 停止

### 3. 使用

1. 新建检测项目 → 定义缺陷类别
2. 导入数据集（填写图像目录路径）→ 划分训练/验证/测试集
3. 标注工作台：画框 / 分类 / SAM 一键掩码 / 逐像素画笔
4. 训练中心：选任务类型和模型 → 提交训练（单 GPU 串行队列）
5. 图表 / 训练效果页对比分析
6. 模型库：导出 ONNX → 推理预览验证 → 部署到产线

## 生产部署注意事项

- **首次推理较慢**（约 6 秒，CUDA 会话初始化），之后单图 20-40ms
- 数据集路径为服务器本地路径，网络共享盘需确保权限
- 数据备份：`backend/data/ccd.db`（数据库）+ `demo_data` 之外的用户图像目录
- 端口冲突：若 8000 被占用，修改 start.bat 中的 `--port`

## 常见问题

| 现象 | 处理 |
|---|---|
| 启动报 torch 找不到 | 重跑 install.bat |
| 推理预览报 CUDA 错误 | 检查 NVIDIA 驱动版本（需支持 CUDA 12） |
| 训练显示 failed | 训练中心点任务看日志尾部，通常是数据/标注问题 |
| 中文显示乱码 | 确认图像文件名为英文路径 |

## 开发模式（可选）

```
cd frontend && npm run dev      # 前端 5173（代理到 8000）
cd backend && .venv\Scripts\python -m uvicorn app.main:app --port 8000
```

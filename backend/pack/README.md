# CCD Train 独立版打包指南（exe + 安装程序）

## 产物
| 产物 | 位置 | 说明 |
|---|---|---|
| 独立运行版 | `backend/dist/CCDTrain/CCDTrain.exe` | 双击即用：自动起后端(8000端口，占用则顺延) + 打开浏览器；数据存 exe 旁 `data/` 目录 |
| 安装程序 | `backend/dist_installer/CCDTrain-Setup-<版本>.exe` | Inno Setup 安装包（安装到用户目录，创建桌面/开始菜单快捷方式，卸载时可选择删除数据） |
| 配套标注工具 | `dist/CCDTrain/X-AnyLabeling-CPU.exe` | 开源独立标注工作台（X-AnyLabeling v2.5.0 CPU 版），随包分发，双击即用 |

## 一键重打包

```bat
cd backend\pack
pack.bat
```

`pack.bat` 依次执行：① `npm run build`（前端构建）→ ② 清理旧 dist → ③ PyInstaller（约 20-30 分钟）→ ④ ISCC 生成安装包（约 25 分钟）。
**版本号单源**：`pack/VERSION` 文件，pack.bat 以 `/DMyAppVersion=` 注入 installer.iss（iss 内 `#ifndef` 兜底默认值）。

手动分步（等价）：
```bat
cd backend
.venv\Scripts\pyinstaller pack\ccd_train.spec --noconfirm
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" pack\installer.iss /DMyAppVersion=0.2.0
```

## 打包要点（踩坑记录）
- **launcher.py**（`backend/pack/`）：冻结版入口。
  - 通过环境变量把数据目录重定向到 exe 旁（`CCD_BACKEND_DIR`/`CCD_RESOURCE_DIR`/`CCD_WEBUI_DIR`），
    因此**可安装到任意目录**，数据不写死源码路径。
  - 自动把预训练权重（yolo11n.pt/yolo26n.pt/mobile_sam.pt）从包内复制到 exe 旁。
  - 端口 8000 被占时顺延到 8019；后端就绪探测后自动开浏览器。
  - **Windows 单实例互斥体**（`CCDTrain_SingleInstance`，与 installer.iss 的 AppMutex 同名）：
    第二实例直接退出，防止双开共享 SQLite。
  - **引擎子进程模式**：冻结版无法 `python -m`，训练队列改走 `CCDTrain.exe --engine-runner <module> <config.json>`。
- **ccd_train.spec**：onedir 打包；收集前端 `frontend/dist` → `webui/`、权重、`backend/tools/X-AnyLabeling-CPU.exe`。
  - ⚠️ spec 顶部必须 `sys.path.insert(0, backend)`，否则 collect_submodules('app') 静默收集不到
    `app.routers.*`（表现为启动即 "No module named 'app.routers.annotations'"）。
  - ⚠️ **不要 excludes matplotlib**：ultralytics 训练收尾 `plot_results` 函数内延迟 import 它，
    排除会导致冻结版 YOLO 训练完成即 ImportError（权重建好任务却判 failed）。代价：包体 +30~60MB。
- **installer.iss**：
  - `[Files] Excludes: "data\*"` —— **排除运行时数据目录**（此前 dist 内混入开发者数据库导致
    安装包内嵌脏数据）；不得排除 `*.pt`（_internal 资源内权重是 launcher 首启复制源）。
  - `CloseApplications=yes`：卸载/升级前关闭运行中的实例。
  - `AppMutex=CCDTrain_SingleInstance`：与 launcher 互斥体同名。
- **app/main.py**：路由自动发现增加冻结版显式回退清单；SPA 兜底路由已加 `resolve + is_relative_to`
  路径穿越防护（越界回退 index.html）。
- **app/services/train_queue.py**：冻结版使用 `--engine-runner` 启动引擎子进程；子进程 returncode
  兜底标 failed；queued 任务可取消；`_recover()` 重启时强杀孤儿引擎进程。

## 交付前检查
1. `pack.bat` 完成后确认 `dist\CCDTrain\data` 不存在（运行时数据，首次启动才生成）。
2. 安装包静默安装冒烟：`CCDTrain-Setup-x.x.x.exe /VERYSILENT /DIR=C:\t` 后检查
   `CCDTrain.exe`、`_internal\webui`、`_internal\*.pt`、`X-AnyLabeling-CPU.exe` 齐全。
3. 双击安装目录 `CCDTrain.exe` → 浏览器自动打开 → 看板正常（首次启动会创建空的 data/）。

## 目标机要求
- Windows 10/11 64 位
- NVIDIA 显卡 + CUDA 12 兼容驱动（训练/加速推理；无 GPU 也能启动，部分功能降级 CPU）
- 磁盘 ≥ 10GB（安装包 ~2GB，解压后 ~5.5GB）
- 无需安装 Python / CUDA Toolkit（已内置 torch CUDA 运行时）

## 常见问题
- 启动无反应：看控制台输出（保留 console 窗口便于排查）；数据目录 `data/` 权限需可写。
- 占用 8000 端口：端口顺延至 8019（浏览器自动打开对应端口）。
- 打包后新增了路由/引擎：直接重跑打包即可（无需额外 pip install 到打包环境）。

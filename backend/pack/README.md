# CCD Train 独立版打包指南（exe + 安装程序）

## 产物
| 产物 | 位置 | 说明 |
|---|---|---|
| 独立运行版 | `backend/dist/CCDTrain/CCDTrain.exe` | 双击即用：自动起后端(8000端口，占用则顺延) + 打开浏览器；数据存 exe 旁 `data/` 目录 |
| 安装程序 | `backend/dist_installer/CCDTrain-Setup-0.2.0.exe` | Inno Setup 安装包（安装到用户目录，创建桌面/开始菜单快捷方式，卸载时可选择删除数据） |

## 一键重打包
```bat
cd backend
.venv\Scripts\pyinstaller pack\ccd_train.spec --noconfirm        :: ① 打包 exe（约 5-10 分钟）
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" pack\installer.iss :: ② 制作安装程序（约 10-30 分钟）
```

## 打包要点（踩坑记录）
- **launcher.py**（`backend/pack/`）：冻结版入口。
  - 通过环境变量把数据目录重定向到 exe 旁（`CCD_BACKEND_DIR`/`CCD_RESOURCE_DIR`/`CCD_WEBUI_DIR`），
    因此**可安装到任意目录（含 Program Files 之外的用户目录）**，数据不写死源码路径。
  - 自动把预训练权重（yolo11n.pt/yolo26n.pt/mobile_sam.pt）从包内复制到 exe 旁（YOLO/SAM 按 cwd 相对加载）。
  - 端口 8000 被占时顺延到 8019；后端就绪后自动开浏览器。
  - **引擎子进程模式**：冻结版无法 `python -m`，训练队列改走 `CCDTrain.exe --engine-runner <module> <config.json>`。
- **ccd_train.spec**：onedir 打包；收集前端 `frontend/dist` → `webui/`、权重；`collect_submodules('app')` 等。
  - ⚠️ spec 顶部必须 `sys.path.insert(0, backend)`，否则 collect_submodules('app') 静默收集不到
    `app.routers.*`（表现为启动即 "No module named 'app.routers.annotations'"）。
- **app/main.py**：路由自动发现增加冻结版显式回退清单（pkgutil 在冻结环境枚举不到模块）。
- **app/config.py**：路径支持 `CCD_BACKEND_DIR`/`CCD_RESOURCE_DIR` 环境变量覆盖。
- **app/services/train_queue.py**：冻结版使用 `--engine-runner` 启动引擎子进程。

## 目标机要求
- Windows 10/11 64 位
- NVIDIA 显卡 + CUDA 12 兼容驱动（训练/加速推理；无 GPU 也能启动，部分功能降级 CPU）
- 磁盘 ≥ 10GB（安装包 ~2.5GB，解压后 ~5GB）
- 无需安装 Python / CUDA Toolkit（已内置 torch CUDA 运行时）

## 常见问题
- 启动无反应：看控制台输出（保留 console 窗口便于排查）；数据目录 `data/` 权限需可写。
- 首次训练较慢：CUDA 初始化。
- 打包后新增了路由/引擎：重新 `pip install -r requirements.txt` 无关，直接重跑打包即可。

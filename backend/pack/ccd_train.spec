# -*- mode: python ; coding: utf-8 -*-
"""CCD Train 独立版打包配置（onedir）。

构建：cd backend && .venv\Scripts\pyinstaller pack\ccd_train.spec --noconfirm
产物：backend\dist\CCDTrain\CCDTrain.exe（双击运行，自动起后端+开浏览器）
"""
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent.parent          # ccd-train/（项目根）
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))  # 让 collect_submodules('app') 能找到 app 包

datas = [
    (str(ROOT / "frontend" / "dist"), "webui"),
    (str(BACKEND / "yolo11n.pt"), "."),
    (str(BACKEND / "yolo26n.pt"), "."),
    (str(BACKEND / "mobile_sam.pt"), "."),
]
binaries = []
hiddenimports = (
    collect_submodules("app")
    + collect_submodules("app.routers")
    + collect_submodules("app.engines")
    + collect_submodules("app.services")
    + collect_submodules("app.xal")
)

# 重型依赖：整体收集（数据/二进制/子模块）
for pkg in ("ultralytics", "torchvision", "segmentation_models_pytorch",
            "albumentations", "sklearn", "timm", "onnx", "onnxruntime", "onnxscript"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ["launcher.py"],
    pathex=[str(BACKEND)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "pytest", "IPython", "PySide6", "tkinter", "notebook"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="CCDTrain",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CCDTrain",
)

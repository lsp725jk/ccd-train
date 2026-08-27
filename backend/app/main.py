"""FastAPI 入口：路由自动发现。

新增 API 模块：在 app/routers/ 下新建文件，定义 `router`（统一前缀 /api），
无需修改本文件。
"""
import importlib
import os
import pkgutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import RUNS_DIR
from app.db import init_db

# 让 onnxruntime-gpu 能加载 torch 捆绑的 CUDA/cuDNN 运行时 DLL（无需系统安装 CUDA）
try:
    import torch
    _torch_lib = Path(torch.__file__).parent / "lib"
    if _torch_lib.is_dir():
        os.add_dll_directory(str(_torch_lib))
except Exception:
    pass

app = FastAPI(title="CCD Train", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

RUNS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/runs", StaticFiles(directory=RUNS_DIR), name="runs")

from app import routers as routers_pkg  # noqa: E402

for mod_info in pkgutil.iter_modules(routers_pkg.__path__):
    mod = importlib.import_module(f"app.routers.{mod_info.name}")
    if hasattr(mod, "router"):
        app.include_router(mod.router, prefix="/api", tags=[mod_info.name])

# ---- 生产模式：托管前端构建产物（dist 存在时启用，单端口访问） ----
DIST_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if DIST_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        target = DIST_DIR / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST_DIR / "index.html")  # SPA history 路由回退


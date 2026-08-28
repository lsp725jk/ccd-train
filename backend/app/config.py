"""全局路径配置。所有模块从这里取路径，移动目录只需改这里。

PyInstaller 冻结版：通过环境变量覆盖（launcher.py 设置）：
- CCD_BACKEND_DIR  = exe 所在目录（data/ 可写目录建在这里）
- CCD_RESOURCE_DIR = 打包资源目录（前端 dist、预训练权重）
"""
import os
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parent.parent

BACKEND_DIR = Path(os.environ.get("CCD_BACKEND_DIR") or _DEFAULT)
RESOURCE_DIR = Path(os.environ.get("CCD_RESOURCE_DIR") or BACKEND_DIR)
DB_PATH = BACKEND_DIR / "data" / "ccd.db"
RUNS_DIR = BACKEND_DIR / "data" / "runs"
PLUGINS_DIR = BACKEND_DIR / "plugins"

"""全局路径配置。所有模块从这里取路径，移动目录只需改这里。"""
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND_DIR / "data" / "ccd.db"
RUNS_DIR = BACKEND_DIR / "data" / "runs"
PLUGINS_DIR = BACKEND_DIR / "plugins"

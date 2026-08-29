"""CCD Train 独立版入口（PyInstaller 冻结版；也支持源码直接运行）。

用法：
- 正常启动：python pack/launcher.py
- 引擎子进程（冻结版训练队列）：CCDTrain.exe --engine-runner <module> <config.json>
"""
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


def base_dir() -> Path:
    """数据目录：exe 所在目录（可写）"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """资源目录：PyInstaller 解包目录（前端 webui、预训练权重）"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", base_dir()))
    return base_dir()


def _find_engine_cls(module):
    from app.engines.base import EngineBase
    import importlib
    mod = importlib.import_module(module)
    for v in vars(mod).values():
        if isinstance(v, type) and issubclass(v, EngineBase) and v is not EngineBase:
            return v
    raise RuntimeError(f"未找到引擎类: {module}")


def _engine_runner(module: str, cfg_path: str) -> int:
    """冻结版引擎子进程：加载配置并运行引擎（不依赖 -m 参数）。"""
    import json
    import traceback
    base = base_dir()
    os.chdir(base)
    sys.path.insert(0, str(base))
    os.environ.setdefault("CCD_BACKEND_DIR", str(base))
    os.environ.setdefault("CCD_RESOURCE_DIR", str(resource_dir()))
    try:
        cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        cls = _find_engine_cls(module)
        cls(cfg).start()
        return 0
    except SystemExit as e:
        return int(e.code or 0)
    except Exception:
        print(traceback.format_exc(), flush=True)
        return 1


def _acquire_single_instance() -> bool:
    """Windows 单实例互斥体（与 installer.iss 的 AppMutex 同名）。

    双开会导致两个实例共享同一 SQLite → database is locked / 状态错乱。
    """
    if sys.platform != "win32" or getattr(sys, "frozen", False) is False:
        return True
    try:
        import ctypes
        ERROR_ALREADY_EXISTS = 183
        kernel32 = ctypes.windll.kernel32
        mutex = kernel32.CreateMutexW(None, False, "CCDTrain_SingleInstance")
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(mutex)
            return False
        return True
    except Exception:
        return True  # 互斥失败不阻塞启动（尽力而为）


def main() -> int:
    if "--engine-runner" in sys.argv:
        idx = sys.argv.index("--engine-runner")
        return _engine_runner(sys.argv[idx + 1], sys.argv[idx + 2])

    if not _acquire_single_instance():
        print("CCD Train 已在运行（单实例），本次启动退出", flush=True)
        return 0

    base = base_dir()
    res = resource_dir()

    os.environ["CCD_BACKEND_DIR"] = str(base)
    os.environ["CCD_RESOURCE_DIR"] = str(res)
    webui = res / "webui"
    if webui.is_dir():
        os.environ["CCD_WEBUI_DIR"] = str(webui)

    # 预训练权重：资源 → 数据目录（首次运行复制；YOLO/SAM 按 cwd 相对路径加载）
    for name in ("yolo11n.pt", "yolo26n.pt", "mobile_sam.pt"):
        src = res / name
        dst = base / name
        if src.is_file() and not dst.exists():
            try:
                dst.write_bytes(src.read_bytes())
            except Exception:
                pass

    (base / "data").mkdir(parents=True, exist_ok=True)
    (base / "data" / "runs").mkdir(parents=True, exist_ok=True)
    os.chdir(base)
    sys.path.insert(0, str(base))

    # 端口占用则顺延（8000 起）
    host = "127.0.0.1"
    port = 8000
    for p in range(8000, 8020):
        with socket.socket() as s:
            try:
                s.bind((host, p))
                port = p
                break
            except OSError:
                continue

    # 后端就绪后自动开浏览器
    def _open_browser():
        try:
            import urllib.request
            for _ in range(60):
                try:
                    urllib.request.urlopen(f"http://{host}:{port}/api/projects", timeout=1)
                    break
                except Exception:
                    time.sleep(0.5)
            webbrowser.open(f"http://{host}:{port}")
        except Exception:
            pass
    threading.Thread(target=_open_browser, daemon=True).start()

    import uvicorn
    # 冻结版：直接传 app 对象（字符串导入在 PyInstaller 环境不可靠）
    from app.main import app
    uvicorn.run(app, host=host, port=port, reload=False, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())

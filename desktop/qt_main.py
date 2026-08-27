"""CCD Train 桌面版入口：拉起后端服务 + Qt 原生主窗口。

启动方式：双击 qt.bat（或 python desktop/qt_main.py）
"""
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
PYTHON = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"


def find_free_port(start: int = 8010) -> int:
    for port in range(start, start + 100):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def main() -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    import api_client
    from app_window import MainWindow
    from themes import current_theme, build_qss

    port = find_free_port()
    proc = subprocess.Popen(
        [str(PYTHON), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND_DIR),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    api_client.BASE_URL = f"http://127.0.0.1:{port}"

    app = QApplication(sys.argv)
    app.setApplicationName("CCD Train")
    app.setStyleSheet(build_qss(current_theme()))
    win = MainWindow()
    win.show()

    def wait_and_ready() -> None:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/scenes", timeout=1)
        except Exception:
            QTimer.singleShot(300, wait_and_ready)
            return
        win.set_backend_ready(port)

    QTimer.singleShot(100, wait_and_ready)

    try:
        sys.exit(app.exec())
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    main()

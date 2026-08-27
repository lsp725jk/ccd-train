"""PyQt6 → PySide6 兼容层：让 X-AnyLabeling（PyQt6 代码）跑在 ccd-train 的 PySide6 上。

用法（必须在 import anylabeling 之前）：
    import qt6_compat  # noqa

原理：向 sys.modules 注册 PyQt6 / PyQt6.QtCore / PyQt6.QtGui / PyQt6.QtWidgets
等别名，全部映射到 PySide6 对应模块，并把 pyqtSignal/pyqtSlot/pyqtProperty
映射为 PySide6 的 Signal/Slot/Property。

PySide6 >= 6.4 已支持 PyQt6 风格枚举访问（Qt.AlignmentFlag 等），
6.11 实测 X-AnyLabeling 4.0.4 的 import 面全部兼容。
"""
import sys
import types
from pathlib import Path

from PySide6 import (
    QtCore,
    QtGui,
    QtMultimedia,
    QtMultimediaWidgets,
    QtNetwork,
    QtOpenGL,
    QtOpenGLWidgets,
    QtPrintSupport,
    QtSvg,
    QtUiTools,
    QtWebEngineCore,
    QtWebEngineWidgets,
    QtWidgets,
    QtXml,
)

# ---- PyQt6 信号/槽/属性别名（PySide6 名称不同） ----
QtCore.pyqtSignal = QtCore.Signal
QtCore.pyqtSlot = QtCore.Slot
QtCore.pyqtProperty = QtCore.Property
QtCore.pyqtBoundSignal = QtCore.SignalInstance


# ---- PyQt6.uic 兼容（X-AnyLabeling 仅用 uic.loadUi(ui_path, widget)） ----
# PySide6 无 Python 版 uic，用 pyside6-uic.exe 预编译 .ui → setupUi(widget)，
# 完全还原 PyQt6 uic.loadUi 语义（子控件挂为目标 widget 的属性）。
import subprocess as _subprocess

_UIC_CACHE = {}


def _compile_ui(ui_path):
    if ui_path not in _UIC_CACHE:
        # ui 生成的代码 import resources_rc：映射到 anylabeling 的 PyQt6 资源模块
        if "resources_rc" not in sys.modules:
            try:
                import anylabeling.resources.resources as _rc
                sys.modules["resources_rc"] = _rc
            except ImportError:
                pass
        exe = str(Path(sys.executable).parent / "pyside6-uic.exe")
        proc = _subprocess.run([exe, ui_path], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"pyside6-uic 编译失败: {proc.stderr}")
        _UIC_CACHE[ui_path] = proc.stdout
    return _UIC_CACHE[ui_path]


def _load_ui(ui_path, widget=None):
    ns = {}
    exec(compile(_compile_ui(ui_path), str(ui_path), "exec"), ns)
    ui_class = next(v for v in ns.values()
                    if isinstance(v, type) and v.__name__.startswith("Ui_"))
    ui = ui_class()
    ui.setupUi(widget)
    if widget is not None:
        # PyQt6 uic.loadUi 语义：把 Ui 实例的控件属性复制到目标 widget
        for k, v in ui.__dict__.items():
            setattr(widget, k, v)
        return widget
    return ui


_uic_mod = types.ModuleType("PyQt6.uic")
_uic_mod.loadUi = _load_ui
_uic_mod.loadUiType = lambda path: (_load_ui(path), None)

# PyQt6 中 QAction/QShortcut/QKeySequence 在 QtGui；PySide6 两者都提供，无需处理。

_MODULES = {
    "PyQt6": None,  # 聚合模块，见下
    "PyQt6.QtCore": QtCore,
    "PyQt6.QtGui": QtGui,
    "PyQt6.QtWidgets": QtWidgets,
    "PyQt6.QtNetwork": QtNetwork,
    "PyQt6.QtMultimedia": QtMultimedia,
    "PyQt6.QtMultimediaWidgets": QtMultimediaWidgets,
    "PyQt6.QtOpenGL": QtOpenGL,
    "PyQt6.QtOpenGLWidgets": QtOpenGLWidgets,
    "PyQt6.QtPrintSupport": QtPrintSupport,
    "PyQt6.QtSvg": QtSvg,
    "PyQt6.QtUiTools": QtUiTools,
    "PyQt6.QtWebEngineCore": QtWebEngineCore,
    "PyQt6.QtWebEngineWidgets": QtWebEngineWidgets,
    "PyQt6.QtXml": QtXml,
    "PyQt6.uic": _uic_mod,
}


def _install():
    for name, mod in _MODULES.items():
        if name == "PyQt6":
            agg = types.ModuleType("PyQt6")
            for sub, m in _MODULES.items():
                if sub != "PyQt6":
                    setattr(agg, sub.split(".")[-1], m)
            sys.modules[name] = agg
        else:
            sys.modules[name] = mod


_install()

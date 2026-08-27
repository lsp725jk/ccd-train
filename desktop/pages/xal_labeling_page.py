"""标注工作台（X-AnyLabeling 嵌入版）：数据集选择 + LabelingWidget 画布。

把 ccd-train 的「标注」标签页画布替换为 X-AnyLabeling（开源，不重复造轮子）：
- 导出：后端数据集 → 镜像目录（图像 + LabelMe JSON），LabelingWidget 直接打开
- 标注：画笔/橡皮擦/多边形/椭圆/SAM 智能标注 全部由 X-AnyLabeling 提供
- 回写：解析镜像目录 JSON → 后端 annotations API（全量重建）

依赖与适配：
- anylabeling 源码在 third_party/x_anylabeling_cvhub-4.0.4（PyPI x-anylabeling-cvhub）
- 代码用 PyQt6，本平台用 PySide6 → 先 import qt6_compat 做运行时映射
- 嵌入需要隐藏 QMainWindow 宿主（LabelingWidget 经 parent.parent 访问 menuBar/statusBar）
"""
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QMessageBox, QMainWindow,
)

import api_client as api
import xal_sync

ROOT = Path(__file__).resolve().parent.parent.parent  # ccd-train/
MIRROR_ROOT = ROOT / "backend" / "data" / "xal_mirror"
WORK_DIR = ROOT / "backend" / "data" / "xal_work"
XAL_ROOT = ROOT / "third_party" / "x_anylabeling_cvhub-4.0.4"


def _init_xal():
    """初始化 X-AnyLabeling 运行环境，返回配置 dict。"""
    import qt6_compat  # noqa: F401  PyQt6 → PySide6 映射（必须先于 anylabeling import）

    if not XAL_ROOT.exists():
        raise RuntimeError(f"X-AnyLabeling 源码目录不存在：{XAL_ROOT}\n"
                           "请把 x_anylabeling_cvhub-4.0.4 解压到 third_party/")
    if str(XAL_ROOT) not in sys.path:
        sys.path.insert(0, str(XAL_ROOT))

    import anylabeling.config as xal_config

    xal_config.set_work_directory(str(WORK_DIR))
    cfg = xal_config.get_default_config()
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    cfg_path = WORK_DIR / "xanylabeling_config.yaml"
    if not cfg_path.exists():
        import yaml
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True)
    xal_config.current_config_file = str(cfg_path)
    return xal_config.get_config()


def _create_labeling_widget(config):
    """创建 X-AnyLabeling 的 LabelingWrapper（已验证可嵌入 PySide6）。"""
    try:
        from anylabeling.views.labeling.label_wrapper import LabelingWrapper
    except ImportError as e:
        raise RuntimeError(
            "未找到 X-AnyLabeling 源码：请把 x_anylabeling_cvhub-4.0.4 解压到\n"
            f"  {XAL_ROOT.parent}\n（原始错误：{e}）"
        )
    if not XAL_ROOT.exists():
        raise RuntimeError(f"X-AnyLabeling 源码目录不存在：{XAL_ROOT}")
    host = QMainWindow()  # 隐藏宿主：LabelingWidget 需要 parent.parent.menuBar()/statusBar()
    wrapper = LabelingWrapper(host, config=config)
    return wrapper, host


class XalLabelingPage(QWidget):
    """标注工作台页：数据集 → X-AnyLabeling 画布 → 回写后端。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pid = None
        self.datasets = []
        self.mirror = None          # 当前导出的镜像目录
        self._xal_wrapper = None
        self._xal_host = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        title = QLabel("标注工作台（X-AnyLabeling）")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        lay.addWidget(title)

        # 工具栏
        bar = QHBoxLayout()
        bar.addWidget(QLabel("数据集"))
        self.combo_ds = QComboBox()
        self.combo_ds.setMinimumWidth(200)
        bar.addWidget(self.combo_ds)
        bar.addSpacing(12)

        self.btn_export = QPushButton("导出到 X-AnyLabeling")
        self.btn_export.setProperty("primary", True)
        self.btn_export.clicked.connect(self.export_to_xal)
        bar.addWidget(self.btn_export)

        self.btn_save = QPushButton("回写保存到平台")
        self.btn_save.clicked.connect(self.import_back)
        self.btn_save.setEnabled(False)
        bar.addWidget(self.btn_save)

        self.btn_open = QPushButton("打开镜像目录")
        self.btn_open.clicked.connect(self.open_mirror)
        self.btn_open.setEnabled(False)
        bar.addWidget(self.btn_open)

        self.lbl_hint = QLabel("先在 X-AnyLabeling 里按数据集类别名新建标签（屏蔽区用 __shield__）")
        self.lbl_hint.setStyleSheet("color: #8a8175;")
        bar.addStretch(1)
        lay.addLayout(bar)
        lay.addWidget(self.lbl_hint)

        # 画布容器：LabelingWidget 嵌入（首次导出时创建）
        self.canvas_host = QWidget()
        self.canvas_host_lay = QVBoxLayout(self.canvas_host)
        self.canvas_host_lay.setContentsMargins(0, 0, 0, 0)
        placeholder = QLabel("选择数据集后点击「导出到 X-AnyLabeling」")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: #8a8175; font-size: 14px;")
        self.canvas_host_lay.addWidget(placeholder)
        lay.addWidget(self.canvas_host, 1)

    # ---------- 加载 ----------

    def load_project(self, pid: int):
        self.pid = pid
        try:
            self.datasets = api.datasets_list(pid)
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))
            return
        self.combo_ds.blockSignals(True)
        self.combo_ds.clear()
        for ds in self.datasets:
            self.combo_ds.addItem(f"{ds['name']}（{ds['image_count']} 张）", ds["id"])
        self.combo_ds.blockSignals(False)

    # ---------- 动作 ----------

    def export_to_xal(self):
        ds_id = self.combo_ds.currentData()
        if not ds_id:
            QMessageBox.warning(self, "提示", "请先选择数据集")
            return
        try:
            self.mirror = xal_sync.export_dataset(ds_id, MIRROR_ROOT)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
            return

        # 首次使用：初始化并嵌入 LabelingWrapper
        if self._xal_wrapper is None:
            try:
                config = _init_xal()
                self._xal_wrapper, self._xal_host = _create_labeling_widget(config)
            except Exception as e:
                QMessageBox.critical(self, "X-AnyLabeling 初始化失败", str(e))
                self.btn_save.setEnabled(False)
                self.btn_open.setEnabled(True)
                return
            self.canvas_host_lay.addWidget(self._xal_wrapper)

        # 加载第一张图
        try:
            first_img = next(p for p in sorted(self.mirror.rglob("*"))
                             if p.suffix.lower() in
                             {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"})
            self._xal_wrapper.view.load_file(str(first_img))
        except Exception as e:
            QMessageBox.warning(self, "打开失败", str(e))
        self.btn_save.setEnabled(True)
        self.btn_open.setEnabled(True)
        self.lbl_hint.setText(
            f"镜像目录：{self.mirror}　·　标注完成后点「回写保存到平台」"
        )

    def import_back(self):
        if not self.mirror:
            return
        # 让 X-AnyLabeling 先把当前标注落盘（当前图）
        try:
            self._xal_wrapper.view.save_file()
        except Exception:
            pass
        try:
            stats = xal_sync.import_dataset(self.mirror)
        except Exception as e:
            QMessageBox.critical(self, "回写失败", str(e))
            return
        msg = (f"回写完成：处理 {stats['images']} 张图，"
               f"新建 {stats['created']} 条，删除 {stats['deleted']} 条")
        if stats["skipped"]:
            msg += "\n\n跳过：\n" + "\n".join(stats["skipped"][:10])
        QMessageBox.information(self, "回写完成", msg)

    def open_mirror(self):
        if not self.mirror:
            return
        if os.name == "nt":
            os.startfile(str(self.mirror))
        else:
            QMessageBox.information(self, "镜像目录", str(self.mirror))

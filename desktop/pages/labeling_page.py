"""标注工作台页面：数据集选择 + 图像列表 + 画布 + 缺陷类型 + 工具条。"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QListWidget, QListWidgetItem, QSplitter, QMessageBox, QSpinBox,
)

import api_client as api
from pages.labeling import CanvasView, TOOL_SELECT, TOOL_BOX, TOOL_BRUSH, TOOL_ERASE


class LabelingPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pid = None
        self.datasets = []
        self.images = []
        self.categories = []
        self.current_ds = None
        self.current_image = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        title = QLabel("标注工作台")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        lay.addWidget(title)

        # 工具条
        bar = QHBoxLayout()
        bar.addWidget(QLabel("数据集"))
        self.combo_ds = QComboBox()
        self.combo_ds.setMinimumWidth(180)
        self.combo_ds.currentIndexChanged.connect(self._on_ds_changed)
        bar.addWidget(self.combo_ds)
        bar.addSpacing(16)
        self.tool_buttons = {}
        for tid, tlabel in [(TOOL_SELECT, "选择"), (TOOL_BOX, "画框"), (TOOL_BRUSH, "画笔"), (TOOL_ERASE, "橡皮擦")]:
            btn = QPushButton(tlabel)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, t=tid: self._set_tool(t))
            self.tool_buttons[tid] = btn
            bar.addWidget(btn)
        self.tool_buttons[TOOL_SELECT].setChecked(True)
        bar.addWidget(QLabel("笔刷"))
        self.spin_brush = QSpinBox()
        self.spin_brush.setRange(2, 200)
        self.spin_brush.setValue(20)
        self.spin_brush.valueChanged.connect(lambda v: setattr(self.canvas, "brush_size", v))
        bar.addWidget(self.spin_brush)
        bar.addStretch(1)
        btn_undo = QPushButton("撤销")
        btn_undo.clicked.connect(self.canvas_undo)
        btn_redo = QPushButton("重做")
        btn_redo.clicked.connect(self.canvas_redo)
        btn_save = QPushButton("保存")
        btn_save.setProperty("primary", True)
        btn_save.clicked.connect(self.canvas_save)
        bar.addWidget(btn_undo)
        bar.addWidget(btn_redo)
        bar.addWidget(btn_save)
        lay.addLayout(bar)

        # 主体
        split = QSplitter(Qt.Horizontal)
        self.list_images = QListWidget()
        self.list_images.setMinimumWidth(170)
        self.list_images.currentRowChanged.connect(self._on_image_changed)
        split.addWidget(self.list_images)

        self.canvas = CanvasView()
        split.addWidget(self.canvas)

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.addWidget(QLabel("缺陷类型"))
        self.list_cats = QListWidget()
        self.list_cats.currentRowChanged.connect(self._on_cat_changed)
        rlay.addWidget(self.list_cats, 1)
        split.addWidget(right)

        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([180, 700, 180])
        lay.addWidget(split, 1)

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
        if self.datasets:
            self._load_ds(self.datasets[0]["id"])

    def _on_ds_changed(self):
        did = self.combo_ds.currentData()
        if did:
            self._load_ds(did)

    def _load_ds(self, ds_id: int):
        try:
            r = api.dataset_images(ds_id, page_size=500)
            self.categories = api.dataset_categories(ds_id)
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))
            return
        self.images = r["items"]
        self.current_ds = ds_id
        self.list_images.blockSignals(True)
        self.list_images.clear()
        for im in self.images:
            mark = "●" if im.get("annotation_count") else "○"
            it = QListWidgetItem(f"{mark} {im['rel_path'].split('/')[-1]}")
            it.setData(Qt.UserRole, im["id"])
            self.list_images.addItem(it)
        self.list_images.blockSignals(False)

        self.list_cats.blockSignals(True)
        self.list_cats.clear()
        for c in self.categories:
            it = QListWidgetItem(c["name"])
            color = QColor(c.get("color") or "#4E79A7")
            it.setForeground(color)
            it.setData(Qt.UserRole, c["id"])
            self.list_cats.addItem(it)
        self.list_cats.blockSignals(False)
        if self.categories:
            self.list_cats.setCurrentRow(0)
        self.canvas.set_categories(self.categories)

    # ---------- 图像切换 ----------

    def _on_image_changed(self, row: int):
        if row < 0 or row >= len(self.images):
            return
        im = self.images[row]
        self.current_image = im
        try:
            data = api.image_bytes(im["id"])
        except Exception as e:
            QMessageBox.warning(self, "加载图像失败", str(e))
            return
        pix = QPixmap()
        if not pix.loadFromData(data):
            QMessageBox.warning(self, "加载图像失败", "图像解码失败")
            return
        self.canvas.set_image(im["id"], pix)
        self.canvas.set_categories(self.categories)

    def _on_cat_changed(self, row: int):
        if 0 <= row < len(self.categories):
            self.canvas.categories = [self.categories[row]]

    # ---------- 工具与动作 ----------

    def _set_tool(self, tool: str):
        for tid, btn in self.tool_buttons.items():
            btn.setChecked(tid == tool)
        self.canvas.set_tool(tool)

    def canvas_undo(self):
        self.canvas.undo()

    def canvas_redo(self):
        self.canvas.redo()

    def canvas_save(self):
        if self.canvas.save():
            self._refresh_image_marks()

    def _refresh_image_marks(self):
        row = self.list_images.currentRow()
        for i in range(self.list_images.count()):
            it = self.list_images.item(i)
            im_id = it.data(Qt.UserRole)
            it.setText(("●" if im_id == self.current_image["id"] else "○") + " " + it.text()[2:])
        self.list_images.setCurrentRow(row)

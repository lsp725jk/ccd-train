"""训练中心页：任务表单（引擎联动/参数/增强）+ 任务列表 + 进度刷新。"""
import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QFormLayout, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QListWidget, QListWidgetItem, QSplitter, QDialog, QPlainTextEdit,
)

import api_client as api

TASK_TYPES = [
    ("detect", "目标检测"), ("segment", "语义分割"), ("classify", "分类"),
    ("us_classify", "非监督分类"), ("us_segment", "非监督分割"),
]


class TrainPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pid = None
        self.engines = []
        self.datasets = []
        self.pipelines = []
        self.tasks = []
        self.form = {
            "name": "", "task_type": "detect", "engine": "", "dataset_ids": [],
            "epochs": 100, "imgsz": 640, "batch": 16, "custom_arch": "",
            "preprocess_pipeline_id": None, "aug_pipeline_id": None,
            "aug_flip": True, "aug_mosaic": 1.0, "aug_mixup": 0.0, "aug_hsv": 0.015,
        }

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        title = QLabel("训练中心")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        lay.addWidget(title)

        split = QSplitter(Qt.Horizontal)
        # 左：表单
        left = QWidget()
        llay = QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 0, 0)
        fg = QGroupBox("新建训练任务")
        form = QFormLayout(fg)

        self.edit_name = QLineEdit()
        form.addRow("模型名称", self.edit_name)

        self.combo_type = QComboBox()
        for v, l in TASK_TYPES:
            self.combo_type.addItem(l, v)
        self.combo_type.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("任务类型", self.combo_type)

        self.combo_engine = QComboBox()
        form.addRow("模型档位", self.combo_engine)

        self.edit_arch = QLineEdit()
        self.edit_arch.setPlaceholderText("如：yolo11n-custom.yaml")
        form.addRow("架构定义", self.edit_arch)

        self.list_ds = QListWidget()
        self.list_ds.setMaximumHeight(110)
        form.addRow("数据集（可多选）", self.list_ds)

        self.combo_pre = QComboBox()
        self.combo_pre.addItem("（无）", None)
        form.addRow("预处理管线", self.combo_pre)

        self.combo_aug = QComboBox()
        self.combo_aug.addItem("（无）", None)
        form.addRow("增强管线", self.combo_aug)

        self.spin_epochs = QSpinBox()
        self.spin_epochs.setRange(1, 2000)
        self.spin_epochs.setValue(100)
        form.addRow("Epochs", self.spin_epochs)

        self.spin_imgsz = QSpinBox()
        self.spin_imgsz.setRange(64, 4096)
        self.spin_imgsz.setValue(640)
        self.spin_imgsz.setSingleStep(32)
        form.addRow("输入尺寸", self.spin_imgsz)

        self.spin_batch = QSpinBox()
        self.spin_batch.setRange(1, 256)
        self.spin_batch.setValue(16)
        form.addRow("Batch", self.spin_batch)

        aug_box = QGroupBox("内置增强（Ultralytics）")
        alay = QFormLayout(aug_box)
        self.chk_flip = QCheckBox("水平翻转")
        self.chk_flip.setChecked(True)
        alay.addRow(self.chk_flip)
        self.spin_mosaic = QDoubleSpinBox()
        self.spin_mosaic.setRange(0, 1)
        self.spin_mosaic.setSingleStep(0.1)
        self.spin_mosaic.setValue(1.0)
        alay.addRow("Mosaic", self.spin_mosaic)
        self.spin_mixup = QDoubleSpinBox()
        self.spin_mixup.setRange(0, 1)
        self.spin_mixup.setSingleStep(0.05)
        alay.addRow("MixUp", self.spin_mixup)
        self.spin_hsv = QDoubleSpinBox()
        self.spin_hsv.setRange(0, 0.1)
        self.spin_hsv.setSingleStep(0.005)
        self.spin_hsv.setValue(0.015)
        alay.addRow("HSV 扰动", self.spin_hsv)
        btn_safe = QPushButton("一键工业安全增强")
        btn_safe.clicked.connect(self.apply_safe_aug)
        alay.addRow(btn_safe)

        btn_submit = QPushButton("提交训练")
        btn_submit.setProperty("primary", True)
        btn_submit.clicked.connect(self.submit)

        llay.addWidget(fg)
        llay.addWidget(aug_box)
        llay.addWidget(btn_submit)
        llay.addStretch(1)
        split.addWidget(left)

        # 右：任务列表
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rhead = QHBoxLayout()
        rhead.addWidget(QLabel("训练任务"))
        rhead.addStretch(1)
        btn_log = QPushButton("查看日志")
        btn_log.clicked.connect(self.show_log)
        btn_stop = QPushButton("停止")
        btn_stop.clicked.connect(self.stop)
        rhead.addWidget(btn_log)
        rhead.addWidget(btn_stop)
        rlay.addLayout(rhead)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["名称", "引擎", "任务", "状态", "进度", "时间"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        rlay.addWidget(self.table)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([430, 500])
        lay.addWidget(split)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.load_tasks)
        self.timer.start(4000)

    # ---------- 加载 ----------

    def load_project(self, pid: int):
        self.pid = pid
        try:
            proj = api.project_get(pid)
            plan_prefill = None
            if proj.get("plan") and proj["plan"] != "{}":
                plan_prefill = json.loads(proj["plan"])
            self.engines = api.engines_list()
            self.datasets = api.datasets_list(pid)
            self.pipelines = api.pipelines_list(pid)
            self._fill_engines()
            self._fill_datasets()
            self._fill_pipelines()
            if plan_prefill:
                self._prefill(plan_prefill)
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))
        self.load_tasks()

    def _fill_engines(self):
        self.combo_engine.clear()
        for e in self.engines:
            self.combo_engine.addItem(e["label"], e["id"])
        self._on_type_changed()

    def _engines_of(self, task_type: str):
        return [e for e in self.engines if e["task_type"] == task_type]

    def _on_type_changed(self):
        task_type = self.combo_type.currentData()
        self.combo_engine.clear()
        for e in self._engines_of(task_type):
            self.combo_engine.addItem(e["label"], e["id"])
        self.edit_arch.setVisible(task_type == "detect")

    def _fill_datasets(self):
        self.list_ds.clear()
        for d in self.datasets:
            it = QListWidgetItem(f"{d['name']}（{d['image_count']} 张）")
            it.setData(Qt.UserRole, d["id"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            self.list_ds.addItem(it)

    def _fill_pipelines(self):
        self.combo_pre.clear()
        self.combo_pre.addItem("（无）", None)
        self.combo_aug.clear()
        self.combo_aug.addItem("（无）", None)
        for p in self.pipelines:
            if p.get("type", "pre") == "pre":
                self.combo_pre.addItem(p["name"], p["id"])
            else:
                self.combo_aug.addItem(p["name"], p["id"])

    def _prefill(self, plan):
        if plan.get("engines"):
            e0 = plan["engines"][0]
            idx = self.combo_type.findData(e0.get("task_type"))
            if idx >= 0:
                self.combo_type.setCurrentIndex(idx)
            eidx = self.combo_engine.findData(e0.get("engine"))
            if eidx >= 0:
                self.combo_engine.setCurrentIndex(eidx)
        d = plan.get("defaults", {})
        if d.get("epochs"):
            self.spin_epochs.setValue(int(d["epochs"]))
        if d.get("imgsz"):
            self.spin_imgsz.setValue(int(d["imgsz"]))
        if d.get("batch"):
            self.spin_batch.setValue(int(d["batch"]))

    # ---------- 操作 ----------

    def apply_safe_aug(self):
        try:
            d = api.safe_aug()
        except Exception:
            QMessageBox.warning(self, "失败", "无法获取安全增强配置")
            return
        self.chk_flip.setChecked(d["flip"])
        self.spin_mosaic.setValue(d["mosaic"])
        self.spin_mixup.setValue(d["mixup"])
        self.spin_hsv.setValue(d["hsv"])
        QMessageBox.information(self, "完成", "已应用工业安全增强（保守光照/几何参数）")

    def _checked_ds(self):
        ids = []
        for i in range(self.list_ds.count()):
            it = self.list_ds.item(i)
            if it.checkState() == Qt.Checked:
                ids.append(it.data(Qt.UserRole))
        return ids

    def submit(self):
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入模型名称")
            return
        ds_ids = self._checked_ds()
        if not ds_ids:
            QMessageBox.warning(self, "提示", "请至少选择一个数据集")
            return
        try:
            api.train_create({
                "project_id": self.pid, "name": name,
                "task_type": self.combo_type.currentData(),
                "engine": self.combo_engine.currentData(),
                "dataset_ids": ds_ids,
                "epochs": self.spin_epochs.value(),
                "imgsz": self.spin_imgsz.value(),
                "batch": self.spin_batch.value(),
                "custom_arch": self.edit_arch.text().strip(),
                "preprocess_pipeline_id": self.combo_pre.currentData(),
                "aug_pipeline_id": self.combo_aug.currentData(),
                "aug_flip": self.chk_flip.isChecked(),
                "aug_mosaic": self.spin_mosaic.value(),
                "aug_mixup": self.spin_mixup.value(),
                "aug_hsv": self.spin_hsv.value(),
            })
        except Exception as e:
            QMessageBox.warning(self, "提交失败", str(e))
            return
        self.edit_name.clear()
        self.load_tasks()

    def load_tasks(self):
        if not self.pid:
            return
        try:
            self.tasks = api.tasks_list(self.pid)
        except Exception:
            return
        self.table.setRowCount(len(self.tasks))
        for r, t in enumerate(self.tasks):
            self.table.setItem(r, 0, QTableWidgetItem(t.get("model_name", "")))
            self.table.setItem(r, 1, QTableWidgetItem(t.get("engine", "")))
            self.table.setItem(r, 2, QTableWidgetItem(t.get("task_type", "")))
            self.table.setItem(r, 3, QTableWidgetItem(t.get("status", "")))
            self.table.setItem(r, 4, QTableWidgetItem(f"{int(t.get('progress', 0) * 100)}%"))
            self.table.setItem(r, 5, QTableWidgetItem(t.get("created_at", "")))

    def _selected_task(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一个任务")
            return None
        return self.tasks[row]

    def show_log(self):
        t = self._selected_task()
        if not t:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"训练日志 · {t.get('model_name', '')}")
        dlg.resize(760, 480)
        lay = QVBoxLayout(dlg)
        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        lay.addWidget(txt)
        try:
            r = api.task_log(t["id"], 0)
            txt.setPlainText("\n".join(r["lines"]))
        except Exception as e:
            txt.setPlainText(str(e))
        dlg.exec()

    def stop(self):
        t = self._selected_task()
        if not t:
            return
        r = api.task_stop(t["id"])
        QMessageBox.information(self, "停止", r.get("message", "已处理"))
        self.load_tasks()

"""模型库页：模型列表、评估指标、可视化图片、ONNX 导出。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox, QDialog,
    QSplitter, QScrollArea, QGridLayout, QFormLayout, QPlainTextEdit,
)

import api_client as api


class ModelDetailDialog(QDialog):
    def __init__(self, model: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"模型详情 · {model.get('name', '')}")
        self.resize(900, 620)
        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Horizontal)

        left = QWidget()
        llay = QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 0, 0)
        metrics = model.get("metrics", {})
        if isinstance(metrics, str):
            import json
            try:
                metrics = json.loads(metrics)
            except Exception:
                metrics = {}
        form = QFormLayout()
        for k, v in metrics.items():
            form.addRow(k, QLabel(str(v)))
        llay.addLayout(form)
        llay.addStretch(1)
        split.addWidget(left)

        right = QScrollArea()
        right.setWidgetResizable(True)
        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        viz = model.get("viz", [])
        for i, url in enumerate(viz):
            from PySide6.QtGui import QPixmap
            from PySide6.QtWidgets import QLabel as ImgLabel
            lbl = ImgLabel()
            lbl.setAlignment(Qt.AlignCenter)
            local = api.run_url_to_path(url)
            pix = QPixmap(local)
            if not pix.isNull():
                lbl.setPixmap(pix.scaled(400, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                lbl.setText(url)
            grid.addWidget(lbl, i // 2, i % 2)
        if not viz:
            grid.addWidget(QLabel("暂无可视化图片"))
        right.setWidget(grid_w)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 640])
        lay.addWidget(split)

        btn = QPushButton("关闭")
        btn.clicked.connect(self.accept)
        lay.addWidget(btn, alignment=Qt.AlignRight)


class ModelsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pid = None
        self.models = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        head = QHBoxLayout()
        title = QLabel("模型库")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        head.addWidget(title)
        head.addStretch(1)
        btn_detail = QPushButton("模型详情")
        btn_detail.clicked.connect(self.show_detail)
        btn_export = QPushButton("导出 ONNX")
        btn_export.setProperty("primary", True)
        btn_export.clicked.connect(self.export)
        btn_del = QPushButton("删除")
        btn_del.clicked.connect(self.remove)
        head.addWidget(btn_detail)
        head.addWidget(btn_export)
        head.addWidget(btn_del)
        lay.addLayout(head)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["名称", "任务", "引擎", "状态", "mAP50", "召回", "大小", "时间"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table)

    def load_project(self, pid: int):
        self.pid = pid
        self.load()

    def load(self):
        if not self.pid:
            return
        try:
            self.models = api.models_list(self.pid)
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))
            return
        self.table.setRowCount(len(self.models))
        for r, m in enumerate(self.models):
            metrics = m.get("metrics", {})
            if isinstance(metrics, str):
                import json
                try:
                    metrics = json.loads(metrics)
                except Exception:
                    metrics = {}
            self.table.setItem(r, 0, QTableWidgetItem(m.get("name", "")))
            self.table.setItem(r, 1, QTableWidgetItem(m.get("task_type", "")))
            self.table.setItem(r, 2, QTableWidgetItem(m.get("engine", "")))
            self.table.setItem(r, 3, QTableWidgetItem(m.get("status", "")))
            self.table.setItem(r, 4, QTableWidgetItem(str(metrics.get("mAP50", "-"))))
            self.table.setItem(r, 5, QTableWidgetItem(str(metrics.get("recall", "-"))))
            self.table.setItem(r, 6, QTableWidgetItem(self._fmt_size(m.get("file_size", 0))))
            self.table.setItem(r, 7, QTableWidgetItem(m.get("created_at", "")))

    @staticmethod
    def _fmt_size(b):
        try:
            b = int(b)
        except (TypeError, ValueError):
            return "-"
        if b <= 0:
            return "-"
        return f"{b / 1048576:.1f} MB"

    def _selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一个模型")
            return None
        return self.models[row]

    def show_detail(self):
        m = self._selected()
        if not m:
            return
        try:
            r = api.model_result(m["id"])
            m = {**m, "metrics": r.get("metrics", {}), "viz": r.get("viz", [])}
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))
            return
        dlg = ModelDetailDialog(m, self)
        dlg.exec()

    def export(self):
        m = self._selected()
        if not m:
            return
        try:
            r = api.model_export(m["id"])
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))
            return
        QMessageBox.information(self, "导出完成",
                                f"ONNX 已导出：\n{r.get('onnx_path', '')}\n大小 {r.get('size_mb', '-')} MB")
        self.load()

    def remove(self):
        m = self._selected()
        if not m:
            return
        if QMessageBox.question(self, "确认删除", f"删除模型「{m.get('name', '')}」？") != QMessageBox.Yes:
            return
        try:
            api.model_delete(m["id"])
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e))
            return
        self.load()

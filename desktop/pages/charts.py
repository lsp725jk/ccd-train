"""图表页：任务选择 → 训练曲线（loss / mAP / recall / precision）。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QMessageBox,
)
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis, QCategoryAxis

import api_client as api

METRIC_LABELS = {
    "train_loss": "训练损失", "val_loss": "验证损失",
    "mAP50": "mAP50", "mAP50-95": "mAP50-95",
    "precision": "精确率", "recall": "召回率", "accuracy": "准确率", "iou": "IoU",
    "auroc_image": "AUROC",
}


class ChartsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pid = None
        self.tasks = []
        self.data = None
        self.chart = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        head = QHBoxLayout()
        title = QLabel("训练曲线")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(QLabel("任务"))
        self.combo_task = QComboBox()
        self.combo_task.setMinimumWidth(260)
        self.combo_task.currentIndexChanged.connect(self.load_curve)
        head.addWidget(self.combo_task)
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.load_tasks)
        head.addWidget(btn_refresh)
        lay.addLayout(head)

        self.combo_metric = QComboBox()
        self.combo_metric.currentIndexChanged.connect(self.render)
        lay.addWidget(self.combo_metric)

        self.view = QChartView()
        self.view.setRenderHint(self.view.renderHints())
        lay.addWidget(self.view, 1)

    def load_project(self, pid: int):
        self.pid = pid
        self.load_tasks()

    def load_tasks(self):
        if not self.pid:
            return
        try:
            self.tasks = api.tasks_list(self.pid)
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))
            return
        self.combo_task.clear()
        for t in self.tasks:
            self.combo_task.addItem(f"{t.get('model_name', '')}（{t.get('status', '')}）", t["id"])

    def load_curve(self):
        if self.combo_task.count() == 0:
            return
        tid = self.combo_task.currentData()
        try:
            self.data = api.task_curve(tid)
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))
            return
        if not self.data.get("exists"):
            self._empty("该任务还没有曲线数据")
            return
        cols = self.data["columns"]
        self.combo_metric.clear()
        for c in cols:
            if c == "epoch":
                continue
            self.combo_metric.addItem(METRIC_LABELS.get(c, c), c)
        self.render()

    def render(self):
        if not self.data or not self.data.get("exists") or self.combo_metric.count() == 0:
            return
        metric = self.combo_metric.currentData()
        rows = self.data["rows"]
        if not rows:
            return
        series = QLineSeries()
        series.setName(METRIC_LABELS.get(metric, metric))
        for row in rows:
            try:
                series.append(float(row[0]), float(row[self.data["columns"].index(metric)]))
            except (ValueError, IndexError):
                continue

        chart = QChart()
        chart.setTitle(metric)
        chart.legend().setVisible(True)
        chart.legend().setAlignment(Qt.AlignTop)
        chart.addSeries(series)
        axis_x = QValueAxis()
        axis_x.setTitleText("epoch")
        axis_y = QValueAxis()
        axis_y.setTitleText(metric)
        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        chart.setMargins(chart.margins())
        self.view.setChart(chart)

    def _empty(self, msg: str):
        from PySide6.QtWidgets import QGraphicsScene
        scene = QGraphicsScene()
        scene.addText(msg)
        self.view.setScene(scene)

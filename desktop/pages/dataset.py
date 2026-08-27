"""数据集页：项目下数据集列表、创建（目录导入）、划分、类别管理。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QInputDialog, QFileDialog,
    QMessageBox, QDialog, QLineEdit, QFormLayout, QDialogButtonBox,
)

import api_client as api
from themes import THEMES, current_theme


class SplitDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("划分训练/验证/测试")
        self.setMinimumWidth(320)
        form = QFormLayout(self)
        self.train_edit = QLineEdit("0.7")
        self.val_edit = QLineEdit("0.15")
        self.seed_edit = QLineEdit("42")
        form.addRow("训练比例", self.train_edit)
        form.addRow("验证比例", self.val_edit)
        form.addRow("随机种子", self.seed_edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def values(self):
        return (float(self.train_edit.text()), float(self.val_edit.text()), int(self.seed_edit.text()))


class CategoryDialog(QDialog):
    def __init__(self, parent=None, color: str = "#4E79A7"):
        super().__init__(parent)
        self.setWindowTitle("添加缺陷类别")
        self.setMinimumWidth(320)
        self.color = color
        form = QFormLayout(self)
        self.name_edit = QLineEdit()
        form.addRow("类别名称", self.name_edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def accept(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "提示", "请输入类别名称")
            return
        super().accept()


class DatasetPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pid = None
        self.datasets = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)

        head = QHBoxLayout()
        title = QLabel("数据集")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        head.addWidget(title)
        head.addStretch(1)
        btn_new = QPushButton("创建数据集")
        btn_new.setProperty("primary", True)
        btn_new.clicked.connect(self.create_dataset)
        head.addWidget(btn_new)
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.load)
        head.addWidget(btn_refresh)
        lay.addLayout(head)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["名称", "路径", "图片数", "状态", "创建时间"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        btn_split = QPushButton("划分训练集")
        btn_split.clicked.connect(self.split)
        btn_cats = QPushButton("缺陷类别")
        btn_cats.clicked.connect(self.manage_categories)
        row.addWidget(btn_split)
        row.addWidget(btn_cats)
        row.addStretch(1)
        lay.addLayout(row)

    def load_project(self, pid: int):
        self.pid = pid
        self.load()

    def load(self):
        if not self.pid:
            return
        try:
            self.datasets = api.datasets_list(self.pid)
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))
            return
        self.table.setRowCount(len(self.datasets))
        for r, ds in enumerate(self.datasets):
            self.table.setItem(r, 0, QTableWidgetItem(ds["name"]))
            self.table.setItem(r, 1, QTableWidgetItem(ds["root_path"]))
            self.table.setItem(r, 2, QTableWidgetItem(str(ds["image_count"])))
            self.table.setItem(r, 3, QTableWidgetItem(ds["status"]))
            self.table.setItem(r, 4, QTableWidgetItem(ds["created_at"]))

    def _selected_ds(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一个数据集")
            return None
        return self.datasets[row]

    def create_dataset(self):
        if not self.pid:
            return
        name, ok = QInputDialog.getText(self, "创建数据集", "数据集名称：")
        if not ok or not name.strip():
            return
        path = QFileDialog.getExistingDirectory(self, "选择图像目录")
        if not path:
            return
        try:
            api.dataset_create(self.pid, name.strip(), path)
        except Exception as e:
            QMessageBox.warning(self, "创建失败", str(e))
            return
        self.load()

    def split(self):
        ds = self._selected_ds()
        if not ds:
            return
        dlg = SplitDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            tr, vr, seed = dlg.values()
            r = api.dataset_split(ds["id"], tr, vr, seed)
        except Exception as e:
            QMessageBox.warning(self, "划分失败", str(e))
            return
        QMessageBox.information(self, "完成", r.get("message", "划分完成"))

    def manage_categories(self):
        ds = self._selected_ds()
        if not ds:
            return
        try:
            cats = api.dataset_categories(ds["id"])
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"缺陷类别 · {ds['name']}")
        dlg.resize(360, 360)
        lay = QVBoxLayout(dlg)
        self.cat_list = QTableWidget(0, 2)
        self.cat_list.setHorizontalHeaderLabels(["名称", "颜色"])
        self.cat_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cat_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cat_list.verticalHeader().setVisible(False)
        lay.addWidget(self.cat_list)

        def refresh():
            cats = api.dataset_categories(ds["id"])
            self.cat_list.setRowCount(len(cats))
            for r, c in enumerate(cats):
                self.cat_list.setItem(r, 0, QTableWidgetItem(c["name"]))
                item = QTableWidgetItem(c["color"])
                item.setBackground(Qt.GlobalColor.transparent)
                item.setForeground(Qt.GlobalColor.transparent)
                item.setText(c["color"])
                self.cat_list.setItem(r, 1, item)

        refresh()
        row = QHBoxLayout()
        btn_add = QPushButton("添加类别")
        btn_del = QPushButton("删除选中")

        def add():
            d = CategoryDialog(dlg)
            if d.exec() == QDialog.Accepted:
                try:
                    api.category_create(ds["id"], d.name_edit.text().strip(), "#4E79A7")
                except Exception as e:
                    QMessageBox.warning(dlg, "添加失败", str(e))
                    return
                refresh()

        def remove():
            r = self.cat_list.currentRow()
            if r < 0:
                return
            cats = api.dataset_categories(ds["id"])
            cid = cats[r]["id"]
            if QMessageBox.question(dlg, "确认", "删除该类别？相关标注将变为未分类。") != QMessageBox.Yes:
                return
            api.category_delete(cid)
            refresh()

        btn_add.clicked.connect(add)
        btn_del.clicked.connect(remove)
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        row.addStretch(1)
        lay.addLayout(row)
        dlg.exec()

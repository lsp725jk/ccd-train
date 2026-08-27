"""CCD Train Qt 主窗口：菜单栏 + 左侧项目树 + 右侧页面容器。

页面按模块拆分在 pages/ 下，主窗口负责导航与挂载。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QStackedWidget, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QInputDialog,
    QTabWidget, QAbstractItemView, QStatusBar,
)

from api_client import projects_list, project_create, project_delete, project_get
from themes import THEMES, build_qss, theme_names, current_theme, save_theme
from pages.scenes import ScenesPage
from pages.dataset import DatasetPage
from pages.train import TrainPage
from pages.charts import ChartsPage
from pages.models import ModelsPage
# 标注工作台：X-AnyLabeling 嵌入版（原自研页 pages/labeling_page.py 保留，可回退）
from pages.xal_labeling_page import XalLabelingPage


class ProjectsPage(QWidget):
    """项目列表页：新建 / 删除 / 打开。"""

    opened = Signal(int)  # 项目 id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.projects = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)

        head = QHBoxLayout()
        title = QLabel("检测项目")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        head.addWidget(title)
        head.addStretch(1)
        btn_new = QPushButton("新建项目")
        btn_new.setProperty("primary", True)
        btn_new.clicked.connect(self.create_project)
        head.addWidget(btn_new)
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.load)
        head.addWidget(btn_refresh)
        lay.addLayout(head)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["名称", "描述", "缺陷类别", "数据集", "创建时间"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(lambda _: self.open_selected())
        lay.addWidget(self.table)

        self.load()

    def load(self):
        try:
            self.projects = projects_list()
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))
            return
        self.table.setRowCount(len(self.projects))
        for r, p in enumerate(self.projects):
            self.table.setItem(r, 0, QTableWidgetItem(p["name"]))
            self.table.setItem(r, 1, QTableWidgetItem(p.get("description", "")))
            self.table.setItem(r, 2, QTableWidgetItem(str(p.get("category_count", 0))))
            self.table.setItem(r, 3, QTableWidgetItem(str(p.get("dataset_count", 0))))
            self.table.setItem(r, 4, QTableWidgetItem(p.get("created_at", "")))

    def create_project(self):
        name, ok = QInputDialog.getText(self, "新建检测项目", "项目名称：")
        if not ok or not name.strip():
            return
        desc, ok2 = QInputDialog.getText(self, "新建检测项目", "描述（可选）：")
        if not ok2:
            return
        try:
            project_create(name.strip(), desc.strip())
        except Exception as e:
            QMessageBox.warning(self, "创建失败", str(e))
            return
        self.load()

    def open_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        self.opened.emit(self.projects[row]["id"])

    def remove_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        p = self.projects[row]
        if QMessageBox.question(self, "确认删除",
                                f"删除项目「{p['name']}」？其数据集与模型将一并删除。") != QMessageBox.Yes:
            return
        try:
            project_delete(p["id"])
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e))
            return
        self.load()


class ProjectWorkspace(QWidget):
    """项目工作区：标签页容器，各模块页面挂载在这里。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        self.page_dataset = DatasetPage()
        self.page_labeling = XalLabelingPage()
        self.page_train = TrainPage()
        self.page_charts = ChartsPage()
        self.page_models = ModelsPage()
        self.tabs.addTab(self.page_dataset, "数据集")
        self.tabs.addTab(self.page_labeling, "标注")
        self.tabs.addTab(self._placeholder("预处理 · 增强（P3 开发中）"), "预处理")
        self.tabs.addTab(self._placeholder("聚类（P3 开发中）"), "聚类")
        self.tabs.addTab(self.page_train, "训练中心")
        self.tabs.addTab(self.page_charts, "图表")
        self.tabs.addTab(self.page_models, "模型库")

    def _placeholder(self, msg: str):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        lbl = QLabel(msg)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color: #8a8175; font-size: 14px;")
        lay.addWidget(lbl)
        lay.addStretch(1)
        return w

    def load_project(self, pid: int):
        self.pid = pid
        for page in (self.page_dataset, self.page_labeling, self.page_train,
                     self.page_charts, self.page_models):
            page.load_project(pid)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CCD Train 缺陷检测训练平台")
        self.resize(1440, 900)

        self._build_body()
        self._build_menu()
        self.statusBar().showMessage("后端服务启动中…")

    def _build_menu(self):
        bar = self.menuBar()
        m_file = bar.addMenu("文件")
        m_file.addAction("新建项目", self.pages_projects.create_project)
        m_file.addSeparator()
        m_file.addAction("退出", self.close)
        m_view = bar.addMenu("视图")
        self.theme_menu = m_view.addMenu("主题风格")
        for tid, tname in theme_names():
            act = self.theme_menu.addAction(tname)
            act.setCheckable(True)
            act.setData(tid)
            act.triggered.connect(lambda _, _t=tid: self.apply_theme(_t))
        m_help = bar.addMenu("帮助")
        m_help.addAction("关于", self._about)
        self._sync_theme_checks()

    def apply_theme(self, theme_id: str):
        if theme_id not in THEMES:
            return
        from PySide6.QtWidgets import QApplication
        QApplication.instance().setStyleSheet(build_qss(theme_id))
        save_theme(theme_id)
        self._sync_theme_checks()

    def _sync_theme_checks(self):
        cur = current_theme()
        for act in self.theme_menu.actions():
            act.setChecked(act.data() == cur)

    def _build_body(self):
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：导航（全局菜单 + 项目树）
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("导航")
        self.tree.setMinimumWidth(200)
        splitter.addWidget(self.tree)

        # 右侧：页面容器
        self.stack = QStackedWidget()
        self.pages_projects = ProjectsPage()
        self.pages_projects.opened.connect(self.open_project)
        self.pages_scenes = ScenesPage()
        self.pages_scenes.project_created.connect(self.open_project)
        self.workspace = ProjectWorkspace()
        self.stack.addWidget(self.pages_projects)
        self.stack.addWidget(self.pages_scenes)
        self.stack.addWidget(self.workspace)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 1180])
        self.setCentralWidget(splitter)
        self._refresh_tree()
        self.tree.itemClicked.connect(self._on_tree_click)

    def open_project(self, pid: int):
        self.workspace.load_project(pid)
        self.stack.setCurrentWidget(self.workspace)
        self._refresh_tree(pid)

    def _refresh_tree(self, active_pid: int = 0):
        self.tree.clear()
        nav = QTreeWidgetItem(["导航"])
        it_projects = QTreeWidgetItem(["项目管理"])
        it_projects.setData(0, Qt.UserRole, ("nav", "projects"))
        it_scenes = QTreeWidgetItem(["场景方案"])
        it_scenes.setData(0, Qt.UserRole, ("nav", "scenes"))
        nav.addChild(it_projects)
        nav.addChild(it_scenes)
        self.tree.addTopLevelItem(nav)
        root = QTreeWidgetItem(["检测项目"])
        self.tree.addTopLevelItem(root)
        try:
            for p in projects_list():
                item = QTreeWidgetItem([p["name"]])
                item.setData(0, Qt.UserRole, ("project", p["id"]))
                root.addChild(item)
                if p["id"] == active_pid:
                    item.setSelected(True)
        except Exception:
            pass
        nav.setExpanded(True)
        root.setExpanded(True)

    def _on_tree_click(self, item, _col):
        role = item.data(0, Qt.UserRole)
        if not role:
            return
        kind = role[0]
        if kind == "nav":
            if role[1] == "projects":
                self.pages_projects.load()
                self.stack.setCurrentWidget(self.pages_projects)
            elif role[1] == "scenes":
                self.pages_scenes.load()
                self.stack.setCurrentWidget(self.pages_scenes)
        elif kind == "project":
            self.open_project(role[1])

    def set_backend_ready(self, port: int):
        self.statusBar().showMessage(f"后端服务就绪  http://127.0.0.1:{port}")
        self._refresh_tree()

    def _about(self):
        QMessageBox.about(self, "关于",
                          "CCD Train 缺陷检测训练平台\n\n"
                          "PySide6 桌面版 · FastAPI 后端\n"
                          "数据标注 / 模型训练 / 场景方案 / 模型库")

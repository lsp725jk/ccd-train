"""主题系统：三套皮肤（深色工业 / 水墨 / 绿金暖纸）+ QSS 生成。

颜色变量集中在 THEMES 字典，QSS 模板用占位符填充，改一处全变。
设置菜单可切换，选择存 QSettings，重启记忆。
"""
from string import Template
from PySide6.QtCore import QSettings

ORG = "CCDTrain"
APP = "desktop"

# 每套主题：色板 + 默认缺陷色板（缺陷颜色可用户自选，此处为初始预设）
THEMES = {
    "dark_industrial": {
        "name": "深色工业",
        "bg": "#151A20",          # 窗口底
        "panel": "#1C232B",       # 侧栏/菜单
        "panel2": "#222A33",      # 工具条/表头
        "card": "#242C36",        # 卡片
        "border": "#2E3942",
        "text": "#D8DEE6",
        "text_muted": "#8A94A0",
        "accent": "#5BA8D8",
        "on_accent": "#151A20",
        "accent_soft": "rgba(91,168,216,0.16)",
        "radius": "6px",
        "font_family": "'Microsoft YaHei', system-ui, sans-serif",
        "defect_colors": ["#E65C4F", "#E8A33D", "#6FA8DC", "#5F8F6F", "#C77DDB",
                          "#E8B04D", "#4FC1C1", "#B0A16C", "#7C8B9C", "#E0789A"],
    },
    "ink_wash": {
        "name": "水墨",
        "bg": "#F3EEE2",
        "panel": "#FBF8F0",
        "panel2": "#EDE8DA",
        "card": "#FBF8F0",
        "border": "#3A3A38",
        "text": "#2B2B28",
        "text_muted": "#6B6860",
        "accent": "#B03A2E",
        "on_accent": "#FBF8F0",
        "accent_soft": "rgba(176,58,46,0.10)",
        "radius": "2px",
        "font_family": "'SimSun', 'Noto Serif SC', serif",
        "defect_colors": ["#B03A2E", "#3E4A5C", "#8C6A3E", "#2F4F4F", "#6B5B8E",
                          "#7A6A4F", "#B8860B", "#4F6D5A", "#8B5A2B", "#5C6B73"],
    },
    "green_gold": {
        "name": "绿金暖纸",
        "bg": "#F4EFE3",
        "panel": "#EDE6D6",
        "panel2": "#FBF7EE",
        "card": "#FFFDF7",
        "border": "#D8CFBE",
        "text": "#4A433C",
        "text_muted": "#8A8175",
        "accent": "#4A6B4A",
        "on_accent": "#FBF7EE",
        "accent_soft": "rgba(74,107,74,0.14)",
        "radius": "6px",
        "font_family": "'Noto Serif SC', 'SimSun', serif",
        "defect_colors": ["#4A6B4A", "#B8935A", "#A0522D", "#3D5A43", "#7A6A4F",
                          "#6E8B6E", "#B0A16C", "#8B7355", "#556B2F", "#C97A5A"],
    },
}

QSS_TEMPLATE = Template("""
QMainWindow, QWidget#root { background: $bg; }
QWidget { color: $text; font-family: $font_family; }
QMenuBar { background: $panel; color: $text; }
QMenuBar::item { padding: 4px 10px; background: transparent; }
QMenuBar::item:selected { background: $accent_soft; }
QMenu { background: $panel; color: $text; border: 1px solid $border; }
QMenu::item { padding: 5px 24px 5px 14px; }
QMenu::item:selected { background: $accent_soft; }
QTreeWidget { background: $panel; color: $text; border: none; font-size: 13px; }
QTreeWidget::item { height: 26px; border-radius: $radius; }
QTreeWidget::item:selected { background: $accent_soft; color: $accent; }
QTreeWidget::item:hover { background: $accent_soft; }
QHeaderView::section { background: $panel2; color: $text_muted; border: none; padding: 5px 8px; }
QTableWidget { background: $panel; color: $text; border: 1px solid $border;
               gridline-color: $border; selection-background-color: $accent_soft;
               selection-color: $text; }
QTableWidget::item { padding: 2px 4px; }
QPushButton { background: $panel2; color: $text; border: 1px solid $border;
              border-radius: $radius; padding: 4px 14px; }
QPushButton:hover { border-color: $accent; color: $accent; }
QPushButton[primary="true"] { background: $accent; color: $on_accent; border: none; }
QPushButton[primary="true"]:hover { color: $on_accent; }
QLabel { color: $text; }
QStatusBar { background: $panel; color: $text_muted; }
QStatusBar::item { border: none; }
QTabWidget::pane { border: 1px solid $border; }
QTabBar::tab { background: $panel; color: $text_muted; padding: 6px 16px;
               border: 1px solid $border; border-bottom: none; }
QTabBar::tab:selected { background: $panel2; color: $accent; }
QSplitter::handle { background: $panel; }
QLineEdit, QComboBox, QTextEdit { background: $panel2; color: $text;
    border: 1px solid $border; border-radius: $radius; padding: 3px 6px; }
QLineEdit:focus, QComboBox:focus { border-color: $accent; }
QScrollBar:vertical { background: $panel; width: 10px; }
QScrollBar::handle:vertical { background: $border; border-radius: 4px; min-height: 30px; }
QScrollBar:horizontal { background: $panel; height: 10px; }
QScrollBar::handle:horizontal { background: $border; border-radius: 4px; min-width: 30px; }
QMessageBox, QInputDialog, QDialog { background: $panel; }
""")


def build_qss(theme_id: str) -> str:
    t = THEMES[theme_id]
    return QSS_TEMPLATE.substitute(**t)


def theme_names() -> list[tuple[str, str]]:
    return [(tid, t["name"]) for tid, t in THEMES.items()]


def current_theme() -> str:
    return QSettings(ORG, APP).value("theme", "dark_industrial")


def save_theme(theme_id: str) -> None:
    QSettings(ORG, APP).setValue("theme", theme_id)

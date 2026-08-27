"""场景方案页：物品 → 缺陷勾选 → 推荐方案 → 应用创建项目 / 保存自定义。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
    QLabel, QCheckBox, QPushButton, QGroupBox, QGridLayout, QInputDialog,
    QMessageBox, QScrollArea, QListWidget, QListWidgetItem,
)

import api_client as api

ENGINE_LABELS = {
    "yolo11n": "YOLO11n", "yolo11s": "YOLO11s", "yolo11m": "YOLO11m",
    "yolo11n-cls": "YOLO11n 分类", "yolo11s-cls": "YOLO11s 分类",
    "unet_resnet18": "UNet-ResNet18", "unet_resnet50": "UNet-ResNet50",
    "deeplabv3p_resnet50": "DeepLabV3+", "patchcore": "PatchCore",
}


class ScenesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scenes = []
        self.customs = []
        self.task_labels = {}
        self.active_item = None      # (scene_id, scene_name, item)
        self.active_custom = None
        self.defect_boxes = []       # (QCheckBox, name)
        self.plan = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        title = QLabel("场景方案 · 按检测物品与缺陷类型推荐模型组合")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        lay.addWidget(title)

        split = QSplitter(Qt.Horizontal)
        # 左侧：场景树
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("场景")
        self.tree.setMinimumWidth(230)
        self.tree.itemClicked.connect(self._on_tree_click)
        split.addWidget(self.tree)
        # 右侧：详情
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)

        self.head = QLabel("从左侧选择检测物品")
        self.head.setStyleSheet("font-size: 14px; font-weight: 600;")
        rlay.addWidget(self.head)

        self.defect_box = QGroupBox("待检测缺陷类型")
        dlay = QGridLayout(self.defect_box)
        self.defect_grid = dlay
        rlay.addWidget(self.defect_box)

        self.plan_box = QGroupBox("推荐方案")
        play = QVBoxLayout(self.plan_box)
        self.plan_label = QLabel("")
        self.plan_label.setWordWrap(True)
        self.plan_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        play.addWidget(self.plan_label)
        rlay.addWidget(self.plan_box)

        btns = QHBoxLayout()
        self.btn_apply = QPushButton("应用方案（创建项目）")
        self.btn_apply.setProperty("primary", True)
        self.btn_apply.clicked.connect(self.apply)
        self.btn_save = QPushButton("保存为自定义方案")
        self.btn_save.clicked.connect(self.save_custom)
        btns.addWidget(self.btn_apply)
        btns.addWidget(self.btn_save)
        btns.addStretch(1)
        rlay.addLayout(btns)
        rlay.addStretch(1)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 700])
        lay.addWidget(split)

        self._enable(False)
        self.load()

    def load(self):
        try:
            data = api.scenes_list()
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))
            return
        self.scenes = data["scenes"]
        self.customs = data["customs"]
        self.task_labels = data.get("task_type_labels", {})
        self._rebuild_tree()

    def _rebuild_tree(self):
        self.tree.clear()
        for scene in self.scenes:
            node = QTreeWidgetItem([scene["name"]])
            node.setData(0, Qt.UserRole, ("scene", scene))
            for item in scene["items"]:
                it = QTreeWidgetItem([item["name"]])
                it.setData(0, Qt.UserRole, ("item", scene["id"], scene["name"], item))
                node.addChild(it)
            self.tree.addTopLevelItem(node)
            node.setExpanded(True)
        if self.customs:
            cnode = QTreeWidgetItem(["自定义方案"])
            cnode.setData(0, Qt.UserRole, ("custom_root", None))
            for c in self.customs:
                it = QTreeWidgetItem([f"{c['name']}（{c.get('item_name', '')}）"])
                it.setData(0, Qt.UserRole, ("custom", c))
                cnode.addChild(it)
            self.tree.addTopLevelItem(cnode)
            cnode.setExpanded(True)

    def _on_tree_click(self, item, _col):
        role = item.data(0, Qt.UserRole)
        if not role:
            return
        kind = role[0]
        if kind == "item":
            _, scene_id, scene_name, it = role
            self.active_item = (scene_id, scene_name, it)
            self.active_custom = None
            self._show_item(it)
        elif kind == "custom":
            c = role[1]
            self.active_custom = c
            self.active_item = None
            self._show_custom(c)

    def _clear_defects(self):
        while self.defect_grid.count():
            w = self.defect_grid.itemAt(0).widget()
            if w:
                w.deleteLater()
            self.defect_grid.removeItem(self.defect_grid.itemAt(0))
        self.defect_boxes = []

    def _show_item(self, it):
        self._clear_defects()
        self.head.setText(f"{it['name']}")
        for i, d in enumerate(it["defects"]):
            cb = QCheckBox(d["name"])
            cb.setChecked(True)
            cb.toggled.connect(self._refresh_plan)
            self.defect_grid.addWidget(cb, i // 2, i % 2)
            self.defect_boxes.append(cb)
        self._enable(True)
        self._refresh_plan()

    def _show_custom(self, c):
        self._clear_defects()
        self.head.setText(f"{c.get('item_name', c['name'])}（自定义）")
        for i, name in enumerate(c.get("defects", [])):
            cb = QCheckBox(str(name))
            cb.setChecked(True)
            cb.toggled.connect(self._refresh_plan)
            self.defect_grid.addWidget(cb, i // 2, i % 2)
            self.defect_boxes.append(cb)
        self._enable(True)
        self.plan = {
            "engines": c.get("recommend", {}).get("engines", []),
            "defaults": c.get("recommend", {}).get("defaults", {}),
            "notes": c.get("recommend", {}).get("notes", []),
            "pre_ops": c.get("recommend", {}).get("pre_ops", []),
            "aug_ops": c.get("recommend", {}).get("aug_ops", []),
        }
        self._render_plan()

    def _selected_defects(self):
        return [name for cb, name in self.defect_boxes if cb.isChecked()]

    def _refresh_plan(self):
        if not self.active_item:
            return
        scene_id, _sn, it = self.active_item
        try:
            r = api.scenes_plan(scene_id, it["id"], self._selected_defects())
        except Exception as e:
            QMessageBox.warning(self, "生成方案失败", str(e))
            return
        self.plan = r["plan"]
        self._render_plan()

    def _render_plan(self):
        if not self.plan:
            return
        p = self.plan
        lines = []
        engines = p.get("engines", [])
        lines.append("模型组合：" + "  +  ".join(
            f"{ENGINE_LABELS.get(e['engine'], e['engine'])}（{e.get('role', '')}）" for e in engines) or "（无）")
        d = p.get("defaults", {})
        lines.append(f"参数：epochs={d.get('epochs', '-')}  imgsz={d.get('imgsz', '-')}  batch={d.get('batch', '-')}")
        pre = [op["name"] for op in p.get("pre_ops", []) if op.get("enabled")]
        aug = [op["name"] for op in p.get("aug_ops", []) if op.get("enabled")]
        if pre:
            lines.append("建议预处理：" + "、".join(pre))
        if aug:
            lines.append("建议增强：" + "、".join(aug))
        for n in p.get("notes", []):
            lines.append(f"· {n}")
        self.plan_label.setText("\n".join(lines))

    def _enable(self, on: bool):
        self.defect_box.setEnabled(on)
        self.plan_box.setEnabled(on)
        self.btn_apply.setEnabled(on)
        self.btn_save.setEnabled(on)

    def apply(self):
        if not self.plan:
            return
        if self.active_custom:
            item_name = self.active_custom.get("item_name") or "自定义"
        else:
            item_name = self.active_item[2]["name"]
        import re
        name = re.sub(r"[\\/]", "", item_name) + "检测"
        desc = (f"场景：{item_name}\n缺陷：{'、'.join(self._selected_defects()) or '（未勾选）'}\n"
                f"方案：{self.plan_label.text()}")
        import json
        try:
            proj = api.project_create(name, desc, json.dumps(self.plan, ensure_ascii=False))
            for ops, pname, ptype in [
                (self.plan.get("pre_ops"), "场景推荐预处理", "pre"),
                (self.plan.get("aug_ops"), "场景推荐增强", "aug"),
            ]:
                if ops:
                    try:
                        api.pipeline_create(proj["id"], pname,
                                            [{"name": o["name"], "params": o.get("params", {}),
                                              "enabled": o.get("enabled", True)} for o in ops], ptype)
                    except Exception:
                        pass
        except Exception as e:
            QMessageBox.warning(self, "应用失败", str(e))
            return
        QMessageBox.information(self, "完成", f"项目「{name}」已创建，训练页已预填方案")
        self.project_created.emit(proj["id"])

    project_created = Signal(int)

    def save_custom(self):
        if not self.plan:
            return
        name, ok = QInputDialog.getText(self, "保存自定义方案", "方案名称：")
        if not ok or not name.strip():
            return
        item_name = self.active_custom.get("item_name") if self.active_custom else self.active_item[2]["name"]
        try:
            api.scenes_save_custom({
                "name": name.strip(), "item_name": item_name,
                "defects": self._selected_defects(), "recommend": self.plan, "note": "",
            })
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return
        QMessageBox.information(self, "完成", "自定义方案已保存")
        self.load()

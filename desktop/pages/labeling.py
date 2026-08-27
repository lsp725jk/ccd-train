"""标注工作台：QGraphicsView 画布 + 画框/画笔/选择/橡皮擦 + 撤销重做 + 保存。

标注内存模型：self.shapes = [{id, type, category_id, category_name, color, data}]
保存策略：当前图全量重建（删除后端 manual 标注 → 按 shapes 重建）。
"""
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QBrush, QPolygonF, QPainterPath
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsPolygonItem, QGraphicsPathItem, QGraphicsItem,
)

import api_client as api

TOOL_SELECT = "select"
TOOL_BOX = "box"
TOOL_BRUSH = "brush"
TOOL_ERASE = "erase"


class CanvasView(QGraphicsView):
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sc = QGraphicsScene(self)
        self.setScene(self.sc)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.pix_item = None
        self.image_id = None
        self.tool = TOOL_SELECT
        self.brush_size = 20
        self.categories = []          # [{id, name, color}]
        self.shapes = []              # 内存标注
        self.items = {}               # shape id → QGraphicsItem
        self._pending_rect = None
        self._pending_path = None
        self._drawing = False
        self._undo_stack = []
        self._redo_stack = []

    # ---------- 图像与数据 ----------

    def set_image(self, image_id: int, pix: QPixmap):
        self.sc.clear()
        self.pix_item = self.sc.addPixmap(pix)
        self.sc.setSceneRect(0, 0, pix.width(), pix.height())
        self.image_id = image_id
        self.shapes = []
        self.items = {}
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.resetTransform()
        self.fitInView(self.sc.sceneRect(), Qt.KeepAspectRatio)
        self._load_shapes()

    def _load_shapes(self):
        try:
            rows = api.image_annotations(self.image_id)
        except Exception:
            rows = []
        for a in rows:
            if a["type"] not in ("box", "mask"):
                continue
            shape = {
                "id": a["id"], "type": a["type"],
                "category_id": a.get("category_id"), "category_name": a.get("category_name", ""),
                "color": a.get("color") or "#4E79A7", "data": self._parse_data(a["data"]),
            }
            self.shapes.append(shape)
        self._render_all()

    @staticmethod
    def _parse_data(raw):
        import json
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def set_categories(self, cats: list):
        self.categories = cats

    def current_category(self):
        if not self.categories:
            return None
        return self.categories[0]

    def set_tool(self, tool: str):
        self.tool = tool
        if tool != TOOL_BRUSH:
            self._finish_brush()
        self.setDragMode(QGraphicsView.RubberBandDrag if tool == TOOL_SELECT else QGraphicsView.NoDrag)

    # ---------- 渲染 ----------

    def _render_all(self):
        for it in self.items.values():
            self.sc.removeItem(it)
        self.items = {}
        for s in self.shapes:
            self._add_item(s)

    def _add_item(self, shape: dict):
        color = QColor(shape["color"])
        if shape["type"] == "box":
            d = shape["data"]
            item = QGraphicsRectItem(QRectF(d["x1"], d["y1"], d["x2"] - d["x1"], d["y2"] - d["y1"]))
            item.setPen(QPen(color, 2))
            item.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 30)))
        else:
            pts = shape["data"].get("points", [])
            if not pts:
                return
            poly = QPolygonF([QPointF(p[0], p[1]) for p in pts])
            item = QGraphicsPolygonItem(poly)
            item.setPen(QPen(color, 2))
            item.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 40)))
        item.setFlag(QGraphicsItem.ItemIsSelectable, True)
        item.setData(0, id(shape))
        self.sc.addItem(item)
        self.items[id(shape)] = item

    def _refresh_item(self, shape: dict):
        it = self.items.get(id(shape))
        if it:
            self.sc.removeItem(it)
        self._add_item(shape)

    # ---------- 交互 ----------

    def _scene_pos(self, ev) -> QPointF:
        return self.mapToScene(ev.position().toPoint())

    def mousePressEvent(self, ev):
        if not self.pix_item:
            return
        pos = self._scene_pos(ev)
        if ev.button() == Qt.LeftButton:
            if self.tool == TOOL_BOX:
                self._begin_rect(pos)
            elif self.tool == TOOL_BRUSH:
                self._begin_brush(pos)
            elif self.tool == TOOL_ERASE:
                self._erase_at(pos)
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drawing and self.pix_item:
            pos = self._scene_pos(ev)
            if self.tool == TOOL_BOX and self._pending_rect:
                r = QRectF(self._rect_origin, pos).normalized()
                self._pending_rect.setRect(r)
            elif self.tool == TOOL_BRUSH and self._pending_path:
                self._brush_points.append([pos.x(), pos.y()])
                path = QPainterPath(self._brush_points[0] if len(self._brush_points) == 1 else QPointF(*self._brush_points[-2]))
                for p in self._brush_points[-2:]:
                    path.lineTo(p[0], p[1])
                self._pending_path.setPath(path)
            self.status.emit(f"x: {pos.x():.0f}  y: {pos.y():.0f}")
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._drawing:
            if self.tool == TOOL_BOX and self._pending_rect:
                r = self._pending_rect.rect()
                self._commit_box(r)
            elif self.tool == TOOL_BRUSH:
                self._finish_brush()
        super().mouseReleaseEvent(ev)

    def wheelEvent(self, ev):
        if self.pix_item:
            factor = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
        else:
            super().wheelEvent(ev)

    # ---------- 工具实现 ----------

    def _begin_rect(self, pos: QPointF):
        self._rect_origin = pos
        self._pending_rect = QGraphicsRectItem(QRectF(pos, pos))
        self._pending_rect.setPen(QPen(QColor("#5BA8D8"), 1, Qt.DashLine))
        self.sc.addItem(self._pending_rect)
        self._drawing = True

    def _commit_box(self, r: QRectF):
        cat = self.current_category()
        shape = {
            "id": None, "type": "box",
            "category_id": cat["id"] if cat else None,
            "category_name": cat["name"] if cat else "",
            "color": cat["color"] if cat else "#4E79A7",
            "data": {"x1": r.left(), "y1": r.top(), "x2": r.right(), "y2": r.bottom()},
        }
        self.sc.removeItem(self._pending_rect)
        self._pending_rect = None
        self._drawing = False
        self._push_undo()
        self.shapes.append(shape)
        self._add_item(shape)

    def _begin_brush(self, pos: QPointF):
        self._brush_points = [[pos.x(), pos.y()]]
        self._pending_path = QGraphicsPathItem()
        pen = QPen(QColor("#5BA8D8"), self.brush_size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self._pending_path.setPen(pen)
        self.sc.addItem(self._pending_path)
        self._drawing = True

    def _finish_brush(self):
        if not self._drawing or self.tool != TOOL_BRUSH or not self._pending_path:
            return
        self._drawing = False
        pts = self._brush_points
        self.sc.removeItem(self._pending_path)
        self._pending_path = None
        if len(pts) < 2:
            return
        cat = self.current_category()
        try:
            r = api.annotation_brush(self.image_id, cat["id"] if cat else None, pts, self.brush_size)
        except Exception as e:
            self.status.emit(f"画笔失败：{e}")
            return
        shape = {
            "id": r.get("id"), "type": "mask",
            "category_id": r.get("category_id"), "category_name": r.get("category_name", ""),
            "color": r.get("color") or "#4E79A7", "data": r.get("data", {}),
        }
        self._push_undo()
        self.shapes.append(shape)
        self._add_item(shape)
        self.status.emit(f"已标注 {len(self.shapes)} 条")

    def _erase_at(self, pos: QPointF):
        it = self.sc.itemAt(pos, self.transform())
        if it and it is not self.pix_item:
            sid = it.data(0)
            shape = next((s for s in self.shapes if id(s) == sid), None)
            if shape:
                self._push_undo()
                self.shapes.remove(shape)
                self.sc.removeItem(it)
                self.items.pop(sid, None)
                self.status.emit(f"已删除标注，剩余 {len(self.shapes)} 条")

    # ---------- 撤销/重做/保存 ----------

    def _push_undo(self):
        import copy
        self._undo_stack.append(copy.deepcopy(self.shapes))
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _restore(self, shapes: list):
        self.shapes = shapes
        self._render_all()

    def undo(self):
        if not self._undo_stack:
            return
        import copy
        self._redo_stack.append(copy.deepcopy(self.shapes))
        self._restore(self._undo_stack.pop())

    def redo(self):
        if not self._redo_stack:
            return
        import copy
        self._undo_stack.append(copy.deepcopy(self.shapes))
        self._restore(self._redo_stack.pop())

    def dirty_shapes(self):
        """返回需要写回后端的标注列表（id=None 的是新增）。"""
        return [s for s in self.shapes]

    def save(self) -> bool:
        """全量重建：删除后端 manual 标注，按当前 shapes 写入。"""
        if not self.image_id:
            return False
        try:
            old = api.image_annotations(self.image_id)
            for a in old:
                if a.get("source", "manual") == "manual" and a["type"] in ("box", "mask"):
                    api.annotation_delete(a["id"])
            for s in self.shapes:
                if s["type"] == "box":
                    api.annotation_create(self.image_id, s["category_id"], "box", s["data"])
                elif s["type"] == "mask" and s["id"] is None:
                    # 画笔已即时写入后端，跳过；纯多边形需重建
                    if s.get("_local"):
                        api.annotation_create(self.image_id, s["category_id"], "mask", s["data"])
        except Exception as e:
            self.status.emit(f"保存失败：{e}")
            return False
        self.status.emit(f"已保存 {len(self.shapes)} 条标注")
        return True

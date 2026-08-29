"""SAM 辅助标注 + 笔刷转掩码。

- POST /sam/predict：图像 + 点击点 → MobileSAM 掩码 → 多边形
- POST /annotations/brush：笔刷轨迹点 → 掩码多边形 → 直接创建 mask 标注
"""
import json
import sqlite3
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.db import get_conn

# ---- 常量 ----
SAM_CONF = 0.25        # SAM 推理置信度阈值
MAX_POLYS = 3          # 单次推理最多保留的多边形数
MIN_POLY_AREA = 30     # 小于该面积的轮廓忽略（像素）
MAX_PAINT_SIDE = 1024  # 逐像素编辑时降采样最长边
POLY_EPS = 0.5         # 轮廓简化精度（像素）；0.5 让多边形更贴合掩码边界，适配像素级精修

class SamPredictRequest(BaseModel):
    image_id: int
    points: list[list[float]] = []  # [[x, y], ...] 前景点击点
    neg_points: list[list[float]] = []  # [[x, y], ...] 背景点击点（抑制误检）
    box: list[float] | None = None  # [x1, y1, x2, y2] 框提示

class BrushRequest(BaseModel):
    image_id: int
    category_id: int
    points: list[list[float]]  # 笔刷轨迹（原图坐标）
    brush_size: int = 20
    type: str = "mask"  # mask=缺陷掩码 / shield=屏蔽区（不参与训练）

class PaintRequest(BaseModel):
    points: list[list[float]]  # 笔刷轨迹（原图坐标）
    brush_size: int = 8
    erase: bool = False  # True=擦除

router = APIRouter()

_sam_model = None


def _get_sam():
    """懒加载 MobileSAM（权重 mobile_sam.pt 需预先放到 backend 目录）。"""
    global _sam_model
    if _sam_model is None:
        from ultralytics import SAM
        try:
            _sam_model = SAM("mobile_sam.pt")
        except Exception as e:
            raise HTTPException(500, f"SAM 模型加载失败（检查 backend/mobile_sam.pt）：{e}")
    return _sam_model


def _load_image(image_id: int):
    """按 image_id 读取图像（BGR），返回 (img, width, height)。"""
    from app.engines.data_utils import load_image_by_id
    try:
        img, im = load_image_by_id(image_id)
    except ValueError:
        raise HTTPException(404, "图像不存在")
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    return img, im["width"], im["height"]


def _mask_to_polygons(mask: np.ndarray, max_polys: int = MAX_POLYS) -> list[list[list[float]]]:
    """二进制 mask → 简化多边形列表。"""
    mask_u8 = (mask > 0).astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:max_polys]
    polys = []
    for c in contours:
        if cv2.contourArea(c) < MIN_POLY_AREA:
            continue
        poly = cv2.approxPolyDP(c, POLY_EPS, True).reshape(-1, 2)
        if len(poly) >= 3:
            polys.append([[float(x), float(y)] for x, y in poly])
    return polys


@router.post("/sam/predict")
def sam_predict(body: SamPredictRequest):
    if not body.points and not body.box:
        raise HTTPException(400, "至少提供点击点或框提示")
    img, w, h = _load_image(body.image_id)
    model = _get_sam()
    try:
        kwargs = {"conf": SAM_CONF, "verbose": False}
        # 提示合并：box 转 2 角点（label 2/3，SAM 原版约定），与正负点统一走 points 路径。
        # 不传 bboxes：Ultralytics MobileSAM 在 points 数量 > 1 且同时传 box 时会崩溃。
        all_pts = [list(p) for p in body.points] + [list(p) for p in body.neg_points]
        all_labels = [1] * len(body.points) + [0] * len(body.neg_points)
        if body.box:
            x1, y1, x2, y2 = body.box
            all_pts += [[x1, y1], [x2, y2]]
            all_labels += [2, 3]
        if all_pts:
            kwargs["points"] = np.array(all_pts, dtype=float).reshape(-1, 2)
            kwargs["labels"] = np.array(all_labels, dtype=int)
        results = model.predict(img, **kwargs)
    except Exception as e:
        raise HTTPException(500, f"SAM 推理失败：{e}")

    if not results or results[0].masks is None:
        return {"polygons": []}
    masks = results[0].masks.data.cpu().numpy()  # (N, H, W)
    if masks.shape[-2:] != (h, w):
        masks = [cv2.resize(m.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST).astype(bool) for m in masks]
    polygons = []
    for m in masks:
        polygons.extend(_mask_to_polygons(m))
    return {"polygons": polygons}


@router.post("/annotations/{annotation_id}/paint")
def paint_mask(annotation_id: int, body: PaintRequest):
    """逐像素编辑 mask 标注：涂抹/擦除后重新提取轮廓更新多边形。

    大图优化：mask 操作在降采样尺寸上进行（最长边 MAX_SIDE），
    轮廓提取后坐标按比例放大回原图，速度提升 5-10 倍。
    """
    MAX_SIDE = MAX_PAINT_SIDE
    with get_conn() as conn:
        ann = conn.execute("SELECT * FROM annotations WHERE id=?", (annotation_id,)).fetchone()
        if not ann:
            raise HTTPException(404, "标注不存在")
        if ann["type"] != "mask":
            raise HTTPException(400, "只能编辑 mask 标注")
        im = conn.execute("SELECT width, height FROM images WHERE id=?", (ann["image_id"],)).fetchone()
        if not im:
            raise HTTPException(404, "图像不存在")
        w, h = im["width"], im["height"]
        d = json.loads(ann["data"]) if ann["data"] else {}

    scale_f = min(1.0, MAX_SIDE / max(w, h))
    sw, sh = max(1, int(w * scale_f)), max(1, int(h * scale_f))

    # 还原现有掩码（降采样尺寸）
    mask = np.zeros((sh, sw), dtype=np.uint8)
    if d.get("points"):
        pts = np.array(d["points"], dtype=np.float32).reshape(-1, 2) * scale_f
        cv2.fillPoly(mask, [pts.astype(np.int32)], 255)

    # 涂抹/擦除（降采样尺寸）
    r = max(1, int(round(body.brush_size * scale_f / 2)))
    value = 0 if body.erase else 255
    pts = [(int(x * scale_f), int(y * scale_f)) for x, y in body.points]
    for x, y in pts:
        cv2.circle(mask, (x, y), r, value, -1)
    for i in range(len(pts) - 1):
        cv2.line(mask, pts[i], pts[i + 1], value, max(1, r))

    # 重新提取轮廓（降采样尺寸）
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        with get_conn() as conn:
            conn.execute("DELETE FROM annotations WHERE id=?", (annotation_id,))
        return {"deleted": True}
    poly = max(contours, key=cv2.contourArea)
    poly = cv2.approxPolyDP(poly, POLY_EPS, True).reshape(-1, 2)
    if len(poly) < 3:
        with get_conn() as conn:
            conn.execute("DELETE FROM annotations WHERE id=?", (annotation_id,))
        return {"deleted": True}

    # 坐标放大回原图
    if scale_f < 1.0:
        poly = poly.astype(np.float32) / scale_f

    with get_conn() as conn:
        conn.execute(
            "UPDATE annotations SET data=? WHERE id=?",
            (json.dumps({"points": [[float(x), float(y)] for x, y in poly]}, ensure_ascii=False), annotation_id),
        )
        row = conn.execute(
            """SELECT a.*, c.name AS category_name, c.color FROM annotations a
               LEFT JOIN categories c ON c.id = a.category_id WHERE a.id = ?""",
            (annotation_id,),
        ).fetchone()
        return dict(row)


@router.post("/annotations/brush", status_code=201)
def brush_to_mask(body: BrushRequest):
    """笔刷轨迹 → 掩码多边形 → 创建 mask/shield 标注。"""
    if len(body.points) < 2:
        raise HTTPException(400, "轨迹点太少")
    if body.type not in ("mask", "shield"):
        raise HTTPException(400, "type 必须是 mask 或 shield")
    img, w, h = _load_image(body.image_id)
    mask = np.zeros((h, w), dtype=np.uint8)
    pts = [(int(x), int(y)) for x, y in body.points]
    r = max(1, int(body.brush_size) // 2)
    for x, y in pts:
        cv2.circle(mask, (x, y), r, 255, -1)
    for i in range(len(pts) - 1):
        cv2.line(mask, pts[i], pts[i + 1], 255, max(1, r))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise HTTPException(400, "笔刷区域太小，无法生成掩码")
    poly = max(contours, key=cv2.contourArea)
    poly = cv2.approxPolyDP(poly, POLY_EPS, True).reshape(-1, 2)
    if len(poly) < 3:
        raise HTTPException(400, "笔刷区域太小，无法生成掩码")

    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM images WHERE id=?", (body.image_id,)).fetchone():
            raise HTTPException(404, "图像不存在")
        if not conn.execute("SELECT 1 FROM categories WHERE id=?", (body.category_id,)).fetchone():
            raise HTTPException(404, "类别不存在")
        cur = conn.execute(
            """INSERT INTO annotations (image_id, category_id, type, data, source)
               VALUES (?, ?, ?, ?, 'manual')""",
            (body.image_id, body.category_id, body.type,
             json.dumps({"points": [[float(x), float(y)] for x, y in poly]}, ensure_ascii=False)),
        )
        row = conn.execute(
            """SELECT a.*, c.name AS category_name, c.color FROM annotations a
               LEFT JOIN categories c ON c.id = a.category_id WHERE a.id = ?""",
            (cur.lastrowid,),
        ).fetchone()
        return dict(row)

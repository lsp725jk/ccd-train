"""X-AnyLabeling 几何/掩码核心算法复用（Apache-2.0，来源：
third_party/x_anylabeling_cvhub-4.0.4/anylabeling/views/labeling/utils/shape.py
与 widgets/canvas.py 的形状生成逻辑，去除 Qt 依赖）。

提供：掩码绘制（圆/矩形/多边形/线/点）、掩码→bbox、圆/椭圆→多边形采样、
对角线→矩形顶点等，供标注工作台后端 API 与格式转换使用。
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw


# ---------------------------------------------------------------------------
# 形状 → 掩码（原 shape_to_mask，PIL 绘制）
# ---------------------------------------------------------------------------

def shape_to_mask(
    img_shape: tuple,
    points: Sequence[Sequence[float]],
    shape_type: str | None = None,
    line_width: int = 10,
    point_size: int = 5,
) -> np.ndarray:
    """把形状点列绘制为 bool 掩码。points 为 [[x, y], ...]。"""
    img = Image.fromarray(np.zeros(img_shape[:2], dtype=np.uint8))
    draw = ImageDraw.Draw(img)
    xy = [tuple(point) for point in points]
    if shape_type == "circle":
        assert len(xy) == 2, "circle 需要 2 个点（圆心 + 边缘点）"
        (cx, cy), (px, py) = xy
        d = math.sqrt((cx - px) ** 2 + (cy - py) ** 2)
        draw.ellipse([cx - d, cy - d, cx + d, cy + d], outline=1, fill=1)
    elif shape_type == "rectangle":
        assert len(xy) == 2, "rectangle 需要 2 个点"
        draw.rectangle(xy, outline=1, fill=1)
    elif shape_type == "rotation":
        assert len(xy) == 4, "rotation 需要 4 个点"
        draw.polygon(xy=xy, outline=1, fill=1)
    elif shape_type == "quadrilateral":
        assert len(xy) == 4, "quadrilateral 需要 4 个点"
        draw.polygon(xy=xy, outline=1, fill=1)
    elif shape_type == "line":
        assert len(xy) == 2, "line 需要 2 个点"
        draw.line(xy=xy, fill=1, width=line_width)
    elif shape_type == "linestrip":
        draw.line(xy=xy, fill=1, width=line_width)
    elif shape_type == "point":
        assert len(xy) == 1, "point 需要 1 个点"
        cx, cy = xy[0]
        r = point_size
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=1, fill=1)
    else:
        assert len(xy) > 2, "多边形至少需要 3 个点"
        draw.polygon(xy=xy, outline=1, fill=1)
    return np.array(img, dtype=bool)


def masks_to_bboxes(masks: np.ndarray) -> np.ndarray:
    """(N, H, W) bool 掩码 → (N, 4) bbox（y1, x1, y2, x2）。"""
    if masks.ndim != 3:
        raise ValueError(f"masks.ndim 必须为 3，实际 {masks.ndim}")
    if masks.dtype != bool:
        raise ValueError(f"masks.dtype 必须为 bool，实际 {masks.dtype}")
    bboxes = []
    for mask in masks:
        where = np.argwhere(mask)
        (y1, x1), (y2, x2) = where.min(0), where.max(0) + 1
        bboxes.append((y1, x1, y2, x2))
    return np.asarray(bboxes, dtype=np.float32)


def rectangle_from_diagonal(diagonal_vertices: Sequence[Sequence[float]]) -> list:
    """对角线两点 → 矩形四顶点 [tl -> tr -> br -> bl]。"""
    x1, y1 = diagonal_vertices[0]
    x2, y2 = diagonal_vertices[1]
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


# ---------------------------------------------------------------------------
# 圆/椭圆 → 多边形（原 circle_to_polygon：等角采样）
# ---------------------------------------------------------------------------

def circle_to_polygon(
    center: Sequence[float],
    radius: float,
    num_sides: int = 32,
) -> list[list[float]]:
    """圆 → 正多边形点列（顺时针）。"""
    center_x, center_y = float(center[0]), float(center[1])
    pts = []
    for i in range(num_sides):
        angle = 2 * math.pi * i / num_sides
        pts.append([center_x + radius * math.cos(angle),
                    center_y + radius * math.sin(angle)])
    return pts


def ellipse_to_polygon(
    cx: float, cy: float, rx: float, ry: float, num_sides: int = 32
) -> list[list[float]]:
    """椭圆 → 多边形点列（参数方程采样）。"""
    pts = []
    for i in range(num_sides):
        angle = 2 * math.pi * i / num_sides
        pts.append([cx + rx * math.cos(angle), cy + ry * math.sin(angle)])
    return pts


def circle_center_radius(points: Sequence[Sequence[float]]) -> tuple:
    """circle 两点（圆心+边缘）→ (cx, cy, r)。"""
    if len(points) != 2:
        return None, None, None
    (cx, cy), (ex, ey) = points[0], points[1]
    r = math.hypot(ex - cx, ey - cy)
    if r <= 0:
        return None, None, None
    return float(cx), float(cy), float(r)


def ellipse_center_radii(points: Sequence[Sequence[float]]) -> tuple:
    """ellipse 两点（圆心+边缘）→ (cx, cy, rx, ry)，支持椭圆。"""
    if len(points) != 2:
        return None, None, None, None
    (cx, cy), (ex, ey) = points[0], points[1]
    rx = abs(ex - cx)
    ry = abs(ey - cy)
    if rx <= 0 or ry <= 0:
        return None, None, None, None
    return float(cx), float(cy), float(rx), float(ry)


# ---------------------------------------------------------------------------
# 掩码 → 多边形（cv2 轮廓简化）
# ---------------------------------------------------------------------------

def mask_to_polygons(mask: np.ndarray, max_polys: int = 3,
                     eps: float = 2.0) -> list[list[list[float]]]:
    """bool 掩码 → 简化多边形列表（按面积降序，取前 max_polys 个连通域）。"""
    import cv2

    mask_u8 = (mask > 0).astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:max_polys]
    polys = []
    for c in contours:
        if cv2.contourArea(c) < 30:
            continue
        poly = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
        if len(poly) >= 3:
            polys.append([[float(x), float(y)] for x, y in poly])
    return polys

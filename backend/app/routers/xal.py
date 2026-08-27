"""X-AnyLabeling 代码复用路由：椭圆/圆→多边形、掩码→bbox 等标注辅助。

来源：third_party/x_anylabeling_cvhub-4.0.4（Apache-2.0），算法实现
见 app/xal/geometry.py。Web 标注页通过本路由获得与 X-AnyLabeling
一致的几何行为，无需自研。
"""
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.xal import geometry as xal_geo

router = APIRouter()


class EllipseRequest(BaseModel):
    points: list[list[float]]  # 两点：圆心 + 边缘点（rx=|dx|, ry=|dy|）
    num_sides: int = 32


class CircleRequest(BaseModel):
    points: list[list[float]]  # 两点：圆心 + 边缘点
    num_sides: int = 32


class MaskBboxRequest(BaseModel):
    points: list[list[float]]  # 掩码多边形
    image_width: int
    image_height: int


class ShapeMaskRequest(BaseModel):
    points: list[list[float]]
    shape_type: str = "polygon"  # polygon/rectangle/circle/line/point
    image_width: int
    image_height: int
    line_width: int = 10
    point_size: int = 5


@router.post("/xal/ellipse")
def ellipse_to_polygon(body: EllipseRequest):
    """椭圆（圆心+边缘点）→ 多边形点列，前端直接存为 mask 标注。"""
    cx, cy, rx, ry = xal_geo.ellipse_center_radii(body.points)
    if rx is None:
        raise HTTPException(400, "椭圆参数无效：需要 2 个点（圆心 + 边缘点）")
    return {"points": xal_geo.ellipse_to_polygon(cx, cy, rx, ry, body.num_sides)}


@router.post("/xal/circle")
def circle_to_polygon(body: CircleRequest):
    """圆（圆心+边缘点）→ 正多边形点列。"""
    cx, cy, r = xal_geo.circle_center_radius(body.points)
    if r is None:
        raise HTTPException(400, "圆参数无效：需要 2 个点（圆心 + 边缘点）")
    return {"points": xal_geo.circle_to_polygon([cx, cy], r, body.num_sides)}


@router.post("/xal/mask/bbox")
def mask_to_bbox(body: MaskBboxRequest):
    """掩码多边形 → 最小外接矩形（目标检测标注辅助：画完掩码自动出框）。"""
    pts = np.asarray(body.points, dtype=np.float32)
    if len(pts) < 3:
        raise HTTPException(400, "掩码至少需要 3 个点")
    mask = xal_geo.shape_to_mask((body.image_height, body.image_width), body.points)
    (y1, x1, y2, x2) = xal_geo.masks_to_bboxes(mask[None, :, :])[0]
    return {"x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2)}


@router.post("/xal/shape/mask")
def shape_to_mask_route(body: ShapeMaskRequest):
    """任意形状 → bool 掩码（以多边形列表返回，供校验/转换）。"""
    try:
        mask = xal_geo.shape_to_mask(
            (body.image_height, body.image_width),
            body.points,
            shape_type=body.shape_type,
            line_width=body.line_width,
            point_size=body.point_size,
        )
    except AssertionError as e:
        raise HTTPException(400, str(e))
    polys = xal_geo.mask_to_polygons(mask)
    return {"polygons": polys}

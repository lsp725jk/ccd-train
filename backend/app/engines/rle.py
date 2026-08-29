"""RLE 位图掩码编解码（Label Studio / COCO 兼容格式）。

格式：{"size": [h, w], "counts": "a,b,c,..."}，counts 为交替的游程长度，
从 0 开始，按 Fortran（列优先）展平顺序 —— 与 pycocotools / Label Studio 一致，
可与其他标注工具互通。RLE 是逐像素精确的掩码存储，无多边形折线误差。
"""
import cv2
import numpy as np


def mask_to_rle(mask: np.ndarray) -> dict:
    """(h, w) 布尔/uint8 掩码 → RLE 字典（向量化，5M 像素 ~15ms）。"""
    h, w = mask.shape
    flat = np.ascontiguousarray(mask > 0, dtype=np.uint8).ravel(order="F")
    n = flat.size
    if n == 0:
        return {"size": [int(h), int(w)], "counts": "0"}
    change = np.flatnonzero(np.diff(flat))
    starts = np.concatenate(([0], change + 1))
    lens = np.diff(np.concatenate((starts, [n]))).tolist()
    if flat[0] == 1:
        lens.insert(0, 0)  # 首段 0 值游程（COCO 约定：偶数位为 0 游程长度）
    return {"size": [int(h), int(w)], "counts": ",".join(map(str, lens))}


def rle_to_mask(rle: dict) -> np.ndarray:
    """RLE 字典 → (h, w) 布尔掩码。"""
    h, w = int(rle["size"][0]), int(rle["size"][1])
    counts = [int(x) for x in str(rle["counts"]).split(",")]
    flat = np.zeros(h * w, dtype=np.uint8)
    pos = 0
    val = 0
    for c in counts:
        flat[pos:pos + c] = val
        pos += c
        val ^= 1
    # Fortran 展平 → 行优先 (h, w)；ascontiguousarray 保证输出 C 连续
    #（numpy 2.x 的 ufunc 对非连续输入可能返回非连续输出，cv2 会拒绝）
    mask = flat.reshape((w, h)).T
    return np.ascontiguousarray(mask > 0)


def ann_to_mask(d: dict, h: int, w: int) -> np.ndarray:
    """标注 data → (h, w) 布尔掩码：RLE 优先（逐像素精确），points 兜底（fillPoly）。

    兼容旧数据：历史上 mask 标注只存简化多边形 points。
    """
    if isinstance(d, str):
        import json
        try:
            d = json.loads(d)
        except Exception:
            d = {}
    rle = d.get("rle")
    if isinstance(rle, dict) and rle.get("size") and rle.get("counts"):
        try:
            return rle_to_mask(rle)
        except Exception:
            pass
    pts = d.get("points")
    if pts and len(pts) >= 3:
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask, [np.array(pts, dtype=np.int32).reshape(-1, 2)], 255)
        return np.ascontiguousarray(mask > 0)
    return np.zeros((h, w), dtype=bool)


def mask_to_ann_data(mask: np.ndarray, eps: float = 0.5) -> dict:
    """掩码 → 标注 data：RLE（权威）+ points（简化轮廓，供轮廓渲染/命中/兼容）。

    points 只取最大连通域（扁平坐标，与历史格式一致：前端按单多边形渲染）；
    多连通域的其余像素由 RLE 位图完整保留，渲染填充/擦除均为逐像素精确。
    eps 取 0.5：轮廓只做轻微简化，视觉与 RLE 边界基本一致。
    """
    rle = mask_to_rle(mask)
    pts = _mask_to_points(mask, eps=eps, max_polys=1)
    d: dict = {"points": pts[0] if pts else [], "rle": rle}
    if not d["points"]:
        d.pop("points", None)
    return d


def _mask_to_points(mask: np.ndarray, eps: float = 0.5, max_polys: int = 3,
                    min_area: int = 1) -> list[list[list[float]]]:
    """掩码 → 简化多边形列表（按面积降序，取前 max_polys 个连通域）。"""
    mask_u8 = (mask > 0).astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:max_polys]
    polys = []
    for c in contours:
        if cv2.contourArea(c) < min_area:
            continue
        poly = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
        if len(poly) >= 3:
            polys.append([[float(x), float(y)] for x, y in poly])
    return polys

"""预处理管线管理 + 预处理/增强预览。"""
import json
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.db import get_conn
from app.ops import AUG_REGISTRY, OP_REGISTRY, apply_augmentation, apply_preprocess, encode_preview

class OpSpec(BaseModel):
    name: str
    params: dict = {}
    enabled: bool = True

class PipelineCreate(BaseModel):
    project_id: int
    name: str = Field(min_length=1, max_length=64)
    ops: list[OpSpec] = []
    type: str = "pre"  # pre=预处理 / aug=增强

class PreprocessPreviewRequest(BaseModel):
    image_id: int
    ops: list[OpSpec] = []

class AugmentPreviewRequest(BaseModel):
    image_id: int
    augs: list[OpSpec] = []
    seed: int = 42

router = APIRouter()


def _op_public(reg):
    return [{"name": v["name"], "label": v["label"], "params": v["params"]} for v in reg.values()]


@router.get("/ops/preprocess")
def list_preprocess_ops():
    return _op_public(OP_REGISTRY)


@router.get("/ops/augment")
def list_augment_ops():
    return _op_public(AUG_REGISTRY)


def _load_image(image_id: int):
    """按 image_id 读取图像（BGR）。"""
    from app.engines.data_utils import load_image_by_id
    try:
        return load_image_by_id(image_id)[0]
    except ValueError:
        raise HTTPException(404, "图像不存在")
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))


@router.post("/preview/preprocess")
def preview_preprocess(body: PreprocessPreviewRequest):
    img = _load_image(body.image_id)
    try:
        out = apply_preprocess(img, [op.model_dump() for op in body.ops])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"image": encode_preview(out)}


@router.post("/preview/augment")
def preview_augment(body: AugmentPreviewRequest):
    img = _load_image(body.image_id)
    try:
        out = apply_augmentation(img, [a.model_dump() for a in body.augs], seed=body.seed)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"image": encode_preview(out)}


class ResizePreviewRequest(BaseModel):
    image_id: int
    width: int = Field(ge=32, le=8192)
    height: int = Field(ge=32, le=8192)


def _letterbox(img: np.ndarray, tw: int, th: int):
    """等比缩放 + 灰边填充到目标尺寸，返回 (canvas, nw, nh, scale)。"""
    h, w = img.shape[:2]
    scale = min(tw / w, th / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((th, tw, 3), 114, dtype=np.uint8)
    y0, x0 = (th - nh) // 2, (tw - nw) // 2
    canvas[y0:y0 + nh, x0:x0 + nw] = resized
    return canvas, nw, nh, scale


def _defect_stats(image_id: int, scale: float, w: int, h: int):
    """图像缺陷统计：类别/像素/输入尺寸像素/占比。"""
    defects = []
    total_px = 0
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT a.type, a.data, c.name FROM annotations a
               LEFT JOIN categories c ON c.id = a.category_id
               WHERE a.image_id = ? AND a.type IN ('box','mask')""",
            (image_id,),
        ).fetchall()
    for a in rows:
        d = json.loads(a["data"])
        if a["type"] == "box" and all(k in d for k in ("x1", "y1", "x2", "y2")):
            px = (d["x2"] - d["x1"]) * (d["y2"] - d["y1"])
        elif a["type"] == "mask" and d.get("points"):
            pts = np.array(d["points"], dtype=np.float32).reshape(-1, 2)
            px = float(cv2.contourArea(pts))
        else:
            continue
        total_px += px
        defects.append({
            "category": a["name"] or "未分类",
            "pixels": round(px),
            "input_pixels": round(px * scale * scale),  # 模型输入尺寸下的像素
            "ratio": round(px / (w * h) * 100, 2),
        })
    return defects, total_px


@router.post("/preview/resize")
def preview_resize(body: ResizePreviewRequest):
    """模型视角预览：letterbox 到输入尺寸，附带图像与缺陷统计信息。"""
    img = _load_image(body.image_id)
    h, w = img.shape[:2]
    canvas, nw, nh, scale = _letterbox(img, body.width, body.height)
    defects, total_px = _defect_stats(body.image_id, scale, w, h)

    info = {
        "orig_size": [w, h],
        "input_size": [body.width, body.height],
        "resized_size": [nw, nh],
        "scale_ratio": round(scale, 4),
        "effective_ratio": round(nw * nh / (body.width * body.height) * 100, 1),
        "defect_count": len(defects),
        "defect_pixels_total": round(total_px),
        "defects": defects,
    }
    return {"image": encode_preview(canvas), "info": info}


@router.post("/pipelines", status_code=201)
def create_pipeline(body: PipelineCreate):
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (body.project_id,)).fetchone():
            raise HTTPException(404, "项目不存在")
        try:
            cur = conn.execute(
                "INSERT INTO preprocess_pipelines (project_id, name, ops, type) VALUES (?, ?, ?, ?)",
                (body.project_id, body.name.strip(),
                 json.dumps([o.model_dump() for o in body.ops], ensure_ascii=False),
                 body.type),
            )
        except Exception:
            raise HTTPException(400, f"管线名「{body.name}」已存在")
        return dict(conn.execute(
            "SELECT * FROM preprocess_pipelines WHERE id = ?", (cur.lastrowid,)
        ).fetchone())


@router.get("/projects/{project_id}/pipelines")
def list_pipelines(project_id: int, type: str = ""):
    with get_conn() as conn:
        if type:
            rows = conn.execute(
                "SELECT * FROM preprocess_pipelines WHERE project_id = ? AND type = ? ORDER BY id",
                (project_id, type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM preprocess_pipelines WHERE project_id = ? ORDER BY id", (project_id,)
            ).fetchall()
        return [dict(r) for r in rows]


@router.delete("/pipelines/{pipeline_id}", status_code=204)
def delete_pipeline(pipeline_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM preprocess_pipelines WHERE id = ?", (pipeline_id,))
        if conn.total_changes == 0:
            raise HTTPException(404, "管线不存在")

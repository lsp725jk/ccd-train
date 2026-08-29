"""数据集管理：目录扫描导入、图像列表、划分、离线增强扩充。"""
import json
import random
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query
from PIL import Image

from app.db import get_conn

class DatasetCreate(BaseModel):
    project_id: int
    name: str = Field(min_length=1, max_length=64)
    root_path: str = Field(min_length=1)

class SplitRequest(BaseModel):
    train_ratio: float = Field(default=0.8, ge=0, le=1)
    val_ratio: float = Field(default=0.1, ge=0, le=1)
    seed: int = 42


class AugmentRequest(BaseModel):
    pipeline_id: int
    copies: int = Field(default=3, ge=1, le=20)
    name: str = Field(min_length=1, max_length=64)

router = APIRouter()

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _scan_images(root: Path):
    """返回 (rel_path, width, height) 列表。PIL 只读文件头，不加载像素。"""
    out = []
    for p in root.rglob("*"):
        if p.suffix.lower() in IMG_EXT and p.is_file():
            try:
                with Image.open(p) as im:
                    out.append((p.relative_to(root).as_posix(), im.width, im.height))
            except Exception:
                continue
    return out


@router.post("/datasets", status_code=201)
def create_dataset(body: DatasetCreate):
    root = Path(body.root_path.strip())
    if not root.is_dir():
        raise HTTPException(400, f"目录不存在：{root}")
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (body.project_id,)).fetchone():
            raise HTTPException(404, "项目不存在")
        images = _scan_images(root)
        if not images:
            raise HTTPException(400, "目录中没有找到图片（支持 jpg/png/bmp/webp）")
        try:
            cur = conn.execute(
                "INSERT INTO datasets (project_id, name, root_path, image_count) VALUES (?, ?, ?, ?)",
                (body.project_id, body.name.strip(), str(root.resolve()), len(images)),
            )
        except Exception:
            raise HTTPException(400, f"数据集名「{body.name}」已存在")
        ds_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO images (dataset_id, rel_path, width, height) VALUES (?, ?, ?, ?)",
            [(ds_id, rel, w, h) for rel, w, h in images],
        )
        return dict(conn.execute("SELECT * FROM datasets WHERE id = ?", (ds_id,)).fetchone())


@router.get("/datasets")
def list_datasets(project_id: int = Query(...)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM datasets WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if not row:
            raise HTTPException(404, "数据集不存在")
        stats = conn.execute(
            "SELECT split, COUNT(*) AS n FROM images WHERE dataset_id = ? GROUP BY split",
            (dataset_id,),
        ).fetchall()
        return {**dict(row), "split_stats": {r["split"] or "none": r["n"] for r in stats}}


@router.get("/datasets/{dataset_id}/images")
def list_images(
    dataset_id: int,
    split: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM datasets WHERE id = ?", (dataset_id,)).fetchone():
            raise HTTPException(404, "数据集不存在")
        where, args = "dataset_id = ?", [dataset_id]
        if split:
            where += " AND split = ?"
            args.append(split)
        total = conn.execute(f"SELECT COUNT(*) FROM images WHERE {where}", args).fetchone()[0]
        rows = conn.execute(
            f"""SELECT im.*, (SELECT COUNT(*) FROM annotations a WHERE a.image_id = im.id) AS annotation_count
                FROM images im WHERE {where} ORDER BY im.id LIMIT ? OFFSET ?""",
            (*args, page_size, (page - 1) * page_size),
        ).fetchall()
        return {"total": total, "items": [dict(r) for r in rows]}


@router.delete("/datasets/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: int):
    task_ids = []
    with get_conn() as conn:
        # 级联清理引用该数据集的训练任务与模型（训练产物依赖数据集）
        task_ids = [r[0] for r in conn.execute(
            "SELECT id FROM train_tasks WHERE dataset_id = ?", (dataset_id,)).fetchall()]
        model_ids = [r[0] for r in conn.execute(
            "SELECT model_id FROM train_tasks WHERE dataset_id = ?", (dataset_id,)).fetchall()]
        conn.execute("DELETE FROM train_tasks WHERE dataset_id = ?", (dataset_id,))
        for mid in model_ids:
            conn.execute("DELETE FROM models WHERE id = ?", (mid,))
        conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
        if conn.total_changes == 0:
            raise HTTPException(404, "数据集不存在")
    from app.config import RUNS_DIR
    import shutil
    for tid in task_ids:
        shutil.rmtree(RUNS_DIR / str(tid), ignore_errors=True)


@router.post("/datasets/{dataset_id}/augment")
def _render_ann_masks(items: list, h: int, w: int) -> list[tuple]:
    """标注 → (type, category_id, mask) 列表，统一走 mask 通道做几何变换。"""
    from app.engines.rle import ann_to_mask
    ann_masks = []
    for a in items:
        d = json.loads(a["data"])
        m = np.zeros((h, w), dtype=np.uint8)
        if a["type"] == "box":
            cv2.rectangle(m, (int(d["x1"]), int(d["y1"])), (int(d["x2"]), int(d["y2"])), 255, -1)
            ann_masks.append(("box", a["category_id"], m))
        elif a["type"] == "mask":
            m = ann_to_mask(d, h, w).astype(np.uint8) * 255
            if m.any():
                ann_masks.append(("mask", a["category_id"], m))
    return ann_masks


def _extract_ann_from_mask(typ: str, tm: np.ndarray) -> dict | None:
    """变换后的 mask → 标注 data（box→外接矩，mask→RLE + 简化多边形）。返回 None 表示无法提取。"""
    from app.engines.rle import mask_to_ann_data
    contours, _ = cv2.findContours(tm.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    poly = max(contours, key=cv2.contourArea)
    if typ == "box":
        x, y, bw, bh = cv2.boundingRect(poly)
        if bw < 2 or bh < 2:
            return None
        return {"x1": x, "y1": y, "x2": x + bw, "y2": y + bh}
    return mask_to_ann_data(tm > 0)


def augment_dataset(dataset_id: int, body: AugmentRequest):
    """离线增强扩充：每张图生成 copies 个增强副本（标注同步变换）→ 新数据集。"""
    import random

    with get_conn() as conn:
        ds = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if not ds:
            raise HTTPException(404, "数据集不存在")
        pipeline = conn.execute(
            "SELECT ops FROM preprocess_pipelines WHERE id=? AND type='aug'", (body.pipeline_id,)
        ).fetchone()
        if not pipeline:
            raise HTTPException(400, "增强管线不存在（需为增强类型）")
        imgs = list(conn.execute(
            "SELECT * FROM images WHERE dataset_id=? ORDER BY id", (dataset_id,)
        ).fetchall())
        anns: dict[int, list] = {}
        for a in conn.execute(
            "SELECT * FROM annotations WHERE image_id IN (SELECT id FROM images WHERE dataset_id=?)",
            (dataset_id,),
        ).fetchall():
            anns.setdefault(a["image_id"], []).append(a)
    ops = json.loads(pipeline["ops"])
    if not ops or ops[0].get("name") == "__ultra__":
        raise HTTPException(400, "离线扩充仅支持自定义增强管线（albumentations 算子）")

    from app.ops import AUG_REGISTRY
    import albumentations as A

    # 输出目录 + 新数据集
    root = Path(ds["root_path"])
    out_dir = root.parent / f"{root.name}_aug"
    out_dir.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO datasets (project_id, name, root_path) VALUES (?, ?, ?)",
            (ds["project_id"], body.name.strip(), str(out_dir.resolve())),
        )
        new_ds_id = cur.lastrowid

    created_imgs = 0
    created_anns = 0
    from app.engines.data_utils import read_image as _read_image
    for im in imgs:
        img = _read_image(ds, im)
        if img is None:
            continue
        items = anns.get(im["id"], [])
        class_items = [a for a in items if a["type"] == "class"]
        ann_masks = _render_ann_masks(items, img.shape[0], img.shape[1])
        for i in range(body.copies):
            seed = random.randint(0, 2**31)
            transforms = [AUG_REGISTRY[o["name"]]["builder"](**(o.get("params") or {})) for o in ops]
            transform = A.Compose(transforms, seed=seed)
            kwargs = {"image": img}
            if ann_masks:
                kwargs["masks"] = [x[2] for x in ann_masks]
            aug = transform(**kwargs)
            out_img = aug["image"]
            # 保存图像
            img_name = f"{im['id']:07d}_a{i:02d}.jpg"
            cv2.imencode(".jpg", out_img)[1].tofile(out_dir / img_name)
            with get_conn() as conn:
                cur = conn.execute(
                    "INSERT INTO images (dataset_id, rel_path, width, height, split) VALUES (?, ?, ?, ?, ?)",
                    (new_ds_id, img_name, out_img.shape[1], out_img.shape[0], im["split"] or ""),
                )
                new_img_id = cur.lastrowid
                created_imgs += 1
                # 从变换后的 mask 重新提取标注
                for idx, (typ, cat_id, _m) in enumerate(ann_masks):
                    data = _extract_ann_from_mask(typ, aug["masks"][idx])
                    if data is None:
                        continue
                    conn.execute(
                        "INSERT INTO annotations (image_id, category_id, type, data, source) VALUES (?, ?, ?, ?, 'aug')",
                        (new_img_id, cat_id, typ, json.dumps(data)),
                    )
                    created_anns += 1
                for a in class_items:
                    conn.execute(
                        "INSERT INTO annotations (image_id, category_id, type, data, source) VALUES (?, ?, 'class', '{}', 'aug')",
                        (new_img_id, a["category_id"]),
                    )
                    created_anns += 1
    with get_conn() as conn:
        conn.execute("UPDATE datasets SET image_count=? WHERE id=?", (created_imgs, new_ds_id))
    return {"dataset_id": new_ds_id, "images": created_imgs, "annotations": created_anns}


@router.post("/datasets/{dataset_id}/split")
def split_dataset(dataset_id: int, body: SplitRequest):
    if body.train_ratio + body.val_ratio > 1:
        raise HTTPException(400, "train_ratio + val_ratio 不能超过 1")
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM datasets WHERE id = ?", (dataset_id,)).fetchone():
            raise HTTPException(404, "数据集不存在")
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM images WHERE dataset_id = ? ORDER BY id", (dataset_id,)
        ).fetchall()]
        if not ids:
            raise HTTPException(400, "数据集为空")
        rng = random.Random(body.seed)
        rng.shuffle(ids)
        n_val = int(len(ids) * body.val_ratio)
        n_train = int(len(ids) * body.train_ratio)
        splits = (
            [("train", i) for i in ids[:n_train]]
            + [("val", i) for i in ids[n_train:n_train + n_val]]
            + [("test", i) for i in ids[n_train + n_val:]]
        )
        conn.executemany("UPDATE images SET split = ? WHERE id = ?", splits)
        return {"message": f"划分完成：train {n_train} / val {n_val} / test {len(ids) - n_train - n_val}"}

"""标注管理：CRUD + 标注导入（YOLO txt / LabelMe / COCO）。"""
import json
from pathlib import Path

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.db import get_conn

class AnnotationCreate(BaseModel):
    image_id: int
    category_id: int | None = None
    type: str = "box"  # box/mask/class
    data: dict = {}
    source: str = "manual"

class AnnotationUpdate(BaseModel):
    category_id: int | None = None
    data: dict | None = None

class ImportAnnotationsRequest(BaseModel):
    format: str  # yolo/labelme/coco
    path: str = Field(min_length=1)

router = APIRouter()

VALID_TYPES = {"box", "mask", "class", "shield"}


def _load_image_path(image_id: int) -> tuple[Path, int]:
    """返回 (图像绝对路径, dataset_id)。"""
    from app.engines.data_utils import image_path_of
    with get_conn() as conn:
        dsid = conn.execute("SELECT dataset_id FROM images WHERE id=?", (image_id,)).fetchone()
        if not dsid:
            raise HTTPException(404, "图像不存在")
    try:
        return image_path_of(image_id), dsid["dataset_id"]
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))


@router.get("/images/{image_id}/annotations")
def list_annotations(image_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT a.*, c.name AS category_name, c.color
               FROM annotations a LEFT JOIN categories c ON c.id = a.category_id
               WHERE a.image_id = ? ORDER BY a.id""",
            (image_id,),
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("/annotations", status_code=201)
def create_annotation(body: AnnotationCreate):
    if body.type not in VALID_TYPES:
        raise HTTPException(400, f"类型必须是 {sorted(VALID_TYPES)} 之一")
    data = json.dumps(body.data, ensure_ascii=False)
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM images WHERE id=?", (body.image_id,)).fetchone():
            raise HTTPException(404, "图像不存在")
        if body.category_id is not None and not conn.execute(
            "SELECT 1 FROM categories WHERE id=?", (body.category_id,)
        ).fetchone():
            raise HTTPException(404, "类别不存在")
        cur = conn.execute(
            """INSERT INTO annotations (image_id, category_id, type, data, source)
               VALUES (?, ?, ?, ?, ?)""",
            (body.image_id, body.category_id, body.type, data, body.source),
        )
        row = conn.execute(
            """SELECT a.*, c.name AS category_name, c.color FROM annotations a
               LEFT JOIN categories c ON c.id = a.category_id WHERE a.id = ?""",
            (cur.lastrowid,),
        ).fetchone()
        return dict(row)


@router.put("/annotations/{annotation_id}")
def update_annotation(annotation_id: int, body: AnnotationUpdate):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM annotations WHERE id=?", (annotation_id,)).fetchone()
        if not row:
            raise HTTPException(404, "标注不存在")
        if body.category_id is not None:
            if not conn.execute("SELECT 1 FROM categories WHERE id=?", (body.category_id,)).fetchone():
                raise HTTPException(404, "类别不存在")
            conn.execute("UPDATE annotations SET category_id=? WHERE id=?", (body.category_id, annotation_id))
        if body.data is not None:
            conn.execute("UPDATE annotations SET data=? WHERE id=?", (json.dumps(body.data, ensure_ascii=False), annotation_id))
        row = conn.execute(
            """SELECT a.*, c.name AS category_name, c.color FROM annotations a
               LEFT JOIN categories c ON c.id = a.category_id WHERE a.id = ?""",
            (annotation_id,),
        ).fetchone()
        return dict(row)


@router.delete("/annotations/{annotation_id}", status_code=204)
def delete_annotation(annotation_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM annotations WHERE id=?", (annotation_id,))
        if conn.total_changes == 0:
            raise HTTPException(404, "标注不存在")


# ---------------- 标注导入 ----------------

def _cat_map(conn, dataset_id: int) -> dict:
    """数据集的类别名 → id；以及按 id 排序的索引列表。"""
    cats = conn.execute(
        "SELECT * FROM categories WHERE dataset_id=? ORDER BY id", (dataset_id,)
    ).fetchall()
    return {c["name"]: c["id"] for c in cats}, [c["id"] for c in cats]


@router.post("/datasets/{dataset_id}/import-annotations")
def import_annotations(dataset_id: int, body: ImportAnnotationsRequest):
    path = Path(body.path.strip())
    if not path.exists():
        raise HTTPException(400, f"路径不存在：{path}")
    with get_conn() as conn:
        ds = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if not ds:
            raise HTTPException(404, "数据集不存在")
        images = {
            r["rel_path"]: dict(r) for r in conn.execute(
                "SELECT * FROM images WHERE dataset_id=?", (dataset_id,)
            ).fetchall()
        }
        name2id, id_order = _cat_map(conn, dataset_id)
        if not id_order:
            raise HTTPException(400, "数据集还没有缺陷类别，请先在数据集中定义类别")
        idx2id = {i: cid for i, cid in enumerate(id_order)}

        created = 0
        if body.format == "yolo":
            created = _import_yolo(conn, path, images, idx2id, ds)
        elif body.format == "labelme":
            created = _import_labelme(conn, path, images, name2id)
        elif body.format == "coco":
            created = _import_coco(conn, path, images, name2id)
        else:
            raise HTTPException(400, "格式必须是 yolo/labelme/coco")
        conn.commit()
        return {"created": created}


def _import_yolo(conn, path: Path, images: dict, idx2id: dict, ds) -> int:
    """YOLO txt：path 指向 labels 目录（txt 文件名与图像同名），或 images 目录的平行 labels。"""
    labels_dir = path if path.is_dir() else path.parent
    created = 0
    for txt in labels_dir.glob("*.txt"):
        stem = txt.stem
        # 匹配图像：先按 id 命名（平台导出格式），再按原始文件名
        img = None
        for rel, im in images.items():
            if Path(rel).stem == stem:
                img = im
                break
        if img is None:
            continue
        lines = []
        for ln in txt.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = ln.split()
            if len(parts) < 5:
                continue
            try:
                c, cx, cy, w, h = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            except ValueError:
                continue
            cid = idx2id.get(int(c)) if int(c) in idx2id else None
            if cid is None:
                continue
            x1 = (cx - w / 2) * img["width"]
            y1 = (cy - h / 2) * img["height"]
            x2 = (cx + w / 2) * img["width"]
            y2 = (cy + h / 2) * img["height"]
            lines.append((img["id"], cid, "box", json.dumps({"x1": x1, "y1": y1, "x2": x2, "y2": y2}), "imported"))
        if lines:
            conn.execute("DELETE FROM annotations WHERE image_id=? AND source='imported'", (img["id"],))
            conn.executemany(
                "INSERT INTO annotations (image_id, category_id, type, data, source) VALUES (?, ?, ?, ?, ?)",
                lines,
            )
            created += len(lines)
    return created


def _import_labelme(conn, path: Path, images: dict, name2id: dict) -> int:
    """LabelMe：path 为目录（含 *.json）或单个 json 文件。"""
    json_files = [path] if path.is_file() else list(path.glob("*.json"))
    created = 0
    for jf in json_files:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        img_name = Path(data.get("imagePath", jf.stem + ".jpg")).name
        img = None
        for rel, im in images.items():
            if Path(rel).name == img_name:
                img = im
                break
        if img is None:
            continue
        rows = []
        for shape in data.get("shapes", []):
            cid = name2id.get(shape.get("label", ""))
            if cid is None:
                continue
            pts = shape.get("points", [])
            if len(pts) < 2:
                continue
            if shape.get("shape_type") == "rectangle":
                (x1, y1), (x2, y2) = pts[0], pts[1]
                rows.append((img["id"], cid, "box",
                             json.dumps({"x1": min(x1, x2), "y1": min(y1, y2), "x2": max(x1, x2), "y2": max(y1, y2)}),
                             "imported"))
            else:
                rows.append((img["id"], cid, "mask", json.dumps({"points": pts}), "imported"))
        if rows:
            conn.execute("DELETE FROM annotations WHERE image_id=? AND source='imported'", (img["id"],))
            conn.executemany(
                "INSERT INTO annotations (image_id, category_id, type, data, source) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            created += len(rows)
    return created


def _import_coco(conn, path: Path, images: dict, name2id: dict) -> int:
    """COCO：path 为 annotations json。bbox 为 [x, y, w, h]，segmentation 多边形。

    注意：COCO 的 image_id 是 COCO 图片数组内的自增 id，与平台 images 表 id 无关，
    必须经 COCO images[].file_name 与平台 rel_path 的文件名匹配来定位图像。
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    # COCO image id → 其 file_name；file_name → 平台 images 记录（优先按文件名匹配）
    cat_name = {c["id"]: c["name"] for c in data.get("categories", [])}
    file_to_img = {}
    for rel, im in images.items():
        file_to_img.setdefault(Path(rel).name.lower(), im)
    coco_img_id = {im["id"]: im for im in data.get("images", [])}
    created = 0
    for ann in data.get("annotations", []):
        cinfo = coco_img_id.get(ann.get("image_id"))
        if not cinfo:
            continue
        img = file_to_img.get(Path(cinfo.get("file_name", "")).name.lower())
        if img is None:
            continue
        cname = cat_name.get(ann.get("category_id", -1), "")
        cid = name2id.get(cname)
        if cid is None:
            continue
        if ann.get("bbox") is not None:
            x, y, w, h = ann["bbox"]
            conn.execute(
                "INSERT INTO annotations (image_id, category_id, type, data, source) VALUES (?, ?, 'box', ?, 'imported')",
                (img["id"], cid, json.dumps({"x1": x, "y1": y, "x2": x + w, "y2": y + h})),
            )
            created += 1
        elif ann.get("segmentation") and isinstance(ann["segmentation"], list):
            # 多段多边形：逐段展开为独立 mask 标注，避免嵌套数组 reshape 报错
            segs = ann["segmentation"]
            if segs and isinstance(segs[0], list):
                for seg in segs:
                    if len(seg) >= 6:  # 至少 3 个点
                        conn.execute(
                            "INSERT INTO annotations (image_id, category_id, type, data, source) VALUES (?, ?, 'mask', ?, 'imported')",
                            (img["id"], cid, json.dumps({"points": [[float(seg[i]), float(seg[i + 1])]
                                                                    for i in range(0, len(seg), 2)]})),
                        )
                        created += 1
            else:
                conn.execute(
                    "INSERT INTO annotations (image_id, category_id, type, data, source) VALUES (?, ?, 'mask', ?, 'imported')",
                    (img["id"], cid, json.dumps({"points": ann["segmentation"]})),
                )
                created += 1
    return created

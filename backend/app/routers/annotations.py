"""标注管理：CRUD + 标注导入（YOLO txt / LabelMe / COCO）。

导入两种模式：
- /datasets/{id}/import-annotations：指定格式 + 路径（旧模式，兼容）
- /datasets/{id}/import-folder：选文件夹自动识别（傻瓜式）——扫描目录，
  自动识别 YOLO/LabelMe/COCO 标注文件（支持与图片混放、labels/ 子目录、
  classes.txt 类别表、多 COCO 文件等常见情况），缺失类别自动创建。
"""
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

class ImportFolderRequest(BaseModel):
    path: str = Field(min_length=1)

router = APIRouter()

VALID_TYPES = {"box", "mask", "class", "shield"}

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
CAT_COLORS = ["#4E79A7", "#E15759", "#59A14F", "#F28E2B", "#B07AA1", "#76B7B2", "#EDC948", "#FF9DA7"]
CLASS_FILES = {"classes.txt", "classes.names", "obj.names", "class_names.txt"}


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


def _ensure_categories(conn, project_id: int, dataset_id: int, names: list[str]) -> dict:
    """类别自动补全（傻瓜式导入）：已有类别复用，缺失的自动创建。返回 name -> id。"""
    existing = {}
    for r in conn.execute("SELECT * FROM categories WHERE dataset_id=?", (dataset_id,)):
        existing[r["name"]] = r["id"]
    for r in conn.execute("SELECT * FROM categories WHERE dataset_id IS NULL AND project_id=?", (project_id,)):
        existing.setdefault(r["name"], r["id"])
    out = {}
    for name in names:
        name = (name or "").strip()
        if not name:
            continue
        if name in existing:
            out[name] = existing[name]
        else:
            cur = conn.execute(
                "INSERT INTO categories (project_id, dataset_id, name, color) VALUES (?, ?, ?, ?)",
                (project_id, dataset_id, name, CAT_COLORS[len(existing) % len(CAT_COLORS)]),
            )
            existing[name] = cur.lastrowid
            out[name] = cur.lastrowid
    return out


def _looks_yolo(p: Path) -> bool:
    """txt 内容前几行是否为 YOLO 格式（每行 ≥5 个数字）。utf-8-sig 兼容 BOM 头。"""
    head: list[str] = []
    try:
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            for _ in range(3):
                head.append(next(f))
    except StopIteration:
        pass  # 文件不足 3 行（正常）
    except Exception:
        return False
    for ln in head:
        parts = ln.split()
        if len(parts) >= 5:
            try:
                for v in parts[:5]:
                    float(v)
                return True
            except ValueError:
                pass
    return False


def _scan_annotations(root: Path) -> tuple[list, list, list, list]:
    """扫描文件夹，自动识别标注文件。

    返回 (labelme_jsons, yolo_txts, coco_jsons, classes_names)。
    支持：标注与图片混放、任意子目录深度、labels/ 目录、classes.txt 类别表。
    """
    labelme_files, yolo_txts, coco_files = [], [], []
    classes_names: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf in IMG_EXTS:
            continue  # 图片不处理（按 DB 已有图片匹配）
        if suf == ".json":
            try:
                data = json.loads(p.read_text(encoding="utf-8-sig", errors="replace"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if isinstance(data.get("shapes"), list):
                labelme_files.append(p)
            elif isinstance(data.get("images"), list) and isinstance(data.get("annotations"), list):
                coco_files.append(p)
        elif suf == ".txt":
            if p.name.lower() in CLASS_FILES:
                names = [ln.strip() for ln in
                         p.read_text(encoding="utf-8-sig", errors="replace").splitlines() if ln.strip()]
                # 防御：纯数字行的文件不是类别表
                if names and not all(n.replace(" ", "").replace(".", "").isdigit() for n in names):
                    classes_names = names
                continue
            if _looks_yolo(p):
                yolo_txts.append(p)
    return labelme_files, yolo_txts, coco_files, classes_names


def _images_by_stem(images: dict) -> dict:
    """images 可以是 rel_path->row 或 stem->row；统一为 stem -> row（同名取先到者）。"""
    out = {}
    for k, im in images.items():
        stem = Path(k).stem
        if stem not in out:
            out[stem] = im
    return out


@router.post("/datasets/{dataset_id}/import-folder")
def import_folder(dataset_id: int, body: ImportFolderRequest):
    """傻瓜式导入：选一个文件夹，自动识别 YOLO/LabelMe/COCO 标注并匹配图片。

    常见情况全覆盖：标注与图片同目录混放、labels/ 子目录、任意子目录深度、
    classes.txt/obj.names 类别表、单个或多个 COCO json。缺失类别自动创建。
    返回分格式统计与未匹配文件列表（便于排查）。
    """
    root = Path(body.path.strip())
    if not root.is_dir():
        raise HTTPException(400, f"文件夹不存在：{root}")
    labelme_files, yolo_txts, coco_files, classes_names = _scan_annotations(root)
    with get_conn() as conn:
        ds = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if not ds:
            raise HTTPException(404, "数据集不存在")
        images = _images_by_stem({
            r["rel_path"]: dict(r) for r in conn.execute(
                "SELECT * FROM images WHERE dataset_id=?", (dataset_id,)).fetchall()
        })
        project_id = ds["project_id"]
        name2id, id_order = _cat_map(conn, dataset_id)
        idx2id = {i: cid for i, cid in enumerate(id_order)}

        created = 0
        by_format = {"labelme": 0, "yolo": 0, "coco": 0}
        unmatched: list[str] = []
        if labelme_files:
            n, un = _import_labelme(conn, labelme_files, images, name2id,
                                    project_id, dataset_id, auto_create=True)
            created += n
            by_format["labelme"] = n
            unmatched += un
        if yolo_txts:
            n, un = _import_yolo(conn, yolo_txts, images, idx2id, ds,
                                 classes_names, auto_create=True,
                                 project_id=project_id, dataset_id=dataset_id)
            created += n
            by_format["yolo"] = n
            unmatched += un
        if coco_files:
            n, un = _import_coco(conn, coco_files, images, name2id,
                                 project_id, dataset_id, auto_create=True)
            created += n
            by_format["coco"] = n
            unmatched += un
        conn.commit()
    return {
        "created": created,
        "by_format": by_format,
        "scanned": {"labelme": len(labelme_files), "yolo": len(yolo_txts), "coco": len(coco_files)},
        "unmatched": unmatched[:50],
        "unmatched_total": len(unmatched),
    }


@router.post("/datasets/{dataset_id}/import-annotations")
def import_annotations(dataset_id: int, body: ImportAnnotationsRequest):
    """指定格式导入（兼容旧模式）。"""
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
            created, _ = _import_yolo(conn, path, images, idx2id, ds)
        elif body.format == "labelme":
            created, _ = _import_labelme(conn, path, images, name2id)
        elif body.format == "coco":
            created, _ = _import_coco(conn, path, images, name2id)
        else:
            raise HTTPException(400, "格式必须是 yolo/labelme/coco")
        conn.commit()
        return {"created": created}


def _import_yolo(conn, txt_files, images: dict, idx2id: dict, ds,
                 classes_names: list[str] | None = None, auto_create: bool = False,
                 project_id: int | None = None, dataset_id: int | None = None):
    """YOLO txt 导入。返回 (created, unmatched_files)。

    classes_names 提供时按「行号 = 类别名」映射（配合 classes.txt）；
    否则按数据集类别 id 排序的索引映射；auto_create 时越界索引自动创建 class_N。
    """
    txt_files = list(txt_files.glob("*.txt")) if isinstance(txt_files, Path) and txt_files.is_dir() \
        else ([txt_files] if isinstance(txt_files, Path) else list(txt_files))
    imgs = _images_by_stem(images)
    if classes_names and auto_create and project_id and dataset_id:
        name_map = _ensure_categories(conn, project_id, dataset_id, classes_names)
        # 行号 = 类别名在 classes_names 中的位置
        id2cat = {i: name_map.get(n) for i, n in enumerate(classes_names)}
        id2cat = {i: c for i, c in id2cat.items() if c is not None}
    else:
        id2cat = dict(idx2id)
    created = 0
    unmatched: list[str] = []
    for txt in txt_files:
        stem = txt.stem
        img = imgs.get(stem)
        if img is None:
            unmatched.append(str(txt))
            continue
        lines = []
        for ln in txt.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            parts = ln.split()
            if len(parts) < 5:
                continue
            try:
                c, cx, cy, w, h = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            except ValueError:
                continue
            ci = int(c)
            cid = id2cat.get(ci)
            if cid is None and auto_create and project_id and dataset_id:
                cname = f"class_{ci}"
                cid = _ensure_categories(conn, project_id, dataset_id, [cname]).get(cname)
                if cid is not None:
                    id2cat[ci] = cid
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
    return created, unmatched


def _import_labelme(conn, json_files, images: dict, name2id: dict,
                    project_id: int | None = None, dataset_id: int | None = None,
                    auto_create: bool = False):
    """LabelMe 导入：目录（含 *.json）或单个 json。返回 (created, unmatched_files)。"""
    json_files = list(json_files.glob("*.json")) if isinstance(json_files, Path) and json_files.is_dir() \
        else ([json_files] if isinstance(json_files, Path) else list(json_files))
    imgs = _images_by_stem(images)
    if auto_create and project_id and dataset_id:
        # 预收集全部标签名，一次性自动创建缺失类别
        all_labels: set[str] = set()
        for jf in json_files:
            try:
                d = json.loads(jf.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            for s in d.get("shapes", []):
                lbl = str(s.get("label", "")).strip()
                if lbl:
                    all_labels.add(lbl)
        name2id = dict(name2id)
        name2id.update(_ensure_categories(conn, project_id, dataset_id, sorted(all_labels)))
    created = 0
    unmatched: list[str] = []
    for jf in json_files:
        try:
            data = json.loads(jf.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        img_name = Path(data.get("imagePath", jf.stem + ".jpg")).name
        img = imgs.get(Path(img_name).stem)
        if img is None:
            unmatched.append(str(jf))
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
    return created, unmatched


def _import_coco(conn, coco_files, images: dict, name2id: dict,
                 project_id: int | None = None, dataset_id: int | None = None,
                 auto_create: bool = False):
    """COCO 导入：单个或多个 annotations json。返回 (created, unmatched_files)。

    注意：COCO 的 image_id 是 COCO 图片数组内的自增 id，与平台 images 表 id 无关，
    必须经 COCO images[].file_name 与平台 rel_path 的文件名匹配来定位图像。
    """
    coco_files = list(coco_files.glob("*.json")) if isinstance(coco_files, Path) and coco_files.is_dir() \
        else ([coco_files] if isinstance(coco_files, Path) else list(coco_files))
    if auto_create and project_id and dataset_id:
        all_names: set[str] = set()
        for cf in coco_files:
            try:
                d = json.loads(cf.read_text(encoding="utf-8-sig"))
                for c in d.get("categories", []):
                    nm = str(c.get("name", "")).strip()
                    if nm:
                        all_names.add(nm)
            except Exception:
                continue
        name2id = dict(name2id)
        name2id.update(_ensure_categories(conn, project_id, dataset_id, sorted(all_names)))
    created = 0
    unmatched: list[str] = []
    for cf in coco_files:
        try:
            data = json.loads(cf.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        cat_name = {c["id"]: c["name"] for c in data.get("categories", [])}
        # 兼容 rel_path 或 stem 两种 images 键：统一转 stem（小写）匹配 COCO file_name
        imgs = _images_by_stem(images)
        file_to_img = {}
        for stem, im in imgs.items():
            file_to_img.setdefault(stem.lower(), im)
        coco_img_id = {im["id"]: im for im in data.get("images", [])}
        touched_img_ids = set()
        # 第一遍：确定本文件涉及的图片（先删旧 imported，避免与本次插入交错）
        for ann in data.get("annotations", []):
            cinfo = coco_img_id.get(ann.get("image_id"))
            if not cinfo:
                continue
            img = file_to_img.get(Path(cinfo.get("file_name", "")).stem.lower())
            if img is not None:
                touched_img_ids.add(img["id"])
        if touched_img_ids:
            ph = ",".join("?" * len(touched_img_ids))
            conn.execute(f"DELETE FROM annotations WHERE image_id IN ({ph}) AND source='imported'",
                         tuple(touched_img_ids))
        # 第二遍：写入
        for ann in data.get("annotations", []):
            cinfo = coco_img_id.get(ann.get("image_id"))
            if not cinfo:
                continue
            img = file_to_img.get(Path(cinfo.get("file_name", "")).stem.lower())
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
    return created, unmatched

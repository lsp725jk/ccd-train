"""X-AnyLabeling ↔ ccd-train 后端 标注同步适配器。

背景
----
- ccd-train 后端把标注存在 SQLite（annotations 表，type ∈ box/mask/class/shield）。
- X-AnyLabeling 基于「图片目录 + 同名 LabelMe JSON」工作（foo.jpg ↔ foo.json）。
- 本模块负责双向转换，让 X-AnyLabeling 可以直接标注 ccd-train 的数据集，
  再把结果全量回写后端，训练流水线无需任何改动。

数据流
------
打开数据集（export_dataset）：
    后端 images/categories/annotations
        → 镜像目录 workdir/<ds_name>/<rel_path>（图像：符号链接优先，失败则复制）
        → 每张图生成同名 .json（LabelMe 格式，兼容 X-AnyLabeling）

保存回写（import_dataset）：
    workdir 下所有 .json（X-AnyLabeling 修改后的最终状态）
        → 按图全量重建后端 box/mask/shield 标注（class 与 source=sam 保留）
        → 返回统计

约定
----
- 类别映射：按「名称」匹配。在 X-AnyLabeling 中新建标签时，
  标签名必须与 ccd-train 数据集的类别名完全一致（含中文）。
- 屏蔽区：在 X-AnyLabeling 中建一个名为 __shield__ 的标签，画多边形即屏蔽区。
- 整图分类（class 标注）：X-AnyLabeling 没有对应工具，导出时跳过、回写时保留，
  分类标注请继续在 Web 端或本平台原有标注页操作。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import api_client as api

# X-AnyLabeling 中代表"屏蔽区"的专用标签名
SHIELD_LABEL = "__shield__"
# 镜像目录内保存数据集 id 的标记文件
DS_MARK = ".ccd_ds_id"
# 回写时覆盖的标注类型（source 不区分，全量重建）
SYNC_TYPES = {"box", "mask", "shield"}
# 需要保留、不参与重建的标注类型（整图分类）
KEEP_TYPES = {"class"}


# ---------------------------------------------------------------------------
# 后端 → LabelMe
# ---------------------------------------------------------------------------

def _shape_from_annotation(ann: dict) -> dict | None:
    """后端标注 → LabelMe shape。返回 None 表示该标注无法表达（如 class）。"""
    import json as _json
    raw = ann.get("data")
    data = raw if isinstance(raw, dict) else (_json.loads(raw) if raw else {})
    label = SHIELD_LABEL if ann.get("type") == "shield" else (ann.get("category_name") or "")
    if ann.get("type") == "class":
        return None
    if ann["type"] == "box":
        pts = [[data["x1"], data["y1"]], [data["x2"], data["y2"]]]
        return {"label": label, "points": pts, "group_id": None,
                "shape_type": "rectangle", "flags": {}}
    # mask / shield：多边形
    pts = data.get("points", [])
    if not pts or len(pts) < 3:
        return None
    return {"label": label, "points": pts, "group_id": None,
            "shape_type": "polygon", "flags": {}}


def _labelme_json(image_rel_path: str, width: int, height: int, shapes: list) -> dict:
    return {
        "version": "5.2.1",
        "flags": {},
        "shapes": shapes,
        "imagePath": Path(image_rel_path).name,
        "imageData": None,
        "imageHeight": height,
        "imageWidth": width,
    }


def export_dataset(ds_id: int, workdir: str | Path, use_symlink: bool = True) -> Path:
    """把后端数据集导出为 X-AnyLabeling 可直接打开的镜像目录。

    返回镜像目录路径（workdir/<数据集名>/）。
    """
    workdir = Path(workdir)
    images = _fetch_all_images(ds_id)
    if not images:
        raise RuntimeError("数据集为空，没有可导出的图像")

    # 数据集 root_path：dataset_images 不带该字段，从数据集列表取
    root_path = ""
    for ds in api.datasets_list(0) + _all_datasets():
        if ds["id"] == ds_id:
            root_path = ds.get("root_path", "")
            break
    if not root_path:
        raise RuntimeError("未找到数据集信息（root_path）")

    mirror = workdir / _safe_name(_dataset_name(ds_id))
    if mirror.exists():
        shutil.rmtree(mirror)
    mirror.mkdir(parents=True, exist_ok=True)

    img_count = json_count = 0
    (mirror / DS_MARK).write_text(str(ds_id), encoding="utf-8")
    for im in images:
        src = Path(root_path) / im["rel_path"]
        dst = mirror / im["rel_path"]
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if use_symlink:
            try:
                dst.symlink_to(src)
            except OSError:
                shutil.copy2(src, dst)
        else:
            shutil.copy2(src, dst)
        img_count += 1

        # 标注 → LabelMe JSON
        try:
            anns = api.image_annotations(im["id"])
        except Exception:
            anns = []
        shapes = [s for s in (_shape_from_annotation(a) for a in anns) if s]
        (dst.with_suffix(".json")).write_text(
            json.dumps(_labelme_json(im["rel_path"], im.get("width", 0),
                                     im.get("height", 0), shapes),
                       ensure_ascii=False, indent=1),
            encoding="utf-8")
        json_count += 1

    return mirror


# ---------------------------------------------------------------------------
# LabelMe → 后端
# ---------------------------------------------------------------------------

def import_dataset(mirror: str | Path) -> dict:
    """把镜像目录中的 LabelMe JSON 全量回写后端。

    对每张图：删除后端该图全部 box/mask/shield 标注（含 source=sam），
    按 JSON 重建；class 标注保留不动。
    返回统计：{"images": n, "created": n, "deleted": n, "skipped": [文件名...]}
    """
    mirror = Path(mirror)
    ds_id = _ds_id_from_mirror(mirror)
    label_to_cat = _build_label_map(ds_id)
    images = _fetch_all_images(ds_id) if ds_id > 0 else []
    stats = {"images": 0, "created": 0, "deleted": 0, "skipped": []}

    for jf in sorted(mirror.rglob("*.json")):
        try:
            doc = json.loads(jf.read_text(encoding="utf-8"))
        except Exception as e:
            stats["skipped"].append(f"{jf.name}（JSON 解析失败：{e}）")
            continue

        image_id = _find_image_id(images, mirror, jf, doc)
        if image_id is None:
            stats["skipped"].append(f"{jf.name}（未匹配到后端图像）")
            continue

        # 1) 删除该图旧标注（box/mask/shield 全量，class 保留）
        try:
            old = api.image_annotations(image_id)
        except Exception:
            old = []
        for a in old:
            if a["type"] in SYNC_TYPES:
                try:
                    api.annotation_delete(a["id"])
                    stats["deleted"] += 1
                except Exception:
                    pass

        # 2) 按 JSON 重建
        for shape in doc.get("shapes", []):
            label = str(shape.get("label", ""))
            cat_id = label_to_cat.get(label)
            shape_type = shape.get("shape_type", "polygon")
            pts = shape.get("points") or []
            if label == SHIELD_LABEL:
                ann_type, data = "shield", {"points": pts}
            elif shape_type == "rectangle" and len(pts) >= 2:
                (x1, y1), (x2, y2) = pts[0], pts[1]
                ann_type, data = "box", {
                    "x1": min(x1, x2), "y1": min(y1, y2),
                    "x2": max(x1, x2), "y2": max(y1, y2),
                }
            elif len(pts) >= 3:
                ann_type, data = "mask", {"points": pts}
            else:
                continue
            if ann_type != "shield" and cat_id is None:
                stats["skipped"].append(f"{jf.name}（无类别「{label}」，请先在数据集定义）")
                continue
            try:
                api.annotation_create(image_id, cat_id, ann_type, data)
                stats["created"] += 1
            except Exception as e:
                stats["skipped"].append(f"{jf.name}（写入失败：{e}）")
        stats["images"] += 1

    return stats


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _dataset_name(ds_id: int) -> str:
    for ds in api.datasets_list(0) + _all_datasets():
        if ds["id"] == ds_id:
            return ds["name"]
    return f"ds_{ds_id}"


def _all_datasets():
    """跨项目枚举数据集（datasets_list 需要 project_id）。"""
    try:
        out = []
        for p in api.projects_list():
            out.extend(api.datasets_list(p["id"]))
        return out
    except Exception:
        return []


def _fetch_all_images(ds_id: int) -> list[dict]:
    """分页拉取数据集全部图像。"""
    items, page = [], 1
    while True:
        r = api.dataset_images(ds_id, page=page, page_size=500)
        items.extend(r["items"])
        if len(r["items"]) < 500:
            break
        page += 1
    return items


def _image_abs_path(im: dict, root_path: str = "") -> Path:
    """后端 images 记录 → 磁盘绝对路径。"""
    if root_path:
        return Path(root_path) / im["rel_path"]
    return Path(im.get("root_path", "")) / im["rel_path"]


def _find_image_id(images: list[dict], mirror: Path, jf: Path, doc: dict) -> int | None:
    """镜像目录里的 json 文件 → 后端 image id。

    优先按镜像相对路径匹配 rel_path；再按 imagePath 文件名匹配。
    """
    rel = jf.relative_to(mirror).with_suffix("")
    img_name = Path(doc.get("imagePath", "")).name
    for im in images:
        if Path(im["rel_path"]).with_suffix("") == rel:
            return im["id"]
        if Path(im["rel_path"]).name == img_name:
            return im["id"]
    return None


def _ds_id_from_mirror(mirror: Path) -> int:
    """读镜像目录标记文件拿数据集 id；没有则按目录名反查。"""
    mark = mirror / DS_MARK
    if mark.exists():
        try:
            return int(mark.read_text(encoding="utf-8").strip())
        except Exception:
            pass
    name = mirror.name
    for ds in _all_datasets():
        if _safe_name(ds["name"]) == name:
            return ds["id"]
    return -1


def _build_label_map(ds_id: int) -> dict:
    """数据集全部类别：名称 → id。"""
    if ds_id <= 0:
        return {}
    try:
        return {c["name"]: c["id"] for c in api.dataset_categories(ds_id)}
    except Exception:
        return {}


def _safe_name(name: str) -> str:
    import re
    return re.sub(r'[\\/:*?"<>|]', "_", str(name)).strip() or "ds"

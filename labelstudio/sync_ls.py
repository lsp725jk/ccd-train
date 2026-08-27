"""ccd-train ↔ Label Studio 双向同步脚本。

Label Studio 是开源 Web 标注平台（pip 安装），支持画笔(Brush)/多边形/矩形/
SAM2 等。本脚本负责数据打通：

    创建项目   python sync_ls.py create  --ds <数据集id> [--ls http://127.0.0.1:8081]
    导出到LS   python sync_ls.py export --ds <数据集id> [--ls ...]   # 上传图像+已有标注
    回写平台   python sync_ls.py import --ds <数据集id> [--ls ...]   # LS标注 → 后端

类别/屏蔽区约定（与 xal_sync.py 一致）：
- 类别按名称映射：LS 中 <Label value> 与后端类别名一致
- 屏蔽区：标签名 __shield__（回写为 shield，不参与训练）
- 整图分类：LS 的 Choices 控件（cls），回写为 class 标注
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "desktop"))
import api_client as api  # noqa: E402

# ccd-train 后端地址（桌面端 api_client 默认 8010，实际服务在 8000）
api.BASE_URL = "http://127.0.0.1:8000"

LS_BASE = "http://127.0.0.1:8081"
LS_TOKEN = "dsh-ccd-token"   # 与启动脚本 labelstudio.bat 的 --user-token 保持一致
SHIELD_LABEL = "__shield__"
CLS_NAME = "cls"             # Label Studio Choices 控件名

HEADERS = {"Authorization": f"Token {LS_TOKEN}"}


# ---------------------------------------------------------------------------
# Label Studio 基础
# ---------------------------------------------------------------------------

def _ls(method: str, path: str, **kw):
    r = requests.request(method, f"{LS_BASE}{path}", headers=HEADERS, timeout=60, **kw)
    r.raise_for_status()
    return r.json() if r.content else {}


def label_config(categories: list) -> str:
    """按数据集类别生成 LS label_config（矩形/多边形/画笔/屏蔽区/分类）。"""
    cats = [c for c in categories if c["name"] != SHIELD_LABEL]
    def labels(tag: str, ctl_name: str, extra: list | None = None):
        parts = []
        for i, c in enumerate(cats):
            color = c.get("color") or "#4E79A7"
            parts.append(f'<Label value="{c["name"]}" background="{color}"/>')
        for name in (extra or []):
            parts.append(f'<Label value="{name}" background="#8a8175"/>')
        return f'<{tag} name="{ctl_name}" toName="image">' + "".join(parts) + f"</{tag}>"

    shield = [SHIELD_LABEL] if SHIELD_LABEL not in {c["name"] for c in cats} else []
    return (
        '<View>'
        '<Image name="image" value="$image" zoom="true"/>'
        + labels("RectangleLabels", "anno_rect")
        + labels("PolygonLabels", "anno_polygon")
        + labels("BrushLabels", "anno_brush", shield)
        + f'<Choices name="{CLS_NAME}" toName="image" choice="single">'
        + "".join(f'<Choice value="{c["name"]}"/>' for c in cats)
        + "</Choices>"
        "</View>"
    )


# ---------------------------------------------------------------------------
# 创建项目 / 导出到 LS
# ---------------------------------------------------------------------------

def _find_project(title: str) -> int | None:
    for page in _ls_pages("/api/projects"):
        for p in page:
            if p.get("title") == title:
                return p["id"]
    return None


def _ls_pages(path: str):
    page, page_size = 1, 100
    while True:
        data = _ls("GET", f"{path}?page={page}&page_size={page_size}")
        items = data if isinstance(data, list) else data.get("results", [])
        if not items:
            break
        yield items
        if len(items) < page_size:
            break
        page += 1


def create_project(ds_id: int) -> int:
    cats = api.dataset_categories(ds_id)
    title = f"ccd-ds-{ds_id}"
    pid = _find_project(title)
    if pid is not None:
        print(f"[LS] 项目已存在：{title} (id={pid})")
        return pid
    body = {"title": title, "label_config": label_config(cats),
            "description": "由 ccd-train 同步创建（sync_ls.py）"}
    proj = _ls("POST", "/api/projects", json=body)
    print(f"[LS] 已创建项目：{title} (id={proj['id']})")
    return proj["id"]


def _ls_shape(ann_type: str, label: str, pts: list) -> dict:
    """后端标注 → LS result 条目。"""
    if ann_type == "box":
        return {"from_name": "anno_rect", "to_name": "image", "type": "rectanglelabels",
                "value": {"rectanglelabels": [label],
                          "x": pts[0][0] * 100, "y": pts[0][1] * 100,
                          "width": (pts[1][0] - pts[0][0]) * 100,
                          "height": (pts[1][1] - pts[0][1]) * 100}}
    return {"from_name": "anno_polygon", "to_name": "image", "type": "polygonlabels",
            "value": {"polygonlabels": [label], "points": pts}}


def export_to_ls(ds_id: int, with_annotations: bool = True) -> dict:
    """上传数据集图像为 LS task，可选带入已有标注。"""
    pid = create_project(ds_id)
    images = api.dataset_images(ds_id, page_size=500)["items"]
    stats = {"tasks": 0, "annotations": 0}

    for im in images:
        url = f"http://127.0.0.1:8000/api/images/{im['id']}/file"
        task = _ls("POST", "/api/tasks", json={"project": pid, "data": {"image": url}})
        stats["tasks"] += 1
        if not with_annotations:
            continue
        anns = api.image_annotations(im["id"])
        result = []
        for a in anns:
            raw = a.get("data")
            data = raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})
            label = SHIELD_LABEL if a["type"] == "shield" else (a.get("category_name") or "")
            if a["type"] == "box":
                result.append(_ls_shape("box", label,
                                        [[data["x1"], data["y1"]], [data["x2"], data["y2"]]]))
            elif a["type"] in ("mask", "shield") and len(data.get("points", [])) >= 3:
                result.append(_ls_shape("polygon", label, data["points"]))
        if result:
            _ls("POST", f"/api/tasks/{task['id']}/annotations",
                json={"result": result, "was_cancelled": False})
            stats["annotations"] += 1
    print(f"[LS] 导出完成：{stats['tasks']} 个 task，{stats['annotations']} 张带标注")
    return stats


# ---------------------------------------------------------------------------
# LS → ccd-train 回写
# ---------------------------------------------------------------------------

def rle_to_polygons(rle: list, width: int, height: int, eps: float = 2.0) -> list[list[list[float]]]:
    """Label Studio brush 的 RLE → 简化多边形列表（与原笔刷掩码同策略）。"""
    import cv2
    import numpy as np
    flat = np.zeros(width * height, dtype=np.uint8)
    pos, val = 0, 0
    for count in rle:
        flat[pos:pos + count] = val
        pos += count
        val = 1 - val
    mask = flat.reshape(height, width)
    contours, _ = cv2.findContours((mask * 255).astype(np.uint8),
                                   cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:3]:
        if cv2.contourArea(c) < 30:
            continue
        poly = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
        if len(poly) >= 3:
            out.append([[float(x), float(y)] for x, y in poly])
    return out


def _ls_value_to_ann(v: dict, t: str, label: str) -> tuple[str, dict] | None:
    """LS result value → (后端类型, data)。"""
    if t == "rectanglelabels":
        x, y = v["x"] / 100, v["y"] / 100
        w, h = v["width"] / 100, v["height"] / 100
        return ("box", {"x1": x, "y1": y, "x2": x + w, "y2": y + h})
    if t == "polygonlabels":
        pts = v.get("points") or []
        if len(pts) >= 3:
            return ("shield" if label == SHIELD_LABEL else "mask", {"points": pts})
        return None
    if t == "brushlabels":
        rle = v.get("rle") or []
        if rle:
            polys = rle_to_polygons(rle, int(v.get("width", 0)), int(v.get("height", 0)))
            if polys:
                # 多个连通域：分开存，避免一个 mask 跨洞
                return ("shield" if label == SHIELD_LABEL else "mask",
                        {"points": polys[0], "_extra": polys[1:]})
        return None
    return None


def import_from_ls(ds_id: int) -> dict:
    """LS 标注全量回写后端（该数据集图全量重建 box/mask/shield/class）。"""
    pid = create_project(ds_id)
    cats = api.dataset_categories(ds_id)
    label_to_cat = {c["name"]: c["id"] for c in cats}
    images = api.dataset_images(ds_id, page_size=500)["items"]
    url_to_id = {f"http://127.0.0.1:8000/api/images/{im['id']}/file": im["id"] for im in images}
    stats = {"tasks": 0, "created": 0, "deleted": 0, "skipped": []}

    for page in _ls_pages(f"/api/projects/{pid}/tasks"):
        for task in page:
            im_id = url_to_id.get((task.get("data") or {}).get("image"))
            if im_id is None:
                stats["skipped"].append(f"task {task['id']}：图像 URL 未匹配后端")
                continue

            # 1) 全量删除该图旧标注（class 也重建，保证一致性）
            for a in api.image_annotations(im_id):
                try:
                    api.annotation_delete(a["id"])
                    stats["deleted"] += 1
                except Exception:
                    pass

            # 2) 按 LS annotations 重建
            for ann in task.get("annotations") or []:
                for r in ann.get("result") or []:
                    t = r.get("type", "")
                    v = r.get("value", {})
                    if t in ("rectanglelabels", "polygonlabels", "brushlabels"):
                        label = (v.get("rectanglelabels") or v.get("polygonlabels") or
                                 v.get("brushlabels") or [""])[0]
                        conv = _ls_value_to_ann(v, t, label)
                        if conv is None:
                            continue
                        ann_type, data = conv
                        cat_id = None if ann_type == "shield" else label_to_cat.get(label)
                        if ann_type != "shield" and cat_id is None:
                            stats["skipped"].append(f"task {task['id']}：无类别「{label}」")
                            continue
                        api.annotation_create(im_id, cat_id, ann_type,
                                              {"points": data["points"]} if "points" in data else data)
                        stats["created"] += 1
                        for extra in data.get("_extra", []):
                            api.annotation_create(im_id, cat_id, ann_type, {"points": extra})
                            stats["created"] += 1
                    elif t == "choices" and v.get("choices"):
                        cat_name = v["choices"][0]
                        cat_id = label_to_cat.get(cat_name)
                        if cat_id is not None:
                            api.annotation_create(im_id, cat_id, "class", {})
                            stats["created"] += 1
            stats["tasks"] += 1

    print(f"[LS] 回写完成：{stats['tasks']} 图，新建 {stats['created']}，删除 {stats['deleted']}")
    for s in stats["skipped"][:10]:
        print(f"  ⚠ {s}")
    return stats


# ---------------------------------------------------------------------------

def main():
    global LS_BASE
    ap = argparse.ArgumentParser(description="ccd-train ↔ Label Studio 同步")
    ap.add_argument("cmd", choices=["create", "export", "import"])
    ap.add_argument("--ds", type=int, required=True, help="ccd-train 数据集 id")
    ap.add_argument("--ls", default=LS_BASE, help=f"Label Studio 地址（默认 {LS_BASE}）")
    args = ap.parse_args()
    LS_BASE = args.ls.rstrip("/")
    if args.cmd == "create":
        create_project(args.ds)
    elif args.cmd == "export":
        export_to_ls(args.ds)
    else:
        import_from_ls(args.ds)


if __name__ == "__main__":
    main()

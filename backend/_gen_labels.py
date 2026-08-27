"""生成带标注的 demo 数据：30 张模拟缺陷图 + annotations 表 bbox 标注。

缺陷类型：脏污/划痕/裂痕/卡屑（多目标）/气泡/正常，均匀分布。
bbox 与图像严格对应（同一随机种子生成）。
"""
import json
import os
import shutil
import sqlite3
import urllib.request
from pathlib import Path

import cv2
import numpy as np

# 基于脚本自身位置推导路径，项目移动后无需修改
_BACKEND = Path(__file__).resolve().parent
_PROJECT = _BACKEND.parent
ROOT = str(_PROJECT / "demo_data")
DB = str(_BACKEND / "data" / "ccd.db")
BASE = "http://127.0.0.1:8000/api"
PROJECT_ID = 5
N = 90


def req(method, url, body=None):
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw.decode()) if raw else None


# ---------- 1. 生成图像 + bbox ----------
if os.path.isdir(ROOT):
    shutil.rmtree(ROOT)
os.makedirs(ROOT)
rng = np.random.default_rng(7)
records = {}  # 文件名 -> [(cat, x1, y1, x2, y2)]


def g(a, b):
    return int(rng.integers(a, b))


for i in range(N):
    img = np.full((480, 640, 3), g(180, 215), dtype=np.uint8)
    kind = i % 6
    boxes = []
    if kind == 0:  # 脏污（面状）
        cx, cy, r = g(60, 580), g(60, 420), g(15, 45)
        cv2.circle(img, (cx, cy), r, (g(20, 60), g(20, 60), g(20, 60)), -1)
        boxes.append(("脏污", cx - r, cy - r, cx + r, cy + r))
    elif kind == 1:  # 划痕（线状）
        x1, y1 = g(40, 300), g(40, 300)
        x2, y2 = x1 + g(100, 350), y1 + g(-60, 60)
        t = g(2, 5)
        cv2.line(img, (x1, y1), (x2, y2), (g(60, 100), g(60, 100), g(60, 100)), t)
        boxes.append(("划痕", min(x1, x2) - t, min(y1, y2) - t, max(x1, x2) + t, max(y1, y2) + t))
    elif kind == 2:  # 裂痕（细长折线）
        x, y = g(80, 500), g(80, 400)
        pts = [(x, y)]
        for _ in range(4):
            x += g(20, 60)
            y += g(-40, 40)
            pts.append((x, y))
        cv2.polylines(img, [np.array(pts)], False, (30, 30, 30), 1)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        boxes.append(("裂痕", min(xs) - 2, min(ys) - 2, max(xs) + 2, max(ys) + 2))
    elif kind == 3:  # 卡屑（小目标，一图多个）
        for _ in range(g(1, 4)):
            cx, cy, r = g(40, 600), g(40, 440), g(3, 8)
            cv2.circle(img, (cx, cy), r, (g(0, 80), g(0, 80), g(0, 80)), -1)
            boxes.append(("卡屑", cx - r, cy - r, cx + r, cy + r))
    elif kind == 4:  # 气泡（环形）
        cx, cy, r = g(80, 560), g(80, 400), g(8, 20)
        cv2.circle(img, (cx, cy), r, (40, 40, 40), 2)
        boxes.append(("气泡", cx - r, cy - r, cx + r, cy + r))
    # kind == 5 正常，无标注
    name = f"img_{i:03d}.jpg"
    cv2.imwrite(f"{ROOT}/{name}", img)
    if boxes:
        records[name] = boxes

# ---------- 2. 重建数据集（API）----------
for ds_old in req("GET", f"{BASE}/datasets?project_id={PROJECT_ID}"):
    req("DELETE", f"{BASE}/datasets/{ds_old['id']}")
ds = req("POST", BASE + "/datasets", {"project_id": PROJECT_ID, "name": "线体A", "root_path": ROOT})
req("POST", f"{BASE}/datasets/{ds['id']}/split", {"train_ratio": 0.7, "val_ratio": 0.15, "seed": 42})
print(f"dataset {ds['id']} with {ds['image_count']} images, split done")

# ---------- 3. 插入标注（直接写库，annotations API 后续提供）----------
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cat_ids = {r["name"]: r["id"] for r in conn.execute(
    "SELECT id, name FROM categories WHERE project_id=?", (PROJECT_ID,))}
img_ids = {r["rel_path"]: r["id"] for r in conn.execute(
    "SELECT id, rel_path FROM images WHERE dataset_id=?", (ds["id"],))}
conn.execute("DELETE FROM annotations WHERE image_id IN "
             "(SELECT id FROM images WHERE dataset_id=?)", (ds["id"],))
n = 0
for name, boxes in records.items():
    for cat, x1, y1, x2, y2 in boxes:
        conn.execute(
            "INSERT INTO annotations (image_id, category_id, type, data, source) VALUES (?, ?, 'box', ?, 'auto')",
            (img_ids[name], cat_ids[cat],
             json.dumps({"x1": x1, "y1": y1, "x2": x2, "y2": y2})),
        )
        n += 1
conn.commit()
annotated = conn.execute("SELECT COUNT(DISTINCT image_id) FROM annotations").fetchone()[0]
conn.close()
print(f"annotations inserted: {n} boxes on {annotated} images")

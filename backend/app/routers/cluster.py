"""非监督分类：特征提取 + KMeans 聚类 + 伪标注生成。

流程：
1. POST /cluster/run {dataset_id, k} → 特征提取 + 聚类，返回聚类代表图与全部映射
2. 用户在 UI 命名/忽略聚类
3. POST /cluster/apply {assignments} → 批量写入 class 伪标注（source='cluster'）
"""
import json
import sqlite3
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.db import get_conn

class ClusterRequest(BaseModel):
    dataset_id: int
    k: int = Field(default=6, ge=2, le=50)

class ClusterApplyRequest(BaseModel):
    assignments: dict[int, int] = {}  # image_id -> category_id

router = APIRouter()

FEAT_SIZE = 224
_SAMPLE_PER_CLUSTER = 12


@router.post("/cluster/run")
def cluster_run(body: ClusterRequest):
    with get_conn() as conn:
        ds = conn.execute("SELECT * FROM datasets WHERE id=?", (body.dataset_id,)).fetchone()
        if not ds:
            raise HTTPException(404, "数据集不存在")
        imgs = conn.execute(
            "SELECT * FROM images WHERE dataset_id=? ORDER BY id", (body.dataset_id,)
        ).fetchall()
    if len(imgs) < body.k:
        raise HTTPException(400, f"图像数（{len(imgs)}）少于聚类数（{body.k}）")

    feats, valid_ids = _extract_features(ds, imgs)
    if len(valid_ids) < body.k:
        raise HTTPException(400, "可用的图像太少")

    from sklearn.cluster import KMeans
    km = KMeans(n_clusters=body.k, n_init=10, random_state=0).fit(feats)
    dist = km.transform(feats)  # (N, k) 每图到各中心距离
    assignments = {int(iid): int(c) for iid, c in zip(valid_ids, km.labels_)}

    clusters = []
    for c in range(body.k):
        members = [i for i in range(len(valid_ids)) if km.labels_[i] == c]
        members.sort(key=lambda i: dist[i, c])  # 距中心近的优先
        sample_ids = [int(valid_ids[i]) for i in members[:_SAMPLE_PER_CLUSTER]]
        clusters.append({"id": c, "size": len(members), "samples": sample_ids})

    return {"clusters": clusters, "assignments": assignments, "total": len(valid_ids)}


def _extract_features(ds, imgs):
    """resnet18 ImageNet 特征（avgpool 前 512 维）。权重优先本地缓存。"""
    import torch
    import torchvision

    try:
        model = torchvision.models.resnet18(weights=torchvision.models.ResNet18_Weights.DEFAULT)
    except Exception as e:
        raise HTTPException(500, f"预训练模型不可用：{e}")
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    root = Path(ds["root_path"])
    feats, valid_ids = [], []
    from app.engines.data_utils import read_image as _read_image
    with torch.no_grad():
        for im in imgs:
            img = _read_image(ds, im)
            if img is None:
                continue
            img = cv2.resize(img, (FEAT_SIZE, FEAT_SIZE), interpolation=cv2.INTER_LINEAR)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            img = (img - mean) / std
            x = torch.from_numpy(np.ascontiguousarray(img.transpose(2, 0, 1)))[None].to(device)
            x = model.maxpool(model.relu(model.bn1(model.conv1(x))))
            x = model.layer1(x)
            x = model.layer2(x)
            x = model.layer3(x)
            x = model.layer4(x)
            x = model.avgpool(x)
            feats.append(torch.flatten(x, 1).cpu().numpy()[0])
            valid_ids.append(im["id"])
    return np.stack(feats), valid_ids


@router.post("/cluster/apply")
def cluster_apply(body: ClusterApplyRequest):
    """批量生成 class 伪标注：覆盖指定图像的现有 class 标注。"""
    assignments = body.assignments or {}
    if not assignments:
        raise HTTPException(400, "没有可生成的标注")
    created = 0
    with get_conn() as conn:
        for image_id, category_id in assignments.items():
            if not conn.execute("SELECT 1 FROM images WHERE id=?", (image_id,)).fetchone():
                continue
            if not conn.execute("SELECT 1 FROM categories WHERE id=?", (category_id,)).fetchone():
                continue
            conn.execute("DELETE FROM annotations WHERE image_id=? AND type='class'", (image_id,))
            conn.execute(
                "INSERT INTO annotations (image_id, category_id, type, data, source) VALUES (?, ?, 'class', '{}', 'cluster')",
                (image_id, category_id),
            )
            created += 1
    return {"created": created}

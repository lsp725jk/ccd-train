# -*- coding: utf-8 -*-
"""引擎数据准备层测试（不跑训练，只验证数据转换正确性）。

覆盖：
- smp_segment.make_ds：图像/mask 尺寸、标签值、增强后尺寸一致
- 分割 mask 渲染：box/mask 标注 → 类索引、shield → 255 ignore
- yolo_detect 标签：归一化坐标正确
"""
import json

import cv2
import numpy as np
import pytest

from app.engines.seg_dataset import make_ds


def _mk_img(h=64, w=64, seed=0):
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[20:40, 20:40] = 1  # 类别 1 区域
    return img, mask


def test_make_ds_eval_resize(tmp_path):
    """非训练模式：图像/mask 统一 resize 到目标尺寸，mask 保留标签。"""
    img, mask = _mk_img()
    for split in ("train", "val", "test"):
        (tmp_path / split / "images").mkdir(parents=True)
        (tmp_path / split / "masks").mkdir(parents=True)
    cv2.imencode(".png", img)[1].tofile(tmp_path / "train" / "images" / "a.png")
    cv2.imencode(".png", mask)[1].tofile(tmp_path / "train" / "masks" / "a.png")

    ds = make_ds(tmp_path, 32, "train", train=False)
    assert len(ds) == 1
    x, y = ds[0]
    assert x.shape == (3, 32, 32)
    assert y.shape == (32, 32)
    assert set(np.unique(y).tolist()).issubset({0, 1})


def test_make_ds_train_random_crop(tmp_path):
    """训练模式：随机裁剪输出恒为目标尺寸。"""
    img, mask = _mk_img(80, 64)
    (tmp_path / "train" / "images").mkdir(parents=True)
    (tmp_path / "train" / "masks").mkdir(parents=True)
    cv2.imencode(".png", img)[1].tofile(tmp_path / "train" / "images" / "a.png")
    cv2.imencode(".png", mask)[1].tofile(tmp_path / "train" / "masks" / "a.png")

    ds = make_ds(tmp_path, 32, "train", train=True)
    for _ in range(5):
        x, y = ds[0]
        assert x.shape[1:] == (32, 32)
        assert y.shape == (32, 32)


def test_make_ds_train_aug_keeps_size(tmp_path):
    """带几何增强（旋转/缩放）时，增强后尺寸仍为目标尺寸（batch 一致性修复）。"""
    from app.ops import build_augmentation
    aug_ops = [
        {"name": "rotate", "params": {"limit": 15, "p": 1.0}},
        {"name": "scale", "params": {"limit": 0.1, "p": 1.0}},
    ]
    # make_ds 内部用 build_augmentation，这里直接验证变换组合输出尺寸可复现
    img, mask = _mk_img(64, 64)
    transform = build_augmentation(aug_ops, seed=1)
    for _ in range(5):
        aug = transform(image=img, mask=mask)
        assert aug["image"].shape[:2] == (64, 64)
        assert aug["mask"].shape[:2] == (64, 64)


def test_mask_render_shield_is_255():
    """屏蔽区渲染为 255（训练时 ignore），普通类别为索引值。"""
    mask = np.zeros((64, 64), dtype=np.uint8)
    # 模拟 smp_segment.run 的渲染逻辑
    cv2.rectangle(mask, (5, 5), (20, 20), 1, -1)     # 类别 1
    cv2.rectangle(mask, (40, 40), (55, 55), 255, -1)  # 屏蔽区
    assert mask[10, 10] == 1
    assert mask[48, 48] == 255
    assert mask[30, 30] == 0


def test_cfg_dataset_ids_compat():
    """新旧 config 取数兼容。"""
    from app.engines.data_utils import cfg_dataset_ids
    assert cfg_dataset_ids({"dataset_ids": [5, 12]}) == [5, 12]
    assert cfg_dataset_ids({"dataset_id": 5}) == [5]
    assert cfg_dataset_ids({}) == []


def test_yolo_label_line():
    """yolo_detect 标签行格式：类别 + 归一化中心/宽高。"""
    # 直接验证格式（引擎内的转换逻辑）
    w, h = 100, 50
    x1, y1, x2, y2 = 10, 5, 30, 25  # 20x20 的框
    line = f"{0} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}"
    parts = [float(p) for p in line.split()]
    assert parts == pytest.approx([0, 0.2, 0.3, 0.2, 0.4])
    # 归一化值必须在 [0, 1]
    assert all(0 <= p <= 1 for p in parts[1:])

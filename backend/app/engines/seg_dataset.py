"""语义分割数据集：图像+mask 读取、随机裁剪、增强、尺寸统一。

从 smp_segment.py 拆出，独立可单测。make_ds 负责把 run_dir/data/{split}/
下的 images/masks 变成 torch Dataset。
"""
import random
from pathlib import Path

import cv2
import numpy as np

from app.engines.data_utils import imgsz_wh


def make_ds(data_dir: Path, imgsz: int, split: str, train: bool, aug_ops: list | None = None):
    import torch
    from torch.utils.data import Dataset

    img_dir = data_dir / split / "images"
    pairs = sorted((img_dir / p.name, data_dir / split / "masks" / p.name)
                   for p in img_dir.glob("*.png"))

    class SegDS(Dataset):
        def __len__(self):
            return len(pairs)

        def __getitem__(self, i):
            ip, mp = pairs[i]
            img = cv2.imread(str(ip), cv2.IMREAD_COLOR)
            mask = cv2.imread(str(mp), cv2.IMREAD_GRAYSCALE)
            h, w = img.shape[:2]
            tw, th = imgsz_wh(imgsz)
            if train:
                scale = max(th / h, tw / w)
                nh, nw = int(h * scale), int(w * scale)
                img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
                mask = cv2.resize(mask, (nw, nh), interpolation=cv2.INTER_NEAREST)
                y0 = random.randint(0, max(0, nh - th))
                x0 = random.randint(0, max(0, nw - tw))
                img = img[y0:y0 + th, x0:x0 + tw]
                mask = mask[y0:y0 + th, x0:x0 + tw]
                if random.random() < 0.5:
                    img = img[:, ::-1]
                    mask = mask[:, ::-1]
            else:
                img = cv2.resize(img, (tw, th), interpolation=cv2.INTER_LINEAR)
                mask = cv2.resize(mask, (tw, th), interpolation=cv2.INTER_NEAREST)
            if train and aug_ops:
                from app.ops import build_augmentation
                transform = build_augmentation(aug_ops, seed=None)
                aug = transform(image=img, mask=mask)
                img, mask = aug["image"], aug["mask"]
                # 几何增强（旋转/缩放/仿射）可能改变尺寸，强制回目标尺寸保证 batch 一致
                if img.shape[:2] != (th, tw):
                    img = cv2.resize(img, (tw, th), interpolation=cv2.INTER_LINEAR)
                    mask = cv2.resize(mask, (tw, th), interpolation=cv2.INTER_NEAREST)
            img = img.astype(np.float32) / 255.0
            img = np.ascontiguousarray(img.transpose(2, 0, 1))
            return torch.from_numpy(img), torch.from_numpy(mask.astype(np.int64))

    return SegDS()

"""语义分割引擎（SMP：UNet / DeepLabV3+，类式）。

数据：images + annotations(type='mask' 多边形 / type='box') → 类索引 mask PNG
"""
import csv
import json
import random
import time
from pathlib import Path

import cv2
import numpy as np

from app.engines.base import EngineBase, get_db, run_engine
from app.engines.data_utils import (
    cat_index_1, cfg_dataset_ids, get_pipeline_ops, imgsz_wh, load_annotations_multi, load_categories, load_ds, load_images, read_image,
)
from app.engines.seg_dataset import make_ds

OUT_COLS = ["epoch", "train_loss", "val_loss", "iou"]


class SmpSegmentEngine(EngineBase):
    task_type = "segment"

    def run(self):
        cfg = self.cfg
        data_dir = self.run_dir / "data"
        for split in ("train", "val", "test"):
            (data_dir / split / "images").mkdir(parents=True, exist_ok=True)
            (data_dir / split / "masks").mkdir(parents=True, exist_ok=True)

        with get_db() as conn:
            ds_ids = cfg_dataset_ids(cfg)
            ds_rows = [load_ds(conn, dsid) for dsid in ds_ids]
            cats = load_categories(conn, cfg["project_id"], ds_ids)
            idx = cat_index_1(cats)  # 1 起，0 留给背景
            names = [c["name"] for c in cats]
            imgs = []
            for ds in ds_rows:
                imgs.extend(load_images(conn, ds["id"]))
            anns = load_annotations_multi(conn, ds_ids, ("mask", "box", "shield"))
            pipeline_ops = get_pipeline_ops(conn, cfg.get("preprocess_pipeline_id"))

        copied = {"train": 0, "val": 0, "test": 0}
        for ds in ds_rows:
            for im in [i for i in imgs if i["dataset_id"] == ds["id"]]:
                items = anns.get(im["id"], [])
                if not items:
                    continue
                split = im["split"] if im["split"] in ("train", "val", "test") else "train"
                fname = f"{ds['id']}_{im['id']:07d}.png"
                img_dst = data_dir / split / "images" / fname
                if not img_dst.exists():
                    try:
                        img = read_image(ds, im)
                        if img is None:
                            continue
                        if pipeline_ops:
                            from app.ops import apply_preprocess
                            img = apply_preprocess(img, pipeline_ops)
                        # mask 先按原图尺寸渲染，再同步预处理引起的几何变化（如 resize）
                        mask = np.zeros((im["height"], im["width"]), dtype=np.uint8)
                        for a in items:
                            d = json.loads(a["data"])
                            if a["type"] == "shield":
                                # 屏蔽区：不参与训练（255 = ignore，损失计算时忽略）
                                if d.get("points"):
                                    pts = np.array(d["points"], dtype=np.int32).reshape(-1, 2)
                                    cv2.fillPoly(mask, [pts], 255)
                                continue
                            c = idx.get(a["category_id"])
                            if c is None:
                                continue
                            if a["type"] == "mask" and d.get("points"):
                                pts = np.array(d["points"], dtype=np.int32).reshape(-1, 2)
                                cv2.fillPoly(mask, [pts], c)
                            elif a["type"] == "box":
                                x1, y1 = int(d["x1"]), int(d["y1"])
                                x2, y2 = int(d["x2"]), int(d["y2"])
                                cv2.rectangle(mask, (x1, y1), (x2, y2), c, -1)
                        ph, pw = img.shape[:2]
                        if (ph, pw) != (im["height"], im["width"]):
                            mask = cv2.resize(mask, (pw, ph), interpolation=cv2.INTER_NEAREST)
                        cv2.imencode(".png", img)[1].tofile(img_dst)
                        cv2.imencode(".png", mask)[1].tofile(data_dir / split / "masks" / fname)
                        copied[split] += 1
                    except Exception as e:
                        self.log(f"[warn] 处理失败 {im['rel_path']}: {e}")
                        continue
        if not any((data_dir / "train" / "images").glob("*.png")):
            raise RuntimeError("没有找到带 mask/box 标注的图像，请先在标注工作台标注")
        self.log(f"[data] train={copied['train']} val={copied['val']} test={copied['test']} classes={names}")

        model = self._train(data_dir, len(cats))
        self.weights_path = self.run_dir / "weights" / "best.pth"
        self.arch = cfg["engine"]
        self._evaluate(model, len(cats), data_dir)

    # ---------- 训练 ----------

    def _train(self, data_dir: Path, n_classes: int):
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader
        import segmentation_models_pytorch as smp

        cfg = self.cfg
        device = "cuda" if torch.cuda.is_available() else "cpu"
        encoder = cfg["engine"].split("_")[-1] if cfg["engine"].startswith("unet") else "resnet50"
        arch = "DeepLabV3Plus" if cfg["engine"].startswith("deeplab") else "Unet"

        # 预训练权重：smp 新版从 HF Hub（smp-hub/resnetXX.imagenet）加载 safetensors。
        # 缓存命中时秒加载；设置 HF_HUB_OFFLINE 强制离线，避免网络卡死，缓存缺失时降级随机初始化。
        import os as _os
        cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
        hf_repo = f"models--smp-hub--{encoder}.imagenet"
        cached = (cache_dir / hf_repo).is_dir() and any((cache_dir / hf_repo).glob("snapshots/*/model.safetensors"))
        if cached:
            _os.environ["HF_HUB_OFFLINE"] = "1"
            self.log(f"[model] 使用本地缓存预训练权重: {hf_repo}")
            try:
                model = smp.create_model(arch, encoder_name=encoder, encoder_weights="imagenet",
                                         classes=n_classes + 1, in_channels=3)
                self.log(f"[model] {arch}({encoder}) with cached ImageNet weights")
            except Exception as e:
                self.log(f"[warn] 缓存权重加载失败，随机初始化: {str(e)[:200]}")
                model = smp.create_model(arch, encoder_name=encoder, encoder_weights=None,
                                         classes=n_classes + 1, in_channels=3)
        else:
            # 无缓存：不触发网络下载（会卡死），直接随机初始化并提示
            self.log(f"[warn] 未找到 {encoder} 预训练权重缓存（{hf_repo}），随机初始化"
                     f"（如需迁移学习，请先下载权重：hf_hub_download('smp-hub/{encoder}.imagenet', 'model.safetensors')）")
            model = smp.create_model(arch, encoder_name=encoder, encoder_weights=None,
                                     classes=n_classes + 1, in_channels=3)
        model.to(device)

        with get_db() as conn:
            aug_ops = get_pipeline_ops(conn, cfg.get("aug_pipeline_id"))
        if aug_ops:
            self.log(f"[aug] 增强管线: {[o.get('name') for o in aug_ops]}")
        train_dl = DataLoader(make_ds(data_dir, cfg["imgsz"], "train", True, aug_ops), batch_size=cfg["batch"],
                              shuffle=True, num_workers=0, drop_last=True)
        val_dl = DataLoader(make_ds(data_dir, cfg["imgsz"], "val", False), batch_size=cfg["batch"], num_workers=0)

        loss_fn = smp.losses.DiceLoss(mode="multiclass", ignore_index=255)
        # 类权重：按训练集像素占比倒数，缓解前景占比过小的塌缩（用于加权 CE）
        # 屏蔽区（255）不计入统计
        hist = np.zeros(n_classes + 1)
        for mpath in (data_dir / "train" / "masks").glob("*.png"):
            m = cv2.imread(str(mpath), cv2.IMREAD_GRAYSCALE)
            if m is None:
                continue
            for c in range(n_classes + 1):
                hist[c] += int((m == c).sum())
        hist = hist / max(1.0, hist.sum())
        cw = 1.0 / (hist + 1e-6)
        cw = cw / cw.mean()
        ce = nn.CrossEntropyLoss(weight=torch.tensor(cw, dtype=torch.float32).to(device), ignore_index=255)
        self.log(f"[loss] class weights: {np.round(cw, 2).tolist()}")

        opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=cfg["epochs"])

        best_iou = 0.0
        with open(self.run_dir / "results.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(OUT_COLS)
            for epoch in range(1, cfg["epochs"] + 1):
                model.train()
                t_loss = 0.0
                t0 = time.time()
                for img, msk in train_dl:
                    img, msk = img.to(device), msk.to(device)
                    opt.zero_grad()
                    logits = model(img)
                    loss = 0.6 * loss_fn(logits, msk) + 0.4 * ce(logits, msk)
                    loss.backward()
                    opt.step()
                    t_loss += loss.item() * img.size(0)
                sched.step()
                t_loss /= max(1, len(train_dl.dataset))

                v_loss, v_iou = self._validate(model, val_dl, loss_fn, ce, device) if len(val_dl.dataset) else (0.0, 0.0)
                w.writerow([epoch, round(t_loss, 4), round(v_loss, 4), round(v_iou, 4)])
                f.flush()
                self.set_progress(epoch / cfg["epochs"])
                if v_iou > best_iou:
                    best_iou = v_iou
                    self.save_weights_from_state(model, "best.pth")
                self.log(f"[epoch {epoch}/{cfg['epochs']}] loss={t_loss:.4f} val_loss={v_loss:.4f} iou={v_iou:.4f} "
                         f"({time.time()-t0:.1f}s)")
        return model

    def save_weights_from_state(self, model, name: str) -> Path:
        """分割引擎：state_dict 存盘（非 ultralytics checkpoint）。"""
        import torch
        wdir = self.run_dir / "weights"
        wdir.mkdir(exist_ok=True)
        torch.save(model.state_dict(), wdir / name)
        return wdir / name

    def _validate(self, model, dl, loss_fn, ce, device):
        import torch
        model.eval()
        total_loss, total_iou, n = 0.0, 0.0, 0
        with torch.no_grad():
            for img, msk in dl:
                img, msk = img.to(device), msk.to(device)
                logits = model(img)
                total_loss += (0.6 * loss_fn(logits, msk) + 0.4 * ce(logits, msk)).item() * img.size(0)
                pred = logits.argmax(dim=1)
                for p, m in zip(pred, msk):
                    valid = m < 255  # 屏蔽区不参与评估
                    inter = (((p == m) & (m > 0)) & valid).sum().float()
                    union = (((p > 0) | (m > 0)) & valid).sum().float()
                    total_iou += (inter / union).item() if union > 0 else 1.0
                    n += 1
        model.train()
        return total_loss / max(1, n), total_iou / max(1, n)

    # ---------- 评估 ----------

    def _evaluate(self, model, n_classes: int, data_dir: Path):
        import torch
        from torch.utils.data import DataLoader

        cfg = self.cfg
        test_dir = data_dir / "test" / "images"
        if not test_dir.is_dir() or not any(test_dir.glob("*.png")):
            self.log("[warn] 无测试集，跳过评估")
            return
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.eval()
        test_dl = DataLoader(make_ds(data_dir, cfg["imgsz"], "test", False), batch_size=cfg["batch"], num_workers=0)
        total_iou, total_acc, n = 0.0, 0.0, 0
        with torch.no_grad():
            for img, msk in test_dl:
                img = img.to(device)
                pred = model(img).argmax(dim=1).cpu()
                for p, m in zip(pred, msk):
                    valid = m < 255
                    inter = (((p == m) & (m > 0)) & valid).sum().float()
                    union = (((p > 0) | (m > 0)) & valid).sum().float()
                    total_iou += (inter / union).item() if union > 0 else 1.0
                    total_acc += ((p == m) & valid).float().mean().item()
                    n += 1
        metrics = {"mIoU": round(total_iou / max(1, n), 4), "pixel_acc": round(total_acc / max(1, n), 4)}
        (self.run_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

        pred_dir = self.run_dir / "viz" / "predictions"
        pred_dir.mkdir(parents=True, exist_ok=True)
        # 类别颜色（全局一致：与标注器同一套颜色）
        from app.engines.data_utils import load_categories
        with get_db() as conn:
            ds_ids = cfg_dataset_ids(cfg)
            cats = load_categories(conn, cfg["project_id"], ds_ids)
        def _bgr(hex_color: str):
            h = hex_color.lstrip("#")
            return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)) if len(h) == 6 else (0, 180, 255)
        colors = {i + 1: _bgr(c["color"]) for i, c in enumerate(cats)}
        cat_names = {i + 1: c["name"] for i, c in enumerate(cats)}
        test_pairs = sorted((test_dir / p.name, data_dir / "test" / "masks" / p.name)
                            for p in test_dir.glob("*.png"))
        predictions = []  # 结构化预测明细（前端展示用）
        for ip, _mp in random.Random(1).sample(test_pairs, min(6, len(test_pairs))):
            img = cv2.imread(str(ip), cv2.IMREAD_COLOR)
            orig_h, orig_w = img.shape[:2]
            tw, th = imgsz_wh(cfg["imgsz"])
            resized = cv2.resize(img, (tw, th))
            x = torch.from_numpy(np.ascontiguousarray(resized.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]).to(device)
            pred = model(x).argmax(dim=1)[0].cpu().numpy().astype(np.uint8)
            pred = cv2.resize(pred, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)
            overlay = img.copy()
            # 提取每个类别的连通域：面积/bbox/中心
            regions = []
            for c_idx, bgr in colors.items():
                mask_c = (pred == c_idx).astype(np.uint8)
                if not mask_c.any():
                    continue
                overlay[mask_c.astype(bool)] = bgr
                contours, _ = cv2.findContours(mask_c, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for ct in contours:
                    area = float(cv2.contourArea(ct))
                    if area < 25:
                        continue
                    x, y, bw, bh = cv2.boundingRect(ct)
                    regions.append({
                        "category": cat_names.get(c_idx, f"class{c_idx}"),
                        "confidence": None,  # 分割无单目标置信度，面积即置信度代理
                        "score": round(area / (orig_w * orig_h), 4),  # 面积占比作为得分
                        "bbox": [x, y, x + bw, y + bh],
                        "area_px": round(area),
                        "area_ratio": round(area / (orig_w * orig_h) * 100, 2),
                        "center": [round(x + bw / 2, 1), round(y + bh / 2, 1)],
                    })
                    # 图上标注：类别 + 面积占比
                    label = f"{cat_names.get(c_idx, '')} {area/(orig_w*orig_h)*100:.1f}%"
                    (tw2, th2), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                    cv2.rectangle(overlay, (x, max(0, y - th2 - 6)), (x + tw2, y), bgr, -1)
                    cv2.putText(overlay, label, (x + 2, max(th2, y - 2)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.imencode(".jpg", np.hstack([img, overlay]))[1].tofile(pred_dir / f"{Path(ip).stem}.jpg")
            predictions.append({"image": Path(ip).name, "size": [orig_w, orig_h], "regions": regions})
        (self.run_dir / "predictions.json").write_text(
            json.dumps(predictions, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"[eval] {metrics}")


if __name__ == "__main__":
    run_engine(SmpSegmentEngine)

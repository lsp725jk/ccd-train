"""非监督异常检测引擎（PatchCore 风格，类式）。

数据：train 集中无标注的图视为正常样本 → 特征记忆库；
test 集有 box/mask 标注的图视为异常 → AUROC + 热图。
"""
import csv
import json
import random
from pathlib import Path

import cv2
import numpy as np

from app.engines.base import EngineBase, get_db, run_engine
from app.engines.data_utils import cfg_dataset_ids, load_ds, load_images

IMG_SIZE = 256
SAMPLE_RATIO = 0.1


def _load_model():
    """WideResNet-50 → ResNet-18 → 随机，逐级 fallback。返回 (model, name)。"""
    import torch
    import torchvision
    for weights, name in [(torchvision.models.Wide_ResNet50_2_Weights.DEFAULT, "wide_resnet50_2"),
                          (torchvision.models.ResNet18_Weights.DEFAULT, "resnet18")]:
        try:
            model = torchvision.models.__dict__[name](weights=weights)
            return model, name
        except Exception as e:
            print(f"[warn] {name} 权重不可用: {e}", flush=True)
    return torchvision.models.resnet18(weights=None), "resnet18"


def _extract_features(model, img_bgr, device):
    """单图特征：layer2 + layer3 拼接，展平 patch 特征 (P, D)。"""
    import torch
    import torchvision.transforms as T
    tf = T.Compose([
        T.ToTensor(),
        T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    x = tf(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))[None].to(device)
    with torch.no_grad():
        x = model.maxpool(model.relu(model.bn1(model.conv1(x))))
        f2 = model.layer2(model.layer1(x))
        f3 = model.layer3(f2)
        f2 = torch.nn.functional.interpolate(f2, size=f3.shape[-2:], mode="bilinear")
        feat = torch.cat([f2, f3], dim=1)
    return feat[0].permute(1, 2, 0).reshape(-1, feat.shape[1]).cpu().numpy(), feat.shape[1]


class PatchCoreEngine(EngineBase):
    task_type = "us_segment"

    def _normal_images(self):
        """train 集中无 box/mask 标注的图 = 正常样本。"""
        dsid = cfg_dataset_ids(self.cfg)[0]
        with get_db() as conn:
            ds = load_ds(conn, dsid)
            imgs = list(conn.execute(
                """SELECT * FROM images WHERE dataset_id=? AND split='train' AND id NOT IN
                    (SELECT DISTINCT image_id FROM annotations
                     WHERE type IN ('box','mask') AND image_id IN
                     (SELECT id FROM images WHERE dataset_id=? AND split='train'))""",
                (dsid, dsid),
            ).fetchall())
        return ds, imgs

    def _build_bank(self, model, device):
        """正常样本 → PatchCore 特征库（coreset 采样）。"""
        import torch
        from app.engines.data_utils import read_image as _read_image
        ds, imgs = self._normal_images()
        if not imgs:
            raise RuntimeError("训练集中没有正常样本（无标注图像），请先划分包含无缺陷图像的数据集")
        root = Path(ds["root_path"])
        features = []
        total = len(imgs)
        for i, im in enumerate(imgs):
            img = _read_image(ds, im)
            if img is None:
                continue
            feat, _dim = _extract_features(model, img, device)
            features.append(feat)
            self.set_progress(0.3 + 0.5 * (i + 1) / max(1, total))
            if (i + 1) % 10 == 0:
                self.log(f"[bank] {i + 1}/{total}")
        all_feats = np.concatenate(features, axis=0)
        n_keep = max(1, int(len(all_feats) * SAMPLE_RATIO))
        idx = random.Random(0).sample(range(len(all_feats)), n_keep)
        bank = all_feats[idx]
        self.log(f"[bank] {len(all_feats)} patches -> coreset {len(bank)}")
        np.save(self.run_dir / "bank.npy", bank)
        return bank

    def _evaluate(self, model, bank, device):
        """测试集评估：距离分数 → AUROC + 热图。"""
        import torch
        from sklearn.metrics import roc_auc_score
        from app.engines.data_utils import read_image as _read_image
        cfg = self.cfg
        dsid = cfg_dataset_ids(cfg)[0]
        with get_db() as conn:
            ds = load_ds(conn, dsid)
            test_imgs = load_images(conn, dsid, split="test")
            ann_ids = {r[0] for r in conn.execute(
                "SELECT DISTINCT image_id FROM annotations WHERE type IN ('box','mask') AND image_id IN "
                "(SELECT id FROM images WHERE dataset_id=? AND split='test')", (dsid,)
            ).fetchall()}
        root = Path(ds["root_path"])
        bank_t = torch.from_numpy(bank).to(device)
        scores, labels = [], []
        pred_dir = self.run_dir / "viz" / "predictions"
        pred_dir.mkdir(parents=True, exist_ok=True)
        total = len(test_imgs)
        for i, im in enumerate(test_imgs):
            img = _read_image(ds, im)
            if img is None:
                continue
            feat, _ = _extract_features(model, img, device)
            feat_t = torch.from_numpy(feat).to(device)
            dist = torch.cdist(feat_t, bank_t).min(dim=1).values
            scores.append(float(dist.max()))
            labels.append(1 if im["id"] in ann_ids else 0)
            h = int(np.sqrt(len(dist)))
            hm = dist.cpu().numpy()[: h * h].reshape(h, h)
            hm = cv2.resize(hm, (img.shape[1], img.shape[0]))
            hm = cv2.normalize(hm, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            heat = cv2.applyColorMap(hm, cv2.COLORMAP_JET)
            cv2.imencode(".jpg", cv2.addWeighted(img, 0.6, heat, 0.4, 0))[1].tofile(pred_dir / f"{im['id']:07d}.jpg")
            self.set_progress(0.8 + 0.2 * (i + 1) / max(1, total))

        metrics = {"test_count": len(scores)}
        if len(set(labels)) > 1:
            metrics["auroc_image"] = round(float(roc_auc_score(labels, scores)), 4)
        (self.run_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"[eval] {metrics}")

    def run(self):
        import torch
        cfg = self.cfg
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model, name = _load_model()
        model.to(device).eval()
        self.log(f"[model] {name}")

        # ---------- 特征库（正常样本） ----------
        bank = self._build_bank(model, device)
        self.arch = f"patchcore_{name}"

        # ---------- 评估 ----------
        self._evaluate(model, bank, device)

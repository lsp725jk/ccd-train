"""YOLO11 目标检测引擎（类式）。

数据：images + annotations(type='box') → YOLO 目录结构 + data.yaml
"""
import json
import shutil
import threading
from pathlib import Path

import cv2

from app.engines.base import EngineBase, get_db, run_engine, sync_ultralytics_curve
from app.engines.data_utils import (
    cat_index, cfg_dataset_ids, get_pipeline_ops, imgsz_hw, load_annotations_multi, load_categories,
    load_ds, load_images, read_image,
)

COL_MAP = {
    "train/box_loss": "train_loss",
    "val/box_loss": "val_loss",
    "metrics/precision(B)": "precision",
    "metrics/recall(B)": "recall",
    "metrics/mAP50(B)": "mAP50",
    "metrics/mAP50-95": "mAP50-95",
}
OUT_COLS = ["epoch", "train_loss", "val_loss", "mAP50", "mAP50-95", "precision", "recall"]

# 类别画框颜色（BGR，与前端标注色系一致）
CAT_BGR = [(83, 121, 78), (89, 87, 225), (79, 161, 89), (43, 142, 242), (161, 122, 176), (178, 183, 118), (72, 201, 237), (167, 157, 255)]


class YoloDetectEngine(EngineBase):
    task_type = "detect"

    def run(self):
        cfg = self.cfg
        from ultralytics import YOLO

        # ---------- 数据准备 ----------
        data_dir = self.run_dir / "data"
        for split in ("train", "val", "test"):
            (data_dir / split / "images").mkdir(parents=True, exist_ok=True)
            (data_dir / split / "labels").mkdir(parents=True, exist_ok=True)

        with get_db() as conn:
            ds_ids = cfg_dataset_ids(cfg)
            ds_rows = [load_ds(conn, dsid) for dsid in ds_ids]
            cats = load_categories(conn, cfg["project_id"], ds_ids)
            idx = cat_index(cats)
            names = [c["name"] for c in cats]
            imgs = []
            for ds in ds_rows:
                imgs.extend(load_images(conn, ds["id"]))
            anns = load_annotations_multi(conn, ds_ids, ("box",))
            pipeline_ops = get_pipeline_ops(conn, cfg.get("preprocess_pipeline_id"))

        # 多数据集时用数据集 id 前缀避免文件重名
        id_off = 0
        copied = {"train": 0, "val": 0, "test": 0}
        for ds in ds_rows:
            for im in [i for i in imgs if i["dataset_id"] == ds["id"]]:
                split = im["split"] if im["split"] in ("train", "val", "test") else "train"
                img_name = f"{ds['id']}_{im['id']:07d}{Path(im['rel_path']).suffix.lower()}"
                dst_img = data_dir / split / "images" / img_name
                if not dst_img.exists():
                    try:
                        if pipeline_ops:
                            from app.ops import apply_preprocess
                            img = read_image(ds, im)
                            if img is None:
                                continue
                            out = apply_preprocess(img, pipeline_ops)
                            cv2.imencode(dst_img.suffix.lower() or ".jpg", out)[1].tofile(dst_img)
                        else:
                            shutil.copy2(Path(ds["root_path"]) / im["rel_path"], dst_img)
                    except Exception as e:
                        self.log(f"[warn] 图像处理失败 {im['rel_path']}: {e}")
                        continue
                lines = []
                for a in anns.get(im["id"], []):
                    if a["category_id"] not in idx:
                        continue
                    d = json.loads(a["data"])
                    w, h = im["width"], im["height"]
                    x1, y1, x2, y2 = d["x1"], d["y1"], d["x2"], d["y2"]
                    lines.append(
                        f"{idx[a['category_id']]} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} "
                        f"{(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}"
                    )
                if lines:
                    (data_dir / split / "labels" / f"{ds['id']}_{im['id']:07d}.txt").write_text(
                        "\n".join(lines), encoding="utf-8"
                    )
                copied[split] += 1

        yaml_path = self.run_dir / "data.yaml"
        yaml_path.write_text(
            f"path: {data_dir.as_posix()}\n"
            f"train: train/images\nval: val/images\ntest: test/images\n"
            f"names: {json.dumps(names, ensure_ascii=False)}\n",
            encoding="utf-8",
        )
        self.log(f"[data] train={copied['train']} val={copied['val']} test={copied['test']} classes={names}")

        # ---------- 训练 ----------
        yolo_project = self.run_dir / "yolo"
        try:
            model = YOLO(f"{cfg['engine']}.pt")
        except Exception as e:
            self.log(f"[warn] 预训练权重不可用，从零训练: {e}")
            model = YOLO(f"{cfg['engine']}.yaml")
        stop_evt = threading.Event()
        threading.Thread(
            target=sync_ultralytics_curve,
            args=(cfg, yolo_project / "train" / "results.csv", self.run_dir / "results.csv",
                  COL_MAP, OUT_COLS, stop_evt),
            daemon=True,
        ).start()
        model.train(
            data=str(yaml_path), epochs=cfg["epochs"], imgsz=imgsz_hw(cfg["imgsz"]),
            batch=cfg["batch"], device=0, project=str(yolo_project), name="train",
            exist_ok=True, workers=2, patience=20, verbose=True,
            fliplr=float(cfg.get("aug_flip", True)),
            mosaic=float(cfg.get("aug_mosaic", 1.0)),
            mixup=float(cfg.get("aug_mixup", 0.0)),
            hsv_h=float(cfg.get("aug_hsv", 0.015)),
        )
        stop_evt.set()

        best = yolo_project / "train" / "weights" / "best.pt"
        if best.is_file():
            self.weights_path = self.save_weights(best)
            self.arch = cfg["engine"]

        # ---------- 评估 ----------
        if not self.weights_path:
            self.log("[warn] 无权重文件，跳过评估")
            return
        model = YOLO(str(self.weights_path))
        val_dir = yolo_project / "val"
        results = model.val(
            data=str(yaml_path), split="test",
            project=str(yolo_project), name="val", exist_ok=True, device=0,
        )
        metrics = {
            "mAP50": round(float(results.box.map50), 4),
            "mAP50-95": round(float(results.box.map), 4),
            "precision": round(float(results.box.mp), 4),
            "recall": round(float(results.box.mr), 4),
        }
        (self.run_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        viz = self.run_dir / "viz"
        viz.mkdir(exist_ok=True)
        for name in ("PR_curve.png", "confusion_matrix.png"):
            src = val_dir / name
            if src.is_file():
                shutil.copy2(src, viz / name)
        pred_dir = viz / "predictions"
        pred_dir.mkdir(exist_ok=True)
        with get_db() as conn:
            ds_ids = cfg_dataset_ids(cfg)
            ds_map = {ds["id"]: ds for ds in (load_ds(conn, d) for d in ds_ids)}
            test_imgs = []
            for dsid in ds_ids:
                test_imgs.extend(load_images(conn, dsid, split="test"))
        import random
        predictions = []  # 结构化预测明细（前端展示用）
        for im in random.Random(1).sample(list(test_imgs), min(8, len(test_imgs))):
            ds = ds_map[im["dataset_id"]]
            img_path = Path(ds["root_path"]) / im["rel_path"]
            res = model.predict(str(img_path), imgsz=imgsz_hw(cfg["imgsz"]), device=0, conf=0.25, verbose=False)
            r = res[0]
            # 自定义绘制：类别名（中文）+ 置信度 + 面积（ultralytics 默认只画 class id）
            img_show = r.orig_img.copy() if r.orig_img is not None else cv2.imread(str(img_path))
            if r.boxes is not None and len(r.boxes):
                for box in r.boxes:
                    x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
                    conf = float(box.conf[0])
                    cls = int(box.cls[0])
                    label = names[cls] if cls < len(names) else f"class{cls}"
                    color = CAT_BGR[cls % len(CAT_BGR)]
                    cv2.rectangle(img_show, (x1, y1), (x2, y2), color, 3)
                    area_txt = f"{label} {conf:.2f} | {abs(x2-x1)*abs(y2-y1)}px"
                    (tw, th), _ = cv2.getTextSize(area_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                    cv2.rectangle(img_show, (x1, max(0, y1 - th - 8)), (x1 + tw, y1), color, -1)
                    cv2.putText(img_show, area_txt, (x1 + 2, max(th, y1 - 4)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.imencode(".jpg", img_show)[1].tofile(pred_dir / f"{ds['id']}_{im['id']:07d}.jpg")
            # 结构化明细：类型/位置/置信度/面积
            img_w, img_h = im["width"], im["height"]
            entry = {"image": im["rel_path"], "size": [img_w, img_h], "boxes": []}
            if r.boxes is not None and len(r.boxes):
                for box in r.boxes:
                    x1, y1, x2, y2 = [float(v) for v in box.xyxy[0]]
                    conf = float(box.conf[0])
                    cls = int(box.cls[0])
                    entry["boxes"].append({
                        "category": names[cls] if cls < len(names) else f"class{cls}",
                        "confidence": round(conf, 4),
                        "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                        "area_px": round((x2 - x1) * (y2 - y1)),
                        "area_ratio": round((x2 - x1) * (y2 - y1) / (img_w * img_h) * 100, 2),
                        "center": [round((x1 + x2) / 2, 1), round((y1 + y2) / 2, 1)],
                    })
            predictions.append(entry)
        (self.run_dir / "predictions.json").write_text(
            json.dumps(predictions, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"[eval] {metrics}")


if __name__ == "__main__":
    run_engine(YoloDetectEngine)

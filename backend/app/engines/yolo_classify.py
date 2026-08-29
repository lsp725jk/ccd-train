"""YOLO 分类引擎（类式）。

数据：images + annotations(type='class') → {split}/{类别名}/ 目录结构
"""
import json
import shutil
import threading
from pathlib import Path

from app.engines.base import EngineBase, get_db, run_engine, sync_ultralytics_curve
from app.engines.data_utils import cfg_dataset_ids, imgsz_hw, load_categories, load_ds, load_images, resolve_device

COL_MAP = {
    "train/loss": "train_loss",
    "val/loss": "val_loss",
    "metrics/accuracy_top1": "accuracy",
}
OUT_COLS = ["epoch", "train_loss", "val_loss", "accuracy"]


class YoloClassifyEngine(EngineBase):
    task_type = "classify"

    def run(self):
        cfg = self.cfg
        from ultralytics import YOLO

        # ---------- 数据准备 ----------
        data_dir = self.run_dir / "data"
        with get_db() as conn:
            ds_ids = cfg_dataset_ids(cfg)
            ds_rows = [load_ds(conn, dsid) for dsid in ds_ids]
            cats = load_categories(conn, cfg["project_id"], ds_ids)
            name_by_id = {c["id"]: c["name"] for c in cats}
            imgs = []
            for ds in ds_rows:
                imgs.extend(load_images(conn, ds["id"]))
            ds_by_id = {ds["id"]: ds for ds in ds_rows}
            cls_ann = {}
            ph = ",".join("?" * len(ds_ids))
            for a in conn.execute(
                "SELECT * FROM annotations WHERE type='class' AND image_id IN "
                f"(SELECT id FROM images WHERE dataset_id IN ({ph}))", tuple(ds_ids)
            ).fetchall():
                cls_ann[a["image_id"]] = a

        copied = {"train": 0, "val": 0, "test": 0}
        for im in imgs:
            a = cls_ann.get(im["id"])
            if not a or a["category_id"] not in name_by_id:
                continue
            split = im["split"] if im["split"] in ("train", "val", "test") else "train"
            cls_dir = data_dir / split / name_by_id[a["category_id"]]
            cls_dir.mkdir(parents=True, exist_ok=True)
            ds = ds_by_id[im["dataset_id"]]
            src = Path(ds["root_path"]) / im["rel_path"]
            dst = cls_dir / f"{ds['id']}_{im['id']:07d}{src.suffix.lower()}"
            if not dst.exists():
                try:
                    shutil.copy2(src, dst)
                    copied[split] += 1
                except Exception as e:
                    self.log(f"[warn] 拷贝失败 {src}: {e}")
        if not any(data_dir.iterdir()):
            raise RuntimeError("没有找到带分类标注的图像，请先在标注工作台打图像分类标签")
        self.log(f"[data] train={copied['train']} val={copied['val']} test={copied['test']} "
                 f"classes={[c['name'] for c in cats]}")

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
            data=str(data_dir), epochs=cfg["epochs"], imgsz=imgsz_hw(cfg["imgsz"]),
            batch=cfg["batch"], device=resolve_device(cfg), project=str(yolo_project), name="train",
            exist_ok=True, workers=2, patience=20, verbose=True,
            fliplr=float(cfg.get("aug_flip", True)),
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
        results = model.val(data=str(data_dir), project=str(yolo_project), name="val",
                            exist_ok=True, device=resolve_device(cfg))
        metrics = {
            "top1_acc": round(float(results.top1), 4),
            "top5_acc": round(float(results.top5), 4),
        }
        (self.run_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        viz = self.run_dir / "viz"
        viz.mkdir(exist_ok=True)
        for name in ("confusion_matrix.png", "results.png"):
            src = val_dir / name
            if src.is_file():
                shutil.copy2(src, viz / name)
        self.log(f"[eval] {metrics}")


if __name__ == "__main__":
    run_engine(YoloClassifyEngine)

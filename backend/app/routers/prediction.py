"""模型预测明细补生成：对已 ready 模型用测试集重跑推理，生成 predictions.json + 标注图。

适用场景：旧任务（predictions.json 功能上线前训练的）没有结构化明细，
本服务用保存的权重对测试集重新推理，补生成，无需重新训练。
"""
import json
import random
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException

from app.config import RUNS_DIR
from app.db import get_conn
from app.engines.data_utils import cfg_dataset_ids, load_categories, load_ds, load_images, imgsz_hw, imgsz_wh

router = APIRouter()

CAT_BGR = [(83, 121, 78), (89, 87, 225), (79, 161, 89), (43, 142, 242),
           (161, 122, 176), (178, 183, 118), (72, 201, 237), (167, 157, 255)]

MAX_SAMPLE = 8  # 最多处理测试集前 N 张（与训练评估一致）


def _run_config(model_id: int):
    """取模型的 run 目录与训练配置。"""
    with get_conn() as conn:
        model = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        if not model:
            raise HTTPException(404, "模型不存在")
        task = conn.execute(
            "SELECT id FROM train_tasks WHERE model_id=? ORDER BY id DESC LIMIT 1", (model_id,)
        ).fetchone()
    if not task:
        raise HTTPException(400, "模型没有训练任务")
    run_dir = RUNS_DIR / str(task["id"])
    cfg_path = run_dir / "config.json"
    if not cfg_path.is_file():
        raise HTTPException(400, "训练配置缺失")
    return model, run_dir, json.loads(cfg_path.read_text(encoding="utf-8"))


def _test_images(cfg: dict):
    """测试集图像列表（带 ds 信息）。"""
    with get_db_conn() as conn:
        ds_ids = cfg_dataset_ids(cfg)
        ds_map = {ds["id"]: ds for ds in (load_ds(conn, d) for d in ds_ids)}
        test_imgs = []
        for dsid in ds_ids:
            test_imgs.extend(load_images(conn, dsid, split="test"))
    return ds_map, test_imgs


def get_db_conn():
    from app.engines.base import get_db
    return get_db()


def _sample(imgs, n=MAX_SAMPLE):
    if len(imgs) <= n:
        return imgs
    return random.Random(1).sample(list(imgs), n)


def _load_weight(run_dir: Path) -> Path:
    for name in ("best.pt", "best.pth"):
        p = run_dir / "weights" / name
        if p.is_file():
            return p
    raise HTTPException(400, "模型权重文件不存在")


# ---------------- 检测（YOLO） ----------------

def _predict_detect(model, run_dir, cfg):
    from ultralytics import YOLO
    ds_map, test_imgs = _test_images(cfg)
    with get_db_conn() as conn:
        cats = load_categories(conn, cfg["project_id"], cfg_dataset_ids(cfg))
    names = [c["name"] for c in cats]
    yolo = YOLO(str(_load_weight(run_dir)))
    pred_dir = run_dir / "viz" / "predictions"
    pred_dir.mkdir(parents=True, exist_ok=True)
    predictions = []
    for im in _sample(test_imgs):
        ds = ds_map[im["dataset_id"]]
        img_path = Path(ds["root_path"]) / im["rel_path"]
        res = yolo.predict(str(img_path), imgsz=imgsz_hw(cfg["imgsz"]), device=0, conf=0.25, verbose=False)
        r = res[0]
        img_show = r.orig_img.copy() if r.orig_img is not None else cv2.imread(str(img_path))
        img_w, img_h = im["width"], im["height"]
        entry = {"image": im["rel_path"], "size": [img_w, img_h], "boxes": []}
        if r.boxes is not None and len(r.boxes):
            for box in r.boxes:
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                label = names[cls] if cls < len(names) else f"class{cls}"
                entry["boxes"].append({
                    "category": label,
                    "confidence": round(conf, 4),
                    "score": round(conf, 4),
                    "bbox": [x1, y1, x2, y2],
                    "area_px": round(abs(x2 - x1) * abs(y2 - y1)),
                    "area_ratio": round(abs(x2 - x1) * abs(y2 - y1) / (img_w * img_h) * 100, 2),
                    "center": [round((x1 + x2) / 2, 1), round((y1 + y2) / 2, 1)],
                })
                color = CAT_BGR[cls % len(CAT_BGR)]
                cv2.rectangle(img_show, (x1, y1), (x2, y2), color, 3)
                txt = f"{label} {conf:.2f} | {abs(x2-x1)*abs(y2-y1)}px"
                (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                cv2.rectangle(img_show, (x1, max(0, y1 - th - 8)), (x1 + tw, y1), color, -1)
                cv2.putText(img_show, txt, (x1 + 2, max(th, y1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.imencode(".jpg", img_show)[1].tofile(pred_dir / f"{ds['id']}_{im['id']:07d}.jpg")
        predictions.append(entry)
    return predictions


# ---------------- 分割（SMP） ----------------

def _predict_segment(model, run_dir, cfg):
    import torch
    import segmentation_models_pytorch as smp
    from app.engines.data_utils import load_categories as _lc
    with get_db_conn() as conn:
        ds_ids = cfg_dataset_ids(cfg)
        cats = _lc(conn, cfg["project_id"], ds_ids)
    ds_map, test_imgs = _test_images(cfg)
    n_classes = len(cats)
    encoder = cfg["engine"].split("_")[-1] if cfg["engine"].startswith("unet") else "resnet50"
    arch = "DeepLabV3Plus" if cfg["engine"].startswith("deeplab") else "Unet"
    m = smp.create_model(arch, encoder_name=encoder, encoder_weights=None,
                         classes=n_classes + 1, in_channels=3)
    m.load_state_dict(torch.load(_load_weight(run_dir), map_location="cpu"))
    device = "cuda" if torch.cuda.is_available() else "cpu"
    m.to(device).eval()
    cat_names = {i + 1: c["name"] for i, c in enumerate(cats)}
    colors = {}
    for i, c in enumerate(cats):
        hx = c["color"].lstrip("#")
        colors[i + 1] = (int(hx[4:6], 16), int(hx[2:4], 16), int(hx[0:2], 16)) if len(hx) == 6 else (0, 180, 255)
    pred_dir = run_dir / "viz" / "predictions"
    pred_dir.mkdir(parents=True, exist_ok=True)
    predictions = []
    with torch.no_grad():
        for im in _sample(test_imgs):
            ds = ds_map[im["dataset_id"]]
            img_path = Path(ds["root_path"]) / im["rel_path"]
            img = cv2.imdecode(np.fromfile(str(img_path), dtype="uint8"), cv2.IMREAD_COLOR)
            if img is None:
                continue
            orig_h, orig_w = img.shape[:2]
            tw, th = imgsz_wh(cfg["imgsz"])
            resized = cv2.resize(img, (tw, th))
            x = torch.from_numpy(np.ascontiguousarray(resized.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]).to(device)
            pred = m(x).argmax(dim=1)[0].cpu().numpy().astype(np.uint8)
            pred = cv2.resize(pred, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)
            overlay = img.copy()
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
                    x0, y0, bw, bh = cv2.boundingRect(ct)
                    regions.append({
                        "category": cat_names.get(c_idx, f"class{c_idx}"),
                        "confidence": None,
                        "score": round(area / (orig_w * orig_h), 4),
                        "bbox": [x0, y0, x0 + bw, y0 + bh],
                        "area_px": round(area),
                        "area_ratio": round(area / (orig_w * orig_h) * 100, 2),
                        "center": [round(x0 + bw / 2, 1), round(y0 + bh / 2, 1)],
                    })
                    label = f"{cat_names.get(c_idx, '')} {area/(orig_w*orig_h)*100:.1f}%"
                    (tw2, th2), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                    cv2.rectangle(overlay, (x0, max(0, y0 - th2 - 6)), (x0 + tw2, y0), bgr, -1)
                    cv2.putText(overlay, label, (x0 + 2, max(th2, y0 - 2)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.imencode(".jpg", np.hstack([img, overlay]))[1].tofile(pred_dir / f"{ds['id']}_{im['id']:07d}.jpg")
            predictions.append({"image": im["rel_path"], "size": [orig_w, orig_h], "regions": regions})
    return predictions


# ---------------- 路由 ----------------

@router.post("/models/{model_id}/predict-details")
def generate_predict_details(model_id: int):
    """用已有权重对测试集重跑推理，补生成 predictions.json + 标注图。"""
    model, run_dir, cfg = _run_config(model_id)
    if model["status"] != "ready":
        raise HTTPException(400, f"模型状态为 {model['status']}，无法生成预测明细")
    task_type = model["task_type"]
    if task_type in ("detect",):
        predictions = _predict_detect(model, run_dir, cfg)
    elif task_type == "segment":
        predictions = _predict_segment(model, run_dir, cfg)
    elif task_type in ("us_segment", "classify"):
        raise HTTPException(400, "异常检测/分类暂不支持结构化预测明细（PatchCore 为热图，分类为整图标签）")
    else:
        raise HTTPException(400, f"任务类型 {task_type} 暂不支持")
    (run_dir / "predictions.json").write_text(
        json.dumps(predictions, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"images": len(predictions), "targets": sum(
        len(p.get("boxes") or p.get("regions") or []) for p in predictions)}

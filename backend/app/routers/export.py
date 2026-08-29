"""模型导出（ONNX）与推理预览。

- POST /models/{id}/export：训练产物 → ONNX（detect/classify 走 Ultralytics，segment 走 torch.onnx）
- POST /models/{id}/predict：选图 → ONNX 推理 → 叠加可视化图
"""
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException

from app.config import RUNS_DIR
from app.db import get_conn

router = APIRouter()


def _model_and_task(model_id: int):
    with get_conn() as conn:
        model = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        if not model:
            raise HTTPException(404, "模型不存在")
        task = conn.execute(
            "SELECT id FROM train_tasks WHERE model_id=? ORDER BY id DESC LIMIT 1", (model_id,)
        ).fetchone()
    run_dir = RUNS_DIR / str(task["id"]) if task else None
    return model, run_dir


def _weight_path(model, run_dir) -> Path:
    if not run_dir:
        raise HTTPException(400, "模型没有训练产物")
    for name in ("best.pt", "best.pth"):
        p = run_dir / "weights" / name
        if p.is_file():
            return p
    raise HTTPException(400, "模型权重文件不存在")


def _imgsz(model) -> int | list[int]:
    try:
        return json.loads(model["config"] or "{}").get("imgsz", 640)
    except Exception:
        return 640


def _imgsz_hw(imgsz) -> int | list[int]:
    """[w, h] → Ultralytics [h, w]。"""
    if isinstance(imgsz, (list, tuple)) and len(imgsz) == 2:
        return [int(imgsz[1]), int(imgsz[0])]
    return int(imgsz)


@router.post("/models/{model_id}/export")
def export_model(model_id: int):
    model, run_dir = _model_and_task(model_id)
    if model["status"] != "ready":
        raise HTTPException(400, f"模型状态为 {model['status']}，无法导出")
    if model["task_type"] == "us_segment" and model["engine"] == "patchcore":
        raise HTTPException(400, "PatchCore 为特征库模型，不支持 ONNX 导出（部署时使用 torch 编码器 + 特征库）")

    weight = _weight_path(model, run_dir)
    imgsz = _imgsz(model)

    if model["task_type"] in ("detect", "classify"):
        from ultralytics import YOLO
        yolo = YOLO(str(weight))
        # FP32：CPU 部署兼容（FP16 走 TensorRT 场景再转）
        onnx_path = yolo.export(format="onnx", half=False, imgsz=_imgsz_hw(imgsz), opset=12, verbose=False)
    elif model["task_type"] == "segment":
        import torch
        import segmentation_models_pytorch as smp
        encoder = model["engine"].split("_")[-1] if model["engine"].startswith("unet") else "resnet50"
        arch = "DeepLabV3Plus" if model["engine"].startswith("deeplab") else "Unet"
        # 以 checkpoint 实际输出通道数为准（可能与当前类别数不同，如训练时含「正常」）
        sd = torch.load(weight, map_location="cpu")
        total_cls = int(sd["segmentation_head.0.weight"].shape[0])
        m = smp.create_model(arch, encoder_name=encoder, encoder_weights=None,
                             classes=total_cls, in_channels=3)
        m.load_state_dict(sd)
        m.eval()
        onnx_path = run_dir / "weights" / "best.onnx"
        if isinstance(imgsz, (list, tuple)):
            ih, iw = int(imgsz[1]), int(imgsz[0])
        else:
            ih = iw = int(imgsz)
        dummy = torch.randn(1, 3, ih, iw)
        torch.onnx.export(
            m, dummy, str(onnx_path),
            input_names=["images"], output_names=["logits"],
            opset_version=12, dynamic_axes={"images": {0: "batch"}, "logits": {0: "batch"}},
            dynamo=False,  # torch>=2.9 默认新导出器需 onnxscript；legacy 导出器无需额外依赖
        )
    else:
        raise HTTPException(400, f"任务类型 {model['task_type']} 暂不支持导出")

    if isinstance(onnx_path, (list, tuple)):
        onnx_path = onnx_path[0]
    onnx_file = Path(onnx_path)
    if not onnx_file.is_file():
        raise HTTPException(500, f"导出失败：{onnx_file}")
    with get_conn() as conn:
        conn.execute("UPDATE models SET onnx_path=? WHERE id=?", (str(onnx_file.resolve()), model_id))
    return {"onnx_path": str(onnx_file.resolve()), "size_mb": round(onnx_file.stat().st_size / 1048576, 2)}


@router.post("/models/{model_id}/predict")
def predict_image(model_id: int, body: dict):
    image_id = body.get("image_id")
    if not image_id:
        raise HTTPException(400, "缺少 image_id")
    model, run_dir = _model_and_task(model_id)
    with get_conn() as conn:
        cats = list(conn.execute(
            "SELECT * FROM categories WHERE project_id=? ORDER BY id", (model["project_id"],)
        ).fetchall())
        # 任务数据集存在时，优先用数据集类别（类别按数据集隔离）
        cfg_path = run_dir / "config.json"
        if cfg_path.is_file():
            import json as _json
            try:
                _cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
                from app.engines.data_utils import cfg_dataset_ids
                _dsids = cfg_dataset_ids(_cfg)
                if _dsids:
                    ph = ",".join("?" * len(_dsids))
                    ds_cats = list(conn.execute(
                        f"SELECT * FROM categories WHERE dataset_id IN ({ph}) ORDER BY id", tuple(_dsids)
                    ).fetchall())
                    if ds_cats:
                        cats = ds_cats
            except Exception:
                pass
    # 类别索引必须与训练一致：排除常驻「正常」
    from app.engines.data_utils import defect_categories
    cats = defect_categories(cats)
    from app.engines.data_utils import image_path_of
    try:
        img_path = image_path_of(image_id)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(404, str(e))
    imgsz = _imgsz(model)

    viz_dir = run_dir / "viz" / "predict_onnx"
    viz_dir.mkdir(parents=True, exist_ok=True)
    out_path = viz_dir / f"{image_id}.jpg"

    if model["task_type"] == "segment" and model["onnx_path"]:
        _predict_segment(model, img_path, out_path, imgsz, cats)
    elif model["task_type"] == "segment":
        # 未导出 ONNX 时直接用 torch 权重推理（无需先导出即可预览）
        _predict_segment_torch(model, img_path, out_path, imgsz, cats, run_dir)
    elif model["task_type"] == "patchcore" or (model["task_type"] == "us_segment"):
        _predict_patchcore(model, img_path, out_path, run_dir)
    elif model["task_type"] in ("detect", "classify"):
        _predict_ultralytics(model, img_path, out_path, imgsz)
    else:
        raise HTTPException(400, f"任务类型 {model['task_type']} 暂不支持推理预览")

    task_id = run_dir.name
    return {"image_url": f"/runs/{task_id}/viz/predict_onnx/{image_id}.jpg"}


def _predict_ultralytics(model, img_path: Path, out_path: Path, imgsz: int):
    """detect/classify：ONNX（已导出）或 torch 权重推理，Ultralytics 画框。"""
    from ultralytics import YOLO
    from app.engines.data_utils import resolve_device
    src = model["onnx_path"] or (RUNS_DIR / str(_task_dir_of(model)) / "weights" / "best.pt")
    yolo = YOLO(str(src))
    res = yolo.predict(str(img_path), imgsz=_imgsz_hw(imgsz), conf=0.25, verbose=False, device=resolve_device())
    if res and len(res[0].boxes):
        res[0].save(str(out_path))
    else:
        # 无检测结果也保存原图（叠加空框）
        img = cv2.imdecode(np.fromfile(str(img_path), dtype="uint8"), cv2.IMREAD_COLOR)
        cv2.imencode(".jpg", img)[1].tofile(out_path)


def _task_dir_of(model) -> Path:
    _, run_dir = _model_and_task(model["id"])
    return run_dir


def _predict_segment_torch(model, img_path: Path, out_path: Path, imgsz: int | list[int], cats, run_dir: Path):
    """segment（未导出 ONNX）：torch 权重直接推理预览。

    类数以 checkpoint 实际输出通道为准（可能与当前类别计数不同），
    对含/不含「正常」的历史模型均兼容。
    """
    import torch
    import segmentation_models_pytorch as smp

    weight = _weight_path(model, run_dir)
    sd = torch.load(weight, map_location="cpu")
    total_cls = int(sd["segmentation_head.0.weight"].shape[0])
    encoder = model["engine"].split("_")[-1] if model["engine"].startswith("unet") else "resnet50"
    arch = "DeepLabV3Plus" if model["engine"].startswith("deeplab") else "Unet"
    m = smp.create_model(arch, encoder_name=encoder, encoder_weights=None,
                         classes=total_cls, in_channels=3)
    m.load_state_dict(sd)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    m.to(device).eval()

    img = cv2.imdecode(np.fromfile(str(img_path), dtype="uint8"), cv2.IMREAD_COLOR)
    orig_h, orig_w = img.shape[:2]
    if isinstance(imgsz, (list, tuple)):
        ih, iw = int(imgsz[1]), int(imgsz[0])
    else:
        ih = iw = int(imgsz)
    resized = cv2.resize(img, (iw, ih))
    x = torch.from_numpy(np.ascontiguousarray(resized.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]).to(device)
    with torch.no_grad():
        pred = m(x).argmax(dim=1)[0].cpu().numpy().astype(np.uint8)
    pred = cv2.resize(pred, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)

    def _bgr(hex_color):
        h = hex_color.lstrip("#")
        return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)) if len(h) == 6 else (0, 180, 255)
    overlay = img.copy()
    for i, c in enumerate(cats):
        overlay[pred == i + 1] = _bgr(c["color"])
    cv2.imencode(".jpg", np.hstack([img, overlay]))[1].tofile(out_path)


def _predict_segment(model, img_path: Path, out_path: Path, imgsz: int, cats):
    """segment：ONNX 会话推理 → argmax → 类别色叠加。"""
    import onnxruntime as ort
    import torch.nn.functional as F

    img = cv2.imdecode(np.fromfile(str(img_path), dtype="uint8"), cv2.IMREAD_COLOR)
    orig_h, orig_w = img.shape[:2]
    if isinstance(imgsz, (list, tuple)):
        ih, iw = int(imgsz[1]), int(imgsz[0])
    else:
        ih = iw = int(imgsz)
    resized = cv2.resize(img, (iw, ih))
    x = resized.astype(np.float32) / 255.0
    x = np.ascontiguousarray(x.transpose(2, 0, 1))[None]

    sess = ort.InferenceSession(model["onnx_path"], providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    logits = sess.run(None, {"images": x})[0]  # (1, C, H, W)
    pred = np.argmax(logits, axis=1)[0].astype(np.uint8)
    pred = cv2.resize(pred, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)

    def _bgr(hex_color):
        h = hex_color.lstrip("#")
        return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)) if len(h) == 6 else (0, 180, 255)
    overlay = img.copy()
    for i, c in enumerate(cats):
        overlay[pred == i + 1] = _bgr(c["color"])
    cv2.imencode(".jpg", np.hstack([img, overlay]))[1].tofile(out_path)


def _predict_patchcore(model, img_path: Path, out_path: Path, run_dir):
    """PatchCore：torch 编码器 + 特征库 → 热图（无 ONNX）。"""
    import torch
    from app.engines.anomaly import _extract_features, _load_model

    bank = np.load(run_dir / "bank.npy")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    enc, _ = _load_model()
    enc.to(device).eval()
    img = cv2.imdecode(np.fromfile(img_path, dtype="uint8"), cv2.IMREAD_COLOR)
    feat, _ = _extract_features(enc, img, device)
    dist = torch.cdist(torch.from_numpy(feat).to(device), torch.from_numpy(bank).to(device)).min(dim=1).values
    h = int(np.sqrt(len(dist)))
    hm = dist.cpu().numpy()[: h * h].reshape(h, h)
    hm = cv2.resize(hm, (img.shape[1], img.shape[0]))
    hm = cv2.normalize(hm, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    heat = cv2.applyColorMap(hm, cv2.COLORMAP_JET)
    cv2.imencode(".jpg", cv2.addWeighted(img, 0.6, heat, 0.4, 0))[1].tofile(out_path)

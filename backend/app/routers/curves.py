"""训练曲线与模型结果展示。

引擎输出约定（每个训练任务一个目录 data/runs/{task_id}/）：
- results.csv   每 epoch 一行，首行表头。公共列：epoch, train_loss, val_loss,
                mAP50, mAP50-95, precision, recall, accuracy, iou（按任务类型填充）
- metrics.json  最终评估指标字典
- viz/          评估可视化图片（PR_curve.png, confusion_matrix.png, predictions/*.jpg）
"""
import csv
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.db import get_conn

router = APIRouter()

RUNS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "runs"


def _task_run_dir(task_id: int) -> Path:
    return RUNS_DIR / str(task_id)


@router.get("/tasks/{task_id}/curve")
def task_curve(task_id: int):
    """返回 results.csv 的全部数据，前端按列画曲线。"""
    csv_path = _task_run_dir(task_id) / "results.csv"
    if not csv_path.is_file():
        return {"columns": [], "rows": [], "exists": False}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        rows = []
        for row in reader:
            if row and row[0].strip():
                rows.append([_num(v) for v in row])
    return {"columns": header or [], "rows": rows, "exists": True}


def _num(v: str):
    try:
        return float(v)
    except ValueError:
        return v


@router.get("/models/{model_id}/result")
def model_result(model_id: int):
    """模型最终评估：指标 + 可视化图片列表。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, dataset_id, status, created_at FROM train_tasks "
            "WHERE model_id = ? ORDER BY id DESC LIMIT 1",
            (model_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "该模型还没有训练任务")
        task_id = row["id"]
    run_dir = _task_run_dir(task_id)
    metrics = {}
    metrics_path = run_dir / "metrics.json"
    if metrics_path.is_file():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    # 结构化预测明细（评估时生成：类型/位置/置信度/面积）
    predictions = []
    pred_path = run_dir / "predictions.json"
    if pred_path.is_file():
        try:
            predictions = json.loads(pred_path.read_text(encoding="utf-8"))
        except Exception:
            predictions = []
    viz = []
    viz_dir = run_dir / "viz"
    if viz_dir.is_dir():
        for p in sorted(viz_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                viz.append(f"/runs/{task_id}/viz/{p.relative_to(viz_dir).as_posix()}")
    return {
        "task_id": task_id,
        "status": row["status"],
        "metrics": metrics,
        "predictions": predictions,
        "viz": viz,
        "weights": str(run_dir / "weights" / "best.pt") if (run_dir / "weights" / "best.pt").is_file() else "",
    }

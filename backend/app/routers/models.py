"""模型库：内置训练产物与外部导入模型统一管理。

导入模型：把训练好的权重（ONNX 优先，也支持 torch 等）注册进模型库，
记录任务类型/架构/输入尺寸/归一化/类别映射，使其可参与评估与推理预览。
自定义训练引擎通过 plugins/engines/ 目录自动发现（见 ENGINES.md）。
"""
import json
from pathlib import Path

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.db import get_conn

class ModelImportRequest(BaseModel):
    project_id: int
    name: str = Field(min_length=1, max_length=64)
    task_type: str  # detect/segment/classify/us_classify/us_segment
    framework: str = "onnx"  # torch/onnx/tensorrt
    architecture: str = ""
    file_path: str = Field(min_length=1)
    input_size: list[int] = [640, 640]  # [w, h]
    normalize: str = "none"  # none/imagenet/自定义 mean,std 存 config
    categories: list[str] = []
    preprocess_pipeline_id: int | None = None

router = APIRouter()

TASK_TYPES = {"detect", "segment", "classify", "us_classify", "us_segment"}


def _read_params(file_path: Path) -> float:
    """尝试读取参数量（百万）。torch 可用时读取 checkpoint；否则返回 0。"""
    try:
        import torch
        if file_path.suffix.lower() in {".pt", ".pth"}:
            ckpt = torch.load(file_path, map_location="cpu", weights_only=False)
            model = ckpt.get("model") or ckpt
            if hasattr(model, "parameters"):
                return round(sum(p.numel() for p in model.parameters()) / 1e6, 2)
            sd = model if isinstance(model, dict) and "layers" in str(type(model)) else None
            if isinstance(ckpt, dict):
                for key in ("state_dict", "model_state_dict"):
                    if key in ckpt and isinstance(ckpt[key], dict):
                        sd = ckpt[key]
                        break
            if isinstance(sd, dict):
                return round(sum(v.numel() for v in sd.values() if hasattr(v, "numel")) / 1e6, 2)
    except Exception:
        pass
    return 0.0


@router.get("/projects/{project_id}/models")
def list_models(project_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT m.*, t.id AS task_id, t.status AS task_status, t.progress
            FROM models m
            LEFT JOIN train_tasks t ON t.model_id = m.id
                AND t.id = (SELECT MAX(id) FROM train_tasks WHERE model_id = m.id)
            WHERE m.project_id = ?
            ORDER BY m.created_at DESC
            """,
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("/models/import", status_code=201)
def import_model(body: ModelImportRequest):
    if body.task_type not in TASK_TYPES:
        raise HTTPException(400, f"任务类型必须是 {sorted(TASK_TYPES)} 之一")
    path = Path(body.file_path.strip())
    if not path.is_file():
        raise HTTPException(400, f"文件不存在：{path}")
    if path.suffix.lower() == ".onnx" and body.framework == "torch":
        body = body.model_copy(update={"framework": "onnx"})
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (body.project_id,)).fetchone():
            raise HTTPException(404, "项目不存在")
        if body.preprocess_pipeline_id is not None and not conn.execute(
            "SELECT 1 FROM preprocess_pipelines WHERE id = ?", (body.preprocess_pipeline_id,)
        ).fetchone():
            raise HTTPException(400, "预处理管线不存在")
        try:
            cur = conn.execute(
                """INSERT INTO models (project_id, name, task_type, engine, framework, architecture,
                                       config, weights_path, status, params_m, file_size)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)""",
                (
                    body.project_id, body.name.strip(), body.task_type,
                    f"imported:{body.framework}", body.framework, body.architecture,
                    json.dumps({
                        "input_size": body.input_size,
                        "normalize": body.normalize,
                        "categories": body.categories,
                        "preprocess_pipeline_id": body.preprocess_pipeline_id,
                    }, ensure_ascii=False),
                    str(path.resolve()), _read_params(path), path.stat().st_size,
                ),
            )
        except Exception:
            raise HTTPException(400, f"模型名「{body.name}」已存在")
        return dict(conn.execute("SELECT * FROM models WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.get("/models/{model_id}")
def get_model(model_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
        if not row:
            raise HTTPException(404, "模型不存在")
        return dict(row)


@router.post("/models/{model_id}/best")
def mark_best(model_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
        if not row:
            raise HTTPException(404, "模型不存在")
        conn.execute("UPDATE models SET is_best = 0 WHERE project_id = ?", (row["project_id"],))
        conn.execute("UPDATE models SET is_best = 1 WHERE id = ?", (model_id,))
        return {"ok": True}


@router.delete("/models/{model_id}", status_code=204)
def delete_model(model_id: int):
    # 清理训练产物目录（models 删除时 train_tasks 级联删除，runs 文件需手动清）
    task_ids = []
    with get_conn() as conn:
        task_ids = [r[0] for r in conn.execute(
            "SELECT id FROM train_tasks WHERE model_id = ?", (model_id,)).fetchall()]
        conn.execute("DELETE FROM models WHERE id = ?", (model_id,))
        if conn.total_changes == 0:
            raise HTTPException(404, "模型不存在")
    from app.config import RUNS_DIR
    import shutil
    for tid in task_ids:
        shutil.rmtree(RUNS_DIR / str(tid), ignore_errors=True)

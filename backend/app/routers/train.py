"""训练任务：提交、列表、详情、日志增量、停止。"""
import json
import re
from pathlib import Path

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.db import get_conn
from app.config import RUNS_DIR  # 统一来自 config（模块化：避免自行推导在冻结版下指向错误目录）
from app.services import train_queue

class TrainCreate(BaseModel):
    project_id: int
    name: str = Field(min_length=1, max_length=64)
    task_type: str = "detect"
    engine: str
    dataset_ids: list[int] = Field(min_length=1)  # 支持多数据集混合训练
    epochs: int = Field(default=100, ge=1, le=2000)
    imgsz: int | list[int] = 640  # int 或 [w, h]（非正方形输入）
    batch: int = Field(default=16, ge=1, le=256)
    custom_arch: str = ""
    preprocess_pipeline_id: int | None = None
    aug_pipeline_id: int | None = None  # 增强管线（分割引擎应用）
    aug_flip: bool = True              # Ultralytics 内置增强开关（detect/classify）
    aug_mosaic: float = 1.0
    aug_mixup: float = 0.0
    aug_hsv: float = 0.015
    device: str | None = None          # 训练设备（"0"/"cpu"…），缺省自动检测

router = APIRouter()


@router.get("/engines")
def list_engines():
    """引擎配置（前端训练表单动态渲染）。"""
    return train_queue.engines_info()


@router.post("/train", status_code=201)
def create_train(body: TrainCreate):
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (body.project_id,)).fetchone():
            raise HTTPException(404, "项目不存在")
        for dsid in body.dataset_ids:
            if not conn.execute("SELECT 1 FROM datasets WHERE id=?", (dsid,)).fetchone():
                raise HTTPException(404, f"数据集 {dsid} 不存在")
        n_cats = conn.execute(
            "SELECT COUNT(*) FROM categories WHERE dataset_id IN (%s)" %
            ",".join("?" * len(body.dataset_ids)), body.dataset_ids
        ).fetchone()[0]
        if n_cats < 1:
            raise HTTPException(400, "所选数据集还没有缺陷类别，请先在数据集中定义类别")
        if body.engine not in train_queue.available_engines():
            raise HTTPException(400, f"引擎「{body.engine}」不可用，可选：{train_queue.available_engines()}")
        if not train_queue.check_engine(body.engine, body.task_type):
            raise HTTPException(400, f"引擎「{body.engine}」与任务类型「{body.task_type}」不匹配")
        # 模型名去重（源头治理）：去掉连续「(重试)」后缀，若项目内已存在同名则追加版本号，
        # 避免反复重试导致「xx (重试) (重试) (重试)…」冗长命名。
        base = re.sub(r"( \(重试\))+", "", body.name.strip())
        name = base
        i = 2
        while conn.execute("SELECT 1 FROM models WHERE project_id=? AND name=? LIMIT 1",
                           (body.project_id, name)).fetchone():
            name = f"{base} v{i}"
            i += 1
        cur = conn.execute(
            """INSERT INTO models (project_id, name, task_type, engine, config)
               VALUES (?, ?, ?, ?, ?)""",
            (body.project_id, name, body.task_type, body.engine,
             json.dumps({"epochs": body.epochs, "imgsz": body.imgsz, "batch": body.batch,
                         "custom_arch": body.custom_arch}, ensure_ascii=False)),
        )
        model_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO train_tasks (model_id, dataset_id) VALUES (?, ?)",
            (model_id, body.dataset_ids[0]),
        )
        task_id = cur.lastrowid

    run_dir = RUNS_DIR / str(task_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(
        json.dumps({
            "task_id": task_id, "model_id": model_id,
            "project_id": body.project_id, "dataset_ids": body.dataset_ids,
            "engine": body.engine, "custom_arch": body.custom_arch,
            "epochs": body.epochs, "imgsz": body.imgsz, "batch": body.batch,
            "preprocess_pipeline_id": body.preprocess_pipeline_id,
            "aug_pipeline_id": body.aug_pipeline_id,
            "aug_flip": body.aug_flip, "aug_mosaic": body.aug_mosaic,
            "aug_mixup": body.aug_mixup, "aug_hsv": body.aug_hsv,
            "device": body.device,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    train_queue.submit(task_id)
    return {"task_id": task_id, "model_id": model_id}


@router.get("/projects/{project_id}/tasks")
def list_tasks(project_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT t.*, m.name AS model_name, m.engine, m.task_type
            FROM train_tasks t JOIN models m ON m.id = t.model_id
            WHERE m.project_id = ?
            ORDER BY t.id DESC
            """,
            (project_id,),
        ).fetchall()
        items = []
        for r in rows:
            item = dict(r)
            cfg_path = RUNS_DIR / str(r["id"]) / "config.json"
            if cfg_path.is_file():
                try:
                    item["config"] = json.loads(cfg_path.read_text(encoding="utf-8"))
                except Exception:
                    item["config"] = None
            items.append(item)
        return items


@router.get("/tasks/{task_id}")
def task_detail(task_id: int):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT t.*, m.name AS model_name, m.task_type, m.engine, m.id AS model_id
            FROM train_tasks t JOIN models m ON m.id = t.model_id WHERE t.id = ?
            """,
            (task_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "任务不存在")
        return dict(row)


@router.get("/tasks/{task_id}/log")
def task_log(task_id: int, offset: int = 0):
    """增量日志：前端传上次的 offset，返回新行。"""
    log_path = RUNS_DIR / str(task_id) / "train.log"
    if not log_path.is_file():
        return {"offset": 0, "lines": []}
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        lines = f.read().splitlines()
        new_offset = f.tell()
    return {"offset": new_offset, "lines": lines}


@router.post("/tasks/{task_id}/stop")
def stop_task(task_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT status FROM train_tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(404, "任务不存在")
        if row["status"] not in ("queued", "running"):
            return {"ok": False, "message": f"任务已结束（{row['status']}）"}
    if train_queue.stop(task_id):
        return {"ok": True, "message": "已发送停止信号"}
    return {"ok": False, "message": "任务不在运行中"}

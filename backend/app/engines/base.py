"""引擎公共框架。

新引擎接入三步：
1. 继承 EngineBase，实现 run()（数据准备 + 训练 + 评估），
   在 run() 中设置 self.weights_path / self.params_m / self.arch
2. 在 train_queue.ENGINE_REGISTRY 注册
3. 前端通过 /api/engines 自动获取配置，无需改前端

状态管理、异常处理、成功收尾由 start() 模板方法统一处理。
"""
import csv
import json
import os
import shutil
import sqlite3
import sys
import traceback
from pathlib import Path

from app.config import BACKEND_DIR, DB_PATH, RUNS_DIR


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def read_params_m(wfile: Path) -> float:
    """从 torch checkpoint 读参数量（百万）。"""
    try:
        import torch
        ckpt = torch.load(wfile, map_location="cpu", weights_only=False)
        model = ckpt.get("model") if isinstance(ckpt, dict) else None
        if model is not None and hasattr(model, "parameters"):
            return round(sum(p.numel() for p in model.parameters()) / 1e6, 2)
        if isinstance(ckpt, dict):
            for key in ("state_dict", "model_state_dict"):
                if key in ckpt and isinstance(ckpt[key], dict):
                    return round(sum(v.numel() for v in ckpt[key].values() if hasattr(v, "numel")) / 1e6, 2)
    except Exception:
        pass
    return 0.0


def sync_ultralytics_curve(cfg: dict, src: Path, dst: Path, col_map: dict, cols: list,
                           stop_evt: "threading.Event", poll_s: float = 2.0):
    """轮询 Ultralytics results.csv，映射为平台统一列并更新进度。"""
    import threading
    import time

    def once():
        if not src.is_file():
            return
        with open(src, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        if len(lines) < 2:
            return
        header = [h.strip() for h in lines[0].split(",")]
        idx = {h: i for i, h in enumerate(header)}
        cm = {"epoch": "epoch"}
        for sc, dc in col_map.items():
            if sc in idx:
                cm[sc] = dc
        rows = []
        for ln in lines[1:]:
            cells = ln.split(",")
            row = {dc: cells[idx[sc]] for sc, dc in cm.items() if idx[sc] < len(cells)}
            if row:
                rows.append(row)
        if not rows:
            return
        with open(dst, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                w.writerow([r.get(c, "") for c in cols])
        try:
            progress = float(rows[-1].get("epoch", 0)) / cfg["epochs"]
        except (ValueError, ZeroDivisionError):
            progress = 0.0
        with get_db() as conn:
            conn.execute("UPDATE train_tasks SET progress=? WHERE id=?", (min(progress, 0.99), cfg["task_id"]))

    while not stop_evt.is_set():
        time.sleep(poll_s)
        once()
    once()


class EngineBase:
    """引擎基类：模板方法 start() 统一状态/异常/收尾，子类实现 run()。"""

    engine_id = "base"
    task_type = "detect"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.task_id = cfg["task_id"]
        self.model_id = cfg["model_id"]
        self.run_dir = RUNS_DIR / str(self.task_id)
        self.weights_path: Path | None = None
        self.params_m = 0.0
        self.arch = cfg.get("engine", self.engine_id)

    def log(self, msg: str):
        print(msg, flush=True)

    def set_progress(self, p: float):
        with get_db() as conn:
            conn.execute("UPDATE train_tasks SET progress=? WHERE id=?", (min(p, 0.99), self.task_id))

    def write_curve(self, rows: list, cols: list | None = None):
        cols = cols or self.curve_cols
        with open(self.run_dir / "results.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)

    def save_weights(self, src: Path, name: str = "best.pt") -> Path:
        wdir = self.run_dir / "weights"
        wdir.mkdir(exist_ok=True)
        shutil.copy2(src, wdir / name)
        return wdir / name

    def run(self):
        """子类实现：数据准备 + 训练 + 评估。结束时设置 self.weights_path 等。"""
        raise NotImplementedError

    def _finish_success(self):
        # 把 metrics.json（引擎评估写出）同步回 models.metrics，训练效果页使用
        metrics = {}
        mfile = self.run_dir / "metrics.json"
        if mfile.is_file():
            try:
                metrics = json.loads(mfile.read_text(encoding="utf-8"))
            except Exception:
                metrics = {}
        with get_db() as conn:
            conn.execute(
                "UPDATE train_tasks SET status='success', progress=1, "
                "finished_at=datetime('now','localtime') WHERE id=?",
                (self.task_id,),
            )
            conn.execute(
                "UPDATE models SET status='ready', finished_at=datetime('now','localtime'), "
                "file_size=?, params_m=?, architecture=?, metrics=? WHERE id=?",
                (self.weights_path.stat().st_size if self.weights_path and self.weights_path.is_file() else 0,
                 self.params_m, self.arch, json.dumps(metrics, ensure_ascii=False), self.model_id),
            )

    def _fail(self, err: str):
        with get_db() as conn:
            conn.execute(
                "UPDATE train_tasks SET status='failed', error=?, finished_at=datetime('now','localtime') WHERE id=?",
                (err[-2000:], self.task_id),
            )
            conn.execute("UPDATE models SET status='failed' WHERE id=?", (self.model_id,))

    def start(self):
        """模板方法：状态 → run() → 成功收尾；异常 → failed。"""
        with get_db() as conn:
            conn.execute(
                "UPDATE train_tasks SET status='running', pid=?, started_at=datetime('now','localtime') WHERE id=?",
                (os.getpid(), self.task_id),
            )
            conn.execute("UPDATE models SET status='training' WHERE id=?", (self.model_id,))
        try:
            self.run()
            self._finish_success()
            self.log("[train] done")
        except Exception:
            err = traceback.format_exc()
            self.log(err)
            self._fail(err)
            sys.exit(1)


def run_engine(engine_cls):
    """引擎 CLI 入口：python -m app.engines.xxx --config runs/{id}/config.json"""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    engine_cls(cfg).start()

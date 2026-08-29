"""训练队列：单 GPU 串行执行训练任务。

引擎以独立子进程运行（subprocess + sys.executable，锁死解释器避免 Windows
PATH 解析到 uv shim），日志写入 runs/{task_id}/train.log。
引擎清单来自 app.engines.registry（内置 + plugins/engines 插件发现）。
"""
import json
import os
import subprocess
import sys
import threading

from app.config import BACKEND_DIR, RUNS_DIR
from app.db import get_conn
from app.engines.registry import get_all_engines

_lock = threading.Lock()
_queue: list[int] = []
_procs: dict[int, subprocess.Popen] = {}
_running: int | None = None


def available_engines() -> list[str]:
    return sorted(get_all_engines())


def check_engine(engine: str, task_type: str) -> bool:
    """校验引擎存在且与任务类型匹配。"""
    from app.engines.registry import check_engine as _check
    return _check(engine, task_type)


def engines_info() -> list[dict]:
    """前端引擎表单配置。"""
    from app.engines.registry import engines_info as _info
    return _info()


def submit(task_id: int) -> None:
    with _lock:
        _queue.append(task_id)
    _pump()


def stop(task_id: int) -> bool:
    """停止任务：queued（排队中）→ 出队标 stopped；running → kill 子进程。"""
    with _lock:
        if task_id in _queue:
            _queue.remove(task_id)
            queued = True
        else:
            queued = False
            p = _procs.get(task_id)
    if queued:
        with get_conn() as conn:
            conn.execute(
                "UPDATE train_tasks SET status='stopped', finished_at=datetime('now','localtime') WHERE id=?",
                (task_id,),
            )
            row = conn.execute("SELECT model_id FROM train_tasks WHERE id=?", (task_id,)).fetchone()
            if row:
                conn.execute("UPDATE models SET status='failed' WHERE id=?", (row["model_id"],))
        return True
    if p and p.poll() is None:
        p.kill()
        with get_conn() as conn:
            conn.execute(
                "UPDATE train_tasks SET status='stopped', finished_at=datetime('now','localtime') WHERE id=?",
                (task_id,),
            )
            row = conn.execute("SELECT model_id FROM train_tasks WHERE id=?", (task_id,)).fetchone()
            if row:
                conn.execute("UPDATE models SET status='failed' WHERE id=?", (row["model_id"],))
        return True
    return False


def running_task() -> int | None:
    with _lock:
        return _running


def _kill_orphan(pid: int):
    """Windows 下强杀孤儿进程（taskkill 不存在时静默忽略）。"""
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True, timeout=5)
    except Exception:
        pass


def _recover():
    """服务重启后恢复：queued 任务重新入队，running 任务标记失败（引擎进程已丢失）。
    同时把 running 任务对应的模型置为 failed，避免 models 状态永远卡在 training。
    修复：清理孤儿引擎子进程（旧进程仍占 GPU 且可能反向写回 success）。
    """
    queued = []
    orphans = []
    with get_conn() as conn:
        queued = [r[0] for r in conn.execute(
            "SELECT id FROM train_tasks WHERE status='queued' ORDER BY id").fetchall()]
        orphans = [(r[0], r["pid"]) for r in conn.execute(
            "SELECT id, pid FROM train_tasks WHERE status='running'").fetchall()]
        conn.execute(
            "UPDATE train_tasks SET status='failed', error='服务重启，任务中断', "
            "finished_at=datetime('now','localtime') WHERE status='running'")
        # 任务状态与模型状态同步（模型不再滞留 training）
        conn.execute(
            "UPDATE models SET status='failed' WHERE id IN ("
            "SELECT model_id FROM train_tasks WHERE status='failed' AND error='服务重启，任务中断')")
    for tid, pid in orphans:
        if pid:
            _kill_orphan(pid)
    for tid in queued:
        submit(tid)


def _pump() -> None:
    global _running
    with _lock:
        if _running is not None or not _queue:
            return
        _running = _queue.pop(0)
    threading.Thread(target=_run, args=(_running,), daemon=True).start()


def _run(task_id: int) -> None:
    global _running
    run_dir = RUNS_DIR / str(task_id)
    cfg_path = run_dir / "config.json"

    def _finish_failed(reason: str):
        with get_conn() as conn:
            conn.execute(
                "UPDATE train_tasks SET status='failed', error=?, finished_at=datetime('now','localtime') WHERE id=?",
                (reason, task_id),
            )

    try:
        if not cfg_path.is_file():
            _finish_failed("训练配置缺失")
        else:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            module = get_all_engines().get(cfg.get("engine", ""), {}).get("module")
            if not module:
                _finish_failed(f"引擎「{cfg.get('engine')}」尚未实现")
            else:
                # 日志轮转：上次任务的超大日志先清空（当前任务从头写）
                log_path = run_dir / "train.log"
                if log_path.is_file() and log_path.stat().st_size > 5 * 1024 * 1024:
                    log_path.write_text("", encoding="utf-8")
                with open(log_path, "a", encoding="utf-8") as logf:
                    # 子进程环境：跳过 albumentations 版本检查（离线环境会卡超时）、HF 离线
                    # 注意：不加 -u（无缓冲会拖慢训练），引擎关键日志用 flush=True 已即时落盘
                    env = dict(os.environ)
                    env["NO_ALBUMENTATIONS_UPDATE"] = "1"
                    env.setdefault("HF_HUB_OFFLINE", "1")
                    if getattr(sys, "frozen", False):
                        # 冻结版：无法 python -m，改走 --engine-runner 子进程模式
                        cmd = [sys.executable, "--engine-runner", module, str(cfg_path)]
                    else:
                        cmd = [sys.executable, "-m", module, "--config", str(cfg_path)]
                    p = subprocess.Popen(
                        cmd,
                        stdout=logf, stderr=subprocess.STDOUT,
                        cwd=BACKEND_DIR, creationflags=subprocess.CREATE_NO_WINDOW,
                        env=env,
                    )
                    with _lock:
                        _procs[task_id] = p
                    p.wait()
                    with _lock:
                        _procs.pop(task_id, None)
                    # P1 修复：子进程异常退出（非 0）时引擎可能在 start() 前崩溃
                    # （import 错误等），状态会永久卡 running——这里兜底标记 failed
                    if p.returncode != 0:
                        _finish_failed(f"训练进程异常退出（code {p.returncode}），详见 train.log")
    except Exception as e:
        _finish_failed(f"队列异常: {str(e)[:500]}")
    finally:
        with _lock:
            _running = None
        _pump()


_recover()

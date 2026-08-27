"""仪表盘聚合接口：首页统计概览。

GET /api/dashboard 返回：
- totals: 项目/数据集/类别/图像/模型/任务 计数
- task_status: 任务状态分布（running/queued/success/failed/stopped）
- recent_tasks: 最近若干任务（含项目名）
- best_models: 各项目最佳模型
- alerts: 需要关注的告警（模型卡训练、任务失败等）
"""
from fastapi import APIRouter

from app.db import get_conn

router = APIRouter()


@router.get("/dashboard")
def dashboard():
    with get_conn() as conn:
        totals = {
            "projects": conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
            "datasets": conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0],
            "categories": conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0],
            "images": conn.execute("SELECT COUNT(*) FROM images").fetchone()[0],
            "models": conn.execute("SELECT COUNT(*) FROM models").fetchone()[0],
            "tasks": conn.execute("SELECT COUNT(*) FROM train_tasks").fetchone()[0],
        }

        task_status = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) n FROM train_tasks GROUP BY status")}

        recent = [dict(r) for r in conn.execute(
            """SELECT t.id, t.status, t.progress, t.created_at, t.started_at,
                      m.name AS model_name, m.engine, m.task_type, m.project_id, p.name AS project_name
               FROM train_tasks t
               JOIN models m ON m.id = t.model_id
               JOIN projects p ON p.id = m.project_id
               ORDER BY t.id DESC LIMIT 8""")]

        # 各项目最佳模型（按 is_best 优先，其次按时间倒序取第一个 ready/训练成功的）
        best_rows = conn.execute(
            """SELECT m.id AS model_id, m.name, m.task_type, m.engine, m.metrics,
                      m.is_best, m.project_id, p.name AS project_name
               FROM models m JOIN projects p ON p.id = m.project_id
               WHERE m.status='ready'
               ORDER BY m.is_best DESC, m.created_at DESC"""
        ).fetchall()
        best_seen = set()
        best_models = []
        for r in best_rows:
            pid = r["project_id"]
            if pid in best_seen:
                continue
            best_seen.add(pid)
            best_models.append(dict(r))

        # 告警：模型状态为 training/running 但没有对应 running/queued 任务（状态不一致）
        alerts = []
        for r in conn.execute(
            """SELECT m.id, m.name, m.project_id, p.name AS project_name FROM models m
               JOIN projects p ON p.id = m.project_id
               WHERE m.status='training' AND NOT EXISTS (
                    SELECT 1 FROM train_tasks t WHERE t.model_id = m.id
                    AND t.status IN ('queued','running'))"""
        ):
            alerts.append({"level": "error", "kind": "model_stuck",
                           "message": f"模型「{r['name']}」状态异常（training 但无运行任务），建议标记为失败",
                           "model_id": r["id"], "project_id": r["project_id"]})
        for r in conn.execute("SELECT COUNT(*) n FROM train_tasks WHERE status='failed'"):
            if r["n"]:
                alerts.append({"level": "warning", "kind": "failed_tasks",
                               "message": f"有 {r['n']} 个训练任务失败，请到训练中心查看日志"})
        for r in conn.execute("SELECT COUNT(*) n FROM train_tasks WHERE status='running'"):
            if r["n"]:
                alerts.append({"level": "info", "kind": "running",
                               "message": f"{r['n']} 个训练任务正在运行"})

    return {"totals": totals, "task_status": task_status,
            "recent_tasks": recent, "best_models": best_models, "alerts": alerts}

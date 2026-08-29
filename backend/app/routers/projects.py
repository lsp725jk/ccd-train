"""项目与缺陷类别管理。"""
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from app.db import get_conn

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    plan: str = ""  # 场景方案 JSON（应用场景方案时写入）

class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    description: Optional[str] = None

class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    color: str = "#4E79A7"

router = APIRouter()

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@router.get("/projects")
def list_projects():
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT p.*, COUNT(DISTINCT d.id) AS dataset_count,
                   (SELECT COUNT(*) FROM categories c WHERE c.project_id = p.id) AS category_count
            FROM projects p
            LEFT JOIN datasets d ON d.project_id = p.id
            GROUP BY p.id
            ORDER BY p.created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate):
    with get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO projects (name, description, plan) VALUES (?, ?, ?)",
                (body.name.strip(), body.description.strip(), body.plan or "{}"),
            )
        except Exception:
            raise HTTPException(400, f"项目名「{body.name}」已存在")
        return dict(conn.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.get("/projects/{project_id}")
def get_project(project_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(404, "项目不存在")
        return dict(row)


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectUpdate):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(404, "项目不存在")
        fields, values = [], []
        if body.name is not None:
            fields.append("name = ?")
            values.append(body.name.strip())
        if body.description is not None:
            fields.append("description = ?")
            values.append(body.description.strip())
        if fields:
            fields.append("updated_at = datetime('now','localtime')")
            conn.execute(
                f"UPDATE projects SET {', '.join(fields)} WHERE id = ?",
                (*values, project_id),
            )
        return dict(conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int):
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            raise HTTPException(404, "项目不存在")
        # train_tasks.dataset_id 无 ON DELETE 子句：先手动删任务，
        # 否则 DELETE projects 级联删 datasets 时违反外键 → IntegrityError 500
        task_ids = [r[0] for r in conn.execute(
            "SELECT id FROM train_tasks WHERE model_id IN "
            "(SELECT id FROM models WHERE project_id = ?)", (project_id,)).fetchall()]
        conn.execute(
            "DELETE FROM train_tasks WHERE model_id IN "
            "(SELECT id FROM models WHERE project_id = ?)", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    from app.config import RUNS_DIR
    import shutil
    for tid in task_ids:
        shutil.rmtree(RUNS_DIR / str(tid), ignore_errors=True)


@router.get("/datasets/{dataset_id}/categories")
def list_dataset_categories(dataset_id: int):
    """数据集的类别（按数据集隔离）。

    「正常」为常驻分类：每个数据集自动确保存在（绿色），用于整图分类
    （训练/评估时区分正常与缺陷）。
    """
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM datasets WHERE id = ?", (dataset_id,)).fetchone():
            raise HTTPException(404, "数据集不存在")
        # 常驻「正常」类别：不存在则自动创建（幂等）
        normal = conn.execute(
            "SELECT * FROM categories WHERE dataset_id = ? AND name = '正常'", (dataset_id,)
        ).fetchone()
        if not normal:
            ds = conn.execute("SELECT project_id FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
            conn.execute(
                "INSERT INTO categories (project_id, dataset_id, name, color) VALUES (?, ?, '正常', '#3F9D63')",
                (ds["project_id"], dataset_id),
            )
        rows = conn.execute(
            "SELECT * FROM categories WHERE dataset_id = ? ORDER BY id", (dataset_id,)
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("/datasets/{dataset_id}/categories", status_code=201)
def create_dataset_category(dataset_id: int, body: CategoryCreate):
    """新建数据集类别。"""
    with get_conn() as conn:
        ds = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if not ds:
            raise HTTPException(404, "数据集不存在")
        try:
            cur = conn.execute(
                "INSERT INTO categories (project_id, dataset_id, name, color) VALUES (?, ?, ?, ?)",
                (ds["project_id"], dataset_id, body.name.strip(), body.color),
            )
        except Exception:
            raise HTTPException(400, f"类别「{body.name}」已存在")
        return dict(conn.execute("SELECT * FROM categories WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.delete("/projects/categories/{category_id}", status_code=204)
def delete_category(category_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        if conn.total_changes == 0:
            raise HTTPException(404, "类别不存在")


@router.patch("/projects/categories/{category_id}")
def update_category(category_id: int, body: dict):
    fields, values = [], []
    if "name" in body:
        fields.append("name = ?")
        values.append(str(body["name"]).strip())
    if "color" in body:
        fields.append("color = ?")
        values.append(str(body["color"]).strip())
    if not fields:
        raise HTTPException(400, "没有可更新的字段")
    with get_conn() as conn:
        conn.execute(f"UPDATE categories SET {', '.join(fields)} WHERE id = ?", (*values, category_id))
        if conn.total_changes == 0:
            raise HTTPException(404, "类别不存在")
        return dict(conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone())

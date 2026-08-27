"""后端 API 客户端：Qt 界面统一从这里取数，后端地址由主程序注入。"""
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8010"
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
RUNS_LOCAL = BACKEND_DIR / "data" / "runs"


def _url(path: str) -> str:
    return f"{BASE_URL}{path}"


def get(path: str, **kw):
    return requests.get(_url(path), timeout=60, **kw)


def post(path: str, json=None, **kw):
    return requests.post(_url(path), json=json, timeout=60, **kw)


def delete(path: str, **kw):
    return requests.delete(_url(path), timeout=60, **kw)


def run_url_to_path(url: str) -> str:
    """/runs/{task_id}/viz/xxx.png → 本地文件路径。"""
    if url.startswith("/runs/"):
        return str(RUNS_LOCAL / url[len("/runs/"):])
    return url


# ---------- 项目 ----------

def projects_list():
    return get("/api/projects").json()


def project_create(name: str, description: str = "", plan: str = ""):
    r = post("/api/projects", json={"name": name, "description": description, "plan": plan})
    r.raise_for_status()
    return r.json()


def project_delete(pid: int):
    delete(f"/api/projects/{pid}").raise_for_status()


def project_get(pid: int):
    return get(f"/api/projects/{pid}").json()


# ---------- 场景方案 ----------

def scenes_list():
    return get("/api/scenes").json()


def scenes_plan(scene_id: str, item_id: str, defect_names: list):
    return post("/api/scenes/plan", json={
        "scene_id": scene_id, "item_id": item_id, "defect_names": defect_names}).json()


def scenes_save_custom(body: dict):
    return post("/api/scenes/custom", json=body).json()


def scenes_delete_custom(name: str):
    delete("/api/scenes/custom", params={"name": name}).raise_for_status()


def safe_aug():
    return get("/api/scenes/safe_aug").json()


# ---------- 引擎 / 训练 ----------

def engines_list():
    return get("/api/engines").json()


def train_create(body: dict):
    r = post("/api/train", json=body)
    r.raise_for_status()
    return r.json()


def tasks_list(pid: int):
    return get(f"/api/projects/{pid}/tasks").json()


def task_curve(task_id: int):
    return get(f"/api/tasks/{task_id}/curve").json()


def task_log(task_id: int, offset: int = 0):
    return get(f"/api/tasks/{task_id}/log", params={"offset": offset}).json()


def task_stop(task_id: int):
    return post(f"/api/tasks/{task_id}/stop", json={}).json()


# ---------- 数据集 ----------

def datasets_list(pid: int):
    return get("/api/datasets", params={"project_id": pid}).json()


def dataset_create(project_id: int, name: str, root_path: str):
    r = post("/api/datasets", json={"project_id": project_id, "name": name, "root_path": root_path})
    r.raise_for_status()
    return r.json()


def dataset_split(ds_id: int, train_ratio: float, val_ratio: float, seed: int = 42):
    r = post(f"/api/datasets/{ds_id}/split",
             json={"train_ratio": train_ratio, "val_ratio": val_ratio, "seed": seed})
    r.raise_for_status()
    return r.json()


def dataset_categories(ds_id: int):
    return get(f"/api/datasets/{ds_id}/categories").json()


def category_create(ds_id: int, name: str, color: str):
    r = post(f"/api/datasets/{ds_id}/categories",
             json={"name": name, "color": color})
    r.raise_for_status()
    return r.json()


def category_delete(cid: int):
    delete(f"/api/projects/categories/{cid}").raise_for_status()


# ---------- 模型 ----------

def models_list(pid: int):
    return get(f"/api/projects/{pid}/models").json()


def model_result(model_id: int):
    return get(f"/api/models/{model_id}/result").json()


def model_export(model_id: int):
    r = post(f"/api/models/{model_id}/export", json={})
    r.raise_for_status()
    return r.json()


def model_delete(model_id: int):
    delete(f"/api/models/{model_id}").raise_for_status()


# ---------- 管线 ----------

def pipelines_list(pid: int, type: str = ""):
    return get(f"/api/projects/{pid}/pipelines", params={"type": type}).json()


def pipeline_create(project_id: int, name: str, ops: list, type: str):
    r = post("/api/pipelines", json={"project_id": project_id, "name": name, "ops": ops, "type": type})
    r.raise_for_status()
    return r.json()


# ---------- 标注 ----------

def dataset_images(ds_id: int, split: str = "", page: int = 1, page_size: int = 200):
    return get(f"/api/datasets/{ds_id}/images",
               params={"split": split, "page": page, "page_size": page_size}).json()


def image_bytes(image_id: int) -> bytes:
    r = get(f"/api/images/{image_id}/file")
    r.raise_for_status()
    return r.content


def image_annotations(image_id: int):
    return get(f"/api/images/{image_id}/annotations").json()


def annotation_create(image_id: int, category_id, type: str, data: dict):
    r = post("/api/annotations", json={
        "image_id": image_id, "category_id": category_id, "type": type, "data": data})
    r.raise_for_status()
    return r.json()


def annotation_delete(annotation_id: int):
    delete(f"/api/annotations/{annotation_id}").raise_for_status()


def annotation_brush(image_id: int, category_id, points: list, brush_size: int = 20):
    r = post("/api/annotations/brush", json={
        "image_id": image_id, "category_id": category_id,
        "points": points, "brush_size": brush_size})
    r.raise_for_status()
    return r.json()


def sam_predict(image_id: int, points: list = None, box: list = None):
    r = post("/api/sam/predict", json={"image_id": image_id, "points": points or [], "box": box})
    r.raise_for_status()
    return r.json()

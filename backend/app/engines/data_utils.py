"""引擎数据公共工具：数据集/图像/标注查询、类别映射、图像读取、管线获取。"""
import json
import sqlite3
from pathlib import Path

import cv2
import numpy as np

# 常驻「正常」类别名：仅用于整图分类（有无判断），检测/分割训练时自动排除
NORMAL_NAME = "正常"


def defect_categories(cats: list) -> list:
    """排除常驻「正常」类别，返回缺陷类表（检测/分割训练的类列表）。

    cats 可能是 sqlite3.Row 或 dict，统一按下标键访问。
    """
    return [c for c in cats if c["name"] != NORMAL_NAME]


def load_ds(conn: sqlite3.Connection, dataset_id: int):
    row = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    if not row:
        raise ValueError(f"数据集不存在: {dataset_id}")
    return row


def load_images(conn: sqlite3.Connection, dataset_id: int, split: str | None = None) -> list:
    if split:
        return list(conn.execute(
            "SELECT * FROM images WHERE dataset_id=? AND split=? ORDER BY id", (dataset_id, split)
        ).fetchall())
    return list(conn.execute(
        "SELECT * FROM images WHERE dataset_id=? ORDER BY id", (dataset_id,)
    ).fetchall())


def load_categories(conn: sqlite3.Connection, project_id: int, dataset_ids: list[int] | None = None) -> list:
    """加载类别。dataset_ids 为空/None 时取项目全部类别，否则取这些数据集内的类别。"""
    if not dataset_ids:
        return list(conn.execute(
            "SELECT * FROM categories WHERE project_id=? ORDER BY id", (project_id,)
        ).fetchall())
    placeholders = ",".join("?" * len(dataset_ids))
    return list(conn.execute(
        f"SELECT * FROM categories WHERE dataset_id IN ({placeholders}) ORDER BY id",
        tuple(dataset_ids),
    ).fetchall())


def cat_index(cats: list) -> dict[int, int]:
    """类别 id → 顺序编号（0 起）。"""
    return {c["id"]: i for i, c in enumerate(cats)}


def cat_index_1(cats: list) -> dict[int, int]:
    """类别 id → 顺序编号（1 起，0 留给背景）。"""
    return {c["id"]: i + 1 for i, c in enumerate(cats)}


def load_annotations(conn: sqlite3.Connection, dataset_id: int, types: tuple) -> dict[int, list]:
    """image_id → 标注列表（只含指定类型）。"""
    anns: dict[int, list] = {}
    placeholders = ",".join("?" * len(types))
    for a in conn.execute(
        f"""SELECT * FROM annotations WHERE type IN ({placeholders}) AND image_id IN
            (SELECT id FROM images WHERE dataset_id=?)""",
        (*types, dataset_id),
    ).fetchall():
        anns.setdefault(a["image_id"], []).append(a)
    return anns


def load_annotations_multi(conn: sqlite3.Connection, dataset_ids: list[int], types: tuple) -> dict[int, list]:
    """多数据集版：image_id → 标注列表。"""
    anns: dict[int, list] = {}
    if not dataset_ids:
        return anns
    placeholders = ",".join("?" * len(types))
    ds_ph = ",".join("?" * len(dataset_ids))
    for a in conn.execute(
        f"""SELECT * FROM annotations WHERE type IN ({placeholders}) AND image_id IN
            (SELECT id FROM images WHERE dataset_id IN ({ds_ph})) """,
        (*types, *dataset_ids),
    ).fetchall():
        anns.setdefault(a["image_id"], []).append(a)
    return anns


def read_image(ds_row, im_row) -> np.ndarray | None:
    """读取图像（BGR）。失败返回 None。"""
    src = Path(ds_row["root_path"]) / im_row["rel_path"]
    img = cv2.imdecode(np.fromfile(src, dtype="uint8"), cv2.IMREAD_COLOR)
    return img


def get_pipeline_ops(conn: sqlite3.Connection, pipeline_id) -> list[dict]:
    if not pipeline_id:
        return []
    row = conn.execute("SELECT ops FROM preprocess_pipelines WHERE id=?", (pipeline_id,)).fetchone()
    return json.loads(row["ops"]) if row else []


def imgsz_hw(imgsz) -> int | list[int]:
    """平台 imgsz（int 或 [w, h]）→ Ultralytics 格式 [h, w]。"""
    if isinstance(imgsz, (list, tuple)) and len(imgsz) == 2:
        return [int(imgsz[1]), int(imgsz[0])]
    return int(imgsz)


def imgsz_wh(imgsz) -> tuple[int, int]:
    """平台 imgsz（int 或 [w, h]）→ OpenCV (w, h)。"""
    if isinstance(imgsz, (list, tuple)) and len(imgsz) == 2:
        return (int(imgsz[0]), int(imgsz[1]))
    return (int(imgsz), int(imgsz))


def cfg_dataset_ids(cfg: dict) -> list[int]:
    """从训练配置取数据集 id 列表（兼容新旧 config：dataset_ids 列表或 dataset_id 单值）。"""
    return cfg.get("dataset_ids") or ([cfg["dataset_id"]] if cfg.get("dataset_id") else [])


def load_image_by_id(image_id: int) -> tuple[np.ndarray, dict]:
    """按 image_id 读图（BGR）。统一错误语义：返回 (img, im_row)。

    图像不存在 → ValueError；文件缺失/无法解码 → FileNotFoundError。
    调用方按 HTTP 场景转 404/400。
    """
    import sqlite3 as _sqlite3
    from app.db import get_conn as _get_conn
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT im.rel_path, im.width, im.height, ds.root_path FROM images im "
            "JOIN datasets ds ON ds.id = im.dataset_id WHERE im.id = ?",
            (image_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"图像不存在: {image_id}")
        im = dict(row)
    path = Path(im["root_path"]) / im["rel_path"]
    if not path.is_file():
        raise FileNotFoundError(f"图像文件缺失：{path}（请检查数据集目录是否被移动或删除）")
    img = cv2.imdecode(np.fromfile(path, dtype="uint8"), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"图像无法解码：{path}")
    return img, im


def image_path_of(image_id: int) -> Path:
    """按 image_id 返回图像绝对路径（不读图）。图像不存在/文件缺失 → 抛异常。"""
    import sqlite3 as _sqlite3
    from app.db import get_conn as _get_conn
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT im.rel_path, ds.root_path FROM images im "
            "JOIN datasets ds ON ds.id = im.dataset_id WHERE im.id = ?",
            (image_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"图像不存在: {image_id}")
        path = Path(row["root_path"]) / row["rel_path"]
    if not path.is_file():
        raise FileNotFoundError(f"图像文件缺失：{path}")
    return path

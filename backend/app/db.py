"""SQLite 连接与初始化。仅用标准库，零依赖。"""
import sqlite3

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    dataset_id INTEGER REFERENCES datasets(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    color      TEXT NOT NULL DEFAULT '#4E79A7',
    UNIQUE(dataset_id, name)
);

CREATE TABLE IF NOT EXISTS datasets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    root_path   TEXT NOT NULL,
    image_count INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'ready',   -- importing/ready
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS images (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    rel_path   TEXT NOT NULL,
    width      INTEGER,
    height     INTEGER,
    split      TEXT NOT NULL DEFAULT '',          -- train/val/test
    UNIQUE(dataset_id, rel_path)
);

CREATE TABLE IF NOT EXISTS annotations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id    INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    type        TEXT NOT NULL,                    -- box/mask/class
    data        TEXT NOT NULL,                    -- JSON 载荷
    source      TEXT NOT NULL DEFAULT 'manual',   -- manual/imported/sam/cluster
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS models (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    task_type    TEXT NOT NULL,                   -- detect/segment/classify/us_classify/us_segment
    engine       TEXT NOT NULL,                   -- yolo_detect/smp_segment/cluster/anomaly/...
    config       TEXT NOT NULL DEFAULT '{}',      -- 训练超参 JSON
    weights_path TEXT NOT NULL DEFAULT '',
    metrics      TEXT NOT NULL DEFAULT '{}',      -- 评估指标 JSON
    status       TEXT NOT NULL DEFAULT 'pending', -- pending/training/ready/failed
    is_best      INTEGER NOT NULL DEFAULT 0,
    framework    TEXT NOT NULL DEFAULT 'torch',   -- torch/onnx（导入模型记录来源）
    architecture TEXT NOT NULL DEFAULT '',       -- 架构名，如 yolo11s / 自定义名
    params_m     REAL NOT NULL DEFAULT 0,        -- 参数量（百万）
    file_size    INTEGER NOT NULL DEFAULT 0,     -- 权重文件字节
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    finished_at  TEXT
);

CREATE TABLE IF NOT EXISTS preprocess_pipelines (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    ops        TEXT NOT NULL DEFAULT '[]',     -- JSON 有序算子列表
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(project_id, name)
);

CREATE TABLE IF NOT EXISTS train_tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id   INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id),
    status     TEXT NOT NULL DEFAULT 'queued',    -- queued/running/success/failed/stopped
    pid        INTEGER,
    log_path   TEXT NOT NULL DEFAULT '',
    progress   REAL NOT NULL DEFAULT 0,
    error      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    started_at TEXT,
    finished_at TEXT
);

-- 常用查询索引（P2：避免 N+1 全表扫描）
CREATE INDEX IF NOT EXISTS idx_annotations_image ON annotations(image_id);
CREATE INDEX IF NOT EXISTS idx_annotations_cat ON annotations(category_id);
CREATE INDEX IF NOT EXISTS idx_images_dataset ON images(dataset_id);
CREATE INDEX IF NOT EXISTS idx_categories_dataset ON categories(dataset_id);
CREATE INDEX IF NOT EXISTS idx_categories_project ON categories(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_model ON train_tasks(model_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON train_tasks(status);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # 并发写等待（P2：多实例/训练子进程写同一库时避免立即 locked 报错）
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """增量迁移：为已存在的旧表补充新列（幂等）。"""
    model_cols = {r["name"] for r in conn.execute("PRAGMA table_info(models)")}
    for name, ddl in {
        "framework": "ALTER TABLE models ADD COLUMN framework TEXT NOT NULL DEFAULT 'torch'",
        "architecture": "ALTER TABLE models ADD COLUMN architecture TEXT NOT NULL DEFAULT ''",
        "params_m": "ALTER TABLE models ADD COLUMN params_m REAL NOT NULL DEFAULT 0",
        "file_size": "ALTER TABLE models ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0",
        "onnx_path": "ALTER TABLE models ADD COLUMN onnx_path TEXT NOT NULL DEFAULT ''",
    }.items():
        if name not in model_cols:
            conn.execute(ddl)
    pipe_cols = {r["name"] for r in conn.execute("PRAGMA table_info(preprocess_pipelines)")}
    if "type" not in pipe_cols:
        conn.execute("ALTER TABLE preprocess_pipelines ADD COLUMN type TEXT NOT NULL DEFAULT 'pre'")

    proj_cols = {r["name"] for r in conn.execute("PRAGMA table_info(projects)")}
    if "plan" not in proj_cols:
        conn.execute("ALTER TABLE projects ADD COLUMN plan TEXT NOT NULL DEFAULT '{}'")

    # categories 加 dataset_id（类别按数据集隔离）；旧数据按标注分布迁移到所属数据集
    cat_cols = {r["name"] for r in conn.execute("PRAGMA table_info(categories)")}
    if "dataset_id" not in cat_cols:
        conn.execute("ALTER TABLE categories ADD COLUMN dataset_id INTEGER")
        # 旧类别（dataset_id IS NULL）按标注分布归属：每类标注最多的数据集
        rows = conn.execute(
            """SELECT a.category_id, i.dataset_id, COUNT(*) n FROM annotations a
                JOIN images i ON i.id = a.image_id
                WHERE a.category_id IS NOT NULL
                GROUP BY a.category_id, i.dataset_id"""
        ).fetchall()
        best: dict[int, int] = {}
        for r in rows:
            cid, dsid, n = r["category_id"], r["dataset_id"], r["n"]
            if cid not in best or n > best[cid][1]:
                best[cid] = (dsid, n)
        for cid, (dsid, _) in best.items():
            conn.execute("UPDATE categories SET dataset_id=? WHERE id=?", (dsid, cid))
        # 若项目只有单个数据集，未归属的类别也归到它
        dss = [r[0] for r in conn.execute("SELECT id FROM datasets ORDER BY id").fetchall()]
        if len(dss) == 1:
            conn.execute("UPDATE categories SET dataset_id=? WHERE dataset_id IS NULL", (dss[0],))

    # 历史回填：ready 模型但 metrics 为空 → 从 run 目录 metrics.json 回填（训练效果页使用）
    try:
        import json as _json
        from app.config import RUNS_DIR as _RUNS_DIR
        rows = conn.execute(
            """SELECT m.id AS mid, t.id AS tid FROM models m
               JOIN train_tasks t ON t.model_id = m.id
               WHERE m.status='ready' AND (m.metrics IS NULL OR m.metrics='' OR m.metrics='{}')"""
        ).fetchall()
        for r in rows:
            mf = _RUNS_DIR / str(r["tid"]) / "metrics.json"
            if mf.is_file():
                try:
                    md = _json.loads(mf.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if md:
                    conn.execute("UPDATE models SET metrics=? WHERE id=?",
                                 (_json.dumps(md, ensure_ascii=False), r["mid"]))
    except Exception:
        pass

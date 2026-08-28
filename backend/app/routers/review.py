"""评审框选标注：用户在前端页面框选区域并留言，定位需要改进的位置。

数据存 backend/data/review_marks.json（评审是轻量工作流数据，不进主 DB）。
- POST /api/review : 保存一条（route + project_id + 框选矩形 + 留言）
- GET  /api/review : 全部标注（供改进方读取）
- DELETE /api/review/{id}
"""
import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.config import BACKEND_DIR

router = APIRouter()
MARKS_FILE = BACKEND_DIR / "data" / "review_marks.json"


class Rect(BaseModel):
    x: float
    y: float
    w: float
    h: float


class ReviewMark(BaseModel):
    route: str = ""
    project_id: int | None = None
    comment: str = Field(default="", max_length=2000)
    rects: list[Rect] = []
    viewport: list[int] = Field(default_factory=lambda: [0, 0])  # [W, H] 视口尺寸


def _load() -> list:
    if not MARKS_FILE.is_file():
        return []
    try:
        return json.loads(MARKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: list) -> None:
    MARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    MARKS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


@router.post("/review", status_code=201)
def create_mark(body: ReviewMark):
    items = _load()
    item = {
        "id": (max([m.get("id", 0) for m in items], default=0) + 1),
        "route": body.route,
        "project_id": body.project_id,
        "comment": body.comment.strip(),
        "rects": [r.model_dump() for r in body.rects],
        "viewport": body.viewport,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    items.append(item)
    _save(items)
    return item


@router.get("/review")
def list_marks():
    return _load()


@router.delete("/review/{mark_id}", status_code=204)
def delete_mark(mark_id: int):
    items = _load()
    new_items = [m for m in items if m.get("id") != mark_id]
    if len(new_items) == len(items):
        raise HTTPException(404, "标注不存在")
    _save(new_items)

"""场景方案：内置场景树 + 自定义组合。

- GET    /api/scenes        内置场景树 + 自定义方案列表
- POST   /api/scenes/plan   按物品 + 勾选缺陷生成推荐方案
- POST   /api/scenes/custom 保存自定义方案（按 name upsert）
- DELETE /api/scenes/custom 删除自定义方案（?name=）
"""
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import BACKEND_DIR
from app.scenes_data import SCENES, TASK_TYPE_LABELS, build_plan, scene_tree

router = APIRouter()

CUSTOM_FILE = BACKEND_DIR / "data" / "custom_scenes.json"


class PlanRequest(BaseModel):
    scene_id: str
    item_id: str
    defect_names: list[str] = Field(default_factory=list)


class CustomScene(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    item_name: str = ""
    defects: list[str] = Field(default_factory=list)
    recommend: dict = Field(default_factory=dict)
    note: str = ""


def _load_customs() -> list[dict]:
    if not CUSTOM_FILE.is_file():
        return []
    try:
        data = json.loads(CUSTOM_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_customs(customs: list[dict]) -> None:
    CUSTOM_FILE.parent.mkdir(parents=True, exist_ok=True)
    CUSTOM_FILE.write_text(json.dumps(customs, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_item(scene_id: str, item_id: str) -> dict:
    for scene in SCENES:
        if scene["id"] == scene_id:
            for item in scene["items"]:
                if item["id"] == item_id:
                    return item
    raise HTTPException(404, "场景或物品不存在")


@router.get("/scenes")
def get_scenes():
    return {"scenes": scene_tree(), "customs": _load_customs(),
            "task_type_labels": TASK_TYPE_LABELS}


@router.get("/scenes/safe_aug")
def safe_aug():
    """一键工业安全增强：ultralytics 内置增强的保守默认参数。

    只模拟产线物理真实变化（光照波动、轻微几何公差），不做激进增强。
    """
    return {"flip": True, "mosaic": 0.5, "mixup": 0.05, "hsv": 0.015}


@router.post("/scenes/plan")
def plan(body: PlanRequest):
    item = _find_item(body.scene_id, body.item_id)
    plan = build_plan(item, body.defect_names)
    return {"item": item["name"], "plan": plan}


@router.post("/scenes/custom", status_code=201)
def save_custom(body: CustomScene):
    customs = _load_customs()
    entry = {
        "name": body.name.strip(),
        "item_name": body.item_name.strip(),
        "defects": body.defects,
        "recommend": body.recommend,
        "note": body.note.strip(),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    for i, c in enumerate(customs):
        if c.get("name") == entry["name"]:
            customs[i] = entry
            break
    else:
        customs.append(entry)
    _save_customs(customs)
    return entry


@router.delete("/scenes/custom")
def delete_custom(name: str = Query(...)):
    customs = _load_customs()
    kept = [c for c in customs if c.get("name") != name]
    if len(kept) == len(customs):
        raise HTTPException(404, "自定义方案不存在")
    _save_customs(kept)
    return {"ok": True}

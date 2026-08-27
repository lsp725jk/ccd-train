# -*- coding: utf-8 -*-
"""场景方案 API 测试。"""


def test_scenes_tree(client):
    r = client.get("/api/scenes")
    assert r.status_code == 200
    body = r.json()
    assert len(body["scenes"]) >= 8
    assert body["task_type_labels"]["detect"]


def test_scenes_plan_normal(client):
    r = client.post("/api/scenes/plan", json={
        "scene_id": "metal", "item_id": "steel_sheet", "defect_names": ["裂纹", "麻点"]})
    assert r.status_code == 200
    plan = r.json()["plan"]
    assert plan["engines"]
    assert plan["defaults"]["imgsz"] == 1280  # 微小缺陷 → 高分辨率
    assert plan["notes"]


def test_scenes_plan_not_found(client):
    r = client.post("/api/scenes/plan", json={
        "scene_id": "nope", "item_id": "steel_sheet", "defect_names": []})
    assert r.status_code == 404


def test_scenes_plan_empty_defects(client):
    r = client.post("/api/scenes/plan", json={
        "scene_id": "metal", "item_id": "steel_sheet", "defect_names": []})
    assert r.status_code == 200
    assert r.json()["plan"]["defaults"]["imgsz"] == 640


def test_custom_save_and_delete(client):
    body = {"name": "apitest_custom", "item_name": "测试物品", "defects": ["自定义缺陷"],
            "recommend": {"engines": [], "defaults": {"epochs": 1, "imgsz": 640, "batch": 8}},
            "note": ""}
    r = client.post("/api/scenes/custom", json=body)
    assert r.status_code == 201
    # 重复保存（覆盖）也应成功
    r2 = client.post("/api/scenes/custom", json=body)
    assert r2.status_code == 201
    r3 = client.delete("/api/scenes/custom", params={"name": "apitest_custom"})
    assert r3.status_code == 200
    r4 = client.delete("/api/scenes/custom", params={"name": "apitest_custom"})
    assert r4.status_code == 404


def test_safe_aug(client):
    r = client.get("/api/scenes/safe_aug")
    assert r.status_code == 200
    d = r.json()
    assert d["flip"] is True and 0 < d["mosaic"] <= 1

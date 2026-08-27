# -*- coding: utf-8 -*-
"""标注 / SAM API 测试。"""


def test_annotation_box_crud(client, dataset):
    imgs = client.get(f"/api/datasets/{dataset['id']}/images", params={"page_size": 1}).json()
    image_id = imgs["items"][0]["id"]
    r = client.post("/api/annotations", json={
        "image_id": image_id, "category_id": dataset["category_id"],
        "type": "box", "data": {"x1": 10, "y1": 20, "x2": 100, "y2": 120}})
    assert r.status_code == 201
    ann = r.json()
    assert ann["category_name"] == "划痕"

    lst = client.get(f"/api/images/{image_id}/annotations")
    assert lst.status_code == 200
    assert any(a["id"] == ann["id"] for a in lst.json())

    assert client.delete(f"/api/annotations/{ann['id']}").status_code == 204
    assert client.delete(f"/api/annotations/{ann['id']}").status_code == 404


def test_annotation_bad_type(client, dataset):
    imgs = client.get(f"/api/datasets/{dataset['id']}/images", params={"page_size": 1}).json()
    r = client.post("/api/annotations", json={
        "image_id": imgs["items"][0]["id"], "category_id": dataset["category_id"],
        "type": "star", "data": {}})
    assert r.status_code == 400


def test_annotation_brush(client, dataset):
    imgs = client.get(f"/api/datasets/{dataset['id']}/images", params={"page_size": 1}).json()
    image_id = imgs["items"][0]["id"]
    pts = [[100, 100], [120, 105], [140, 120], [130, 140], [105, 135], [95, 115]]
    r = client.post("/api/annotations/brush", json={
        "image_id": image_id, "category_id": dataset["category_id"],
        "points": pts, "brush_size": 20})
    assert r.status_code == 201
    assert r.json()["type"] == "mask"
    client.delete(f"/api/annotations/{r.json()['id']}")


def test_annotation_brush_few_points(client, dataset):
    imgs = client.get(f"/api/datasets/{dataset['id']}/images", params={"page_size": 1}).json()
    r = client.post("/api/annotations/brush", json={
        "image_id": imgs["items"][0]["id"], "category_id": dataset["category_id"],
        "points": [[1, 1]], "brush_size": 20})
    assert r.status_code == 400


def test_annotation_shield(client, dataset):
    """掩膜（屏蔽区）：brush type=shield 创建，可查询可删除。"""
    imgs = client.get(f"/api/datasets/{dataset['id']}/images", params={"page_size": 1}).json()
    image_id = imgs["items"][0]["id"]
    pts = [[200, 200], [220, 205], [240, 220], [230, 240], [205, 235]]
    r = client.post("/api/annotations/brush", json={
        "image_id": image_id, "category_id": dataset["category_id"],
        "points": pts, "brush_size": 20, "type": "shield"})
    assert r.status_code == 201
    assert r.json()["type"] == "shield"
    lst = client.get(f"/api/images/{image_id}/annotations")
    assert any(a["type"] == "shield" for a in lst.json())
    client.delete(f"/api/annotations/{r.json()['id']}")
    assert client.post("/api/annotations/brush", json={
        "image_id": image_id, "category_id": dataset["category_id"],
        "points": pts, "brush_size": 20, "type": "star"}).status_code == 400


def test_sam_neg_points(client, dataset):
    """SAM 负点参数被接受（predict 至少返回 200，不要求检出）。"""
    imgs = client.get(f"/api/datasets/{dataset['id']}/images", params={"page_size": 1}).json()
    r = client.post("/api/sam/predict", json={
        "image_id": imgs["items"][0]["id"],
        "points": [[300, 300]], "neg_points": [[100, 100]],
        "box": [200, 200, 400, 400]})
    assert r.status_code == 200
    assert "polygons" in r.json()

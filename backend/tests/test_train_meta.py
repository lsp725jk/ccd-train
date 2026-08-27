# -*- coding: utf-8 -*-
"""训练 / 曲线 / 模型 / OpenAPI 完整性测试。"""


def test_engines(client):
    r = client.get("/api/engines")
    assert r.status_code == 200
    ids = [e["id"] for e in r.json()]
    assert "yolo11n" in ids and "patchcore" in ids


def test_train_no_dataset(client, project):
    r = client.post("/api/train", json={
        "project_id": project, "name": "t", "task_type": "detect",
        "engine": "yolo11n", "dataset_ids": [999999], "epochs": 1})
    assert r.status_code == 404


def test_train_engine_type_mismatch(client, dataset, project):
    r = client.post("/api/train", json={
        "project_id": project, "name": "t", "task_type": "segment",
        "engine": "yolo11n", "dataset_ids": [dataset["id"]], "epochs": 1})
    assert r.status_code == 400


def test_curve_missing(client):
    r = client.get("/api/tasks/999999/curve")
    assert r.status_code == 200
    assert r.json()["exists"] is False


def test_model_result_404(client):
    assert client.get("/api/models/999999/result").status_code == 404


def test_openapi_docs(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    for required in ("/api/scenes", "/api/projects", "/api/train",
                     "/api/annotations", "/api/sam/predict"):
        assert required in paths, f"缺少 {required}"

# -*- coding: utf-8 -*-
"""项目 / 数据集 API 测试。"""


# ---------- 项目 ----------

def test_project_empty_name(client):
    r = client.post("/api/projects", json={"name": ""})
    assert r.status_code == 422


def test_project_duplicate_name(client, project):
    r = client.post("/api/projects", json={"name": "apitest_proj"})
    assert r.status_code == 400


def test_project_list(client):
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_project_get_404(client):
    assert client.get("/api/projects/999999").status_code == 404


# ---------- 数据集 ----------

def test_dataset_bad_dir(client, project):
    r = client.post("/api/datasets", json={
        "project_id": project, "name": "bad", "root_path": r"Z:\no_such_dir"})
    assert r.status_code == 400


def test_dataset_scan(client, dataset):
    assert dataset["image_count"] >= 80


def test_dataset_split_normal(client, dataset):
    r = client.post(f"/api/datasets/{dataset['id']}/split",
                    json={"train_ratio": 0.7, "val_ratio": 0.15, "seed": 42})
    assert r.status_code == 200
    assert "train" in r.json()["message"]


def test_dataset_split_ratio_over(client, dataset):
    r = client.post(f"/api/datasets/{dataset['id']}/split",
                    json={"train_ratio": 0.9, "val_ratio": 0.5, "seed": 42})
    assert r.status_code == 400


def test_dataset_images(client, dataset):
    r = client.get(f"/api/datasets/{dataset['id']}/images", params={"page_size": 20})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 80
    assert len(body["items"]) == 20


def test_category_duplicate(client, dataset):
    r = client.post(f"/api/datasets/{dataset['id']}/categories",
                    json={"name": "划痕", "color": "#000000"})
    assert r.status_code == 400

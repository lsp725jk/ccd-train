# -*- coding: utf-8 -*-
"""共享 fixture：TestClient、测试项目、demo 数据集。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

DEMO_DATA = r"E:\Hanako\OH-WorkSpace\ccd-train\demo_data"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def project(client):
    """建一个测试项目，模块结束删除。"""
    r = client.post("/api/projects", json={"name": "apitest_proj", "description": "api integration test"})
    assert r.status_code == 201
    pid = r.json()["id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


@pytest.fixture(scope="module")
def dataset(client, project):
    """用 demo_data 建数据集 + 一个类别。"""
    r = client.post("/api/datasets", json={
        "project_id": project, "name": "demo", "root_path": DEMO_DATA})
    assert r.status_code == 201
    ds = r.json()
    c = client.post(f"/api/datasets/{ds['id']}/categories",
                    json={"name": "划痕", "color": "#E65C4F"})
    assert c.status_code == 201
    ds["category_id"] = c.json()["id"]
    return ds

import os

os.environ.setdefault("LIFELINK_SECRET", "test-secret-0123456789abcdef0123456789abcdef")
os.environ["LIFELINK_BACKGROUND"] = "0"

import pytest  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFELINK_DB", str(tmp_path / "test.db"))
    from app.db import connect, init_db
    from app.seed import seed_demo

    init_db()
    conn = connect()
    seed_demo(conn)
    conn.close()

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def login(client, email, password="demo1234"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def H(client):
    cache = {}

    def get(name):
        if name not in cache:
            cache[name] = login(client, f"{name}@lifelink.test")
        return cache[name]

    return get


def food_listing_id(client, headers):
    items = client.get("/api/v1/resources?mine=true&category=food", headers=headers).json()
    return next(i["id"] for i in items if i["title"] == "Surplus lunch boxes")


def match_for(client, headers, resource_id, org_prefix):
    data = client.get(f"/api/v1/resources/{resource_id}/matches", headers=headers).json()
    return next(c for c in data["candidates"] if c["recipient_org"].startswith(org_prefix))

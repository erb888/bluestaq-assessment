import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import USERS

ALICE, BOB, CAROL = 1, 2, 3
ENG, DESIGN = 1, 2


def login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def as_user(client: TestClient, user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {client.tokens[user_id]}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    # A fresh database file per test. Not ":memory:", because every
    # per-request connection would get its own empty in-memory database.
    monkeypatch.setenv("NOTES_DB", str(tmp_path / "test.db"))
    # The context manager runs the app's lifespan: schema + seed data.
    with TestClient(app) as c:
        # Log in every seeded user once, so tests can act as any of them.
        c.tokens = {user_id: login(c, name, password) for user_id, name, password in USERS}
        yield c

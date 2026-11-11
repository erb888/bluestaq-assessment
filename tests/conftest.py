import pytest
from fastapi.testclient import TestClient

from app.main import app

ALICE, BOB, CAROL = 1, 2, 3
ENG, DESIGN = 1, 2


def as_user(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


@pytest.fixture
def client(tmp_path, monkeypatch):
    # A fresh database file per test. Not ":memory:", because every
    # per-request connection would get its own empty in-memory database.
    monkeypatch.setenv("NOTES_DB", str(tmp_path / "test.db"))
    # The context manager runs the app's lifespan: schema + seed data.
    with TestClient(app) as c:
        yield c

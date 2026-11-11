from app.auth import hash_token
from app.db import connect
from tests.conftest import ALICE, as_user, login


def test_login_returns_bearer_token(client):
    resp = client.post("/auth/login", json={"username": "bob", "password": "bob-password"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert client.get("/notes/1", headers={"Authorization": f"Bearer {body['access_token']}"}).status_code == 200


def test_wrong_password_and_unknown_user_look_the_same(client):
    wrong = client.post("/auth/login", json={"username": "alice", "password": "nope"})
    unknown = client.post("/auth/login", json={"username": "mallory", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_logout_revokes_token(client):
    headers = as_user(client, ALICE)
    assert client.post("/auth/logout", headers=headers).status_code == 204
    assert client.get("/notes/1", headers=headers).status_code == 401
    assert client.post("/auth/logout", headers=headers).status_code == 401


def test_logout_leaves_other_tokens_working(client):
    second = login(client, "alice", "alice-password")
    client.post("/auth/logout", headers=as_user(client, ALICE))
    assert client.get("/notes/1", headers={"Authorization": f"Bearer {second}"}).status_code == 200


def test_expired_token_is_401(client):
    token = client.tokens[ALICE]
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE tokens SET expires_at = '2000-01-01T00:00:00.000000+00:00' WHERE token_hash = ?",
            (hash_token(token),),
        )
    conn.close()
    assert client.get("/notes/1", headers=as_user(client, ALICE)).status_code == 401


def test_raw_token_is_not_stored(client):
    token = client.tokens[ALICE]
    conn = connect()
    stored = [row["token_hash"] for row in conn.execute("SELECT token_hash FROM tokens")]
    conn.close()
    assert token not in stored
    assert hash_token(token) in stored

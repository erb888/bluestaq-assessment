import pytest

from tests.conftest import ALICE, BOB, CAROL, DESIGN, ENG, as_user


def create(client, team_id, user_id, title="Plan", body="Ship it"):
    return client.post(
        f"/teams/{team_id}/notes",
        json={"title": title, "body": body},
        headers=as_user(user_id),
    )


def test_create_note_in_own_team(client):
    resp = create(client, ENG, ALICE)
    assert resp.status_code == 201
    note = resp.json()
    assert note["team_id"] == ENG
    assert note["version"] == 1
    assert note["created_by"] == note["updated_by"] == ALICE


@pytest.mark.parametrize("headers", [{}, {"X-User-Id": "abc"}, {"X-User-Id": "999"}])
def test_bad_identity_is_401(client, headers):
    assert client.get("/notes/1", headers=headers).status_code == 401


def test_team_routes_reject_non_members_with_403(client):
    assert create(client, ENG, CAROL).status_code == 403
    assert client.get(f"/teams/{ENG}/notes", headers=as_user(CAROL)).status_code == 403


def test_other_teams_note_looks_missing(client):
    # Seed note 1 is in eng; carol is only in design.
    assert client.get("/notes/1", headers=as_user(CAROL)).status_code == 404
    assert client.get("/notes/9999", headers=as_user(ALICE)).status_code == 404


def test_update_with_current_version(client):
    resp = client.patch("/notes/1", json={"version": 1, "body": "edited"}, headers=as_user(BOB))
    assert resp.status_code == 200
    note = resp.json()
    assert note["version"] == 2
    assert note["body"] == "edited"
    assert note["title"] == "Welcome"  # fields not sent are kept
    assert note["updated_by"] == BOB


def test_second_update_with_same_version_conflicts(client):
    first = client.patch("/notes/1", json={"version": 1, "body": "alice's"}, headers=as_user(ALICE))
    second = client.patch("/notes/1", json={"version": 1, "body": "bob's"}, headers=as_user(BOB))
    assert first.status_code == 200
    assert second.status_code == 409
    current = second.json()["current"]
    assert current["version"] == 2
    assert current["body"] == "alice's"
    assert client.get("/notes/1", headers=as_user(BOB)).json()["body"] == "alice's"


def test_update_note_in_other_team_is_404_not_409(client):
    resp = client.patch("/notes/1", json={"version": 1, "title": "x"}, headers=as_user(CAROL))
    assert resp.status_code == 404


def test_delete_requires_current_version(client):
    assert client.delete("/notes/1?version=5", headers=as_user(ALICE)).status_code == 409
    assert client.delete("/notes/1?version=1", headers=as_user(ALICE)).status_code == 204
    assert client.get("/notes/1", headers=as_user(ALICE)).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [{"version": 1}, {"version": 1, "title": ""}, {"title": "no version"}],
)
def test_invalid_update_is_422(client, payload):
    assert client.patch("/notes/1", json=payload, headers=as_user(ALICE)).status_code == 422


def test_search_matches_title_or_body_ignoring_case(client):
    create(client, ENG, ALICE, title="Roadmap", body="q3 goals")
    create(client, ENG, ALICE, title="Lunch", body="ROADMAP review at noon")
    create(client, ENG, ALICE, title="Other", body="nothing")
    resp = client.get(f"/teams/{ENG}/notes", params={"q": "roadmap"}, headers=as_user(ALICE))
    assert sorted(n["title"] for n in resp.json()) == ["Lunch", "Roadmap"]


def test_search_treats_wildcards_literally(client):
    create(client, ENG, ALICE, title="Discount", body="50% off")
    create(client, ENG, ALICE, title="Plain", body="500 items")
    resp = client.get(f"/teams/{ENG}/notes", params={"q": "50%"}, headers=as_user(ALICE))
    assert [n["title"] for n in resp.json()] == ["Discount"]


def test_member_of_two_teams_sees_both_and_only_those(client):
    create(client, DESIGN, CAROL, title="Mockups")
    assert [n["title"] for n in client.get(f"/teams/{ENG}/notes", headers=as_user(BOB)).json()] == ["Welcome"]
    assert [n["title"] for n in client.get(f"/teams/{DESIGN}/notes", headers=as_user(BOB)).json()] == ["Mockups"]

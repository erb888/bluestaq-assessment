# bluestaq-assessment
Building a backend for a note taking service shared and used by several small teams. Users need somewhere to capture and work with their notes.

## Quickstart

Requires Python 3.11+.

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs to try every endpoint in the browser. Fill in
the `x-user-id` field with a seeded user ID (below).

Run the tests:

```sh
pytest
```

The database is a SQLite file, `notes.db`, created and seeded on startup. Set
`NOTES_DB` to use a different path. To reset all data, stop the server and
delete the file.

## Seed data

There are no endpoints to create users or teams, so these are created on
startup (re-running is safe):

| User | ID | Teams |
| --- | --- | --- |
| alice | 1 | eng (1) |
| bob | 2 | eng (1), design (2) |
| carol | 3 | design (2) |

Note 1, "Welcome", belongs to `eng`.

## API

Every request needs an `X-User-Id` header (see [Trade-offs](#trade-offs)).

| Method | Path | Body / query | Success |
| --- | --- | --- | --- |
| POST | `/teams/{team_id}/notes` | `{"title", "body"}` | 201, note |
| GET | `/teams/{team_id}/notes` | `?q=text` (optional) | 200, list of notes |
| GET | `/notes/{note_id}` | | 200, note |
| PATCH | `/notes/{note_id}` | `{"version", "title"?, "body"?}` | 200, note |
| DELETE | `/notes/{note_id}` | `?version=N` | 204 |
| GET | `/health` | | 200 |

A note looks like:

```json
{"id": 1, "team_id": 1, "title": "Welcome", "body": "...", "version": 1,
 "created_by": 1, "updated_by": 1,
 "created_at": "2026-11-11T21:45:30.485356+00:00", "updated_at": "..."}
```

- `title` is 1-200 characters. `body` is up to 1,000 characters and may be empty.
- A PATCH changes only the fields it sends and must send at least one.
- `q` matches title or body as a case-insensitive substring. Results are
  newest edit first.

### Status codes

| Case | Status |
| --- | --- |
| `X-User-Id` missing, not a number, or not a known user | 401 |
| List or create in a team you are not in | 403 |
| Note does not exist, or is in a team you are not in | 404 |
| Update or delete with a stale `version` | 409 |
| Invalid body or query | 422 |

A 409 body includes the note as it is now, so the client can merge and retry
without another request:

```json
{"detail": "Version conflict: the note was changed since you read it",
 "current": {"id": 1, "version": 2, "...": "..."}}
```

### Example: two people edit the same note

```sh
# bob reads note 1 (version 1) and saves an edit
curl -X PATCH localhost:8000/notes/1 -H 'X-User-Id: 2' \
  -H 'Content-Type: application/json' -d '{"version": 1, "body": "bob was here"}'
# → 200, "version": 2

# alice also read version 1 and tries to save
curl -X PATCH localhost:8000/notes/1 -H 'X-User-Id: 1' \
  -H 'Content-Type: application/json' -d '{"version": 1, "body": "alice was here"}'
# → 409, "current" holds bob's text at version 2; alice's text is not saved

# other examples
curl localhost:8000/teams/1/notes?q=welcome -H 'X-User-Id: 1'
curl -X POST localhost:8000/teams/2/notes -H 'X-User-Id: 3' \
  -H 'Content-Type: application/json' -d '{"title": "Mockups", "body": "v2"}'
curl -X DELETE 'localhost:8000/notes/1?version=2' -H 'X-User-Id: 1'
```

## Design

Users belong to teams. Each note belongs to one team, and every member of that
team can read, edit and delete it. The full design, including the alternatives
weighed, is in
[docs/designs/team-notes-rest-service.md](docs/designs/team-notes-rest-service.md).

```text
users(id, name)          teams(id, name)
memberships(user_id, team_id)                 -- who is in which team
notes(id, team_id, title, body, version,
      created_by, updated_by, created_at, updated_at)
```

| Module | Role |
| --- | --- |
| `app/main.py` | App setup. Creates the schema and seed data on startup. |
| `app/db.py` | Schema, and one SQLite connection per request. |
| `app/auth.py` | `get_current_user`: the only code that reads `X-User-Id`. |
| `app/notes.py` | The note routes and their SQL. |
| `app/schemas.py` | Request and response models and their validation. |
| `app/seed.py` | Seed data (also `python -m app.seed`). |
| `tests/` | API tests, each on its own temporary database file. |

Two rules carry most of the correctness:

1. **Team isolation is inside the SQL.** Every note query joins on
   `memberships` for the caller. No route checks access in a separate step it
   could forget.
2. **The version check is one statement.**
   `UPDATE … WHERE id = ? AND version = ? AND <caller is in the team>`. SQLite
   applies one write at a time, so if two requests send the same version, only
   the first matches a row. If no row changes, a follow-up read decides
   between 404 (not visible) and 409 (stale version). Delete works the same
   way.

## Trade-offs

- **Identity is a header, not real auth.** Anyone can send any `X-User-Id`. I
  took this shortcut to keep the focus on the notes logic. `get_current_user`
  in `app/auth.py` is the only code that reads the header, so real auth (for
  example a signed token) would replace that one function.
- **Version in the body rather than `ETag`/`If-Match`.** `ETag` is the standard
  HTTP way. A body field is easier to try from `/docs` and curl, and shows the
  same idea.
- **Version check in SQL, not Python.** Reading the version, comparing it in
  Python and then writing lets two requests both pass. A single conditional
  `UPDATE` does not.
- **404 vs 403.** A note in another team returns 404, so outsiders cannot learn
  which note IDs exist. Team routes return 403, because team IDs are few and
  not secret.
- **Delete also needs the version**, so a delete cannot remove an edit the
  caller has not seen.
- **SQLite.** No server to install. It allows one writer at a time and one
  machine. Postgres would be the next step for more load or several instances.
- **Search is `LIKE`, not full-text search.** Fine at a few teams' size.
  Wildcards in the search text (`%`, `_`) are matched literally. Case is
  ignored for ASCII letters only, which is a SQLite limit.
- **Raw SQL, no ORM or migrations.** Five endpoints are easier to follow with
  the queries in view. Changing the schema means deleting `notes.db`.
- **All team members are equal**, with no owner or read-only roles. Deletes are
  permanent, with no trash or history.
- **No pagination** on the list endpoint. It returns all of a team's notes.

## Next steps

- Real authentication in place of the `X-User-Id` header.
- Endpoints to manage users, teams and memberships, plus roles within a team.
- Pagination (`limit`/`offset`) on the list endpoint.
- `ETag`/`If-Match` support.
- Postgres, and full-text search.
- Note history and soft delete.

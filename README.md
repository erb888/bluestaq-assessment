# bluestaq-assessment
Building a backend for a note taking service shared and used by several small teams. Users need somewhere to capture and work with their notes.

## Design Choices
1. The main design choice that i made and the most impactful in my opinion was using the Google Elephant Goldfish Model (EGM). In my opinion EGM is the best framework or setup for modern agentic development. Utilizing AI to go through a thorough design stage with the agent getting user review and verification at every step with design docs generated at the end.
2. The stack and technologies to use. I decided to go w/ a simple Python FastAPI/SQLite stack for 3 main reasons. 1 I'm very familiar with the stack and how easy it is to use. 2. Considering the time constraint i wanted to get something simple up and running as fast as possible. 3. It comes w/ native OpenAPI support so users can easily test the functionality of the app.
3. I waffled on adding a authentication step initially due to the time constrainst but i decided to go with it since i had enough time.

## Quickstart

Requires Python 3.11+.

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs to try every endpoint in the browser:

1. Call `POST /auth/login` with a seeded user, for example
   `{"username": "alice", "password": "alice-password"}`.
2. Copy `access_token` from the response.
3. Click **Authorize** and paste the token. Every request from `/docs` now
   sends it.

If you have a `notes.db` from before login was added, delete it once. The
`users` table gained a column, and there are no migrations.

Run the tests:

```sh
pytest
```

The database is a SQLite file, `notes.db`, created and seeded on startup. Set `NOTES_DB` to use a different path. To reset all data, stop the server and delete the file.

## Seed data

There are no endpoints to create users or teams, so these are created on
startup (re-running is safe):

| User | ID | Password | Teams |
| --- | --- | --- | --- |
| alice | 1 | `alice-password` | eng (1) |
| bob | 2 | `bob-password` | eng (1), design (2) |
| carol | 3 | `carol-password` | design (2) |

Note 1, "Welcome", belongs to `eng`. These passwords are demo credentials only.

## API

### Authentication

1. `POST /auth/login` with `{"username", "password"}` returns
   `{"access_token", "token_type": "bearer", "expires_at"}`.
2. Send the token on every other request as
   `Authorization: Bearer <access_token>`.
3. Tokens last 24 hours. `POST /auth/logout` revokes the token you send.

The server keeps only a SHA-256 hash of each token. Passwords are stored as
salted scrypt hashes.

| Method | Path | Body / query | Success |
| --- | --- | --- | --- |
| POST | `/auth/login` | `{"username", "password"}` | 200, token |
| POST | `/auth/logout` | | 204 |
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
| Bearer token missing, unknown, expired or logged out; or wrong login | 401 |
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
login() {  # prints an access token for user $1
  curl -s -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
    -d "{\"username\": \"$1\", \"password\": \"$1-password\"}" \
    | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])'
}
BOB=$(login bob); ALICE=$(login alice); CAROL=$(login carol)

# bob reads note 1 (version 1) and saves an edit
curl -X PATCH localhost:8000/notes/1 -H "Authorization: Bearer $BOB" \
  -H 'Content-Type: application/json' -d '{"version": 1, "body": "bob was here"}'
# → 200, "version": 2

# alice also read version 1 and tries to save
curl -X PATCH localhost:8000/notes/1 -H "Authorization: Bearer $ALICE" \
  -H 'Content-Type: application/json' -d '{"version": 1, "body": "alice was here"}'
# → 409, "current" holds bob's text at version 2; alice's text is not saved

# other examples
curl 'localhost:8000/teams/1/notes?q=welcome' -H "Authorization: Bearer $ALICE"
curl -X POST localhost:8000/teams/2/notes -H "Authorization: Bearer $CAROL" \
  -H 'Content-Type: application/json' -d '{"title": "Mockups", "body": "v2"}'
curl -X DELETE 'localhost:8000/notes/1?version=2' -H "Authorization: Bearer $ALICE"
curl -X POST localhost:8000/auth/logout -H "Authorization: Bearer $ALICE"
```

## Design

Users belong to teams. Each note belongs to one team, and every member of that
team can read, edit and delete it. The full design, including the alternatives
weighed, is in
[docs/designs/team-notes-rest-service.md](docs/designs/team-notes-rest-service.md).

```text
users(id, name, password_hash)                teams(id, name)
tokens(token_hash, user_id, expires_at)       -- active login tokens
memberships(user_id, team_id)                 -- who is in which team
notes(id, team_id, title, body, version,
      created_by, updated_by, created_at, updated_at)
```

| Module | Role |
| --- | --- |
| `app/main.py` | App setup. Creates the schema and seed data on startup. |
| `app/db.py` | Schema, and one SQLite connection per request. |
| `app/auth.py` | Login, logout, password hashing, and `get_current_user` (the only code that turns a token into a user). |
| `app/notes.py` | The note routes and their SQL. |
| `app/schemas.py` | Request and response models and their validation. |
| `app/seed.py` | Seed data (also `python -m app.seed`). |
| `tests/` | API tests, each on its own temporary database file. |

Two rules carry most of the correctness:

1. **Team isolation is inside the SQL.** Every note query joins on
   `memberships` for the caller. No route checks access in a separate step it could forget.
2. **The version check is one statement.**
   `UPDATE … WHERE id = ? AND version = ? AND <caller is in the team>`. SQLite
   applies one write at a time, so if two requests send the same version, only
   the first matches a row. If no row changes, a follow-up read decides
   between 404 (not visible) and 409 (stale version). Delete works the same
   way.

## Trade-offs

- **Stored random tokens rather than signed tokens (JWT).**
  - A login token is a random string. The server keeps its hash and expiry in
    the `tokens` table.
  - For: logout takes effect immediately, there is no signing secret to
    configure or leak, and no new dependency.
  - Against: every request does one extra database lookup, which a signed
    token would avoid.
  - `get_current_user` is still the only code that decides who the caller is.
- **No sign-up or password change.** Users come only from seed data, with
  published demo passwords. Login has no rate limit, so repeated password
  guessing is not slowed down beyond scrypt's own cost.
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

- Sign-up, password change, and rate limiting on login.
- Endpoints to manage users, teams and memberships, plus roles within a team.
- Pagination (`limit`/`offset`) on the list endpoint.
- `ETag`/`If-Match` support.
- Postgres, and full-text search.
- Note history and soft delete.

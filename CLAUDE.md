# bluestaq-assessment Blueprint

## System Overview
Backend for a note-taking service shared by several small teams (source:
[README.md](./README.md)). The code favours clarity and correctness, and the
README documents each trade-off.

Stack: Python 3.11+, FastAPI, stdlib `sqlite3` with raw SQL (no ORM), pytest.
Users belong to one or more teams. Each note belongs to exactly one team, and
every member of that team can read, edit and delete it. Callers log in with a
username and password (`POST /auth/login`) and send the returned random token
as `Authorization: Bearer <token>`. Tokens are stored hashed with a 24h expiry
and revoked by `POST /auth/logout`.

Run: `uvicorn app.main:app --reload`, then open `/docs`. Seed users (password
`<name>-password`): alice=1, bob=2 (both teams), carol=3. Seed teams: eng=1,
design=2.

## Subdirectories & System Boundaries
- `app/` (no contract file yet) - the service:
  - `app/main.py`: `app`, `lifespan` (runs `init_db` + `seed` on startup),
    `GET /health`.
  - `app/db.py`: `SCHEMA`, `db_path` (reads `NOTES_DB`, default `notes.db`),
    `connect`, `init_db`, `get_db` (one connection per request), `utc_now`.
  - `app/auth.py`: `router` with `POST /auth/login` and `POST /auth/logout`;
    `hash_password` / `verify_password` (stdlib scrypt), `hash_token`
    (SHA-256), `TOKEN_TTL`; `get_current_user`, the only code that turns a
    bearer token into a user ID.
  - `app/notes.py`: `router` with five routes:
    - `POST /teams/{team_id}/notes`
    - `GET /teams/{team_id}/notes?q=`
    - `GET /notes/{note_id}`
    - `PATCH /notes/{note_id}`
    - `DELETE /notes/{note_id}?version=`

    Helpers: `require_team_member`, `fetch_visible_note`,
    `explain_failed_write`, `escape_like`.
  - `app/schemas.py`: `NoteCreate`, `NoteUpdate`, `NoteOut`, `ConflictOut`,
    `LoginIn`, `TokenOut`; `TITLE_MAX = 200`, `BODY_MAX = 1_000`.
  - `app/seed.py`: `seed` (fixed IDs; users hashed and inserted only when
    missing); also `python -m app.seed`.
- `tests/` - API tests. `conftest.py` gives each test its own temporary
  database file through `NOTES_DB` and logs in every seeded user
  (`as_user(client, user_id)` returns the bearer header). `test_notes.py`
  covers each notes status code; `test_auth.py` covers login, logout, expiry
  and token hashing.
- `docs/designs/` - the approved design:
  [team-notes-rest-service.md](./docs/designs/team-notes-rest-service.md).
  It covers goals, data model, alternatives rejected, and the file-by-file
  plan.
- `agents/skills/` - project context skill:
  [bluestaq-assessment-elephant/SKILL.md](./agents/skills/bluestaq-assessment-elephant/SKILL.md).

## Global Invariants
- **Team isolation is inside the SQL.** Every note query joins on, or filters
  by, `memberships` for the caller (`fetch_visible_note`, the `IN_MY_TEAMS`
  clause in `app/notes.py`). Do not check access in a separate step.
- **Version checks are one statement.** `update_note` and `delete_note` use
  `WHERE id = ? AND version = ? AND <caller in team>`. Never read the version,
  compare in Python, then write. If no row matches, `explain_failed_write`
  returns 404 (note not visible) or 409 (stale version).
- **Status codes:**

  | Case | Status |
  | --- | --- |
  | Bearer token missing, unknown, expired or revoked; failed login | 401 |
  | Team route, caller not a member | 403 |
  | Note missing or in another team | 404 |
  | Stale version | 409, body `{"detail", "current"}` |
  | Validation error | 422 |

- **Never store raw tokens or passwords.** Tokens are stored as SHA-256
  hashes; passwords as salted scrypt hashes. Failed logins return the same
  401 whether the user exists or not.
- **Endpoints are plain `def`, not `async def`.** Never share a `sqlite3`
  connection across requests.
- **No migrations.** A schema change means deleting `notes.db`.
- **Tests never use `:memory:`.** Each per-request connection would get its own
  empty database.
- **Behaviour changes update `README.md` and the tests in the same change.**

## Global Side Effects
- Reads and writes the SQLite file at `NOTES_DB` (default `./notes.db`, which
  is gitignored).
- Startup creates the schema and inserts seed rows. Both are safe to repeat.
- Login inserts a `tokens` row (and deletes that user's expired tokens);
  logout deletes one.
- No network calls other than serving HTTP.

## System Verification
- Run: `pytest`

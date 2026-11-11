# Team Notes REST Service

*   **Author:** Erbold Lockhart
*   **Status:** Proposed
*   **Date:** 2026-11-11

--------------------------------------------------------------------------------

## Overview

A REST backend where people on several small teams keep shared notes. A user
can belong to more than one team. Each note belongs to exactly one team, and
every member of that team can read, edit and delete it. The service is written
in Python with FastAPI and stores data in SQLite, so it runs with no database
server.

## The Problem

Small teams need one place to write notes and share them with teammates. Two
problems come up as soon as notes are shared:

1.  **Who can see what.** A note written for one team must not be visible to
    another team. A user in two teams must see both teams' notes and nothing
    else.
2.  **Lost edits.** When two teammates edit the same note at the same time, a
    simple service keeps whichever save arrives last and silently discards the
    other. Neither person learns their work was lost.

The service solves the first with a single membership rule enforced inside
every database query: "the caller must be a member of the note's team." It
solves the second with a version number on every note. A client sends back the
version it last read. If someone else has saved since then, the service refuses
the write with `409 Conflict` and returns the current note, so the client can
merge and retry.

Real login is out of scope for the time budget. The caller says who they are
in an `X-User-Id` header, and the service checks that the user exists. Anyone
can claim to be anyone, so the README states this as the main known gap. All
identity handling lives in one function, so real authentication would replace
that function and leave the rest alone.

## Goals

*   **Runs on first try.** A judge with Python 3.11+ can go from a fresh clone
    to a working API with three commands (create a virtual environment, install
    pinned requirements, start the server). No manual data setup is needed,
    because fixed users, teams and one sample note are seeded at startup.
*   **Notes API.** Create, read, update and delete notes, and list a team's
    notes with a case-insensitive text search over title and body.
*   **Team isolation.** No request can read, change or list a note outside the
    caller's teams. A note in another team returns 404, the same as a note
    that does not exist, so other teams' note IDs are not exposed.
*   **No silent overwrites.** Update and delete both require the version the
    client last read. A stale version returns `409 Conflict`. The check and the
    write happen in one SQL statement, so two requests that arrive at the same
    moment cannot both succeed.
*   **Predictable status codes.** Every error case maps to one documented
    status code (401, 403, 404, 409, 422), and each one has a test.
*   **Tests run in seconds.** `pytest` finishes in a few seconds, with each test
    using its own temporary database file.
*   **Trade-offs written down.** The README has a section that names each
    shortcut, explains why it was taken, and says what would replace it.

## Non-Goals

*   **Real authentication** (passwords, tokens, sessions). Replaced by the
    header stand-in described above.
*   **Endpoints to manage users, teams or memberships.** Seed data covers the
    assessment's needs.
*   **Roles inside a team** (owner, viewer). All members have equal rights.
*   **Private notes or per-note sharing lists.** A note is visible to its whole
    team and no one else.
*   **Folders, tags, version history, soft delete or a trash bin.**
*   **Real-time collaboration** (live cursors, merged edits).
*   **Full-text search ranking** (SQLite FTS5). A simple substring match is
    enough at a few teams' scale.
*   **Database migrations or an ORM.** Changing the schema means deleting the
    database file.
*   **Production deployment concerns**: Docker, multiple server instances,
    request-ID logging. Docker is added only if 15 minutes remain at the end.

## Critical User Journeys (CUJs)

### CUJ 1: Judge runs the service and creates a note

*   **Given**: A fresh clone, Python 3.11+, no `notes.db` file.
*   **When**: The judge installs requirements, starts the server, opens
    `/docs`, and sends `POST /teams/1/notes` with `X-User-Id: 1`.
*   **Then**: The database file and seed data are created on startup. The
    response is `201` with the note, `version: 1`, and `created_by: 1`.

### CUJ 2: Two teammates edit the same note

*   **Given**: Alice (1) and Bob (2) are both in team `eng`. Both have read
    note 5 at `version: 3`.
*   **When**: Alice sends `PATCH /notes/5` with `version: 3`, then Bob sends
    `PATCH /notes/5` with `version: 3`.
*   **Then**: Alice gets `200` with `version: 4`. Bob gets `409` with the
    current note (`version: 4`, Alice's text). Bob's text is not saved.

### CUJ 3: User tries to read another team's note

*   **Given**: Carol (3) is only in team `design`. Note 5 belongs to `eng`.
*   **When**: Carol sends `GET /notes/5`.
*   **Then**: `404`, the same response as for a note ID that does not exist.

## Technical Plan (Architecture)

### Request flow

Every request passes through the same three steps. Each step lives in one
place in the code.

```text
HTTP request
    │
    ▼
┌──────────────────────────┐
│ get_db (dependency)      │  opens one sqlite3 connection for this request,
│                          │  turns on foreign keys, closes it afterwards
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│ get_current_user         │  reads X-User-Id; missing, non-numeric or
│ (dependency)             │  unknown user → 401
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│ notes route handler      │  runs SQL that joins on memberships, so the
│                          │  team check is part of every query
└────────────┬─────────────┘
             ▼
        SQLite file (notes.db, path from NOTES_DB env var)
```

The handlers are plain `def` functions, not `async def`. FastAPI runs plain
functions on a thread pool, so a blocking `sqlite3` call does not stall other
requests. Because requests run on different threads, each request opens its
own connection rather than sharing one.

### Data model

```text
users        (id PK, name)
teams        (id PK, name)
memberships  (user_id FK→users, team_id FK→teams, PK(user_id, team_id))
notes        (id PK, team_id FK→teams, title, body, version,
              created_by FK→users, updated_by FK→users,
              created_at, updated_at)
index on notes(team_id)
```

*   `version` starts at 1 and goes up by one on every successful update.
*   Timestamps are stored and returned as UTC ISO-8601 text.
*   `team_id` is set at creation and never changes.
*   Deleting a team removes its notes and memberships (`ON DELETE CASCADE`).
    No endpoint deletes teams. The cascade keeps the schema consistent if one
    is added later.

The schema is a list of `CREATE TABLE IF NOT EXISTS` statements, run once when
the app starts. Seed data is inserted with `INSERT OR IGNORE` on fixed IDs, so
restarting the server does not duplicate it:

| User | Teams |
| --- | --- |
| alice (1) | eng (1) |
| bob (2) | eng (1), design (2) |
| carol (3) | design (2) |

Plus one sample note in `eng`.

### API

| Method | Path | Body / query | Success |
| --- | --- | --- | --- |
| POST | `/teams/{team_id}/notes` | `{title, body}` | 201, note |
| GET | `/teams/{team_id}/notes` | `?q=` optional | 200, list of notes |
| GET | `/notes/{note_id}` | — | 200, note |
| PATCH | `/notes/{note_id}` | `{version, title?, body?}` | 200, note with new version |
| DELETE | `/notes/{note_id}` | `?version=` | 204 |

A note response contains `id, team_id, title, body, version, created_by,
updated_by, created_at, updated_at`.

Validation:

*   `title` is 1-200 characters.
*   `body` is at most 100,000 characters and may be empty.
*   A PATCH must include `version` and at least one of `title` or `body`.
    Otherwise it returns 422.

### Status codes

| Case | Status |
| --- | --- |
| `X-User-Id` missing, not a number, or no such user | 401 |
| List or create in a team the caller is not in | 403 |
| Note does not exist, or belongs to a team the caller is not in | 404 |
| Update or delete with a stale version | 409, body is the current note |
| Invalid body or query | 422 |

Two different answers for "not your team" are on purpose. Team IDs are few
and not secret, so 403 on team routes tells the caller plainly what is wrong.
Note IDs would let an outsider probe which notes exist, so note routes answer
404.

### Version check (no silent overwrites)

An update is one statement. The version check and the membership check are
both in its `WHERE` clause:

```sql
UPDATE notes
SET title = COALESCE(:title, title), body = COALESCE(:body, body),
    version = version + 1, updated_by = :user, updated_at = :now
WHERE id = :id AND version = :version
  AND team_id IN (SELECT team_id FROM memberships WHERE user_id = :user)
```

SQLite runs one write at a time, so if two requests send the same version,
only the first one matches a row. If the statement changes no rows, one
follow-up query finds out why:

*   The note is not visible to the caller (missing or another team) → 404.
*   The note is visible, so the version must be stale → 409 with the current
    note.

Delete works the same way, with `DELETE ... WHERE id AND version AND team
check`.

### Search

`q` matches any note whose title or body contains the text, ignoring case.
The text is always passed as a query parameter, never pasted into SQL. Before
matching, `\`, `%` and `_` are escaped and the query uses `ESCAPE '\'`, so
searching for `50%` finds the literal text "50%". SQLite ignores case only for
ASCII letters; the README states this. Results are sorted newest edit first
(`updated_at DESC, id`), so the order is stable.

### Code layout

```text
app/
  main.py      FastAPI app, lifespan (create schema + seed), routers
  db.py        get_db dependency, schema SQL, connection setup
  auth.py      get_current_user dependency
  seed.py      seed data; also runnable as `python -m app.seed`
  schemas.py   NoteCreate, NoteUpdate, NoteOut (Pydantic)
  notes.py     the five note routes and their SQL
tests/
  conftest.py  per-test temporary database, TestClient
  test_notes.py
```

A flat layout of six modules suits five endpoints. Splitting into separate
service and repository layers would add files without making anything clearer
at this size.

## Alternatives Considered

### Alternative A: Last write wins

*   **Pros**: No version field. Clients do not need to track anything. About 15
    minutes less work.
*   **Cons**: When two teammates save at the same time, one person's edit is
    lost and neither is told.
*   **Reason for Rejection**: Rejected by author: silent data loss is the main
    risk of shared notes, and the version check costs little.

### Alternative B: Version check in Python (read, compare, then write)

*   **Pros**: Easy to read. The logic sits in Python rather than in SQL.
*   **Cons**: Two requests can both read version 3, both pass the comparison,
    and both write. The second write still overwrites the first.
*   **Reason for Rejection**: Rejected by author: it does not prevent the
    problem it exists to prevent. A single conditional `UPDATE` does.

### Alternative C: `ETag` / `If-Match` headers instead of a `version` field

*   **Pros**: The standard HTTP way to do this. Clients and proxies understand
    it, and a stale write gets `412 Precondition Failed`.
*   **Cons**: Harder to try by hand from `/docs` or curl, because the judge has
    to copy a header between requests. More code to parse and set headers.
*   **Reason for Rejection**: Rejected by author: the version field in the body
    shows the same idea and is easier to demo in the time available. The README
    names `ETag` as the standard alternative.

### Alternative D: Real authentication (passwords or signed tokens)

*   **Pros**: Callers cannot claim to be someone else.
*   **Cons**: About 30-45 minutes for password hashing, token issue and
    checking, plus tests. Little of it relates to the notes problem.
*   **Reason for Rejection**: Rejected by author: it does not fit the time
    budget. Identity is in one function (`get_current_user`), so adding real
    auth later changes only that function.

### Alternative E: Private notes or per-note share lists

*   **Pros**: Finer control over who sees each note.
*   **Cons**: Every query needs a second access rule, and the API needs share
    endpoints. More rules to test, and more chances for a leak.
*   **Reason for Rejection**: Rejected by author: team ownership answers "shared
    by small teams" with one rule.

### Alternative F: SQLAlchemy or SQLModel with Alembic migrations

*   **Pros**: Models in Python classes. Schema changes become migration files.
    Easier to move to Postgres.
*   **Cons**: Setup and configuration time. More concepts for a reader to
    follow for five endpoints.
*   **Reason for Rejection**: Rejected by author: raw `sqlite3` with a short
    schema file is quicker to write and lets judges see every query directly.

### Alternative G: Layered packages (routers, services, repositories)

*   **Pros**: Familiar structure that grows well.
*   **Cons**: About 15 files for five endpoints. A reader jumps between files
    to follow one request.
*   **Reason for Rejection**: Rejected by author: at this size it reads as
    over-engineering. Six flat modules cover it.

### Alternative H: One shared SQLite connection

*   **Pros**: Simplest setup.
*   **Cons**: Requests run on several threads. `sqlite3` either raises an error
    for using a connection from the wrong thread or, with that check off, mixes
    one request's transaction with another's.
*   **Reason for Rejection**: Rejected by author: one connection per request
    avoids both problems for little cost.

### Alternative I: In-memory test database (`:memory:`)

*   **Pros**: Fast, and leaves no files behind.
*   **Cons**: Each new connection to `:memory:` gets its own empty database, so
    per-request connections would see no tables.
*   **Reason for Rejection**: Rejected by author: a temporary file per test is
    just as fast at this size and works with per-request connections.

### Alternative J: 403 for notes in other teams

*   **Pros**: Tells the caller exactly why the request failed.
*   **Cons**: Tells outsiders that a note with that ID exists.
*   **Reason for Rejection**: Rejected by author: note routes return 404.
    Team routes keep 403, because team IDs are not secret.

### Alternative K: Delete without a version

*   **Pros**: Simpler API. A client can delete without reading first.
*   **Cons**: Deletes a note that a teammate edited a moment earlier, without
    either person seeing the edit.
*   **Reason for Rejection**: Rejected by author: same reasoning as Alternative
    A. If time runs short, the fallback is to make `version` optional on delete
    and document it.

### Alternative L: `async def` handlers with `sqlite3`

*   **Pros**: Looks modern. Matches many FastAPI examples.
*   **Cons**: `sqlite3` calls block. Inside `async def` they hold up every other
    request on the event loop.
*   **Reason for Rejection**: Rejected by author: plain `def` handlers run on a
    thread pool, which suits a blocking driver.

### Alternative M: Docker as the main way to run it

*   **Pros**: Same environment everywhere.
*   **Cons**: Debugging an image under time pressure risks the "must run"
    requirement. Judges may not have Docker running.
*   **Reason for Rejection**: Rejected by author: plain Python is the main path.
    Docker is added only if 15 minutes remain.

--------------------------------------------------------------------------------

## Non-Functional Requirements

*   **Security**: Identity can be spoofed by design (see Alternative D). All
    SQL uses bound parameters. No secrets exist to manage.
*   **Performance**: Sized for a few teams. One SQLite writer at a time is
    enough. The index on `notes(team_id)` keeps list queries to one team's rows.
*   **Rollout**: None. Schema changes mean deleting `notes.db`, which is
    recreated and reseeded on the next start.

### Future Improvements

*   Real authentication that replaces `get_current_user`.
*   Postgres, for more than one writer and several server instances.
*   `ETag` / `If-Match` in place of the body `version`.
*   Pagination (`limit` / `offset`) on the team list.
*   Full-text search with SQLite FTS5 or Postgres.
*   Endpoints to manage users, teams and memberships, plus roles inside a team.
*   Note history and soft delete.

--------------------------------------------------------------------------------

## Detailed Implementation Plan

Build order follows the timebox: files 1-8 (0:00-1:15), files 9-10
(1:15-1:50), files 11-12 (1:50-2:15), then a fresh-clone run (2:15-2:30).

### Target Files to Create/Modify

#### 1. `requirements.txt` (Create)

*   **Type / Scope**: Dependency list.
*   **Proposed Changes**: Pin exact versions of `fastapi`, `uvicorn`, `pytest`
    and `httpx` (needed by FastAPI's `TestClient`), using the versions that are
    installed when the code is written. Pydantic v2 comes in with FastAPI. Exact
    pins mean the judge installs what was tested.

#### 2. `.gitignore` (Create)

*   **Type / Scope**: Repository config.
*   **Proposed Changes**: Ignore `.venv/`, `__pycache__/`, `.pytest_cache/` and
    `*.db`, so a local database is never committed and a fresh clone always
    starts from seed data.

#### 3. `app/__init__.py` (Create)

*   **Type / Scope**: Package marker.
*   **Proposed Changes**: Empty. Makes `app` importable as `app.main` and lets
    `python -m app.seed` work.

#### 4. `app/db.py` (Create)

*   **Type / Scope**: Database access.
*   **Proposed Changes**:
    *   `db_path() -> str`: returns `os.environ.get("NOTES_DB", "notes.db")`.
        It is read on every call, not at import time, so tests can point it at
        a temporary file.
    *   `connect() -> sqlite3.Connection`: opens `db_path()`, sets
        `row_factory = sqlite3.Row`, runs `PRAGMA foreign_keys = ON`.
    *   `SCHEMA`: the `CREATE TABLE IF NOT EXISTS` statements and the
        `notes(team_id)` index from the Technical Plan. `notes.title` and
        `notes.body` are `TEXT NOT NULL`. `version` is
        `INTEGER NOT NULL DEFAULT 1`.
    *   `init_db()`: opens a connection and runs `SCHEMA` with
        `executescript`.
    *   `get_db()`: a FastAPI `yield` dependency. It yields a connection from
        `connect()` and closes it in `finally`.
    *   `utc_now() -> str`: `datetime.now(timezone.utc).isoformat()`. Every
        timestamp has the same format, so sorting the text sorts by time.
    *   Writes are wrapped in `with conn:`, which commits on success and rolls
        back on an exception.

#### 5. `app/seed.py` (Create)

*   **Type / Scope**: Seed data.
*   **Proposed Changes**:
    *   `seed(conn)` inserts users alice (1), bob (2) and carol (3), and teams
        eng (1) and design (2).
    *   It adds memberships: alice→eng, bob→eng, bob→design, carol→design.
    *   It adds sample note 1 in eng: title "Welcome", created by alice,
        version 1.
    *   All inserts use `INSERT OR IGNORE` with fixed IDs, so running it twice
        changes nothing.
    *   An `if __name__ == "__main__"` block runs `init_db()` then `seed()`.

#### 6. `app/auth.py` (Create)

*   **Type / Scope**: Identity.
*   **Proposed Changes**:
    *   `get_current_user(x_user_id: str | None = Header(None), db = Depends(get_db)) -> int`.
    *   The header is taken as a string, so this function decides what a bad
        value means:
        *   If the header is missing, not all digits, or names a user ID that is
            not in `users`, it raises `HTTPException(401)`.
        *   Otherwise it returns the user ID.
    *   Declaring it as a `Header` makes `/docs` show an input box for it.
    *   A comment on the function says this is the one place to replace with
        real authentication.

#### 7. `app/schemas.py` (Create)

*   **Type / Scope**: Request and response models (Pydantic v2).
*   **Proposed Changes**:
    *   `NoteCreate`: `title: str` (1-200 characters), `body: str` (0-100,000
        characters, default `""`).
    *   `NoteUpdate`: `version: int` (≥ 1), `title: str | None` (1-200),
        `body: str | None` (≤ 100,000). A model validator raises an error if
        both `title` and `body` are `None`, and FastAPI turns that into 422.
        An explicit `null` counts as "not sent".
    *   `NoteOut`: `id, team_id, title, body, version, created_by, updated_by,
        created_at, updated_at`.
    *   `ConflictOut`: `detail: str`, `current: NoteOut`. This is the 409 body.
        It follows FastAPI's `detail` convention and carries the current note.

#### 8. `app/notes.py` (Create)

*   **Type / Scope**: API routes (`APIRouter`).
*   **Proposed Changes**: Every route depends on `get_db` and
    `get_current_user`. Every route is a plain `def`.
    *   `require_team_member(db, user_id, team_id)`: if no `memberships` row
        matches, it raises 403. A team that does not exist also gives 403,
        because the caller is not a member of it.
    *   `fetch_visible_note(db, user_id, note_id) -> Row | None`: selects the
        note joined to `memberships` for this user. `None` means "missing or
        not your team", which the caller turns into 404.
    *   `POST /teams/{team_id}/notes` → 201 `NoteOut`. It calls
        `require_team_member`, then inserts with `version = 1`,
        `created_by = updated_by = user`, both timestamps = `utc_now()`. It
        returns the inserted row.
    *   `GET /teams/{team_id}/notes?q=` → 200 `list[NoteOut]`:
        *   It calls `require_team_member`.
        *   With no `q`, it lists all of the team's notes.
        *   With `q`, it escapes `\`, `%` and `_`, wraps the text in `%…%`, and
            matches `title LIKE ? ESCAPE '\' OR body LIKE ? ESCAPE '\'`.
        *   Results are ordered by `updated_at DESC, id`.
    *   `GET /notes/{note_id}` → 200 `NoteOut`. It calls `fetch_visible_note`,
        and `None` gives 404.
    *   `PATCH /notes/{note_id}` → 200 `NoteOut`:
        *   It runs the single conditional `UPDATE` from the Technical Plan.
        *   If `rowcount == 1`, it reads the note back and returns it.
        *   Otherwise it calls `fetch_visible_note`. `None` gives 404. A row
            means the version is stale, so it returns a 409 `ConflictOut` with
            that row.
    *   `DELETE /notes/{note_id}?version=` → 204. `version` is a required query
        integer. It runs `DELETE … WHERE id AND version AND team check`, and
        no row deleted is handled the same way as in PATCH (404 or 409).
    *   `get_me` (`GET /me`, returning the caller's ID, name and teams) is
        optional and only built if time remains.

#### 9. `app/main.py` (Create)

*   **Type / Scope**: Application entry point.
*   **Proposed Changes**:
    *   A `lifespan` context manager runs `init_db()` and `seed()` at startup.
    *   It creates `app = FastAPI(title="Team Notes", lifespan=lifespan)`.
    *   It includes the notes router.
    *   It adds `GET /health`, which returns `{"status": "ok"}`.
    *   Run with `uvicorn app.main:app --reload`.

#### 10. `tests/conftest.py` (Create)

*   **Type / Scope**: Test fixtures.
*   **Proposed Changes**:
    *   A `client` fixture uses `monkeypatch` to set `NOTES_DB` to a file in
        `tmp_path`.
    *   It opens `TestClient(app)` as a context manager, so lifespan creates
        the schema and seed data in that file, and yields the client.
    *   Each test gets a new database.
    *   A helper `as_user(id)` returns the header dict.

#### 11. `tests/test_notes.py` (Create)

*   **Type / Scope**: API tests, one per status-code case plus the key
    behaviours. Each test asserts:
    1.  Create in own team → 201, `version` 1, `created_by` set.
    2.  Missing header, non-numeric header, unknown user → 401 (one
        parametrized test).
    3.  Create or list in a team the caller is not in → 403.
    4.  Get a note in another team → 404, and a note ID that does not exist →
        404.
    5.  Update with the current version → 200, `version` goes up by one,
        `updated_by` changes.
    6.  Two updates sending the same version → first 200, second 409, and the
        409 body's `current.version` is the new version. The second update's
        text is not saved.
    7.  Delete with a stale version → 409. Delete with the current version →
        204, and a following GET → 404.
    8.  PATCH with neither title nor body → 422. Empty title → 422.
    9.  Search `q` matches title and body, ignoring ASCII case.
    10. Search for `%` matches only notes that contain a literal `%`.
    11. Bob (in both teams) can list both teams' notes; Carol cannot see eng's
        note.

#### 12. `README.md` (Modify)

*   **Type / Scope**: Documentation for judges.
*   **Proposed Changes**: Keep the existing first two lines. Add, in order:
    *   **Quickstart**: three commands, plus `pytest`.
    *   **Seed data**: the user and team table.
    *   **API**: endpoint table and status-code table, plus curl examples. One
        example shows a stale update returning 409.
    *   **Design**: the data model and a module map.
    *   **Trade-offs**: one line each:
        *   Spoofable header.
        *   Atomic version check.
        *   404 vs 403.
        *   Body version vs `ETag`.
        *   SQLite single writer.
        *   `LIKE` vs FTS5 and ASCII-only case folding.
        *   Equal team members.
        *   Hard delete.
        *   Raw SQL, no migrations.
    *   **Next steps**: the Future Improvements list.

#### 13. `CLAUDE.md` (Modify)

*   **Type / Scope**: Agent contract file.
*   **Proposed Changes**: Replace the `<test-command>` placeholder with
    `pytest`. Rerun `/egm:egm-bootstrap . target_filename=CLAUDE.md` after the
    code exists, if time allows.

### Verification Plan

*   **Compilation/Build**: `pip install -r requirements.txt` in a new virtual
    environment succeeds.
*   **Unit Tests**: `pytest` passes, all 11 tests, in a few seconds.
*   **Static Analysis & Linting**: Not configured. Skipped for the time budget.
*   **Test Coverage Requirement**: Every row of the status-code table has at
    least one test. No percentage target.
*   **E2E/Integration**: From a fresh clone in a new directory:
    1.  Follow the README quickstart exactly.
    2.  Open `/docs`.
    3.  Run the README curl examples, including the 409 example.

--------------------------------------------------------------------------------

<!-- Provenance: Indicates initial structural drafting via EGM. -->

*Drafted with EGM*

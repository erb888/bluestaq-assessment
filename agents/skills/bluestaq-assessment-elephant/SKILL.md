---
name: bluestaq-assessment-elephant
description: Project context for the bluestaq-assessment Team Notes REST service (Python, FastAPI, SQLite). Use before reading, changing, testing or explaining any code, docs or design in this repository.
---

# bluestaq-assessment: Team Notes REST service

## What this project is

A REST backend for a note-taking service shared by several small teams.
Simple, readable code and honest documentation of trade-offs matter more than
extra features.

- **Stack:** Python 3.11+, FastAPI, stdlib `sqlite3` with raw SQL (no ORM),
  pytest.
- **Model:** users belong to one or more teams. Each note belongs to exactly
  one team, and every member of that team can read, edit and delete it.
- **Identity:** `POST /auth/login` (seeded users, password `<name>-password`)
  returns a random bearer token. Send it as `Authorization: Bearer <token>`.
  Tokens are stored hashed, expire after 24h, and `POST /auth/logout` revokes
  them.
- **Run:** `uvicorn app.main:app --reload`, then open `/docs`.
- **Test:** `pytest`, from the repo root.

## Rules to keep

- **Team isolation lives in SQL.** Every note query joins on (or filters by)
  `memberships` for the caller. Do not add a route that checks access in a
  separate step.
- **The version check is one statement.** Update and delete use
  `... WHERE id = ? AND version = ? AND <caller in team>`. Never read the
  version, compare it in Python, then write; two requests could both pass.
- **Status codes are fixed:**

  | Case | Status |
  | --- | --- |
  | Bearer token missing, unknown, expired or revoked; failed login | 401 |
  | Team route, caller not a member | 403 |
  | Note missing or in another team | 404 |
  | Stale version | 409, body `{"detail", "current"}` |
  | Validation error | 422 |

- **Only `get_current_user` in `app/auth.py` decides who the caller is.**
  Routes depend on it; they never read headers themselves.
- **Never store raw tokens or passwords.** Tokens are SHA-256 hashed;
  passwords are salted scrypt hashes. A failed login gives the same 401
  whether or not the user exists.
- **Endpoints are plain `def`, not `async def`**, with one SQLite connection
  per request (`get_db`). Tests use a temporary database file per test, never
  `:memory:`.
- **The schema is in `app/db.py`, with no migrations.** A schema change means
  deleting `notes.db`.
- **Docs must match the code.** If you change behaviour, update the README
  (API, status codes, trade-offs) and the tests in the same change.

## Context to read

Read these in this order, as the task needs them:

1. [README.md](../../../README.md): quickstart, seed users and teams, API and
   status codes, trade-offs, next steps.
2. [docs/designs/team-notes-rest-service.md](../../../docs/designs/team-notes-rest-service.md):
   the approved design. It covers goals, non-goals, user journeys, the data
   model, alternatives rejected and why, and the file-by-file plan.
3. [app/notes.py](../../../app/notes.py): all routes, the access rule and the
   version check.
4. [app/auth.py](../../../app/auth.py) and [app/db.py](../../../app/db.py):
   login, tokens, password hashing, connections and the schema.
5. [app/schemas.py](../../../app/schemas.py): request and response models and
   their length limits.
6. [tests/test_notes.py](../../../tests/test_notes.py) and
   [tests/test_auth.py](../../../tests/test_auth.py): the expected behaviour,
   with one test for each status code.
7. [CLAUDE.md](../../../CLAUDE.md): the repository contract summary.

Out of scope, unless the user asks:
- Sign-up, password change, login rate limiting.
- Endpoints for users, teams or memberships.
- Roles inside a team.
- Folders, tags, history.
- Real-time editing.
- Full-text search.
- An ORM or migrations.

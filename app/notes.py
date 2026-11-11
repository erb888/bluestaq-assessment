"""Note routes.

Access rule: the caller must be a member of the note's team. The rule is part
of every note query (a join or subquery on memberships), so no route can
forget it.

Status policy: team routes answer 403 when the caller is not a member (team
IDs are not secret). Note routes answer 404 for a note in another team, the
same as a missing note, so outsiders cannot probe which note IDs exist.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse

from app.auth import get_current_user
from app.db import get_db, utc_now
from app.schemas import ConflictOut, NoteCreate, NoteOut, NoteUpdate

router = APIRouter(tags=["notes"])

NOTE_COLUMNS = (
    "n.id, n.team_id, n.title, n.body, n.version, "
    "n.created_by, n.updated_by, n.created_at, n.updated_at"
)

# Matches only notes in a team the user (:user) belongs to.
IN_MY_TEAMS = "team_id IN (SELECT team_id FROM memberships WHERE user_id = :user)"


def require_team_member(db: sqlite3.Connection, user_id: int, team_id: int) -> None:
    row = db.execute(
        "SELECT 1 FROM memberships WHERE user_id = ? AND team_id = ?",
        (user_id, team_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this team")


def fetch_visible_note(db: sqlite3.Connection, user_id: int, note_id: int) -> sqlite3.Row | None:
    """The note, or None if it does not exist or is in another team."""
    return db.execute(
        f"""
        SELECT {NOTE_COLUMNS} FROM notes n
        JOIN memberships m ON m.team_id = n.team_id AND m.user_id = ?
        WHERE n.id = ?
        """,
        (user_id, note_id),
    ).fetchone()


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Note not found")


def explain_failed_write(db: sqlite3.Connection, user_id: int, note_id: int) -> JSONResponse:
    """A conditional write matched no row: decide between 404 and 409."""
    current = fetch_visible_note(db, user_id, note_id)
    if current is None:
        raise not_found()
    body = ConflictOut(
        detail="Version conflict: the note was changed since you read it",
        current=NoteOut(**current),
    )
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body.model_dump())


def escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.post(
    "/teams/{team_id}/notes",
    response_model=NoteOut,
    status_code=status.HTTP_201_CREATED,
)
def create_note(
    team_id: int,
    payload: NoteCreate,
    user_id: int = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> NoteOut:
    require_team_member(db, user_id, team_id)
    now = utc_now()
    with db:
        cursor = db.execute(
            """
            INSERT INTO notes
                (team_id, title, body, version, created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (team_id, payload.title, payload.body, user_id, user_id, now, now),
        )
    return NoteOut(**fetch_visible_note(db, user_id, cursor.lastrowid))


@router.get("/teams/{team_id}/notes", response_model=list[NoteOut])
def list_notes(
    team_id: int,
    q: str | None = Query(None, description="Case-insensitive text to find in title or body"),
    user_id: int = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> list[NoteOut]:
    require_team_member(db, user_id, team_id)
    sql = f"SELECT {NOTE_COLUMNS} FROM notes n WHERE n.team_id = ?"
    params: list = [team_id]
    if q:
        # Escape LIKE wildcards so "50%" finds the literal text "50%".
        pattern = f"%{escape_like(q)}%"
        sql += " AND (n.title LIKE ? ESCAPE '\\' OR n.body LIKE ? ESCAPE '\\')"
        params += [pattern, pattern]
    sql += " ORDER BY n.updated_at DESC, n.id"
    return [NoteOut(**row) for row in db.execute(sql, params)]


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(
    note_id: int,
    user_id: int = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> NoteOut:
    row = fetch_visible_note(db, user_id, note_id)
    if row is None:
        raise not_found()
    return NoteOut(**row)


@router.patch(
    "/notes/{note_id}",
    response_model=NoteOut,
    responses={status.HTTP_409_CONFLICT: {"model": ConflictOut}},
)
def update_note(
    note_id: int,
    payload: NoteUpdate,
    user_id: int = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    # The version check, team check and write are one statement, so two
    # requests holding the same version cannot both succeed.
    with db:
        cursor = db.execute(
            f"""
            UPDATE notes
            SET title = COALESCE(:title, title),
                body = COALESCE(:body, body),
                version = version + 1,
                updated_by = :user,
                updated_at = :now
            WHERE id = :id AND version = :version AND {IN_MY_TEAMS}
            """,
            {
                "title": payload.title,
                "body": payload.body,
                "user": user_id,
                "now": utc_now(),
                "id": note_id,
                "version": payload.version,
            },
        )
    if cursor.rowcount == 0:
        return explain_failed_write(db, user_id, note_id)
    return NoteOut(**fetch_visible_note(db, user_id, note_id))


@router.delete(
    "/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={status.HTTP_409_CONFLICT: {"model": ConflictOut}},
)
def delete_note(
    note_id: int,
    version: int = Query(ge=1, description="The version you last read"),
    user_id: int = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    # Same conditional write as update, so a delete cannot discard an edit
    # the caller has not seen.
    with db:
        cursor = db.execute(
            f"DELETE FROM notes WHERE id = :id AND version = :version AND {IN_MY_TEAMS}",
            {"id": note_id, "version": version, "user": user_id},
        )
    if cursor.rowcount == 0:
        return explain_failed_write(db, user_id, note_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Caller identity.

This is a deliberate stand-in for real authentication: the caller states who
they are in the X-User-Id header and we only check that the user exists, so
anyone can claim to be anyone. It is the single place to replace with real
auth (e.g. verifying a signed token); nothing else reads the header.
"""

import re
import sqlite3

from fastapi import Depends, Header, HTTPException, status

from app.db import get_db

# ASCII digits only, and short enough to fit SQLite's 64-bit integers.
_USER_ID = re.compile(r"[0-9]{1,18}")


def get_current_user(
    x_user_id: str | None = Header(None, description="Seeded user ID: 1, 2 or 3"),
    db: sqlite3.Connection = Depends(get_db),
) -> int:
    # Taken as a string so a malformed value is a 401, not FastAPI's default 422.
    if x_user_id is None or not _USER_ID.fullmatch(x_user_id):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid X-User-Id header")
    user_id = int(x_user_id)
    if db.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user_id

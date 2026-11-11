"""
Fixed seed data so the API is usable on first run.

There are no endpoints to manage users or teams, so these rows are the only
way in. Fixed IDs plus INSERT OR IGNORE make seeding safe to repeat.

The passwords are demo credentials, published in the README. Do not reuse
this seed data anywhere real.
"""

import sqlite3

from app.auth import hash_password
from app.db import connect, init_db, utc_now

USERS = [(1, "alice", "alice-password"), (2, "bob", "bob-password"), (3, "carol", "carol-password")]
TEAMS = [(1, "eng"), (2, "design")]
# bob is in both teams, so cross-team behaviour can be tried out.
MEMBERSHIPS = [(1, 1), (2, 1), (2, 2), (3, 2)]


def seed(conn: sqlite3.Connection) -> None:
    now = utc_now()
    with conn:
        for user_id, name, password in USERS:
            # Hash only when the user is missing; scrypt is slow on purpose.
            if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                conn.execute(
                    "INSERT INTO users (id, name, password_hash) VALUES (?, ?, ?)",
                    (user_id, name, hash_password(password)),
                )
        conn.executemany("INSERT OR IGNORE INTO teams (id, name) VALUES (?, ?)", TEAMS)
        conn.executemany(
            "INSERT OR IGNORE INTO memberships (user_id, team_id) VALUES (?, ?)",
            MEMBERSHIPS,
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO notes
                (id, team_id, title, body, version,
                 created_by, updated_by, created_at, updated_at)
            VALUES (1, 1, 'Welcome', 'Shared notes for the eng team.', 1, 1, 1, ?, ?)
            """,
            (now, now),
        )


if __name__ == "__main__":
    init_db()
    conn = connect()
    try:
        seed(conn)
    finally:
        conn.close()

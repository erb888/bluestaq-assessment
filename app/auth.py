"""Authentication: password login, bearer tokens, and caller identity.

Login exchanges a username and password for a random bearer token. Only a
SHA-256 hash of each token is stored, with an expiry, so logout can revoke a
token and no signing secret has to be configured. `get_current_user` is the
only code that turns a request into a user ID.
"""

import hashlib
import hmac
import secrets
import sqlite3
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import get_db, utc_now
from app.schemas import LoginIn, TokenOut

TOKEN_TTL = timedelta(hours=24)

# scrypt cost parameters (about 16 MB of memory per hash).
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1

router = APIRouter(prefix="/auth", tags=["auth"])
# auto_error=False so a missing header is our 401, not FastAPI's 403.
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    _, n, r, p, salt, digest = stored.split("$")
    candidate = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p)
    )
    return hmac.compare_digest(candidate.hex(), digest)


# Checked when the username does not exist, so a failed login takes about the
# same time whether or not the user exists.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: sqlite3.Connection = Depends(get_db)) -> TokenOut:
    user = db.execute(
        "SELECT id, password_hash FROM users WHERE name = ?", (payload.username,)
    ).fetchone()
    password_ok = verify_password(payload.password, user["password_hash"] if user else _DUMMY_HASH)
    if user is None or not password_ok:
        # One message for both cases, so callers cannot probe which usernames exist.
        raise unauthorized("Invalid username or password")

    token = secrets.token_urlsafe(32)
    expires_at = utc_now(TOKEN_TTL)
    with db:
        db.execute(
            "DELETE FROM tokens WHERE user_id = ? AND expires_at <= ?", (user["id"], utc_now())
        )
        db.execute(
            "INSERT INTO tokens (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (hash_token(token), user["id"], expires_at),
        )
    return TokenOut(access_token=token, expires_at=expires_at)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    if credentials is None:
        raise unauthorized("Missing bearer token")
    with db:
        cursor = db.execute(
            "DELETE FROM tokens WHERE token_hash = ?", (hash_token(credentials.credentials),)
        )
    if cursor.rowcount == 0:
        raise unauthorized("Invalid or expired token")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: sqlite3.Connection = Depends(get_db),
) -> int:
    """FastAPI dependency: the user ID behind a valid, unexpired bearer token."""
    if credentials is None:
        raise unauthorized("Missing bearer token")
    row = db.execute(
        "SELECT user_id FROM tokens WHERE token_hash = ? AND expires_at > ?",
        (hash_token(credentials.credentials), utc_now()),
    ).fetchone()
    if row is None:
        raise unauthorized("Invalid or expired token")
    return row["user_id"]

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import auth, notes
from app.db import connect, init_db
from app.seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create the schema and seed data on startup; both are safe to repeat.
    init_db()
    conn = connect()
    try:
        seed(conn)
    finally:
        conn.close()
    yield


app = FastAPI(
    title="Team Notes",
    description=(
        "Shared notes for small teams. Log in with POST /auth/login "
        '(e.g. {"username": "alice", "password": "alice-password"}), '
        "then click Authorize and paste the access_token."
    ),
    lifespan=lifespan,
)
app.include_router(auth.router)
app.include_router(notes.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

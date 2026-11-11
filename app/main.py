from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import notes
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
    description="Shared notes for small teams. Send X-User-Id: 1 (alice), 2 (bob) or 3 (carol).",
    lifespan=lifespan,
)
app.include_router(notes.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

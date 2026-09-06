"""asyncpg connection pool + schema bootstrap."""
import os
from pathlib import Path

import asyncpg

_pool: asyncpg.Pool | None = None

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("db pool not initialized — call db.connect() during startup")
    return _pool


async def connect() -> None:
    global _pool
    dsn = os.environ["DATABASE_URL"]
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=10)
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA_PATH.read_text())


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def row_to_dict(row: asyncpg.Record | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_list(rows: list[asyncpg.Record]) -> list[dict]:
    return [dict(r) for r in rows]

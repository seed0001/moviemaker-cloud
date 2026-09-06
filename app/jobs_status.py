"""Read-only job status — what the agent (and the user) actually check instead of guessing."""
from . import db


async def get_job(job_id: str) -> dict | None:
    row = await db.pool().fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
    return db.row_to_dict(row)


async def list_jobs(status: str | None = None, type: str | None = None,
                     episode_id: str | None = None, scene_id: str | None = None,
                     limit: int = 20) -> list[dict]:
    clauses, params = [], []
    for col, val in (("status", status), ("type", type), ("episode_id", episode_id),
                     ("scene_id", scene_id)):
        if val:
            params.append(val)
            clauses.append(f"{col} = ${len(params)}")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = await db.pool().fetch(
        f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ${len(params)}", *params,
    )
    return db.rows_to_list(rows)

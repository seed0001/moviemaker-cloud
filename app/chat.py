"""Chat thread + message persistence. One episode-level 'planning' thread (scene_id IS NULL)
plus optional scene-level threads, sharing the same message schema (see schema.sql)."""
import json

from . import db
from .ids import new_id

DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"


async def get_or_create_planning_thread(episode_id: str, model: str = DEFAULT_MODEL) -> dict:
    row = await db.pool().fetchrow(
        "SELECT * FROM chat_threads WHERE episode_id = $1 AND scene_id IS NULL", episode_id,
    )
    if row:
        return db.row_to_dict(row)
    tid = new_id("th")
    row = await db.pool().fetchrow(
        """INSERT INTO chat_threads (id, episode_id, scene_id, model) VALUES ($1, $2, NULL, $3)
           ON CONFLICT (episode_id) WHERE scene_id IS NULL DO NOTHING RETURNING *""",
        tid, episode_id, model,
    )
    if row is None:
        # lost a race with a concurrent create — fetch the winner
        row = await db.pool().fetchrow(
            "SELECT * FROM chat_threads WHERE episode_id = $1 AND scene_id IS NULL", episode_id,
        )
    return db.row_to_dict(row)


async def get_or_create_scene_thread(episode_id: str, scene_id: str, model: str = DEFAULT_MODEL) -> dict:
    row = await db.pool().fetchrow("SELECT * FROM chat_threads WHERE scene_id = $1", scene_id)
    if row:
        return db.row_to_dict(row)
    tid = new_id("th")
    row = await db.pool().fetchrow(
        "INSERT INTO chat_threads (id, episode_id, scene_id, model) VALUES ($1, $2, $3, $4) RETURNING *",
        tid, episode_id, scene_id, model,
    )
    return db.row_to_dict(row)


async def get_thread(thread_id: str) -> dict | None:
    row = await db.pool().fetchrow("SELECT * FROM chat_threads WHERE id = $1", thread_id)
    return db.row_to_dict(row)


async def set_thread_model(thread_id: str, model: str) -> None:
    await db.pool().execute("UPDATE chat_threads SET model = $2 WHERE id = $1", thread_id, model)


async def append_message(
    thread_id: str, role: str, *, content: str | None = None,
    tool_calls: list[dict] | None = None, tool_call_id: str | None = None,
    is_synthetic: bool = False,
) -> dict:
    mid = new_id("msg")
    row = await db.pool().fetchrow(
        """INSERT INTO chat_messages (id, thread_id, role, content, tool_calls, tool_call_id, is_synthetic)
           VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *""",
        mid, thread_id, role, content,
        json.dumps(tool_calls) if tool_calls is not None else None,
        tool_call_id, is_synthetic,
    )
    return db.row_to_dict(row)


async def list_messages(thread_id: str) -> list[dict]:
    rows = await db.pool().fetch(
        "SELECT * FROM chat_messages WHERE thread_id = $1 ORDER BY seq", thread_id,
    )
    return db.rows_to_list(rows)


def to_api_messages(rows: list[dict]) -> list[dict]:
    """Convert stored rows into the exact {role, content, tool_calls?, tool_call_id?} shape
    OpenRouter's chat/completions endpoint expects."""
    out = []
    for r in rows:
        msg: dict = {"role": r["role"], "content": r["content"]}
        if r.get("tool_calls"):
            tc = r["tool_calls"]
            msg["tool_calls"] = json.loads(tc) if isinstance(tc, str) else tc
        if r.get("tool_call_id"):
            msg["tool_call_id"] = r["tool_call_id"]
        out.append(msg)
    return out

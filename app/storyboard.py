"""Episode / scene / character / location CRUD. No chat, no jobs — pure state.

Field-update functions accept only the fields the caller actually wants to change
(pass nothing else) so a partial PATCH-style call never clobbers unspecified columns.
"""
from typing import Any

from . import db
from .ids import new_id

_UNSET = object()


async def _update_row(table: str, id_field: str, id_value: str, fields: dict[str, Any]) -> dict | None:
    fields = {k: v for k, v in fields.items() if v is not _UNSET}
    if not fields:
        return await _get_row(table, id_field, id_value)
    set_clauses = [f"{col} = ${i + 2}" for i, col in enumerate(fields)]
    set_clauses.append("updated_at = now()")
    sql = f"UPDATE {table} SET {', '.join(set_clauses)} WHERE {id_field} = $1 RETURNING *"
    row = await db.pool().fetchrow(sql, id_value, *fields.values())
    return db.row_to_dict(row)


async def _get_row(table: str, id_field: str, id_value: str) -> dict | None:
    row = await db.pool().fetchrow(f"SELECT * FROM {table} WHERE {id_field} = $1", id_value)
    return db.row_to_dict(row)


# ---- episodes ----

async def create_episode(title: str = "Untitled episode") -> dict:
    eid = new_id("ep")
    async with db.pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("UPDATE episodes SET is_active = false WHERE is_active")
            row = await conn.fetchrow(
                "INSERT INTO episodes (id, title, is_active) VALUES ($1, $2, true) RETURNING *",
                eid, title,
            )
    return db.row_to_dict(row)


async def update_episode(episode_id: str, *, title=_UNSET, premise=_UNSET, style=_UNSET) -> dict | None:
    return await _update_row("episodes", "id", episode_id,
                              {"title": title, "premise": premise, "style": style})


async def select_episode(episode_id: str) -> dict:
    async with db.pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("UPDATE episodes SET is_active = false WHERE is_active")
            row = await conn.fetchrow(
                "UPDATE episodes SET is_active = true, updated_at = now() WHERE id = $1 RETURNING *",
                episode_id,
            )
    return db.row_to_dict(row)


async def get_active_episode() -> dict | None:
    row = await db.pool().fetchrow("SELECT * FROM episodes WHERE is_active LIMIT 1")
    return db.row_to_dict(row)


async def list_episodes() -> list[dict]:
    rows = await db.pool().fetch("SELECT * FROM episodes ORDER BY created_at")
    return db.rows_to_list(rows)


async def reorder_scenes(episode_id: str, scene_order: list[str]) -> dict | None:
    row = await db.pool().fetchrow(
        "UPDATE episodes SET scene_order = $2, updated_at = now() WHERE id = $1 RETURNING *",
        episode_id, scene_order,
    )
    return db.row_to_dict(row)


# ---- characters ----

async def create_character(episode_id: str, name: str, description: str = "") -> dict:
    cid = new_id("chr")
    row = await db.pool().fetchrow(
        "INSERT INTO characters (id, episode_id, name, description) VALUES ($1, $2, $3, $4) RETURNING *",
        cid, episode_id, name, description,
    )
    return db.row_to_dict(row)


async def update_character(character_id: str, *, name=_UNSET, description=_UNSET) -> dict | None:
    return await _update_row("characters", "id", character_id, {"name": name, "description": description})


async def delete_character(character_id: str) -> None:
    await db.pool().execute("DELETE FROM characters WHERE id = $1", character_id)


async def list_characters(episode_id: str) -> list[dict]:
    rows = await db.pool().fetch(
        "SELECT * FROM characters WHERE episode_id = $1 ORDER BY created_at", episode_id,
    )
    return db.rows_to_list(rows)


# ---- locations ----

async def create_location(episode_id: str, name: str, description: str = "") -> dict:
    lid = new_id("loc")
    row = await db.pool().fetchrow(
        "INSERT INTO locations (id, episode_id, name, description) VALUES ($1, $2, $3, $4) RETURNING *",
        lid, episode_id, name, description,
    )
    return db.row_to_dict(row)


async def update_location(location_id: str, *, name=_UNSET, description=_UNSET) -> dict | None:
    return await _update_row("locations", "id", location_id, {"name": name, "description": description})


async def delete_location(location_id: str) -> None:
    await db.pool().execute("DELETE FROM locations WHERE id = $1", location_id)


async def list_locations(episode_id: str) -> list[dict]:
    rows = await db.pool().fetch(
        "SELECT * FROM locations WHERE episode_id = $1 ORDER BY created_at", episode_id,
    )
    return db.rows_to_list(rows)


# ---- scenes ----

async def create_scene(
    episode_id: str,
    *,
    title: str = "",
    type: str = "dialogue",
    duration: int = 5,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    chain: bool | None = None,
    character_ids: list[str] | None = None,
    location_id: str | None = None,
    prompt: str = "",
    notes: str = "",
    video_model: str | None = None,
) -> dict:
    sid = new_id("sc")
    async with db.pool().acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchval(
                "SELECT array_length(scene_order, 1) FROM episodes WHERE id = $1", episode_id,
            )
            if chain is None:
                chain = bool(existing)  # default true unless it's the first scene, matches old behavior
            row = await conn.fetchrow(
                """INSERT INTO scenes (id, episode_id, title, type, duration, resolution, aspect_ratio,
                       chain, character_ids, location_id, prompt, notes, status, video_model)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) RETURNING *""",
                sid, episode_id, title or f"Scene {(existing or 0) + 1}", type, duration, resolution,
                aspect_ratio, chain, character_ids or [], location_id, prompt, notes,
                "ready" if prompt else "draft", video_model,
            )
            await conn.execute(
                "UPDATE episodes SET scene_order = scene_order || $2, updated_at = now() WHERE id = $1",
                episode_id, [sid],
            )
    return db.row_to_dict(row)


async def update_scene(
    scene_id: str,
    *,
    title=_UNSET, type=_UNSET, duration=_UNSET, resolution=_UNSET, aspect_ratio=_UNSET,
    chain=_UNSET, character_ids=_UNSET, location_id=_UNSET, prompt=_UNSET, notes=_UNSET, status=_UNSET,
    video_model=_UNSET,
) -> dict | None:
    fields = {
        "title": title, "type": type, "duration": duration, "resolution": resolution,
        "aspect_ratio": aspect_ratio, "chain": chain, "character_ids": character_ids,
        "location_id": location_id, "prompt": prompt, "notes": notes, "status": status,
        "video_model": video_model,
    }
    # auto-promote draft -> ready the first time a non-empty prompt is set, matching the old app's
    # dashboard.py:733-734 behavior, unless the caller is explicitly setting status itself
    if prompt is not _UNSET and prompt and status is _UNSET:
        current = await _get_row("scenes", "id", scene_id)
        if current and current["status"] == "draft":
            fields["status"] = "ready"
    return await _update_row("scenes", "id", scene_id, fields)


async def delete_scene(scene_id: str) -> None:
    async with db.pool().acquire() as conn:
        async with conn.transaction():
            episode_id = await conn.fetchval("SELECT episode_id FROM scenes WHERE id = $1", scene_id)
            await conn.execute("DELETE FROM scenes WHERE id = $1", scene_id)
            if episode_id:
                await conn.execute(
                    "UPDATE episodes SET scene_order = array_remove(scene_order, $2), updated_at = now() "
                    "WHERE id = $1",
                    episode_id, scene_id,
                )


async def get_scene(scene_id: str) -> dict | None:
    return await _get_row("scenes", "id", scene_id)


async def list_scenes(episode_id: str) -> list[dict]:
    rows = await db.pool().fetch(
        "SELECT * FROM scenes WHERE episode_id = $1", episode_id,
    )
    by_id = {r["id"]: dict(r) for r in rows}
    order = await db.pool().fetchval("SELECT scene_order FROM episodes WHERE id = $1", episode_id)
    ordered = [by_id[sid] for sid in (order or []) if sid in by_id]
    # any scene missing from scene_order (shouldn't happen, but don't silently drop it) goes at the end
    ordered += [s for s in by_id.values() if s["id"] not in (order or [])]
    return ordered


# ---- storyboard panels ----

async def list_panels(scene_id: str) -> list[dict]:
    rows = await db.pool().fetch(
        "SELECT * FROM storyboard_panels WHERE scene_id = $1 ORDER BY created_at", scene_id,
    )
    return db.rows_to_list(rows)


# ---- full episode assembly (the get_storyboard tool's backend) ----

async def get_full_episode(episode_id: str | None = None) -> dict | None:
    episode = await _get_row("episodes", "id", episode_id) if episode_id else await get_active_episode()
    if episode is None:
        return None
    scenes = await list_scenes(episode["id"])
    for scene in scenes:
        scene["panels"] = await list_panels(scene["id"])
    episode["scenes"] = scenes
    episode["characters"] = await list_characters(episode["id"])
    episode["locations"] = await list_locations(episode["id"])
    return episode

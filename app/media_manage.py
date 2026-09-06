"""Delete generated media and report storage usage. Deleting a file is irreversible, so this
follows the same two-step confirmed contract as generation (media_jobs.py): call without
confirmed first for a preview (what would be deleted, how many bytes freed), call again with
confirmed=true only after the user has explicitly said to proceed.

Jobs themselves are never deleted (see agent/loop.py's system prompt — get_job/list_jobs must
stay truthful forever); deleting media only removes the file on disk and the media_files row,
then clears jobs.media_path and stamps media_deleted_at so the job row still records what
happened.
"""
import os

from . import db, media_jobs, render_pipeline

MEDIA_ROOT = media_jobs.MEDIA_ROOT


async def _job_size_bytes(job) -> int:
    if not job["media_path"]:
        return 0
    row = await db.pool().fetchrow("SELECT bytes FROM media_files WHERE job_id = $1", job["id"])
    if row and row["bytes"] is not None:
        return row["bytes"]
    abs_path = os.path.join(MEDIA_ROOT, job["media_path"])
    return os.path.getsize(abs_path) if os.path.isfile(abs_path) else 0


async def get_storage_summary() -> dict:
    rows = await db.pool().fetch(
        "SELECT j.id, j.type, j.episode_id, j.scene_id, j.media_path, mf.bytes AS mf_bytes "
        "FROM jobs j LEFT JOIN media_files mf ON mf.job_id = j.id "
        "WHERE j.media_path IS NOT NULL ORDER BY j.created_at DESC",
    )
    by_type: dict[str, dict] = {}
    items = []
    total = 0
    for r in rows:
        size = r["mf_bytes"]
        if size is None:
            abs_path = os.path.join(MEDIA_ROOT, r["media_path"])
            size = os.path.getsize(abs_path) if os.path.isfile(abs_path) else 0
        total += size
        bucket = by_type.setdefault(r["type"], {"count": 0, "bytes": 0})
        bucket["count"] += 1
        bucket["bytes"] += size
        items.append({
            "job_id": r["id"], "type": r["type"], "episode_id": r["episode_id"],
            "scene_id": r["scene_id"], "media_path": r["media_path"], "bytes": size,
        })
    return {"total_bytes": total, "by_type": by_type, "jobs": items}


async def delete_job_media(job_id: str, confirmed: bool = False, force: bool = False) -> dict:
    job = await db.pool().fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
    if job is None:
        return {"error": f"job {job_id} not found"}
    if not job["media_path"]:
        return {"error": f"job {job_id} has no media on disk (already deleted, or never completed "
                          "with an output)"}

    approved_scene = await db.pool().fetchrow(
        "SELECT id FROM scenes WHERE approved_take_id = $1", job_id,
    )
    if approved_scene and not force:
        return {"error": f"job {job_id} is the approved take for scene {approved_scene['id']} — "
                          "pass force=true to unapprove it and delete anyway"}

    size = await _job_size_bytes(job)
    if not confirmed:
        return {
            "status": "preview", "job_id": job_id, "type": job["type"], "media_path": job["media_path"],
            "bytes": size, "is_approved_take": bool(approved_scene),
            "message": "Not deleted yet. Call again with confirmed=true to permanently delete this file.",
        }

    if approved_scene:
        await render_pipeline.unapprove_take(approved_scene["id"])

    abs_path = os.path.join(MEDIA_ROOT, job["media_path"])
    try:
        os.remove(abs_path)
    except FileNotFoundError:
        pass

    await db.pool().execute("DELETE FROM media_files WHERE job_id = $1", job_id)
    await db.pool().execute(
        "UPDATE jobs SET media_path=NULL, media_deleted_at=now(), updated_at=now() WHERE id=$1", job_id,
    )
    # a deleted reference-image job leaves the character/location pointing at a dead file
    for table in ("characters", "locations"):
        await db.pool().execute(
            f"UPDATE {table} SET reference_image_path=NULL, reference_image_job_id=NULL, updated_at=now() "
            f"WHERE reference_image_job_id = $1",
            job_id,
        )

    return {"status": "deleted", "job_id": job_id, "freed_bytes": size}


async def delete_rejected_takes(scene_id: str, confirmed: bool = False) -> dict:
    """Deletes every completed video take for a scene except its current approved take —
    the common cleanup case of clearing out the takes you generated but didn't like."""
    scene = await db.pool().fetchrow("SELECT * FROM scenes WHERE id = $1", scene_id)
    if scene is None:
        return {"error": f"scene {scene_id} not found"}

    approved_id = scene["approved_take_id"]
    rows = await db.pool().fetch(
        "SELECT * FROM jobs WHERE scene_id = $1 AND type = 'video' AND status = 'completed' "
        "AND media_path IS NOT NULL AND id IS DISTINCT FROM $2",
        scene_id, approved_id,
    )
    if not rows:
        return {"status": "noop", "scene_id": scene_id, "message": "no rejected takes to delete for this scene"}

    total = sum([await _job_size_bytes(r) for r in rows])
    if not confirmed:
        return {
            "status": "preview", "scene_id": scene_id, "job_ids": [r["id"] for r in rows],
            "count": len(rows), "bytes": total,
            "message": f"Not deleted yet. Call again with confirmed=true to permanently delete these "
                       f"{len(rows)} unapproved takes.",
        }

    freed = 0
    deleted_ids = []
    for r in rows:
        res = await delete_job_media(r["id"], confirmed=True)
        if res.get("status") == "deleted":
            freed += res["freed_bytes"]
            deleted_ids.append(r["id"])
    return {"status": "deleted", "scene_id": scene_id, "deleted_job_ids": deleted_ids, "freed_bytes": freed}

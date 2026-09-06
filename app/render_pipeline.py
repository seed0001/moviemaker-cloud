"""Approve/unapprove takes, and stitch approved scenes into one episode file.
Stitch logic (filter_complex normalize + concat) ported from the old app's run_stitch,
movieMaker/dashboard/dashboard.py:503-545 — same ffmpeg approach, now reading job rows
instead of an in-memory scene['takes'] list.
"""
import asyncio
import json
import os
import re
import time

from . import db, media_jobs
from .ids import new_id

RENDERS_DIR_NAME = "renders"


async def approve_take(scene_id: str, job_id: str) -> dict | None:
    job = await db.pool().fetchrow(
        "SELECT * FROM jobs WHERE id = $1 AND scene_id = $2 AND status = 'completed'", job_id, scene_id,
    )
    if job is None:
        return {"error": f"job {job_id} is not a completed take for scene {scene_id}"}
    row = await db.pool().fetchrow(
        "UPDATE scenes SET approved_take_id=$2, status='approved', updated_at=now() WHERE id=$1 RETURNING *",
        scene_id, job_id,
    )
    return db.row_to_dict(row)


async def unapprove_take(scene_id: str) -> dict | None:
    row = await db.pool().fetchrow(
        "UPDATE scenes SET approved_take_id=NULL, status='review', updated_at=now() WHERE id=$1 RETURNING *",
        scene_id,
    )
    return db.row_to_dict(row)


def _slug(title: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", title).strip("_") or "episode"


async def stitch_episode(episode_id: str) -> dict:
    episode = await db.pool().fetchrow("SELECT * FROM episodes WHERE id = $1", episode_id)
    if episode is None:
        return {"error": f"episode {episode_id} not found"}
    scene_order = episode["scene_order"] or []
    scenes = await db.pool().fetch(
        "SELECT * FROM scenes WHERE episode_id = $1 AND approved_take_id IS NOT NULL", episode_id,
    )
    by_id = {s["id"]: s for s in scenes}
    ordered = [by_id[sid] for sid in scene_order if sid in by_id]
    if not ordered:
        return {"error": "no approved takes to stitch"}

    job_ids = [s["approved_take_id"] for s in ordered]
    jobs = {j["id"]: j for j in await db.pool().fetch(
        "SELECT * FROM jobs WHERE id = ANY($1::text[])", job_ids,
    )}
    input_paths = []
    for s in ordered:
        job = jobs.get(s["approved_take_id"])
        if not job or not job["media_path"]:
            return {"error": f"approved take for scene {s['id']} has no media file on disk"}
        input_paths.append(os.path.join(media_jobs.MEDIA_ROOT, job["media_path"]))

    rel_dir = f"episodes/{episode_id}/{RENDERS_DIR_NAME}"
    abs_dir = os.path.join(media_jobs.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    out_rel = f"{rel_dir}/{_slug(episode['title'])}_{int(time.time())}.mp4"
    out_abs = os.path.join(media_jobs.MEDIA_ROOT, out_rel)

    args = ["ffmpeg", "-y"]
    for p in input_paths:
        args += ["-i", p]
    n = len(input_paths)
    filt_parts = []
    for i in range(n):
        filt_parts.append(
            f"[{i}:v]scale=864:480:force_original_aspect_ratio=decrease,"
            f"pad=864:480:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24[v{i}];"
            f"[{i}:a]aresample=48000[a{i}]"
        )
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
    filt = ";".join(filt_parts) + f";{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]"
    args += [
        "-filter_complex", filt, "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k", out_abs,
    ]

    job_id = new_id("job")
    await db.pool().execute(
        """INSERT INTO jobs (id, type, status, request_payload, episode_id)
           VALUES ($1, 'stitch', 'in_progress', $2, $3)""",
        job_id, json.dumps({"scene_ids": [s["id"] for s in ordered], "output": out_rel}), episode_id,
    )
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not os.path.isfile(out_abs):
        error = stderr.decode(errors="replace")[-1000:]
        await db.pool().execute(
            "UPDATE jobs SET status='failed', error=$2, updated_at=now(), completed_at=now() WHERE id=$1",
            job_id, error,
        )
        return {"status": "failed", "job_id": job_id, "error": error}

    await db.pool().execute(
        """UPDATE jobs SET status='completed', media_path=$2, updated_at=now(), completed_at=now()
           WHERE id=$1""",
        job_id, out_rel,
    )
    return {"status": "completed", "job_id": job_id, "scene_count": n,
            "output_path": media_jobs.media_url(out_rel)}

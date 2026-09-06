"""Image and video generation.

Images are synchronous (the OpenRouter /images call is a normal request/response, typically
well under a minute) — the tool call blocks until the real result is in hand.

Video is genuinely long-running (an async job: submit, poll, download), so it is dispatched
as a background asyncio task instead of blocking the chat turn for minutes — the tool returns
`{status: "queued", job_id}` immediately, and the truth of what happened is only ever
knowable by querying the `jobs` row (via get_job/list_jobs), never narrated speculatively.
"""
import asyncio
import base64
import json
import logging
import os
import time
from decimal import Decimal

from . import db, openrouter, pricing
from .ids import new_id

logger = logging.getLogger(__name__)

MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "./data")
DEFAULT_VIDEO_MODEL = "bytedance/seedance-2.0-mini"  # cheapest OpenRouter video model as of 2026-09-06
VIDEO_POLL_SECONDS = 8
VIDEO_TIMEOUT_SECONDS = 25 * 60
_VIDEO_SEMAPHORE = asyncio.Semaphore(int(os.environ.get("OR_MAX_CONCURRENT_VIDEO", "2")))

_EXT_BY_MEDIA_TYPE = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
}


def media_url(rel_path: str) -> str:
    """Absolute, clickable URL when PUBLIC_BASE_URL is configured (set on Railway to this
    service's public domain); falls back to a relative path for local dev. Tools must return
    this, not the bare relative path — a relative path isn't a real link outside the app."""
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    return f"{base}/media/{rel_path}" if base else f"/media/{rel_path}"

_ENTITY_TABLE = {"character": "characters", "location": "locations"}


def _float(x):
    return float(x) if isinstance(x, Decimal) else x


async def quote_image_cost(model: str) -> dict:
    amount, source = await pricing.estimate_image_cost(model)
    return {"estimated_cost": _float(amount), "pricing_source": source, "model": model}


async def _get_entity(kind: str, entity_id: str) -> dict | None:
    table = _ENTITY_TABLE[kind]
    row = await db.pool().fetchrow(f"SELECT * FROM {table} WHERE id = $1", entity_id)
    return db.row_to_dict(row)


async def _mark_job_failed(job_id: str, error: str) -> None:
    await db.pool().execute(
        "UPDATE jobs SET status='failed', error=$2, updated_at=now(), completed_at=now() WHERE id=$1",
        job_id, error,
    )


async def generate_reference_image(
    kind: str, entity_id: str, prompt: str, confirmed: bool = False,
    model: str = "google/gemini-2.5-flash-image", resolution: str | None = None, n: int = 1,
) -> dict:
    if kind not in _ENTITY_TABLE:
        return {"error": f"unknown kind {kind!r}, expected 'character' or 'location'"}
    entity = await _get_entity(kind, entity_id)
    if entity is None:
        return {"error": f"{kind} {entity_id} not found"}

    quote = await quote_image_cost(model)
    if not confirmed:
        return {
            "status": "quote", **quote,
            "message": "Not generated yet. Call this same tool again with confirmed=true "
                       "once the user has explicitly said to proceed.",
        }

    job_id = new_id("job")
    request_payload = {"model": model, "prompt": prompt, "n": n}
    if resolution:
        request_payload["resolution"] = resolution
    entity_col = f"{kind}_id"
    await db.pool().execute(
        f"""INSERT INTO jobs (id, type, status, phase, request_payload, estimated_cost, pricing_source,
               episode_id, {entity_col})
            VALUES ($1, 'image', 'in_progress', 'submitting', $2, $3, $4, $5, $6)""",
        job_id, json.dumps(request_payload), quote["estimated_cost"],
        quote["pricing_source"], entity["episode_id"], entity_id,
    )

    started = time.time()
    try:
        res = await openrouter.generate_image(request_payload)
        images = res.get("data") or []
        if not images:
            raise RuntimeError("OpenRouter returned no image data")
        img = images[0]
        raw = base64.b64decode(img["b64_json"])
        ext = _EXT_BY_MEDIA_TYPE.get(img.get("media_type", ""), "png")
        media_id = new_id("med")
        rel_dir = f"episodes/{entity['episode_id']}/{kind}s/{entity_id}"
        abs_dir = os.path.join(MEDIA_ROOT, rel_dir)
        os.makedirs(abs_dir, exist_ok=True)
        rel_path = f"{rel_dir}/{media_id}.{ext}"
        with open(os.path.join(MEDIA_ROOT, rel_path), "wb") as f:
            f.write(raw)

        actual_cost = (res.get("usage") or {}).get("cost")
        await db.pool().execute(
            """UPDATE jobs SET status='completed', phase=NULL, result_payload=$2, actual_cost=$3,
                   media_path=$4, updated_at=now(), completed_at=now() WHERE id=$1""",
            job_id, json.dumps({k: v for k, v in res.items() if k != "data"}),
            actual_cost, rel_path,
        )
        await db.pool().execute(
            f"""UPDATE {_ENTITY_TABLE[kind]}
                SET reference_image_job_id=$2, reference_image_path=$3, updated_at=now() WHERE id=$1""",
            entity_id, job_id, rel_path,
        )
        await db.pool().execute(
            "INSERT INTO media_files (id, job_id, kind, path, content_type, bytes) "
            "VALUES ($1, $2, 'image', $3, $4, $5)",
            media_id, job_id, rel_path, img.get("media_type", "image/png"), len(raw),
        )
        return {
            "status": "completed", "job_id": job_id, "image_path": media_url(rel_path),
            "estimated_cost": quote["estimated_cost"], "actual_cost": _float(actual_cost),
            "elapsed_seconds": round(time.time() - started),
        }
    except Exception as e:  # noqa: BLE001 - must reach the model as a real tool result, not crash the turn
        await _mark_job_failed(job_id, str(e))
        return {"status": "failed", "job_id": job_id, "error": str(e)}


# ---- video ----

async def _get_scene(scene_id: str) -> dict | None:
    row = await db.pool().fetchrow("SELECT * FROM scenes WHERE id = $1", scene_id)
    return db.row_to_dict(row)


async def quote_video_cost(model: str, resolution: str | None, duration: int | None) -> dict:
    amount, source = await pricing.estimate_video_cost(model, resolution, duration)
    return {"estimated_cost": _float(amount), "pricing_source": source, "model": model,
            "resolution": resolution, "duration": duration}


async def _extract_last_frame(video_abs_path: str, out_abs_path: str) -> bool:
    """Best-effort: grab the final frame of a completed clip for FL2VA-style scene chaining.
    Never fatal — a missing/failing ffmpeg just means the next scene generates unchained."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-sseof", "-0.15", "-i", video_abs_path,
            "-frames:v", "1", "-update", "1", out_abs_path,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=30)
        return proc.returncode == 0 and os.path.isfile(out_abs_path)
    except Exception:
        logger.exception("last-frame extraction failed for %s", video_abs_path)
        return False


async def _previous_chain_frame(scene: dict) -> str | None:
    """Returns an absolute public URL to the previous scene's last frame, or None."""
    order = await db.pool().fetchval(
        "SELECT scene_order FROM episodes WHERE id = $1", scene["episode_id"],
    )
    order = order or []
    if scene["id"] not in order:
        return None
    idx = order.index(scene["id"])
    if idx == 0:
        return None
    prev_id = order[idx - 1]
    prev = await _get_scene(prev_id)
    if not prev or not prev.get("approved_take_id"):
        return None
    prev_job = await db.pool().fetchrow("SELECT * FROM jobs WHERE id = $1", prev["approved_take_id"])
    if not prev_job or not prev_job["media_path"]:
        return None
    video_abs = os.path.join(MEDIA_ROOT, prev_job["media_path"])
    frame_rel = f"episodes/{scene['episode_id']}/scenes/{scene['id']}/chain_from_{prev_id}.png"
    frame_abs = os.path.join(MEDIA_ROOT, frame_rel)
    os.makedirs(os.path.dirname(frame_abs), exist_ok=True)
    ok = await _extract_last_frame(video_abs, frame_abs)
    return media_url(frame_rel) if ok else None


async def enqueue_video_job(
    scene_id: str, prompt: str | None = None, confirmed: bool = False,
    model: str | None = None, duration: int | None = None, resolution: str | None = None,
    aspect_ratio: str | None = None, use_chain: bool | None = None,
) -> dict:
    scene = await _get_scene(scene_id)
    if scene is None:
        return {"error": f"scene {scene_id} not found"}

    model = model or scene["video_model"] or DEFAULT_VIDEO_MODEL
    prompt = prompt or scene["prompt"]
    duration = duration or scene["duration"]
    resolution = resolution or scene["resolution"]
    aspect_ratio = aspect_ratio or scene["aspect_ratio"]
    if not prompt:
        return {"error": "this scene has no prompt yet — set one (update_scene) before generating"}

    model_entry = await pricing.get_video_model_entry(model)
    validation_errors = pricing.validate_video_params(model_entry, duration, resolution, aspect_ratio)
    if validation_errors:
        return {
            "error": "invalid parameters for this model — fix these and try again (nothing was "
                     "submitted, nothing was charged): " + "; ".join(validation_errors),
        }

    quote = await quote_video_cost(model, resolution, duration)
    if not confirmed:
        return {
            "status": "quote", **quote,
            "message": "Not generated yet. Call this same tool again with confirmed=true "
                       "once the user has explicitly said to proceed.",
        }

    use_chain = scene["chain"] if use_chain is None else use_chain
    job_id = new_id("job")
    request_payload = {
        "model": model, "prompt": prompt, "duration": duration, "resolution": resolution,
        "aspect_ratio": aspect_ratio, "generate_audio": True, "use_chain": use_chain,
    }
    await db.pool().execute(
        """INSERT INTO jobs (id, type, status, phase, request_payload, estimated_cost, pricing_source,
               episode_id, scene_id)
           VALUES ($1, 'video', 'queued', 'queued', $2, $3, $4, $5, $6)""",
        job_id, json.dumps(request_payload), quote["estimated_cost"], quote["pricing_source"],
        scene["episode_id"], scene_id,
    )
    await db.pool().execute("UPDATE scenes SET status='queued', updated_at=now() WHERE id=$1", scene_id)
    asyncio.create_task(_run_video_job(job_id))
    return {"status": "queued", "job_id": job_id, **quote,
            "message": "Generation started in the background — this typically takes a few minutes. "
                       "Check back with get_job or list_jobs; don't guess at progress."}


async def _run_video_job(job_id: str) -> None:
    async with _VIDEO_SEMAPHORE:
        job = await db.pool().fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
        payload = json.loads(job["request_payload"])
        scene_id = job["scene_id"]
        await db.pool().execute(
            "UPDATE jobs SET status='in_progress', phase='submitting', updated_at=now() WHERE id=$1",
            job_id,
        )
        await db.pool().execute("UPDATE scenes SET status='generating', updated_at=now() WHERE id=$1", scene_id)
        started = time.time()
        try:
            scene = await _get_scene(scene_id)
            submit_payload = {
                "model": payload["model"], "prompt": payload["prompt"],
                "duration": payload["duration"], "resolution": payload["resolution"],
                "aspect_ratio": payload["aspect_ratio"], "generate_audio": payload["generate_audio"],
            }
            if payload.get("use_chain"):
                frame_url = await _previous_chain_frame(scene)
                if frame_url:
                    submit_payload["frame_images"] = [{"image_url": frame_url, "frame_type": "first_frame"}]

            res = await openrouter.submit_video(submit_payload)
            provider_job_id = res.get("id")
            polling_url = res.get("polling_url") or f"{openrouter.BASE_URL}/videos/{provider_job_id}"
            status = res.get("status", "pending")
            await db.pool().execute(
                "UPDATE jobs SET provider_job_id=$2, polling_url=$3, phase=$4, updated_at=now() WHERE id=$1",
                job_id, provider_job_id, polling_url, status,
            )

            deadline = time.time() + VIDEO_TIMEOUT_SECONDS
            while status not in ("completed", "failed", "cancelled", "expired") and time.time() < deadline:
                await asyncio.sleep(VIDEO_POLL_SECONDS)
                res = await openrouter.poll_video(polling_url)
                status = res.get("status", "pending")
                await db.pool().execute(
                    "UPDATE jobs SET phase=$2, updated_at=now() WHERE id=$1", job_id, status,
                )
            if status != "completed":
                raise RuntimeError(f"OpenRouter video job ended as {status!r}: {json.dumps(res)[:400]}")

            urls = res.get("unsigned_urls") or []
            if not urls:
                raise RuntimeError("OpenRouter returned no video URL")
            video_bytes = await openrouter.download_bytes(urls[0])
            rel_dir = f"episodes/{scene['episode_id']}/scenes/{scene_id}/takes"
            os.makedirs(os.path.join(MEDIA_ROOT, rel_dir), exist_ok=True)
            rel_path = f"{rel_dir}/{job_id}.mp4"
            with open(os.path.join(MEDIA_ROOT, rel_path), "wb") as f:
                f.write(video_bytes)

            actual_cost = (res.get("usage") or {}).get("cost")
            await db.pool().execute(
                """UPDATE jobs SET status='completed', phase=NULL, result_payload=$2, actual_cost=$3,
                       media_path=$4, updated_at=now(), completed_at=now() WHERE id=$1""",
                job_id, json.dumps({k: v for k, v in res.items() if k != "unsigned_urls"}),
                actual_cost, rel_path,
            )
            media_id = new_id("med")
            await db.pool().execute(
                "INSERT INTO media_files (id, job_id, kind, path, content_type, bytes) "
                "VALUES ($1, $2, 'video', $3, 'video/mp4', $4)",
                media_id, job_id, rel_path, len(video_bytes),
            )
            await db.pool().execute("UPDATE scenes SET status='review', last_error=NULL, updated_at=now() WHERE id=$1", scene_id)
        except Exception as e:  # noqa: BLE001 - failures must land in the jobs row, never crash the loop
            logger.exception("video job %s failed", job_id)
            await _mark_job_failed(job_id, str(e))
            has_prior_success = await db.pool().fetchval(
                "SELECT count(*) > 0 FROM jobs WHERE scene_id=$1 AND type='video' AND status='completed'",
                scene_id,
            )
            fallback_status = "review" if has_prior_success else "ready"
            await db.pool().execute(
                "UPDATE scenes SET status=$2, last_error=$3, updated_at=now() WHERE id=$1",
                scene_id, fallback_status, str(e)[:500],
            )

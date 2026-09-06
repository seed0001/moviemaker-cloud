"""Image generation. Synchronous (the OpenRouter /images call is a normal request/response,
typically well under a minute) — the tool call blocks until the real result is in hand, so
the agent can never narrate a status it hasn't actually observed. Every call is still logged
as a `jobs` row for cost tracking, even though nothing here is dispatched as a background task
yet (that lands with the async job/notification system, once video generation needs it).
"""
import base64
import json
import os
import time
from decimal import Decimal

from . import db, openrouter, pricing
from .ids import new_id

MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "./data")

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

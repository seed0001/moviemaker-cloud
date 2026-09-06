"""Cost estimation. No published per-resolution image pricing is reliably exposed by
OpenRouter's /images/models list (confirmed during design research), so image cost
estimates fall back to this app's own observed history, self-calibrating over time.
Video models DO publish a pricing_skus dict (confirmed against /videos/models) so that's
tried first there.
"""
from decimal import Decimal

from . import db, openrouter

DEFAULT_IMAGE_COST_GUESS = Decimal("0.04")
DEFAULT_VIDEO_COST_GUESS = Decimal("2.00")


async def _historical_average(job_type: str, model: str) -> Decimal | None:
    row = await db.pool().fetchrow(
        "SELECT avg(actual_cost) AS avg_cost, count(*) AS n FROM jobs "
        "WHERE type = $1 AND status = 'completed' AND actual_cost IS NOT NULL "
        "AND request_payload->>'model' = $2",
        job_type, model,
    )
    if row and row["n"] and row["avg_cost"] is not None:
        return Decimal(row["avg_cost"])
    return None


async def estimate_image_cost(model: str) -> tuple[Decimal, str]:
    avg = await _historical_average("image", model)
    if avg is not None:
        return avg, "historical_average"
    return DEFAULT_IMAGE_COST_GUESS, "default_guess"


async def estimate_video_cost(model: str, resolution: str | None, duration: int | None) -> tuple[Decimal, str]:
    try:
        models = (await openrouter.list_video_models()).get("data") or []
        entry = next((m for m in models if m.get("id") == model), None)
        skus = (entry or {}).get("pricing_skus") or {}
        rate = skus.get("generate") or (next(iter(skus.values()), None) if skus else None)
        if rate is not None:
            amount = Decimal(str(rate))
            # duration-scale only when the SKU clearly reads as a per-second rate (small
            # unit price) — a flat per-generation SKU (e.g. "0.50") should not be multiplied
            if duration and amount < Decimal("0.20"):
                amount = amount * duration
            return amount, "published_sku"
    except Exception:
        pass  # fall through to historical/default — a pricing lookup failure must never block a quote
    avg = await _historical_average("video", model)
    if avg is not None:
        return avg, "historical_average"
    return DEFAULT_VIDEO_COST_GUESS, "default_guess"

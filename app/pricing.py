"""Cost estimation. No published per-resolution image pricing is reliably exposed by
OpenRouter's /images/models list (confirmed during design research), so image cost
estimates fall back to this app's own observed history, self-calibrating over time.
"""
from decimal import Decimal

from . import db

DEFAULT_IMAGE_COST_GUESS = Decimal("0.04")


async def estimate_image_cost(model: str) -> tuple[Decimal, str]:
    row = await db.pool().fetchrow(
        "SELECT avg(actual_cost) AS avg_cost, count(*) AS n FROM jobs "
        "WHERE type = 'image' AND status = 'completed' AND actual_cost IS NOT NULL "
        "AND request_payload->>'model' = $1",
        model,
    )
    if row and row["n"] and row["avg_cost"] is not None:
        return Decimal(row["avg_cost"]), "historical_average"
    return DEFAULT_IMAGE_COST_GUESS, "default_guess"

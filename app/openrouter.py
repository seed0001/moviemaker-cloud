"""Thin server-side OpenRouter client. The API key never leaves this process."""
import os

import httpx

BASE_URL = "https://openrouter.ai/api/v1"
_REFERER = "https://moviemaker-cloud.local"
_TITLE = "movieMaker Cloud"


def _headers() -> dict:
    key = os.environ["OPENROUTER_API_KEY"]
    return {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": _REFERER,
        "X-Title": _TITLE,
        "Content-Type": "application/json",
    }


async def chat_completion(model: str, messages: list[dict], tools: list[dict] | None = None,
                           tool_choice: str = "auto") -> dict:
    payload = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{BASE_URL}/chat/completions", json=payload, headers=_headers())
        if r.status_code >= 400:
            raise RuntimeError(f"OpenRouter chat error {r.status_code}: {r.text[:500]}")
        return r.json()


async def list_models() -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{BASE_URL}/models", headers=_headers())
        r.raise_for_status()
        return r.json()


async def list_video_models() -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{BASE_URL}/videos/models", headers=_headers())
        r.raise_for_status()
        return r.json()


async def list_image_models() -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{BASE_URL}/images/models", headers=_headers())
        r.raise_for_status()
        return r.json()


async def submit_video(payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{BASE_URL}/videos", json=payload, headers=_headers())
        if r.status_code not in (200, 201, 202):
            raise RuntimeError(f"OpenRouter video error {r.status_code}: {r.text[:500]}")
        return r.json()


async def poll_video(polling_url: str) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(polling_url, headers=_headers())
        r.raise_for_status()
        return r.json()


async def generate_image(payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{BASE_URL}/images", json=payload, headers=_headers())
        if r.status_code >= 400:
            raise RuntimeError(f"OpenRouter image error {r.status_code}: {r.text[:500]}")
        return r.json()


async def download_bytes(url: str) -> bytes:
    """Downloads a completed video from its unsigned_urls entry. Sent with the same auth
    headers as the old app did (dashboard.py:479) — harmless if the URL doesn't need them."""
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.get(url, headers=_headers())
        r.raise_for_status()
        return r.content

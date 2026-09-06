# movieMaker Cloud

Chat-first, OpenRouter-only rebuild of `movieMaker`: a single persistent chat with an
LLM agent plans an episode (characters, locations, scene-by-scene storyboard), generates
reference art and storyboard panels, kicks off video rendering, and reports on
everything running — all through server-side tool calls. No local GPU, no ComfyUI:
every generation call (chat, images, video) goes through OpenRouter.

Full architecture/design writeup: see the plan this was built from — schema, tool
surface, async job + notification loop, cost-tracking design.

## Status

Milestone **M1** (Postgres schema + episode/scene/character/location CRUD) and the
first half of **M2** (OpenRouter tool-calling chat loop, non-streamed) are built.
Image/video generation, the async job/notification system, WebSocket push, and cost
tracking are not wired yet — see the plan for the remaining milestones (M3-M8).

## Running locally

Requires Python 3.12+ and a Postgres database.

```bash
python -m venv .venv
.venv/Scripts/activate  # or source .venv/bin/activate on Linux/macOS
pip install -r requirements.txt
cp .env.example .env  # fill in DATABASE_URL and OPENROUTER_API_KEY
uvicorn app.main:app --reload
```

The schema in `app/schema.sql` is applied automatically (idempotently) on startup.

## Deploying to Railway

1. Create a new Railway project from this GitHub repo.
2. Add Railway's **Postgres** addon to the project — it injects `DATABASE_URL`
   automatically once attached to this service.
3. Add a **Volume** to this service, mounted at `/data`.
4. Set service variables (Settings -> Variables): `OPENROUTER_API_KEY` (your key,
   server-side only), `MEDIA_ROOT=/data`, `DEFAULT_AGENT_MODEL` (optional).
5. Deploy. Railway auto-detects the `Procfile` (`uvicorn app.main:app --host 0.0.0.0
   --port $PORT`).
6. Once live, hit `/api/health` to confirm the app booted and connected to Postgres.

## API surface (M1/M2)

- `GET/POST /api/episodes`, `PATCH /api/episodes/{id}`, `POST /api/episodes/{id}/select`
- `POST /api/episodes/{id}/characters`, `PATCH/DELETE /api/characters/{id}`
- `POST /api/episodes/{id}/locations`, `PATCH/DELETE /api/locations/{id}`
- `POST /api/episodes/{id}/scenes`, `PATCH/DELETE /api/scenes/{id}`,
  `POST /api/episodes/{id}/reorder_scenes`
- `GET /api/storyboard?episode_id=` — full episode + scenes + characters + locations
- `GET/POST /api/episodes/{id}/chat` — episode-level planning chat thread
- `GET/POST /api/scenes/{id}/chat` — scene-scoped chat thread
- `GET /api/models` — server-proxied OpenRouter model list (for the chat model picker)

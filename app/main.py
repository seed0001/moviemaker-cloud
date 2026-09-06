from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import db, openrouter
from .routes import chat as chat_routes
from .routes import storyboard as storyboard_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()


app = FastAPI(title="movieMaker Cloud", lifespan=lifespan)
app.include_router(storyboard_routes.router)
app.include_router(chat_routes.router)


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/models")
async def api_models():
    """Server-proxied OpenRouter model list, so the browser-side model picker never
    needs the API key (it lives only in OPENROUTER_API_KEY on this process)."""
    return await openrouter.list_models()


app.mount("/", StaticFiles(directory="static", html=True), name="static")

"""Chat routes. M2 scope: synchronous request/response (no WebSocket streaming yet —
that lands in M6; see the plan). POST returns once the full tool-calling turn is done."""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import chat, storyboard
from ..agent.loop import run_agent_turn

router = APIRouter(prefix="/api")


class ChatSend(BaseModel):
    message: str
    model: Optional[str] = None


async def _apply_model(thread: dict, model: Optional[str]) -> dict:
    if model and model != thread["model"]:
        await chat.set_thread_model(thread["id"], model)
        thread = await chat.get_thread(thread["id"])
    return thread


@router.get("/episodes/{episode_id}/chat")
async def api_get_episode_chat(episode_id: str):
    thread = await chat.get_or_create_planning_thread(episode_id)
    return {"thread": thread, "messages": await chat.list_messages(thread["id"])}


@router.post("/episodes/{episode_id}/chat")
async def api_post_episode_chat(episode_id: str, body: ChatSend):
    thread = await chat.get_or_create_planning_thread(episode_id)
    thread = await _apply_model(thread, body.model)
    reply = await run_agent_turn(thread["id"], body.message)
    return {"thread_id": thread["id"], "reply": reply}


@router.get("/scenes/{scene_id}/chat")
async def api_get_scene_chat(scene_id: str):
    scene = await storyboard.get_scene(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="scene not found")
    thread = await chat.get_or_create_scene_thread(scene["episode_id"], scene_id)
    return {"thread": thread, "messages": await chat.list_messages(thread["id"])}


@router.post("/scenes/{scene_id}/chat")
async def api_post_scene_chat(scene_id: str, body: ChatSend):
    scene = await storyboard.get_scene(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="scene not found")
    thread = await chat.get_or_create_scene_thread(scene["episode_id"], scene_id)
    thread = await _apply_model(thread, body.model)
    reply = await run_agent_turn(thread["id"], body.message)
    return {"thread_id": thread["id"], "reply": reply}

"""Tool JSON-Schemas + dispatch table for the agent's tool-calling loop.

M2 scope: storyboard CRUD only. Image/video/job/cost tools are added in M3-M5
(see the plan at C:\\Users\\aztre\\.claude\\plans\\curious-swinging-falcon.md) once
media_jobs.py/pricing.py/cost.py exist — wiring their schemas here now would let the
agent "call" tools that don't do anything real yet.
"""
from .. import storyboard

STRING = {"type": "string"}
OPT_STRING = {"type": "string"}


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SCHEMAS = [
    _schema(
        "get_storyboard",
        "Read the full current storyboard: episode bible (title/premise/style), every character, "
        "every location, and every scene (in order) with its status. Call this whenever you need "
        "to see current state before making a change or answering a question about the storyboard.",
        {"episode_id": OPT_STRING}, [],
    ),
    _schema(
        "update_episode",
        "Update the episode bible: title, premise, and/or visual/tonal style. Only pass the fields "
        "you want to change.",
        {"episode_id": STRING, "title": OPT_STRING, "premise": OPT_STRING, "style": OPT_STRING},
        ["episode_id"],
    ),
    _schema(
        "create_character",
        "Add a new character to the episode.",
        {"episode_id": STRING, "name": STRING, "description": OPT_STRING},
        ["episode_id", "name"],
    ),
    _schema(
        "update_character",
        "Update a character's name and/or description.",
        {"character_id": STRING, "name": OPT_STRING, "description": OPT_STRING},
        ["character_id"],
    ),
    _schema(
        "delete_character",
        "Remove a character from the episode.",
        {"character_id": STRING}, ["character_id"],
    ),
    _schema(
        "create_location",
        "Add a new location/set to the episode.",
        {"episode_id": STRING, "name": STRING, "description": OPT_STRING},
        ["episode_id", "name"],
    ),
    _schema(
        "update_location",
        "Update a location's name and/or description.",
        {"location_id": STRING, "name": OPT_STRING, "description": OPT_STRING},
        ["location_id"],
    ),
    _schema(
        "delete_location",
        "Remove a location from the episode.",
        {"location_id": STRING}, ["location_id"],
    ),
    _schema(
        "create_scene",
        "Add a new scene to the episode's timeline (appended at the end). type is one of "
        "dialogue|action|establishing|closeup|montage|title|custom. duration is seconds.",
        {
            "episode_id": STRING, "title": OPT_STRING, "type": OPT_STRING,
            "duration": {"type": "integer"}, "resolution": OPT_STRING, "aspect_ratio": OPT_STRING,
            "chain": {"type": "boolean"}, "character_ids": {"type": "array", "items": STRING},
            "location_id": OPT_STRING, "prompt": OPT_STRING, "notes": OPT_STRING,
        },
        ["episode_id"],
    ),
    _schema(
        "update_scene",
        "Update any fields of an existing scene. Only pass the fields you want to change.",
        {
            "scene_id": STRING, "title": OPT_STRING, "type": OPT_STRING,
            "duration": {"type": "integer"}, "resolution": OPT_STRING, "aspect_ratio": OPT_STRING,
            "chain": {"type": "boolean"}, "character_ids": {"type": "array", "items": STRING},
            "location_id": OPT_STRING, "prompt": OPT_STRING, "notes": OPT_STRING, "status": OPT_STRING,
        },
        ["scene_id"],
    ),
    _schema(
        "reorder_scenes",
        "Set the scene order for an episode.",
        {"episode_id": STRING, "scene_order": {"type": "array", "items": STRING}},
        ["episode_id", "scene_order"],
    ),
    _schema(
        "delete_scene",
        "Delete a scene from the episode.",
        {"scene_id": STRING}, ["scene_id"],
    ),
]


async def _get_storyboard(episode_id: str | None = None):
    return await storyboard.get_full_episode(episode_id)


async def _update_episode(episode_id: str, **fields):
    return await storyboard.update_episode(episode_id, **fields)


async def _create_character(episode_id: str, name: str, description: str = ""):
    return await storyboard.create_character(episode_id, name=name, description=description)


async def _update_character(character_id: str, **fields):
    return await storyboard.update_character(character_id, **fields)


async def _delete_character(character_id: str):
    await storyboard.delete_character(character_id)
    return {"ok": True}


async def _create_location(episode_id: str, name: str, description: str = ""):
    return await storyboard.create_location(episode_id, name=name, description=description)


async def _update_location(location_id: str, **fields):
    return await storyboard.update_location(location_id, **fields)


async def _delete_location(location_id: str):
    await storyboard.delete_location(location_id)
    return {"ok": True}


async def _create_scene(episode_id: str, **fields):
    return await storyboard.create_scene(episode_id, **fields)


async def _update_scene(scene_id: str, **fields):
    return await storyboard.update_scene(scene_id, **fields)


async def _reorder_scenes(episode_id: str, scene_order: list[str]):
    return await storyboard.reorder_scenes(episode_id, scene_order)


async def _delete_scene(scene_id: str):
    await storyboard.delete_scene(scene_id)
    return {"ok": True}


DISPATCH = {
    "get_storyboard": _get_storyboard,
    "update_episode": _update_episode,
    "create_character": _create_character,
    "update_character": _update_character,
    "delete_character": _delete_character,
    "create_location": _create_location,
    "update_location": _update_location,
    "delete_location": _delete_location,
    "create_scene": _create_scene,
    "update_scene": _update_scene,
    "reorder_scenes": _reorder_scenes,
    "delete_scene": _delete_scene,
}

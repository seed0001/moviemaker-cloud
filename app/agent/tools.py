"""Tool JSON-Schemas + dispatch table for the agent's tool-calling loop.

Storyboard CRUD (M2), image generation (M3), and video generation + approve/stitch (M5) —
every tool listed here actually does something; never describe a capability in the system
prompt that isn't backed by a real entry in DISPATCH.
"""
from .. import jobs_status, media_jobs, media_manage, openrouter, render_pipeline, storyboard

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
        "dialogue|action|establishing|closeup|montage|title|custom. duration is seconds. "
        "video_model sets this scene's own default OpenRouter video model id (persists — no need to "
        "repeat it on every generate_scene_video call); leave unset to use the pipeline default.",
        {
            "episode_id": STRING, "title": OPT_STRING, "type": OPT_STRING,
            "duration": {"type": "integer"}, "resolution": OPT_STRING, "aspect_ratio": OPT_STRING,
            "chain": {"type": "boolean"}, "character_ids": {"type": "array", "items": STRING},
            "location_id": OPT_STRING, "prompt": OPT_STRING, "notes": OPT_STRING, "video_model": OPT_STRING,
        },
        ["episode_id"],
    ),
    _schema(
        "update_scene",
        "Update any fields of an existing scene. Only pass the fields you want to change. "
        "video_model sets/changes this scene's own default video model id (persists across "
        "generations); pass an empty string to clear it back to the pipeline default.",
        {
            "scene_id": STRING, "title": OPT_STRING, "type": OPT_STRING,
            "duration": {"type": "integer"}, "resolution": OPT_STRING, "aspect_ratio": OPT_STRING,
            "chain": {"type": "boolean"}, "character_ids": {"type": "array", "items": STRING},
            "location_id": OPT_STRING, "prompt": OPT_STRING, "notes": OPT_STRING, "status": OPT_STRING,
            "video_model": OPT_STRING,
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
    _schema(
        "list_image_models",
        "List real image-generation models available on OpenRouter right now, with their "
        "ids. Call this before recommending or using a model you haven't confirmed exists.",
        {}, [],
    ),
    _schema(
        "generate_character_portrait",
        "Generate a reference portrait image for a character. IMPORTANT two-step contract: "
        "call this WITHOUT confirmed (or confirmed=false) first — it returns a cost quote and "
        "does not generate anything. Only call it again with confirmed=true after the user has "
        "explicitly said to proceed in their own message.",
        {
            "character_id": STRING, "prompt": STRING,
            "confirmed": {"type": "boolean", "description": "Must be true to actually generate."},
            "model": OPT_STRING, "resolution": OPT_STRING, "n": {"type": "integer"},
        },
        ["character_id", "prompt"],
    ),
    _schema(
        "generate_location_still",
        "Generate a reference still image for a location/set. Same two-step confirmed "
        "contract as generate_character_portrait.",
        {
            "location_id": STRING, "prompt": STRING,
            "confirmed": {"type": "boolean", "description": "Must be true to actually generate."},
            "model": OPT_STRING, "resolution": OPT_STRING, "n": {"type": "integer"},
        },
        ["location_id", "prompt"],
    ),
    _schema(
        "get_job",
        "Look up the real current status of one generation job by id.",
        {"job_id": STRING}, ["job_id"],
    ),
    _schema(
        "list_jobs",
        "List real generation jobs (optionally filtered) to answer 'what's running / what "
        "finished / what failed' truthfully. Never state a job's status without calling this "
        "or get_job first.",
        {"status": OPT_STRING, "type": OPT_STRING, "episode_id": OPT_STRING, "scene_id": OPT_STRING,
         "limit": {"type": "integer"}},
        [],
    ),
    _schema(
        "list_video_models",
        "List real video-generation models available on OpenRouter right now (e.g. ByteDance/"
        "Seedance, Google/Veo, MiniMax/Hailuo), each with its pricing_skus so cost can be compared "
        "before picking one. Call this before recommending or using a model you haven't confirmed exists.",
        {}, [],
    ),
    _schema(
        "generate_scene_video",
        "Generate the actual video for a scene. This is long-running (minutes, not seconds) — "
        "it runs in the background and this call returns immediately once queued; check "
        "progress with get_job/list_jobs, never guess. Same two-step confirmed contract as the "
        "image tools: call WITHOUT confirmed first for a cost quote, generates nothing; call "
        "again with confirmed=true (after the user's explicit yes) to actually start it. Prompt/"
        "duration/resolution/aspect_ratio/model default to the scene's own saved fields (including "
        "video_model) if omitted, then fall back to the pipeline default if the scene has none set. "
        "use_chain defaults to the scene's own chain flag; when true it uses the previous "
        "scene's approved take as the first frame for visual continuity.",
        {
            "scene_id": STRING, "prompt": OPT_STRING,
            "confirmed": {"type": "boolean", "description": "Must be true to actually generate."},
            "model": OPT_STRING, "duration": {"type": "integer"}, "resolution": OPT_STRING,
            "aspect_ratio": OPT_STRING, "use_chain": {"type": "boolean"},
        },
        ["scene_id"],
    ),
    _schema(
        "approve_take",
        "Mark a completed video job as the approved take for its scene (used later for "
        "stitching the full episode together).",
        {"scene_id": STRING, "job_id": STRING}, ["scene_id", "job_id"],
    ),
    _schema(
        "unapprove_take",
        "Clear a scene's approved take.",
        {"scene_id": STRING}, ["scene_id"],
    ),
    _schema(
        "stitch_episode",
        "Concatenate every scene's approved take (in scene order) into one final episode "
        "video file. Requires every scene you want included to already have an approved take. "
        "This uses local ffmpeg only — no OpenRouter cost, no confirmation needed.",
        {"episode_id": STRING}, ["episode_id"],
    ),
    _schema(
        "get_storage_usage",
        "Report real disk usage of generated media: total bytes, a breakdown by job type "
        "(image/video/stitch), and a per-job list (job_id, type, episode_id, scene_id, bytes) so "
        "the biggest or oldest files can be identified for deletion. Call this before suggesting "
        "what to clean up — never guess at sizes.",
        {}, [],
    ),
    _schema(
        "delete_media",
        "Permanently delete one job's generated file from disk to free storage. Same two-step "
        "confirmed contract as generation: call WITHOUT confirmed first — it returns a preview "
        "(bytes that would be freed, whether it's currently an approved take) and deletes nothing. "
        "Only call again with confirmed=true after the user's explicit yes. The job record itself "
        "is kept (never deleted) so history/cost tracking stays intact — only its file and media_path "
        "are cleared. If the job is a scene's approved take, this fails unless force=true (which "
        "unapproves it first, then deletes) — surface that tradeoff to the user rather than passing "
        "force=true automatically.",
        {"job_id": STRING, "confirmed": {"type": "boolean"}, "force": {"type": "boolean"}},
        ["job_id"],
    ),
    _schema(
        "delete_rejected_takes",
        "Bulk cleanup: permanently delete every completed video take for a scene EXCEPT its "
        "current approved take (if any) — the common case of clearing out generations you didn't "
        "like. Same two-step confirmed contract: call WITHOUT confirmed first for a preview (how "
        "many takes, total bytes), then again with confirmed=true to actually delete.",
        {"scene_id": STRING, "confirmed": {"type": "boolean"}}, ["scene_id"],
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


async def _list_image_models():
    res = await openrouter.list_image_models()
    models = res.get("data") or res.get("models") or []
    return [{"id": m.get("id"), "name": m.get("name")} for m in models]


async def _generate_character_portrait(character_id: str, prompt: str, confirmed: bool = False,
                                        model: str | None = None, resolution: str | None = None,
                                        n: int = 1):
    kwargs = {"confirmed": confirmed, "resolution": resolution, "n": n}
    if model:
        kwargs["model"] = model
    return await media_jobs.generate_reference_image("character", character_id, prompt, **kwargs)


async def _generate_location_still(location_id: str, prompt: str, confirmed: bool = False,
                                    model: str | None = None, resolution: str | None = None,
                                    n: int = 1):
    kwargs = {"confirmed": confirmed, "resolution": resolution, "n": n}
    if model:
        kwargs["model"] = model
    return await media_jobs.generate_reference_image("location", location_id, prompt, **kwargs)


async def _get_job(job_id: str):
    return await jobs_status.get_job(job_id)


async def _list_jobs(**kwargs):
    return await jobs_status.list_jobs(**{k: v for k, v in kwargs.items() if v is not None})


async def _list_video_models():
    res = await openrouter.list_video_models()
    models = res.get("data") or res.get("models") or []
    return [
        {
            "id": m.get("id"), "name": m.get("name"), "pricing_skus": m.get("pricing_skus"),
            "generate_audio": m.get("generate_audio"),
            "supported_resolutions": m.get("supported_resolutions"),
            "supported_durations": m.get("supported_durations"),
        }
        for m in models
    ]


async def _generate_scene_video(scene_id: str, prompt: str | None = None, confirmed: bool = False,
                                 model: str | None = None, duration: int | None = None,
                                 resolution: str | None = None, aspect_ratio: str | None = None,
                                 use_chain: bool | None = None):
    return await media_jobs.enqueue_video_job(
        scene_id, prompt=prompt, confirmed=confirmed, model=model, duration=duration,
        resolution=resolution, aspect_ratio=aspect_ratio, use_chain=use_chain,
    )


async def _approve_take(scene_id: str, job_id: str):
    return await render_pipeline.approve_take(scene_id, job_id)


async def _unapprove_take(scene_id: str):
    return await render_pipeline.unapprove_take(scene_id)


async def _stitch_episode(episode_id: str):
    return await render_pipeline.stitch_episode(episode_id)


async def _get_storage_usage():
    return await media_manage.get_storage_summary()


async def _delete_media(job_id: str, confirmed: bool = False, force: bool = False):
    return await media_manage.delete_job_media(job_id, confirmed=confirmed, force=force)


async def _delete_rejected_takes(scene_id: str, confirmed: bool = False):
    return await media_manage.delete_rejected_takes(scene_id, confirmed=confirmed)


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
    "list_image_models": _list_image_models,
    "generate_character_portrait": _generate_character_portrait,
    "generate_location_still": _generate_location_still,
    "get_job": _get_job,
    "list_jobs": _list_jobs,
    "list_video_models": _list_video_models,
    "generate_scene_video": _generate_scene_video,
    "approve_take": _approve_take,
    "unapprove_take": _unapprove_take,
    "stitch_episode": _stitch_episode,
    "get_storage_usage": _get_storage_usage,
    "delete_media": _delete_media,
    "delete_rejected_takes": _delete_rejected_takes,
}

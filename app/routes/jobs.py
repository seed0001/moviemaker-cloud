"""Read-only job routes + approve/unapprove/stitch, so the UI can show and act on
generation results without going through chat."""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import jobs_status, media_manage, render_pipeline

router = APIRouter(prefix="/api")


class ApproveTake(BaseModel):
    job_id: str


class DeleteMedia(BaseModel):
    confirmed: bool = False
    force: bool = False


class DeleteRejectedTakes(BaseModel):
    confirmed: bool = False


@router.get("/jobs")
async def api_list_jobs(status: Optional[str] = None, type: Optional[str] = None,
                         episode_id: Optional[str] = None, scene_id: Optional[str] = None,
                         limit: int = 50):
    return await jobs_status.list_jobs(status=status, type=type, episode_id=episode_id,
                                        scene_id=scene_id, limit=limit)


@router.get("/jobs/{job_id}")
async def api_get_job(job_id: str):
    job = await jobs_status.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="not found")
    return job


@router.post("/scenes/{scene_id}/approve")
async def api_approve_take(scene_id: str, body: ApproveTake):
    result = await render_pipeline.approve_take(scene_id, body.job_id)
    if result and "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/scenes/{scene_id}/unapprove")
async def api_unapprove_take(scene_id: str):
    return await render_pipeline.unapprove_take(scene_id)


@router.post("/episodes/{episode_id}/stitch")
async def api_stitch_episode(episode_id: str):
    return await render_pipeline.stitch_episode(episode_id)


@router.get("/storage")
async def api_get_storage():
    return await media_manage.get_storage_summary()


@router.post("/jobs/{job_id}/delete_media")
async def api_delete_job_media(job_id: str, body: DeleteMedia):
    result = await media_manage.delete_job_media(job_id, confirmed=body.confirmed, force=body.force)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/scenes/{scene_id}/delete_rejected_takes")
async def api_delete_rejected_takes(scene_id: str, body: DeleteRejectedTakes):
    result = await media_manage.delete_rejected_takes(scene_id, confirmed=body.confirmed)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

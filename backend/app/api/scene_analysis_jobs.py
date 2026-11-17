
from fastapi import APIRouter, HTTPException, Query

from backend.app.services.scene_analysis_worker import (
    get_job_status,
    start_scene_analysis_job,
)


router = APIRouter(
    prefix="/api/videos",
    tags=["AI Automatic Analysis"],
)


@router.post("/{video_id}/analysis/start")
def start_analysis(
    video_id: int,
    batch_size: int = Query(default=5, ge=1, le=20),
):
    try:
        return start_scene_analysis_job(
            video_id=video_id,
            batch_size=batch_size,
        )

    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not start analysis: {error}",
        ) from error


@router.get("/{video_id}/analysis/job")
def analysis_job_status(video_id: int):
    job = get_job_status(video_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="No automatic analysis job found for this video.",
        )

    return job

import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from sqlalchemy import select

from backend.app.core.database import SessionLocal
from backend.app.models.pipeline_job import PipelineJob
from backend.app.models.video import Video
from backend.app.services.pipeline_service import run_pipeline_job
from backend.app.core.workflow_logger import log_workflow

router = APIRouter(
    prefix="/api/videos",
    tags=["Automated Video Pipeline"],
)


@router.post("/{video_id}/pipeline/start", status_code=202)
def start_pipeline(
    video_id: int,
    background_tasks: BackgroundTasks,
    evaluation_limit: int = Query(default=40, ge=1, le=100),
    evaluation_batch_size: int = Query(default=3, ge=1, le=5),
    scene_batch_size: int = Query(default=5, ge=1, le=20),
):
    db = SessionLocal()

    try:
        video = db.get(Video, video_id)

        if video is None:
            raise HTTPException(
                status_code=404,
                detail=f"Video {video_id} was not found.",
            )

        if not video.commercial_rights_confirmed:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Commercial rights confirmation is required before "
                    "starting the automated pipeline. Confirm that you "
                    "have the necessary rights or permissions for this video."
                ),
            )

        active_job = db.scalar(
            select(PipelineJob)
            .where(
                PipelineJob.video_id == video_id,
                PipelineJob.status.in_(["pending", "running"]),
            )
            .order_by(PipelineJob.id.desc())
        )

        if active_job is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "A pipeline is already active for this video.",
                    "job_id": active_job.id,
                    "status": active_job.status,
                },
            )

        job = PipelineJob(
            video_id=video_id,
            status="pending",
            current_stage="queued",
            progress_percent=0,
            stage_details="{}",
        )

        db.add(job)
        db.commit()
        db.refresh(job)

        log_workflow(
            job_id=job.id,
            video_id=video.id,
            stage="pipeline",
            status="queued",
            message=(
                f"Filename: {video.original_filename} | "
                f"Evaluation limit: {evaluation_limit} | "
                f"Evaluation batch: {evaluation_batch_size} | "
                f"Scene batch: {scene_batch_size}"
            ),
        )

        background_tasks.add_task(
            run_pipeline_job,
            job.id,
            evaluation_limit,
            evaluation_batch_size,
            scene_batch_size,
        )

        return {
            "message": "Video pipeline started.",
            "job_id": job.id,
            "video_id": video_id,
            "status": job.status,
            "current_stage": job.current_stage,
            "progress_percent": job.progress_percent,
        }

    except HTTPException:
        raise

    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Could not start pipeline: {error}",
        ) from error

    finally:
        db.close()


@router.get("/{video_id}/pipeline/status")
def pipeline_status(video_id: int):
    db = SessionLocal()

    try:
        job = db.scalar(
            select(PipelineJob)
            .where(PipelineJob.video_id == video_id)
            .order_by(PipelineJob.id.desc())
        )

        if job is None:
            raise HTTPException(
                status_code=404,
                detail="No pipeline job found for this video.",
            )

        try:
            stage_details = json.loads(job.stage_details or "{}")
        except (json.JSONDecodeError, TypeError):
            stage_details = {}

        return {
            "job_id": job.id,
            "video_id": job.video_id,
            "status": job.status,
            "current_stage": job.current_stage,
            "progress_percent": job.progress_percent,
            "stage_details": stage_details,
            "error_message": job.error_message,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "updated_at": job.updated_at,
        }

    finally:
        db.close()

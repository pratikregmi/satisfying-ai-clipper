
import logging
import threading

from sqlalchemy import func, select

from backend.app.core.database import SessionLocal
from backend.app.models.scene import Scene
from backend.app.models.scene_analysis import SceneAnalysis
from backend.app.services.scene_batch_service import process_scene_batch


logger = logging.getLogger(__name__)

# Prevent multiple automatic jobs for the same video.
_active_jobs: dict[int, dict] = {}
_jobs_lock = threading.Lock()


def get_job_status(video_id: int) -> dict | None:
    with _jobs_lock:
        job = _active_jobs.get(video_id)

        if job is None:
            return None

        return dict(job)


def run_scene_analysis_job(
    video_id: int,
    batch_size: int = 5,
):
    failed_scene_ids: set[int] = set()

    with _jobs_lock:
        job = _active_jobs[video_id]
        job["status"] = "running"

    try:
        while True:
            db = SessionLocal()

            try:
                result = process_scene_batch(
                    db=db,
                    video_id=video_id,
                    batch_size=batch_size,
                    exclude_scene_ids=failed_scene_ids,
                )

            finally:
                db.close()

            failed_ids = {
                item["scene_id"]
                for item in result["failed_scenes"]
            }

            failed_scene_ids.update(failed_ids)

            with _jobs_lock:
                job = _active_jobs[video_id]

                job["analyzed"] = result["total_analyzed"]
                job["remaining"] = result["remaining"]
                job["progress_percent"] = round(
                    result["total_analyzed"]
                    / result["total_scenes"] * 100,
                    2,
                )
                job["failed"] = len(failed_scene_ids)
                job["last_batch_completed"] = (
                    result["completed_this_batch"]
                )
                job["last_batch_failed"] = (
                    result["failed_this_batch"]
                )
                job["failed_scenes"] = list(
                    failed_scene_ids
                )

            if result["remaining"] == 0:
                with _jobs_lock:
                    job = _active_jobs[video_id]
                    job["status"] = "completed"

                break

            if not result["has_more"] or not result["processed_this_batch"]:
                with _jobs_lock:
                    job = _active_jobs[video_id]
                    job["status"] = (
                        "completed_with_errors"
                        if failed_scene_ids
                        else "completed"
                    )

                break

            # All remaining scenes may have failed.
            if (
                result["completed_this_batch"] == 0
                and result["failed_this_batch"] == 0
            ):
                break

        logger.info(
            "Scene analysis job finished for video %s",
            video_id,
        )

    except Exception as error:
        logger.exception(
            "Scene analysis job failed for video %s",
            video_id,
        )

        with _jobs_lock:
            _active_jobs[video_id]["status"] = "failed"
            _active_jobs[video_id]["error"] = str(error)

    finally:
        with _jobs_lock:
            if video_id in _active_jobs:
                _active_jobs[video_id]["finished"] = True


def start_scene_analysis_job(
    video_id: int,
    batch_size: int = 5,
) -> dict:
    if not 1 <= batch_size <= 20:
        raise ValueError("Batch size must be between 1 and 20.")

    with _jobs_lock:
        existing = _active_jobs.get(video_id)

        if existing and existing["status"] == "running":
            return {
                "message": "Analysis is already running.",
                "job": dict(existing),
            }

        db = SessionLocal()

        try:
            total = db.scalar(
                select(func.count(Scene.id)).where(
                    Scene.video_id == video_id
                )
            ) or 0

            analyzed = db.scalar(
                select(func.count(SceneAnalysis.id))
                .join(
                    Scene,
                    Scene.id == SceneAnalysis.scene_id,
                )
                .where(Scene.video_id == video_id)
            ) or 0

        finally:
            db.close()

        if total == 0:
            raise ValueError("No scenes found for this video.")

        if analyzed == total:
            return {
                "message": "All scenes have already been analyzed.",
                "job": {
                    "video_id": video_id,
                    "status": "completed",
                    "total_scenes": total,
                    "analyzed": analyzed,
                    "remaining": 0,
                    "progress_percent": 100,
                },
            }

        _active_jobs[video_id] = {
            "video_id": video_id,
            "status": "starting",
            "total_scenes": total,
            "analyzed": analyzed,
            "remaining": total - analyzed,
            "progress_percent": round(
                analyzed / total * 100,
                2,
            ),
            "batch_size": batch_size,
            "failed": 0,
            "failed_scenes": [],
            "last_batch_completed": 0,
            "last_batch_failed": 0,
            "error": None,
            "finished": False,
        }

        thread = threading.Thread(
            target=run_scene_analysis_job,
            args=(video_id, batch_size),
            daemon=True,
        )

        thread.start()

        return {
            "message": "Automatic scene analysis started.",
            "job": dict(_active_jobs[video_id]),
        }

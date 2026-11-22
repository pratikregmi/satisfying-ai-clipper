import re
from pathlib import Path
from uuid import uuid4
import subprocess

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.video import Video
from backend.app.models.pipeline_job import PipelineJob
from backend.app.schemas.video import VideoResponse
from backend.app.services.video_service import (
    get_video_metadata,
    generate_thumbnail,
)
from backend.app.services.downloader import download_video
from backend.app.services.pipeline_service import run_pipeline_job
from backend.app.services.video_storage_service import (
    ensure_video_storage,
    get_video_storage_paths,
    get_video_logger,
)


router = APIRouter(prefix="/api/videos", tags=["Videos"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1 GB


class VideoURLIngestRequest(BaseModel):
    source_url: str = Field(min_length=1, max_length=2048)
    source_name: str = Field(min_length=1, max_length=255)
    commercial_rights_confirmed: bool


def _log_video_event(video_id: int, message: str) -> None:
    """Write a per-video event without affecting the main operation."""
    try:
        get_video_logger(video_id).info(message)
    except Exception:
        # Logging must never undo a committed upload or ingestion.
        pass


def _cleanup_created_files(
    video_path: Path | None,
    thumbnail_path: Path | None,
) -> None:
    """Remove only files created by the current upload request."""

    if video_path is not None:
        video_path.unlink(missing_ok=True)

    if thumbnail_path is not None:
        thumbnail_path.unlink(missing_ok=True)


def _reserve_video_record(
    db: Session,
    original_filename: str,
    stored_filename: str,
    source_name: str,
) -> Video:
    """
    Reserve a database ID before creating files.

    This lets every upload use its permanent video-specific directory.
    The transaction is committed only after file processing succeeds.
    """

    video = Video(
        original_filename=original_filename,
        stored_filename=stored_filename,
        file_path="pending",
        thumbnail_path=None,
        file_size=0,
        source_name=source_name,
        commercial_rights_confirmed=True,
    )

    db.add(video)
    db.flush()

    return video


@router.post("/upload", response_model=VideoResponse)
def upload_video(
    file: UploadFile = File(...),
    source_name: str = Form(...),
    commercial_rights_confirmed: bool = Form(...),
    db: Session = Depends(get_db),
):
    if not commercial_rights_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Confirm that you have permission for commercial reuse.",
        )

    original_filename = Path(file.filename or "").name
    extension = Path(original_filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported video format.",
        )

    unique_name = f"{uuid4().hex}{extension}"

    video_path = None
    thumbnail_path = None

    try:
        # Reserve the database ID before writing any files.
        video = _reserve_video_record(
            db=db,
            original_filename=original_filename,
            stored_filename=unique_name,
            source_name=source_name,
        )

        paths = ensure_video_storage(video.id)

        video_path = paths["original"] / unique_name
        thumbnail_path = paths["upload_thumbnail"]

        file_size = 0

        with video_path.open("wb") as destination:
            while True:
                chunk = file.file.read(1024 * 1024)

                if not chunk:
                    break

                file_size += len(chunk)

                if file_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="Maximum upload size is 1 GB.",
                    )

                destination.write(chunk)

        if file_size == 0:
            raise HTTPException(
                status_code=400,
                detail="The uploaded file is empty.",
            )

        metadata = get_video_metadata(video_path)
        generate_thumbnail(video_path, thumbnail_path)

        video.file_path = str(
            video_path.relative_to(PROJECT_ROOT)
        )
        video.thumbnail_path = str(
            thumbnail_path.relative_to(PROJECT_ROOT)
        )
        video.file_size = file_size

        for key, value in metadata.items():
            setattr(video, key, value)

        db.commit()
        db.refresh(video)

        _log_video_event(
            video.id,
            "Direct video upload completed | "
            f"Filename: {video.original_filename} | "
            f"Size: {video.file_size} bytes",
        )

        return video

    except HTTPException:
        db.rollback()
        _cleanup_created_files(video_path, thumbnail_path)
        raise

    except (subprocess.SubprocessError, ValueError, OSError) as error:
        db.rollback()
        _cleanup_created_files(video_path, thumbnail_path)

        raise HTTPException(
            status_code=400,
            detail=f"Could not process this video: {error}",
        ) from error

    except Exception:
        db.rollback()
        _cleanup_created_files(video_path, thumbnail_path)
        raise

    finally:
        file.file.close()


@router.post("/ingest-url", status_code=202)
def ingest_video_url(
    request: VideoURLIngestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Download an authorized direct HTTPS video URL or supported YouTube URL,
    save it inside its video-specific directory,
    create its database record and pipeline job,
    and automatically start the processing pipeline.
    """

    if not request.commercial_rights_confirmed:
        raise HTTPException(
            status_code=403,
            detail="Commercial rights confirmation is required.",
        )

    video_path = None
    thumbnail_path = None

    try:
        # Reserve a permanent video ID before downloading.
        reservation_name = f"{uuid4().hex}.mp4"

        video = _reserve_video_record(
            db=db,
            original_filename="pending",
            stored_filename=reservation_name,
            source_name=request.source_name,
        )

        paths = ensure_video_storage(video.id)

        # Download directly into this video's original directory.
        video_path = download_video(
            request.source_url,
            paths["original"],
        )

        extension = video_path.suffix.lower()

        if extension not in ALLOWED_EXTENSIONS:
            raise ValueError(
                "Unsupported downloaded video format."
            )

        # Validate the downloaded video using FFprobe.
        metadata = get_video_metadata(video_path)

        thumbnail_path = paths["upload_thumbnail"]
        generate_thumbnail(video_path, thumbnail_path)

        source_stem = re.sub(
            r"[^A-Za-z0-9._ -]+",
            "_",
            Path(request.source_name).stem,
        ).strip(" ._-") or "youtube_video"

        original_filename = (
            f"{source_stem}{extension}"
        )[:255]

        file_size = video_path.stat().st_size

        video.original_filename = original_filename
        video.stored_filename = video_path.name
        video.file_path = str(
            video_path.relative_to(PROJECT_ROOT)
        )
        video.thumbnail_path = str(
            thumbnail_path.relative_to(PROJECT_ROOT)
        )
        video.file_size = file_size

        for key, value in metadata.items():
            setattr(video, key, value)

        # Create the video and pipeline job in one transaction.
        job = PipelineJob(
            video_id=video.id,
            status="pending",
            current_stage="queued",
            progress_percent=0,
            stage_details="{}",
        )

        db.add(job)
        db.commit()

        db.refresh(video)
        db.refresh(job)

        _log_video_event(
            video.id,
            "URL video ingestion completed | "
            f"Filename: {video.original_filename} | "
            f"Pipeline job ID: {job.id} | "
            "Pipeline status: queued",
        )

        # Preserve existing automatic pipeline startup for URL ingestion.
        background_tasks.add_task(
            run_pipeline_job,
            job.id,
            40,  # Evaluation limit
            3,   # Evaluation batch size
            5,   # Scene batch size
        )

        return {
            "message": "Video downloaded and automated pipeline started.",
            "video_id": video.id,
            "job_id": job.id,
            "original_filename": video.original_filename,
            "duration": video.duration,
            "status": job.status,
            "current_stage": job.current_stage,
            "progress_percent": job.progress_percent,
        }

    except HTTPException:
        db.rollback()
        _cleanup_created_files(video_path, thumbnail_path)
        raise

    except ValueError as error:
        db.rollback()
        _cleanup_created_files(video_path, thumbnail_path)

        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except httpx.HTTPError as error:
        db.rollback()
        _cleanup_created_files(video_path, thumbnail_path)

        raise HTTPException(
            status_code=502,
            detail=f"Could not download from the provided URL: {error}",
        ) from error

    except (subprocess.SubprocessError, OSError) as error:
        db.rollback()
        _cleanup_created_files(video_path, thumbnail_path)

        raise HTTPException(
            status_code=400,
            detail=f"Could not process downloaded video: {error}",
        ) from error

    except Exception as error:
        db.rollback()
        _cleanup_created_files(video_path, thumbnail_path)

        raise HTTPException(
            status_code=500,
            detail=f"Video ingestion failed: {error}",
        ) from error


@router.get("/", response_model=list[VideoResponse])
def list_videos(db: Session = Depends(get_db)):
    return db.scalars(
        select(Video).order_by(Video.created_at.desc())
    ).all()


@router.get("/{video_id}", response_model=VideoResponse)
def get_video(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)

    if not video:
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    return video

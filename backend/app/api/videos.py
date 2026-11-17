
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.app.core.database import get_db
from backend.app.models.video import Video
from backend.app.schemas.video import VideoResponse
from backend.app.services.video_service import (
    get_video_metadata,
    generate_thumbnail,
)
import subprocess

router = APIRouter(prefix="/api/videos", tags=["Videos"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_DIR = PROJECT_ROOT / "media" / "input"
THUMBNAIL_DIR = PROJECT_ROOT / "media" / "thumbnails"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1 GB


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
    video_path = UPLOAD_DIR / unique_name
    thumbnail_path = THUMBNAIL_DIR / f"{uuid4().hex}.jpg"

    file_size = 0

    try:
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

        video = Video(
            original_filename=original_filename,
            stored_filename=unique_name,
            file_path=str(video_path.relative_to(PROJECT_ROOT)),
            thumbnail_path=str(thumbnail_path.relative_to(PROJECT_ROOT)),
            file_size=file_size,
            source_name=source_name,
            commercial_rights_confirmed=True,
            **metadata,
        )

        db.add(video)
        db.commit()
        db.refresh(video)

        return video

    except HTTPException:
        video_path.unlink(missing_ok=True)
        thumbnail_path.unlink(missing_ok=True)
        raise

    except (subprocess.SubprocessError, ValueError, OSError) as error:
        video_path.unlink(missing_ok=True)
        thumbnail_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"Could not process this video: {error}",
        ) from error

    except Exception:
        video_path.unlink(missing_ok=True)
        thumbnail_path.unlink(missing_ok=True)
        db.rollback()
        raise

    finally:
        file.file.close()


@router.get("/", response_model=list[VideoResponse])
def list_videos(db: Session = Depends(get_db)):
    return db.scalars(
        select(Video).order_by(Video.created_at.desc())
    ).all()


@router.get("/{video_id}", response_model=VideoResponse)
def get_video(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)

    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")

    return video

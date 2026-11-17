
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.core.database import SessionLocal, get_db
from backend.app.models.video import Video
from backend.app.models.transcription import (
    Transcription,
    TranscriptSegment,
)
from backend.app.services.transcription_service import transcribe_video


router = APIRouter(prefix="/api/videos", tags=["Transcriptions"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def run_transcription(video_id: int, model_name: str):
    db = SessionLocal()

    try:
        job = (
            db.query(Transcription)
            .filter(Transcription.video_id == video_id)
            .first()
        )

        video = db.query(Video).filter(Video.id == video_id).first()

        if not job or not video:
            return

        job.status = "processing"
        job.error_message = None
        db.commit()

        video_path = Path(video.file_path)

        if not video_path.is_absolute():
            video_path = PROJECT_ROOT / video_path

        result = transcribe_video(
            video_path=video_path,
            model_name=model_name,
        )

        # Replace old transcript only after successful transcription.
        db.query(TranscriptSegment).filter(
            TranscriptSegment.video_id == video_id
        ).delete(synchronize_session=False)

        for item in result["segments"]:
            db.add(
                TranscriptSegment(
                    video_id=video_id,
                    start_time=item["start_time"],
                    end_time=item["end_time"],
                    text=item["text"],
                )
            )

        job.status = "completed"
        job.language = result["language"]
        job.model_name = model_name
        job.completed_at = datetime.utcnow()
        job.error_message = None

        db.commit()

    except Exception as exc:
        db.rollback()

        job = (
            db.query(Transcription)
            .filter(Transcription.video_id == video_id)
            .first()
        )

        if job:
            job.status = "failed"
            job.error_message = str(exc)[:4000]
            db.commit()

    finally:
        db.close()


@router.post("/{video_id}/transcribe", status_code=202)
def start_transcription(
    video_id: int,
    background_tasks: BackgroundTasks,
    model_name: str = "base",
    db: Session = Depends(get_db),
):
    if model_name not in {"tiny", "base", "small"}:
        raise HTTPException(
            status_code=400,
            detail="Supported models: tiny, base, small",
        )

    video = db.query(Video).filter(Video.id == video_id).first()

    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")

    if not video.has_audio:
        raise HTTPException(
            status_code=400,
            detail="This video does not contain an audio stream.",
        )

    existing = (
        db.query(Transcription)
        .filter(Transcription.video_id == video_id)
        .first()
    )

    if existing and existing.status in {"pending", "processing"}:
        raise HTTPException(
            status_code=409,
            detail="Transcription is already running.",
        )

    if existing:
        existing.status = "pending"
        existing.model_name = model_name
        existing.error_message = None
        existing.completed_at = None
        db.commit()
    else:
        existing = Transcription(
            video_id=video_id,
            status="pending",
            model_name=model_name,
        )
        db.add(existing)
        db.commit()

    background_tasks.add_task(
        run_transcription,
        video_id,
        model_name,
    )

    return {
        "video_id": video_id,
        "status": "pending",
        "model_name": model_name,
        "message": "Transcription started.",
    }


@router.get("/{video_id}/transcription")
def get_transcription_status(
    video_id: int,
    db: Session = Depends(get_db),
):
    job = (
        db.query(Transcription)
        .filter(Transcription.video_id == video_id)
        .first()
    )

    if not job:
        raise HTTPException(
            status_code=404,
            detail="No transcription job found.",
        )

    return {
        "video_id": video_id,
        "status": job.status,
        "language": job.language,
        "model_name": job.model_name,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }


@router.get("/{video_id}/transcript")
def get_transcript(
    video_id: int,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=400,
            detail="Limit must be between 1 and 500.",
        )

    if offset < 0:
        raise HTTPException(
            status_code=400,
            detail="Offset cannot be negative.",
        )

    video = db.query(Video).filter(Video.id == video_id).first()

    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")

    query = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.video_id == video_id)
        .order_by(TranscriptSegment.start_time)
    )

    total = query.count()
    segments = query.offset(offset).limit(limit).all()

    return {
        "video_id": video_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "segments": [
            {
                "id": segment.id,
                "start_time": segment.start_time,
                "end_time": segment.end_time,
                "text": segment.text,
            }
            for segment in segments
        ],
    }

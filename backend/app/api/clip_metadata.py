import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.clip_metadata import ClipMetadata
from backend.app.models.moment_candidate import MomentCandidate
from backend.app.models.video import Video
from backend.app.services.clip_metadata_service import (
    generate_clip_metadata,
    metadata_to_dict,
)


router = APIRouter(
    prefix="/api/videos",
    tags=["Clip Metadata"],
)


class ClipMetadataUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    hashtags: list[str] = Field(min_length=3, max_length=8)


def _get_candidate(
    db: Session,
    video_id: int,
    candidate_id: int,
) -> MomentCandidate:
    video = db.get(Video, video_id)

    if video is None:
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    candidate = db.scalar(
        select(MomentCandidate).where(
            MomentCandidate.id == candidate_id,
            MomentCandidate.video_id == video_id,
        )
    )

    if candidate is None:
        raise HTTPException(
            status_code=404,
            detail="Clip candidate not found for this video.",
        )

    return candidate


@router.post(
    "/{video_id}/clips/{candidate_id}/metadata/generate"
)
def generate_metadata(
    video_id: int,
    candidate_id: int,
    db: Session = Depends(get_db),
):
    _get_candidate(db, video_id, candidate_id)

    try:
        return generate_clip_metadata(
            db=db,
            video_id=video_id,
            candidate_id=candidate_id,
        )

    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Metadata generation request failed: {error}",
        ) from error


@router.patch(
    "/{video_id}/clips/{candidate_id}/metadata"
)
def update_metadata(
    video_id: int,
    candidate_id: int,
    payload: ClipMetadataUpdate,
    db: Session = Depends(get_db),
):
    _get_candidate(db, video_id, candidate_id)

    metadata = db.scalar(
        select(ClipMetadata).where(
            ClipMetadata.candidate_id == candidate_id
        )
    )

    if metadata is None:
        metadata = ClipMetadata(candidate_id=candidate_id)
        db.add(metadata)

    metadata.title = payload.title.strip()
    metadata.description = payload.description.strip()
    metadata.hashtags = json.dumps(
        [tag.strip().lstrip("#") for tag in payload.hashtags],
        ensure_ascii=False,
    )
    metadata.status = "completed"
    metadata.error_message = None

    try:
        db.commit()
        db.refresh(metadata)
        return metadata_to_dict(metadata)

    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not save clip metadata.",
        ) from error

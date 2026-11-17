
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.moment_candidate import MomentCandidate
from backend.app.models.video import Video
from backend.app.services.moment_discovery_service import (
    discover_video_moments,
)


router = APIRouter(
    prefix="/api/videos",
    tags=["AI Moment Discovery"],
)


@router.post("/{video_id}/moments/discover")
def discover_moments(
    video_id: int,
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)

    if video is None:
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    try:
        return discover_video_moments(
            db=db,
            video_id=video_id,
        )

    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    except Exception as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Moment discovery failed: {error}",
        ) from error


@router.get("/{video_id}/moments")
def list_moments(
    video_id: int,
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)

    if video is None:
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    query = select(MomentCandidate).where(
        MomentCandidate.video_id == video_id
    )

    if status is not None:
        allowed_statuses = [
            "pending",
            "approved",
            "rejected",
        ]

        if status not in allowed_statuses:
            raise HTTPException(
                status_code=400,
                detail="Invalid status filter.",
            )

        query = query.where(
            MomentCandidate.status == status
        )

    total_query = select(
        func.count(MomentCandidate.id)
    ).where(
        MomentCandidate.video_id == video_id
    )

    if status is not None:
        total_query = total_query.where(
            MomentCandidate.status == status
        )

    total = db.scalar(total_query) or 0

    candidates = list(
        db.scalars(
            query
            .order_by(
                MomentCandidate.overall_score.desc().nullslast(),
                MomentCandidate.start_time.asc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()
    )

    return {
        "video_id": video_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "candidates": [
            {
                "id": candidate.id,
                "title": candidate.title,
                "summary": candidate.summary,
                "start_time": candidate.start_time,
                "end_time": candidate.end_time,
                "duration": candidate.duration,
                "scene_ids": json.loads(
                    candidate.scene_ids
                ),
                "transcript_excerpt": (
                    candidate.transcript_excerpt
                ),
                "overall_score": candidate.overall_score,
                "status": candidate.status,
                "explanation": candidate.explanation,
            }
            for candidate in candidates
        ],
    }


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.scene import Scene
from backend.app.models.scene_analysis import SceneAnalysis
from backend.app.services.scene_batch_service import process_scene_batch


router = APIRouter(
    prefix="/api/videos",
    tags=["AI Batch Analysis"],
)


@router.post("/{video_id}/analyze-scenes")
def analyze_scenes_batch(
    video_id: int,
    batch_size: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    total = db.scalar(
        select(func.count(Scene.id)).where(
            Scene.video_id == video_id
        )
    ) or 0

    if total == 0:
        raise HTTPException(
            status_code=404,
            detail="No scenes found for this video.",
        )

    try:
        return process_scene_batch(
            db=db,
            video_id=video_id,
            batch_size=batch_size,
        )

    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Batch analysis failed: {error}",
        ) from error


@router.get("/{video_id}/analysis-progress")
def get_analysis_progress(
    video_id: int,
    db: Session = Depends(get_db),
):
    total = db.scalar(
        select(func.count(Scene.id)).where(
            Scene.video_id == video_id
        )
    ) or 0

    if total == 0:
        raise HTTPException(
            status_code=404,
            detail="No scenes found for this video.",
        )

    analyzed = db.scalar(
        select(func.count(SceneAnalysis.id))
        .join(
            Scene,
            Scene.id == SceneAnalysis.scene_id,
        )
        .where(Scene.video_id == video_id)
    ) or 0

    remaining = total - analyzed

    return {
        "video_id": video_id,
        "total_scenes": total,
        "analyzed": analyzed,
        "remaining": remaining,
        "progress_percent": round(
            analyzed / total * 100,
            2,
        ),
        "status": (
            "completed" if remaining == 0 else "pending"
        ),
    }

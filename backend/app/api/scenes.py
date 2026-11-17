
from pathlib import Path
import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.video import Video
from backend.app.models.scene import Scene
from backend.app.schemas.scene import SceneResponse
from backend.app.services.scene_service import (
    detect_scenes,
    generate_scene_thumbnails,
)

router = APIRouter(prefix="/api/videos", tags=["Scenes"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
THUMBNAIL_DIR = PROJECT_ROOT / "media" / "thumbnails"


@router.post("/{video_id}/detect-scenes", response_model=list[SceneResponse])
def detect_video_scenes(
    video_id: int,
    threshold: float = 27.0,
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)

    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")

    video_path = PROJECT_ROOT / video.file_path

    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file is missing.")

    if not 1 <= threshold <= 100:
        raise HTTPException(
            status_code=400,
            detail="Threshold must be between 1 and 100.",
        )

    try:
        detected = detect_scenes(video_path, threshold)

        db.query(Scene).filter(Scene.video_id == video_id).delete()

        scenes = [
            Scene(video_id=video_id, **item)
            for item in detected
        ]

        db.add_all(scenes)
        db.commit()

        for scene in scenes:
            db.refresh(scene)

        return scenes

    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Scene detection failed: {error}",
        ) from error


@router.post("/{video_id}/generate-thumbnails")
def create_scene_thumbnails(
    video_id: int,
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)

    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")

    video_path = PROJECT_ROOT / video.file_path

    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file is missing.")

    scenes = db.scalars(
        select(Scene)
        .where(Scene.video_id == video_id)
        .order_by(Scene.scene_number)
    ).all()

    if not scenes:
        raise HTTPException(
            status_code=404,
            detail="No detected scenes found for this video.",
        )

    output_dir = THUMBNAIL_DIR / f"video_{video_id}"

    try:
        paths = generate_scene_thumbnails(
            video_path=video_path,
            scenes=scenes,
            output_dir=output_dir,
            frame_rate=video.frame_rate,
        )

        updated = 0

        for scene, path in zip(scenes, paths):
            if path.is_file():
                scene.thumbnail_path = str(
                    path.relative_to(PROJECT_ROOT)
                )
                updated += 1

        db.commit()

        return {
            "video_id": video_id,
            "total_scenes": len(scenes),
            "thumbnails_created": updated,
        }

    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Thumbnail generation failed: {error}",
        ) from error


@router.get("/{video_id}/scenes")
def get_video_scenes(
    video_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)

    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")

    total = db.scalar(
        select(func.count(Scene.id))
        .where(Scene.video_id == video_id)
    ) or 0

    scenes = db.scalars(
        select(Scene)
        .where(Scene.video_id == video_id)
        .order_by(Scene.scene_number)
        .offset(offset)
        .limit(limit)
    ).all()

    return {
        "video_id": video_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "scenes": [
            {
                **SceneResponse.model_validate(scene).model_dump(mode="json"),
                "thumbnail_url": (
                    f"/api/videos/{video_id}/scenes/{scene.id}/thumbnail"
                    if scene.thumbnail_path else None
                ),
            }
            for scene in scenes
        ],
    }


@router.get("/{video_id}/stream")
def stream_video(
    video_id: int,
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)

    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")

    video_path = PROJECT_ROOT / video.file_path

    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file is missing.")

    media_type = (
        mimetypes.guess_type(video_path.name)[0]
        or "application/octet-stream"
    )

    return FileResponse(
        path=video_path,
        media_type=media_type,
        filename=video.original_filename,
        content_disposition_type="inline",
    )


@router.get("/{video_id}/scenes/{scene_id}/thumbnail")
def scene_thumbnail(
    video_id: int,
    scene_id: int,
    db: Session = Depends(get_db),
):
    scene = db.get(Scene, scene_id)

    if not scene or scene.video_id != video_id:
        raise HTTPException(status_code=404, detail="Scene not found.")

    if not scene.thumbnail_path:
        raise HTTPException(
            status_code=404,
            detail="Thumbnail has not been generated yet.",
        )

    thumbnail_path = (PROJECT_ROOT / scene.thumbnail_path).resolve()

    if not thumbnail_path.is_relative_to(THUMBNAIL_DIR.resolve()):
        raise HTTPException(
            status_code=400,
            detail="Invalid thumbnail path.",
        )

    if not thumbnail_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Thumbnail file is missing.",
        )

    return FileResponse(
        thumbnail_path,
        media_type="image/jpeg",
    )

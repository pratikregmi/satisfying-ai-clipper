from pathlib import Path
import mimetypes
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.app.core.database import PROJECT_ROOT, get_db
from backend.app.models.video import Video
from backend.app.models.scene import Scene
from backend.app.schemas.scene import SceneResponse
from backend.app.services.scene_service import (
    detect_scenes,
    generate_scene_thumbnails,
)
from backend.app.services.video_storage_service import (
    get_video_storage_paths,
    resolve_video_storage_path,
)


router = APIRouter(prefix="/api/videos", tags=["Scenes"])


def _get_video_file(video: Video) -> Path:
    """Resolve the original video inside its dedicated storage folder."""

    try:
        video_path = resolve_video_storage_path(
            video.id,
            video.file_path,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid video storage path: {error}",
        ) from error

    expected_directory = (
        get_video_storage_paths(video.id)["original"].resolve()
    )

    if not video_path.is_relative_to(expected_directory):
        raise HTTPException(
            status_code=400,
            detail="Video file must belong to this video's original folder.",
        )

    if not video_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Video file is missing.",
        )

    return video_path


def _get_scene_thumbnail_file(
    video_id: int,
    stored_path: str,
) -> Path:
    """Resolve a scene thumbnail inside this video's scene-thumbnail folder."""

    paths = get_video_storage_paths(video_id)
    expected_directory = paths["scene_thumbnails"].resolve()

    try:
        thumbnail_path = resolve_video_storage_path(
            video_id,
            stored_path,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid thumbnail path: {error}",
        ) from error

    if not thumbnail_path.is_relative_to(expected_directory):
        raise HTTPException(
            status_code=400,
            detail="Thumbnail must belong to this video's scene-thumbnail folder.",
        )

    if not thumbnail_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Thumbnail file is missing.",
        )

    return thumbnail_path


@router.post(
    "/{video_id}/detect-scenes",
    response_model=list[SceneResponse],
)
def detect_video_scenes(
    video_id: int,
    threshold: float = 27.0,
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)

    if not video:
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    video_path = _get_video_file(video)

    if not 1 <= threshold <= 100:
        raise HTTPException(
            status_code=400,
            detail="Threshold must be between 1 and 100.",
        )

    try:
        detected = detect_scenes(video_path, threshold)

        db.query(Scene).filter(
            Scene.video_id == video_id
        ).delete()

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
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    video_path = _get_video_file(video)

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

    output_dir = get_video_storage_paths(
        video_id
    )["scene_thumbnails"]

    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        generated_paths = generate_scene_thumbnails(
            video_path=video_path,
            scenes=scenes,
            output_dir=output_dir,
            frame_rate=video.frame_rate,
        )

        updated = 0

        for scene, path in zip(scenes, generated_paths):
            if path.is_file():
                resolved_path = path.resolve()

                if not resolved_path.is_relative_to(
                    output_dir.resolve()
                ):
                    raise ValueError(
                        "Generated thumbnail is outside the video's storage folder."
                    )

                scene.thumbnail_path = str(
                    resolved_path.relative_to(PROJECT_ROOT)
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
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

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
                **SceneResponse.model_validate(scene).model_dump(
                    mode="json"
                ),
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
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    video_path = _get_video_file(video)

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


@router.get("/{video_id}/clips")
def list_video_clips(
    video_id: int,
    db: Session = Depends(get_db),
):
    """List generated review and Shorts clips for one video."""
    video = db.get(Video, video_id)

    if not video:
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    clips_directory = get_video_storage_paths(video_id)["clips"].resolve()

    if not clips_directory.is_dir():
        return {"video_id": video_id, "total": 0, "clips": []}

    clips_by_candidate = {}

    for clip_path in clips_directory.iterdir():
        match = re.fullmatch(
            r"candidate_(\d+)_(review|shorts|full)\.mp4",
            clip_path.name,
        )

        if not match or not clip_path.is_file():
            continue

        try:
            resolved_path = clip_path.resolve()
            if not resolved_path.is_relative_to(clips_directory):
                continue
        except OSError:
            continue

        candidate_id = int(match.group(1))
        clip_type = match.group(2)

        item = clips_by_candidate.setdefault(
            candidate_id,
            {
                "candidate_id": candidate_id,
                "review": None,
                "shorts": None,
                "full": None,
            },
        )

        item[clip_type] = {
            "filename": clip_path.name,
            "url": f"/api/videos/{video_id}/clips/{clip_path.name}",
            "size_bytes": resolved_path.stat().st_size,
        }

    clips = [
        clips_by_candidate[candidate_id]
        for candidate_id in sorted(clips_by_candidate)
    ]

    return {
        "video_id": video_id,
        "total": len(clips),
        "clips": clips,
    }


@router.get("/{video_id}/clips/{filename}")
def stream_video_clip(
    video_id: int,
    filename: str,
    db: Session = Depends(get_db),
):
    """Stream one generated clip without exposing filesystem paths."""
    video = db.get(Video, video_id)

    if not video:
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    if not re.fullmatch(
        r"candidate_\d+_(review|shorts|full)\.mp4",
        filename,
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid clip filename.",
        )

    paths = get_video_storage_paths(video_id)
    clips_directory = paths["clips"].resolve()

    try:
        clip_path = resolve_video_storage_path(
            video_id,
            clips_directory / filename,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail="Invalid clip storage path.",
        ) from error

    if not clip_path.is_relative_to(clips_directory):
        raise HTTPException(
            status_code=400,
            detail="Clip must belong to this video's clips folder.",
        )

    if not clip_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Clip not found.",
        )

    return FileResponse(
        path=clip_path,
        media_type="video/mp4",
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
        raise HTTPException(
            status_code=404,
            detail="Scene not found.",
        )

    if not scene.thumbnail_path:
        raise HTTPException(
            status_code=404,
            detail="Thumbnail has not been generated yet.",
        )

    thumbnail_path = _get_scene_thumbnail_file(
        video_id,
        scene.thumbnail_path,
    )

    return FileResponse(
        thumbnail_path,
        media_type="image/jpeg",
    )

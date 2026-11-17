from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.video import Video
from backend.app.models.scene import Scene
from backend.app.models.transcription import (
    Transcription,
    TranscriptSegment,
)
from backend.app.models.scene_transcript import SceneTranscriptMatch
from backend.app.services.scene_transcript_service import (
    match_scenes_with_transcripts,
)

router = APIRouter(
    prefix="/api/videos",
    tags=["Scene Transcript Matching"],
)


@router.post("/{video_id}/match-transcript")
def create_scene_transcript_matches(
    video_id: int,
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)

    if not video:
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    transcription = db.scalar(
        select(Transcription).where(
            Transcription.video_id == video_id
        )
    )

    if not transcription or transcription.status != "completed":
        raise HTTPException(
            status_code=400,
            detail="A completed transcription is required.",
        )

    scenes = db.scalars(
        select(Scene)
        .where(Scene.video_id == video_id)
        .order_by(Scene.start_time)
    ).all()

    if not scenes:
        raise HTTPException(
            status_code=404,
            detail="No detected scenes found.",
        )

    transcript_segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.video_id == video_id)
        .order_by(TranscriptSegment.start_time)
    ).all()

    if not transcript_segments:
        raise HTTPException(
            status_code=404,
            detail="No transcript segments found.",
        )

    try:
        matches = match_scenes_with_transcripts(
            scenes,
            transcript_segments,
        )

        # Replace previous matches for this video.
        db.execute(
            delete(SceneTranscriptMatch).where(
                SceneTranscriptMatch.video_id == video_id
            )
        )

        db.add_all([
            SceneTranscriptMatch(**match)
            for match in matches
        ])

        db.commit()

        matched_scene_ids = {
            match["scene_id"] for match in matches
        }

        return {
            "video_id": video_id,
            "total_scenes": len(scenes),
            "total_transcript_segments": len(transcript_segments),
            "total_matches": len(matches),
            "scenes_with_dialogue": len(matched_scene_ids),
            "scenes_without_dialogue": (
                len(scenes) - len(matched_scene_ids)
            ),
            "status": "completed",
        }

    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Scene transcript matching failed: {error}",
        ) from error


@router.get("/{video_id}/scene-transcripts")
def get_scene_transcripts(
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
        select(func.count(Scene.id)).where(
            Scene.video_id == video_id
        )
    ) or 0

    scenes = db.scalars(
        select(Scene)
        .where(Scene.video_id == video_id)
        .order_by(Scene.scene_number)
        .offset(offset)
        .limit(limit)
    ).all()

    scene_ids = [scene.id for scene in scenes]

    matches_by_scene = {
        scene_id: [] for scene_id in scene_ids
    }

    if scene_ids:
        results = db.execute(
            select(
                SceneTranscriptMatch,
                TranscriptSegment,
            )
            .join(
                TranscriptSegment,
                SceneTranscriptMatch.transcript_segment_id
                == TranscriptSegment.id,
            )
            .where(
                SceneTranscriptMatch.video_id == video_id,
                SceneTranscriptMatch.scene_id.in_(scene_ids),
            )
            .order_by(TranscriptSegment.start_time)
        ).all()

        for match, segment in results:
            matches_by_scene[match.scene_id].append({
                "id": segment.id,
                "start_time": segment.start_time,
                "end_time": segment.end_time,
                "text": segment.text,
                "overlap_duration": match.overlap_duration,
            })

    return {
        "video_id": video_id,
        "total_scenes": total,
        "limit": limit,
        "offset": offset,
        "scenes": [
            {
                "scene_id": scene.id,
                "scene_number": scene.scene_number,
                "start_time": scene.start_time,
                "end_time": scene.end_time,
                "duration": scene.duration,
                "thumbnail_url": (
                    f"/api/videos/{video_id}/scenes/{scene.id}/thumbnail"
                    if scene.thumbnail_path else None
                ),
                "transcript_segments": matches_by_scene[scene.id],
            }
            for scene in scenes
        ],
    }

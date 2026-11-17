import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.video import Video
from backend.app.models.transcription import (
    Transcription,
    TranscriptSegment,
)
from backend.app.models.scene import Scene
from backend.app.models.scene_analysis import SceneAnalysis
from backend.app.models.scene_transcript import SceneTranscriptMatch
from backend.app.models.moment_candidate import MomentCandidate
from backend.app.models.pipeline_job import PipelineJob

from backend.app.services.video_storage_service import export_json


def _serialize_model(instance) -> dict:
    """Serialize every mapped database column without losing stored values."""
    return {
        column.name: getattr(instance, column.name)
        for column in instance.__table__.columns
    }


def _serialize_rows(rows) -> list[dict]:
    return [_serialize_model(row) for row in rows]


def _parse_json_object(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def refresh_video_results(
    db: Session,
    video_id: int,
) -> dict:
    """
    Export a complete snapshot of one video's database results.

    The database remains the source of truth. Every export belongs
    exclusively to the requested video's results directory.
    """

    video = db.get(Video, video_id)

    if video is None:
        raise ValueError(f"Video {video_id} does not exist.")

    transcription = db.scalar(
        select(Transcription)
        .where(Transcription.video_id == video_id)
    )

    transcript_segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.video_id == video_id)
        .order_by(TranscriptSegment.start_time)
    ).all()

    scenes = db.scalars(
        select(Scene)
        .where(Scene.video_id == video_id)
        .order_by(Scene.scene_number)
    ).all()

    scene_analyses = db.scalars(
        select(SceneAnalysis)
        .join(Scene, Scene.id == SceneAnalysis.scene_id)
        .where(Scene.video_id == video_id)
        .order_by(Scene.scene_number)
    ).all()

    scene_transcript_matches = db.scalars(
        select(SceneTranscriptMatch)
        .where(SceneTranscriptMatch.video_id == video_id)
        .order_by(
            SceneTranscriptMatch.scene_id,
            SceneTranscriptMatch.transcript_segment_id,
        )
    ).all()

    moment_candidates = db.scalars(
        select(MomentCandidate)
        .where(MomentCandidate.video_id == video_id)
        .order_by(MomentCandidate.start_time)
    ).all()

    pipeline_jobs = db.scalars(
        select(PipelineJob)
        .where(PipelineJob.video_id == video_id)
        .order_by(PipelineJob.created_at)
    ).all()

    ranking_exports = []

    for job in pipeline_jobs:
        stage_details = _parse_json_object(job.stage_details)

        ranking_exports.append({
            "job_id": job.id,
            "status": job.status,
            "preliminary_ranking": stage_details.get(
                "preliminary_ranking"
            ),
            "final_ranking": stage_details.get(
                "final_ranking"
            ),
            "stage_details": stage_details,
        })

    generated_at = datetime.utcnow().isoformat()

    common_metadata = {
        "video_id": video_id,
        "generated_at": generated_at,
    }

    exports = {
        "video.json": {
            **common_metadata,
            "video": _serialize_model(video),
        },
        "transcription.json": {
            **common_metadata,
            "transcription": (
                _serialize_model(transcription)
                if transcription else None
            ),
        },
        "transcript_segments.json": {
            **common_metadata,
            "total": len(transcript_segments),
            "segments": _serialize_rows(transcript_segments),
        },
        "scenes.json": {
            **common_metadata,
            "total": len(scenes),
            "scenes": _serialize_rows(scenes),
        },
        "scene_analyses.json": {
            **common_metadata,
            "total": len(scene_analyses),
            "analyses": _serialize_rows(scene_analyses),
        },
        "scene_transcript_matches.json": {
            **common_metadata,
            "total": len(scene_transcript_matches),
            "matches": _serialize_rows(scene_transcript_matches),
        },
        "moment_candidates.json": {
            **common_metadata,
            "total": len(moment_candidates),
            "candidates": _serialize_rows(moment_candidates),
        },
        "pipeline_jobs.json": {
            **common_metadata,
            "total": len(pipeline_jobs),
            "jobs": _serialize_rows(pipeline_jobs),
        },
        "rankings.json": {
            **common_metadata,
            "total_jobs": len(ranking_exports),
            "rankings": ranking_exports,
        },
    }

    exported_files = []

    for filename, data in exports.items():
        output_path = export_json(
            video_id=video_id,
            filename=filename,
            data=data,
        )
        exported_files.append(str(output_path))

    return {
        "video_id": video_id,
        "exported_count": len(exported_files),
        "files": exported_files,
        "generated_at": generated_at,
    }

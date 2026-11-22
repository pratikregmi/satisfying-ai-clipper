
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from backend.app.core.database import (
    PROJECT_ROOT,
    SessionLocal,
)
from backend.app.models.pipeline_job import PipelineJob
from backend.app.models.video import Video
from backend.app.models.scene import Scene
from backend.app.models.scene_analysis import SceneAnalysis
from backend.app.models.transcription import (
    Transcription,
    TranscriptSegment,
)
from backend.app.models.moment_candidate import MomentCandidate
from backend.app.models.scene_transcript import SceneTranscriptMatch

from backend.app.core.workflow_logger import (
    log_workflow,
    log_workflow_error,
)
from backend.app.services.transcription_service import transcribe_video
from backend.app.services.scene_transcript_service import (
    match_scenes_with_transcripts,
)
from backend.app.services.scene_service import (
    detect_scenes,
    generate_scene_thumbnails,
)
from backend.app.services.scene_batch_service import process_scene_batch
from backend.app.services.moment_discovery_service import (
    discover_video_moments,
)
from backend.app.services.moment_evaluation_service import (
    evaluate_moment_candidates_batch,
)
from backend.app.services.moment_ranking_service import (
    rank_video_moments,
)
from backend.app.services.video_storage_service import (
    get_video_storage_paths,
    resolve_video_storage_path,
    get_video_logger,
)
from backend.app.services.video_results_service import (
    refresh_video_results,
)
from backend.app.services.clip_generation_service import (
    generate_review_clips,
    generate_output_clips,
)


def _log_video_event(
    video_id: int,
    level: str,
    message: str,
):
    try:
        logger = get_video_logger(video_id)
        log_method = getattr(logger, level, logger.info)
        log_method(message)
    except Exception as error:
        log_workflow_error(
            job_id=0,
            video_id=video_id,
            stage="video_logging",
            error=error,
        )


def _stage_details(job: PipelineJob) -> dict:
    try:
        value = json.loads(job.stage_details or "{}")
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _save_stage(
    db,
    job: PipelineJob,
    stage: str,
    status: str,
    progress: int,
    details: dict | None = None,
    error: str | None = None,
):
    all_details = _stage_details(job)
    stage_data = all_details.get(stage, {})

    stage_data["status"] = status
    stage_data["updated_at"] = datetime.utcnow().isoformat()

    if status == "running" and "started_at" not in stage_data:
        stage_data["started_at"] = datetime.utcnow().isoformat()

    if status in {
        "completed",
        "completed_with_warnings",
        "failed",
        "skipped",
    }:
        stage_data["completed_at"] = datetime.utcnow().isoformat()

    if details is not None:
        stage_data.update(details)

    if error:
        stage_data["error"] = error[:4000]
    elif status in {"running", "completed", "skipped"}:
        stage_data.pop("error", None)

    all_details[stage] = stage_data

    job.stage_details = json.dumps(
        all_details,
        ensure_ascii=False,
    )
    job.current_stage = stage
    job.progress_percent = max(
        job.progress_percent,
        min(progress, 100),
    )
    job.updated_at = datetime.utcnow()

    db.commit()

    _log_video_event(
        video_id=job.video_id,
        level=(
            "warning"
            if status in {"failed", "completed_with_warnings"}
            else "info"
        ),
        message=(
            f"Job {job.id} | Stage: {stage} | "
            f"Status: {status} | "
            f"Progress: {job.progress_percent}% | "
            f"Details: {details or {}}"
        ),
    )

    log_workflow(
        job_id=job.id,
        video_id=job.video_id,
        stage=stage,
        status=status,
        message=(
            f"Progress: {job.progress_percent}% | "
            f"Details: {details}"
            if details
            else f"Progress: {job.progress_percent}%"
        ),
    )


def _resolve_video_path(video: Video) -> Path:
    """Resolve the original video inside its dedicated video folder."""

    paths = get_video_storage_paths(video.id)
    expected_directory = paths["original"].resolve()

    try:
        path = resolve_video_storage_path(
            video.id,
            video.file_path,
        )
    except ValueError as error:
        raise ValueError(
            f"Invalid original video path for video {video.id}: {error}"
        ) from error

    if not path.is_relative_to(expected_directory):
        raise ValueError(
            f"Video {video.id} original file is outside its original directory: {path}"
        )

    if not path.is_file():
        raise FileNotFoundError(
            f"Video file not found: {path}"
        )

    return path

def _run_transcription(db, video: Video, video_path: Path) -> dict:
    if not video.has_audio:
        return {
            "status": "skipped",
            "reason": "Video has no audio stream.",
        }

    job = db.scalar(
        select(Transcription).where(
            Transcription.video_id == video.id
        )
    )

    existing_segments = db.scalar(
        select(TranscriptSegment.id)
        .where(TranscriptSegment.video_id == video.id)
        .limit(1)
    )

    if job and job.status == "completed" and existing_segments:
        return {
            "status": "reused",
            "message": "Existing completed transcript reused.",
        }

    if job and job.status in {"pending", "processing"}:
        raise RuntimeError(
            "A transcription job is already running for this video."
        )

    result = transcribe_video(
        video_path=video_path,
        model_name="base",
    )

    db.query(TranscriptSegment).filter(
        TranscriptSegment.video_id == video.id
    ).delete(synchronize_session=False)

    for item in result["segments"]:
        db.add(
            TranscriptSegment(
                video_id=video.id,
                start_time=item["start_time"],
                end_time=item["end_time"],
                text=item["text"],
            )
        )

    if job is None:
        job = Transcription(
            video_id=video.id,
            status="completed",
            model_name=result["model_name"],
        )
        db.add(job)

    job.status = "completed"
    job.language = result["language"]
    job.model_name = result["model_name"]
    job.error_message = None
    job.completed_at = datetime.utcnow()

    db.commit()

    return {
        "status": "completed",
        "total_segments": result["total_segments"],
        "language": result["language"],
        "model_name": result["model_name"],
    }


def _ensure_scenes(db, video: Video, video_path: Path) -> dict:
    scenes = db.scalars(
        select(Scene)
        .where(Scene.video_id == video.id)
        .order_by(Scene.scene_number)
    ).all()

    if scenes:
        return {
            "status": "reused",
            "total_scenes": len(scenes),
            "message": "Existing scenes reused; none were deleted.",
        }

    detected = detect_scenes(video_path)

    if not detected:
        raise RuntimeError(
            "Scene detection did not find any scenes."
        )

    scenes = [
        Scene(video_id=video.id, **item)
        for item in detected
    ]

    db.add_all(scenes)
    db.commit()

    return {
        "status": "completed",
        "total_scenes": len(scenes),
    }


def _ensure_thumbnails(db, video: Video, video_path: Path) -> dict:
    scenes = db.scalars(
        select(Scene)
        .where(Scene.video_id == video.id)
        .order_by(Scene.scene_number)
    ).all()

    if not scenes:
        raise RuntimeError(
            "Cannot generate thumbnails because no scenes exist."
        )

    output_dir = get_video_storage_paths(
        video.id
    )["scene_thumbnails"]

    output_dir.mkdir(parents=True, exist_ok=True)
    expected_directory = output_dir.resolve()

    missing = []

    for scene in scenes:
        if not scene.thumbnail_path:
            missing.append(scene)
            continue

        try:
            thumbnail_path = resolve_video_storage_path(
                video.id,
                scene.thumbnail_path,
            )

            if not thumbnail_path.is_relative_to(expected_directory):
                missing.append(scene)
                continue

            if not thumbnail_path.is_file():
                missing.append(scene)

        except (ValueError, OSError):
            missing.append(scene)

    if not missing:
        return {
            "status": "reused",
            "total_scenes": len(scenes),
            "thumbnails_created": 0,
        }

    # Regenerate all thumbnails if any are missing or invalid.
    generated_paths = generate_scene_thumbnails(
        video_path=video_path,
        scenes=scenes,
        output_dir=output_dir,
        frame_rate=video.frame_rate,
    )

    for scene, generated_path in zip(scenes, generated_paths):
        resolved_path = Path(generated_path).resolve()

        if not resolved_path.is_relative_to(expected_directory):
            raise ValueError(
                f"Generated thumbnail is outside video {video.id} storage: "
                f"{resolved_path}"
            )

        if not resolved_path.is_file():
            raise FileNotFoundError(
                f"Generated thumbnail is missing: {resolved_path}"
            )

        scene.thumbnail_path = str(
            resolved_path.relative_to(PROJECT_ROOT)
        )

    db.commit()

    return {
        "status": "completed",
        "total_scenes": len(scenes),
        "thumbnails_regenerated": len(generated_paths),
        "scenes_that_needed_thumbnails": len(missing),
    }

def _match_scene_transcripts(db, video_id: int) -> dict:
    """
    Match existing transcript segments to existing scenes.

    Only replaces matching records belonging to this video.
    Does not run transcription or scene detection.
    """
    scenes = db.scalars(
        select(Scene)
        .where(Scene.video_id == video_id)
        .order_by(Scene.start_time)
    ).all()

    transcript_segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.video_id == video_id)
        .order_by(TranscriptSegment.start_time)
    ).all()

    if not scenes or not transcript_segments:
        return {
            "status": "skipped",
            "total_scenes": len(scenes),
            "total_transcript_segments": len(transcript_segments),
            "total_matches": 0,
            "scenes_with_dialogue": 0,
            "scenes_without_dialogue": len(scenes),
            "reason": (
                "No scenes found."
                if not scenes
                else "No transcript segments found."
            ),
        }

    matches = match_scenes_with_transcripts(
        scenes,
        transcript_segments,
    )

    # Replace matches for this video only.
    db.query(SceneTranscriptMatch).filter(
        SceneTranscriptMatch.video_id == video_id
    ).delete(synchronize_session=False)

    db.add_all([
        SceneTranscriptMatch(**match)
        for match in matches
    ])

    db.commit()

    matched_scene_ids = {
        match["scene_id"] for match in matches
    }

    return {
        "status": "completed",
        "total_scenes": len(scenes),
        "total_transcript_segments": len(transcript_segments),
        "total_matches": len(matches),
        "scenes_with_dialogue": len(matched_scene_ids),
        "scenes_without_dialogue": (
            len(scenes) - len(matched_scene_ids)
        ),
    }


def _analyze_remaining_scenes(
    db,
    video_id: int,
    batch_size: int = 5,
) -> dict:
    total = db.query(Scene).filter(
        Scene.video_id == video_id
    ).count()

    analyzed = db.query(SceneAnalysis).join(
        Scene,
        Scene.id == SceneAnalysis.scene_id,
    ).filter(
        Scene.video_id == video_id
    ).count()

    excluded_scene_ids = set()
    failed_scenes = []
    batches = 0

    while analyzed < total:
        result = process_scene_batch(
            db=db,
            video_id=video_id,
            batch_size=batch_size,
            exclude_scene_ids=excluded_scene_ids,
        )

        batches += 1
        failed_scenes.extend(result["failed_scenes"])

        excluded_scene_ids.update(
            item["scene_id"]
            for item in result["failed_scenes"]
        )

        analyzed = result["total_analyzed"]

        if result["processed_this_batch"] == 0:
            break

    return {
        "total_scenes": total,
        "total_analyzed": analyzed,
        "remaining_unanalyzed": total - analyzed,
        "failed_count": len(failed_scenes),
        "failed_scenes": failed_scenes,
        "batches_processed": batches,
    }


def run_pipeline_job(
    job_id: int,
    evaluation_limit: int = 40,
    evaluation_batch_size: int = 3,
    scene_batch_size: int = 5,
):
    """
    Execute the automated video pipeline.

    Each stage records progress in SQLite and logs.
    Existing scene analyses and candidate evaluations are reused.
    """

    db = SessionLocal()
    current_stage = "initialization"
    job = None
    video = None

    try:
        job = db.get(PipelineJob, job_id)

        if job is None:
            raise ValueError(
                f"Pipeline job {job_id} was not found."
            )

        if job.status in {"completed", "completed_with_warnings"}:
            return

        video = db.get(Video, job.video_id)

        if video is None:
            raise ValueError(
                f"Video {job.video_id} was not found."
            )

        job.status = "running"
        job.error_message = None
        job.started_at = job.started_at or datetime.utcnow()
        db.commit()

        _log_video_event(
            video.id,
            "info",
            (
                f"Pipeline started | Job: {job.id} | "
                f"Filename: {video.original_filename}"
            ),
        )

        log_workflow(
            job_id=job.id,
            video_id=video.id,
            stage="pipeline",
            status="started",
            message=(
                f"Filename: {video.original_filename} | "
                f"Evaluation limit: {evaluation_limit} | "
                f"Evaluation batch: {evaluation_batch_size} | "
                f"Scene batch: {scene_batch_size}"
            ),
        )

        video_path = _resolve_video_path(video)

        # Stage 1: Transcription
        current_stage = "transcription"
        _save_stage(db, job, current_stage, "running", 2)

        transcription_result = _run_transcription(
            db,
            video,
            video_path,
        )

        transcription_status = transcription_result.pop(
            "status",
            "completed",
        )

        _save_stage(
            db,
            job,
            current_stage,
            (
                "skipped"
                if transcription_status == "skipped"
                else "completed"
            ),
            10,
            {
                "result": transcription_result,
                "reuse_status": transcription_status,
            },
        )

        # Stage 2: Scene detection
        current_stage = "scene_detection"
        _save_stage(db, job, current_stage, "running", 12)

        scene_result = _ensure_scenes(
            db,
            video,
            video_path,
        )

        _save_stage(
            db,
            job,
            current_stage,
            "completed",
            20,
            scene_result,
        )

        # Stage 3: Thumbnail generation
        current_stage = "thumbnail_generation"
        _save_stage(db, job, current_stage, "running", 22)

        thumbnail_result = _ensure_thumbnails(
            db,
            video,
            video_path,
        )

        _save_stage(
            db,
            job,
            current_stage,
            "completed",
            30,
            thumbnail_result,
        )

        # Stage 4: Scene transcript matching
        current_stage = "scene_transcript_matching"
        _save_stage(db, job, current_stage, "running", 31)

        matching_result = _match_scene_transcripts(
            db,
            video.id,
        )

        matching_stage_status = (
            "skipped"
            if matching_result["status"] == "skipped"
            else "completed"
        )

        _save_stage(
            db,
            job,
            current_stage,
            matching_stage_status,
            32,
            matching_result,
        )

        _log_video_event(
            video.id,
            "info",
            (
                "Scene transcript matching | "
                f"Status: {matching_stage_status} | "
                f"Matches: {matching_result['total_matches']} | "
                f"Scenes with dialogue: "
                f"{matching_result['scenes_with_dialogue']}/"
                f"{matching_result['total_scenes']}"
            ),
        )

        # Stage 5: Visual analysis
        current_stage = "visual_analysis"
        _save_stage(db, job, current_stage, "running", 33)

        analysis_result = _analyze_remaining_scenes(
            db,
            video.id,
            batch_size=scene_batch_size,
        )

        analysis_stage_status = (
            "completed_with_warnings"
            if (
                analysis_result["remaining_unanalyzed"] > 0
                or analysis_result["failed_count"] > 0
            )
            else "completed"
        )

        _save_stage(
            db,
            job,
            current_stage,
            analysis_stage_status,
            55,
            analysis_result,
        )

        if analysis_stage_status == "completed_with_warnings":
            log_workflow(
                job_id=job.id,
                video_id=video.id,
                stage=current_stage,
                status="warning",
                message=(
                    f"Analyzed: {analysis_result['total_analyzed']}/"
                    f"{analysis_result['total_scenes']} | "
                    f"Failed: {analysis_result['failed_count']} | "
                    f"Remaining: "
                    f"{analysis_result['remaining_unanalyzed']}"
                ),
            )

        # Stage 5: Moment discovery
        current_stage = "moment_discovery"
        _save_stage(db, job, current_stage, "running", 57)

        discovery_result = discover_video_moments(
            db,
            video.id,
        )

        _save_stage(
            db,
            job,
            current_stage,
            "completed",
            65,
            {
                "candidates_created": discovery_result[
                    "candidates_created"
                ],
                "candidates_skipped_as_duplicates": (
                    discovery_result[
                        "candidates_skipped_as_duplicates"
                    ]
                ),
                "total_windows_generated": discovery_result[
                    "total_windows_generated"
                ],
            },
        )

        if discovery_result["candidates_created"] == 0:
            log_workflow(
                job_id=job.id,
                video_id=video.id,
                stage=current_stage,
                status="warning",
                message="No new moment candidates were created.",
            )

        # Stage 6: Preliminary ranking
        current_stage = "preliminary_ranking"
        _save_stage(db, job, current_stage, "running", 67)

        preliminary = rank_video_moments(
            db=db,
            video_id=video.id,
            max_results=max(
                preliminary_count := db.query(
                    MomentCandidate
                ).filter(
                    MomentCandidate.video_id == video.id,
                    MomentCandidate.status == "pending",
                ).count(),
                1,
            ),
            video_duration=video.duration,
        )

        unevaluated_candidates = [
            item
            for item in preliminary["selected_candidates"]
            if not item["ai_evaluated"]
        ]

        candidate_ids = [
            item["id"]
            for item in unevaluated_candidates[:evaluation_limit]
        ]

        preliminary_status = (
            "completed_with_warnings"
            if len(candidate_ids) == 0
            else "completed"
        )

        _save_stage(
            db,
            job,
            current_stage,
            preliminary_status,
            70,
            {
                "total_candidates": preliminary["total_candidates"],
                "shortlist_count": len(candidate_ids),
                "candidate_ids": candidate_ids,
            },
        )

        if not candidate_ids:
            log_workflow(
                job_id=job.id,
                video_id=video.id,
                stage=current_stage,
                status="warning",
                message=(
                    f"No candidates shortlisted from "
                    f"{preliminary['total_candidates']} candidates. "
                    f"Pending candidates checked: {preliminary_count}."
                ),
            )

        # Stage 7: AI evaluation
        current_stage = "ai_evaluation"
        _save_stage(db, job, current_stage, "running", 71)

        evaluation_totals = {
            "evaluated_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "failed": [],
        }

        for start in range(
            0,
            len(candidate_ids),
            evaluation_batch_size,
        ):
            batch_ids = candidate_ids[
                start:start + evaluation_batch_size
            ]

            result = evaluate_moment_candidates_batch(
                db=db,
                candidate_ids=batch_ids,
                batch_size=evaluation_batch_size,
            )

            evaluation_totals["evaluated_count"] += (
                result["evaluated_count"]
            )
            evaluation_totals["skipped_count"] += (
                result["skipped_count"]
            )
            evaluation_totals["failed_count"] += (
                result["failed_count"]
            )
            evaluation_totals["failed"].extend(
                result["failed"]
            )

            completed_count = min(
                start + len(batch_ids),
                len(candidate_ids),
            )

            evaluation_progress = (
                70
                + int(
                    19 * completed_count
                    / max(len(candidate_ids), 1)
                )
            )

            _save_stage(
                db,
                job,
                current_stage,
                "running",
                evaluation_progress,
                {
                    **evaluation_totals,
                    "shortlist_count": len(candidate_ids),
                    "processed_count": completed_count,
                },
            )

        evaluation_status = (
            "completed_with_warnings"
            if evaluation_totals["failed_count"] > 0
            else "completed"
        )

        _save_stage(
            db,
            job,
            current_stage,
            evaluation_status,
            90,
            {
                **evaluation_totals,
                "shortlist_count": len(candidate_ids),
            },
        )

        if evaluation_totals["failed_count"] > 0:
            log_workflow(
                job_id=job.id,
                video_id=video.id,
                stage=current_stage,
                status="warning",
                message=(
                    f"Evaluated: {evaluation_totals['evaluated_count']} | "
                    f"Skipped: {evaluation_totals['skipped_count']} | "
                    f"Failed: {evaluation_totals['failed_count']}"
                ),
            )

        if not candidate_ids:
            log_workflow(
                job_id=job.id,
                video_id=video.id,
                stage=current_stage,
                status="warning",
                message="No candidates available for AI evaluation.",
            )

        # Stage 8: Final ranking
        current_stage = "final_ranking"
        _save_stage(db, job, current_stage, "running", 92)

        final_ranking = rank_video_moments(
            db=db,
            video_id=video.id,
            max_results=10,
            video_duration=video.duration,
            candidate_ids=candidate_ids,
        )

        selected_candidates = final_ranking[
            "selected_candidates"
        ]

        final_ranking_status = (
            "completed_with_warnings"
            if final_ranking["selected_count"] == 0
            else "completed"
        )

        _save_stage(
            db,
            job,
            current_stage,
            final_ranking_status,
            94,
            {
                "selected_count": final_ranking["selected_count"],
                "ai_evaluated_count": final_ranking[
                    "ai_evaluated_count"
                ],
                "selected_candidates": selected_candidates,
            },
        )

        if final_ranking["selected_count"] == 0:
            log_workflow(
                job_id=job.id,
                video_id=video.id,
                stage=current_stage,
                status="warning",
                message=(
                    "Pipeline produced zero selected candidates."
                ),
            )

        # Stage 9: Review clip generation
        current_stage = "clip_generation"
        _save_stage(db, job, current_stage, "running", 95)

        if selected_candidates:
            clip_generation_result = generate_review_clips(
                video_id=video.id,
                video_path=video_path,
                selected_candidates=selected_candidates,
            )

            clip_generation_status = (
                "completed_with_warnings"
                if clip_generation_result["failed_count"] > 0
                else "completed"
            )
        else:
            clip_generation_result = {
                "video_id": video.id,
                "selected_count": 0,
                "generated_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
                "generated": [],
                "skipped": [],
                "failed": [],
                "reason": "No final candidates were selected.",
            }
            clip_generation_status = "skipped"

        _save_stage(
            db,
            job,
            current_stage,
            clip_generation_status,
            96,
            clip_generation_result,
        )

        if clip_generation_result["failed_count"] > 0:
            log_workflow(
                job_id=job.id,
                video_id=video.id,
                stage=current_stage,
                status="warning",
                message=(
                    f"Generated: {clip_generation_result['generated_count']} | "
                    f"Skipped: {clip_generation_result['skipped_count']} | "
                    f"Failed: {clip_generation_result['failed_count']}"
                ),
            )

        # Stage 10: Generate Shorts directly from the original source.
        current_stage = "output_generation"
        _save_stage(db, job, current_stage, "running", 97)

        if selected_candidates:
            output_generation_result = generate_output_clips(
                video_id=video.id,
                video_path=video_path,
                selected_candidates=selected_candidates,
            )

            output_generation_status = (
                "completed_with_warnings"
                if output_generation_result["failed_count"] > 0
                else "completed"
            )
        else:
            output_generation_result = {
                "video_id": video.id,
                "full_screen": False,
                "output_format": "youtube_shorts",
                "resolution": "1080x1920",
                "selected_count": 0,
                "generated_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
                "generated": [],
                "skipped": [],
                "failed": [],
                "reason": "No final candidates were selected.",
            }
            output_generation_status = "skipped"

        _save_stage(
            db,
            job,
            current_stage,
            output_generation_status,
            98,
            output_generation_result,
        )

        if output_generation_result["failed_count"] > 0:
            log_workflow(
                job_id=job.id,
                video_id=video.id,
                stage=current_stage,
                status="warning",
                message=(
                    f"Format: {output_generation_result['output_format']} | "
                    f"Generated: {output_generation_result['generated_count']} | "
                    f"Skipped: {output_generation_result['skipped_count']} | "
                    f"Failed: {output_generation_result['failed_count']}"
                ),
            )

        # Stage 11: Export results before marking the job complete.
        current_stage = "results_export"
        _save_stage(db, job, current_stage, "running", 99)

        try:
            export_result = refresh_video_results(
                db,
                video.id,
            )

            results_export_status = "completed"
            results_export_details = {
                "exported_count": export_result["exported_count"],
            }

            _save_stage(
                db,
                job,
                current_stage,
                results_export_status,
                99,
                results_export_details,
            )

            _log_video_event(
                video.id,
                "info",
                (
                    "Pipeline results exported | "
                    f"Files: {export_result['exported_count']}"
                ),
            )

        except Exception as export_error:
            results_export_status = "completed_with_warnings"
            results_export_details = {
                "error": str(export_error)[:2000],
            }

            _save_stage(
                db,
                job,
                current_stage,
                results_export_status,
                99,
                results_export_details,
                error=str(export_error),
            )

            _log_video_event(
                video.id,
                "error",
                f"Results export failed: {export_error}",
            )

        # Final pipeline status is committed only after export finishes.
        warning_count = sum(
            [
                analysis_stage_status == "completed_with_warnings",
                preliminary_status == "completed_with_warnings",
                evaluation_status == "completed_with_warnings",
                final_ranking_status == "completed_with_warnings",
                clip_generation_status == "completed_with_warnings",
                output_generation_status == "completed_with_warnings",
                results_export_status == "completed_with_warnings",
            ]
        )

        job.status = (
            "completed_with_warnings"
            if warning_count
            else "completed"
        )
        job.current_stage = "completed"
        job.progress_percent = 100
        job.completed_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        db.commit()


        log_workflow(
            job_id=job.id,
            video_id=video.id,
            stage="pipeline",
            status=(
                "completed_with_warnings"
                if warning_count
                else "completed"
            ),
            message=(
                f"Progress: 100% | "
                f"Warnings: {warning_count} | "
                f"Candidates shortlisted: {len(candidate_ids)} | "
                f"Candidates evaluated: "
                f"{evaluation_totals['evaluated_count']} | "
                f"Final selections: "
                f"{final_ranking['selected_count']} | "
                f"Clips generated: "
                f"{clip_generation_result['generated_count']} | "
                f"Clips skipped: "
                f"{clip_generation_result['skipped_count']} | "
                f"Clip failures: "
                f"{clip_generation_result['failed_count']} | "
                f"Output format: "
                f"{output_generation_result['output_format']} | "
                f"Output generated: "
                f"{output_generation_result['generated_count']} | "
                f"Output skipped: "
                f"{output_generation_result['skipped_count']} | "
                f"Output failures: "
                f"{output_generation_result['failed_count']} | "
                f"Results exported: "
                f"{results_export_details.get('exported_count', 0)}"
            ),
        )

    except Exception as error:
        db.rollback()

        failed_job = db.get(PipelineJob, job_id)

        if failed_job is not None:
            failed_video_id = failed_job.video_id

            _log_video_event(
                failed_video_id,
                "error",
                (
                    f"Pipeline failed | Job: {job_id} | "
                    f"Stage: {current_stage} | Error: {error}"
                ),
            )

            log_workflow_error(
                job_id=job_id,
                video_id=failed_video_id,
                stage=current_stage,
                error=error,
            )

            try:
                _save_stage(
                    db,
                    failed_job,
                    current_stage,
                    "failed",
                    failed_job.progress_percent,
                    error=str(error),
                )

                failed_job.status = "failed"
                failed_job.error_message = str(error)[:4000]
                failed_job.updated_at = datetime.utcnow()
                failed_job.completed_at = datetime.utcnow()
                db.commit()

                try:
                    export_result = refresh_video_results(
                        db,
                        failed_video_id,
                    )
                    _log_video_event(
                        failed_video_id,
                        "info",
                        (
                            "Partial pipeline results exported | "
                            f"Files: {export_result['exported_count']}"
                        ),
                    )
                except Exception as export_error:
                    _log_video_event(
                        failed_video_id,
                        "error",
                        f"Partial results export failed: {export_error}",
                    )

                log_workflow(
                    job_id=job_id,
                    video_id=failed_video_id,
                    stage="pipeline",
                    status="failed",
                    message=str(error),
                )

            except Exception:
                db.rollback()
                log_workflow_error(
                    job_id=job_id,
                    video_id=failed_video_id,
                    stage="failure_handler",
                    error=error,
                )

    finally:
        db.close()

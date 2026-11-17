import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.scene import Scene
from backend.app.models.scene_analysis import SceneAnalysis
from backend.app.services.scene_analysis_service import analyze_scene_image
from backend.app.services.video_storage_service import (
    get_video_storage_paths,
    resolve_video_storage_path,
    get_video_logger,
)
from backend.app.services.video_results_service import (
    refresh_video_results,
)


def _log_video_event(video_id: int, level: str, message: str) -> None:
    try:
        logger = get_video_logger(video_id)
        getattr(logger, level)(message)
    except Exception:
        # Logging must never undo a saved analysis.
        pass


def process_scene_batch(
    db: Session,
    video_id: int,
    batch_size: int = 5,
    exclude_scene_ids: set[int] | None = None,
) -> dict:
    """
    Analyze the next batch of scenes without saved AI analysis.

    Successful analyses are committed immediately.
    Failed scene IDs can be excluded during an automatic run.
    Scene thumbnails must belong to this video's storage directory.
    """

    if not 1 <= batch_size <= 20:
        raise ValueError("Batch size must be between 1 and 20.")

    query = (
        select(Scene)
        .outerjoin(
            SceneAnalysis,
            Scene.id == SceneAnalysis.scene_id,
        )
        .where(
            Scene.video_id == video_id,
            SceneAnalysis.id.is_(None),
        )
        .order_by(Scene.scene_number)
    )

    if exclude_scene_ids:
        query = query.where(
            Scene.id.not_in(exclude_scene_ids)
        )

    scenes = db.scalars(
        query.limit(batch_size)
    ).all()

    completed = 0
    failed = []

    expected_thumbnail_directory = (
        get_video_storage_paths(video_id)["scene_thumbnails"]
        .resolve()
    )

    for scene in scenes:
        scene_id = scene.id
        scene_number = scene.scene_number

        try:
            if not scene.thumbnail_path:
                raise FileNotFoundError(
                    "Scene thumbnail path is missing."
                )

            image_path = resolve_video_storage_path(
                video_id,
                scene.thumbnail_path,
            )

            if not image_path.is_relative_to(
                expected_thumbnail_directory
            ):
                raise ValueError(
                    "Scene thumbnail does not belong to this video's scene-thumbnail folder."
                )

            if not image_path.is_file():
                raise FileNotFoundError(
                    f"Thumbnail not found: {image_path}"
                )

            result = analyze_scene_image(image_path)

            analysis = SceneAnalysis(
                scene_id=scene_id,
                description=result["description"],
                characters=json.dumps(result["characters"]),
                actions=json.dumps(result["actions"]),
                objects=json.dumps(result["objects"]),
                setting=result["setting"],
                mood=result["mood"],
                raw_response=result["raw_response"],
                model_name=result["model_name"],
            )

            db.add(analysis)
            db.commit()

            completed += 1

            _log_video_event(
                video_id,
                "info",
                "Batch scene analysis completed | "
                f"Scene ID: {scene_id} | "
                f"Scene number: {scene_number}",
            )

        except Exception as error:
            db.rollback()

            failed.append({
                "scene_id": scene_id,
                "scene_number": scene_number,
                "error": str(error),
            })

            _log_video_event(
                video_id,
                "warning",
                "Batch scene analysis failed | "
                f"Scene ID: {scene_id} | "
                f"Scene number: {scene_number} | "
                f"Error: {error}",
            )

    total = db.query(Scene).filter(
        Scene.video_id == video_id
    ).count()

    analyzed = db.query(SceneAnalysis).join(
        Scene,
        Scene.id == SceneAnalysis.scene_id,
    ).filter(
        Scene.video_id == video_id
    ).count()

    remaining = total - analyzed

    # Refresh this video's exports after the batch. Export failures must
    # not undo analyses that have already been committed.
    try:
        export_result = refresh_video_results(db, video_id)

        _log_video_event(
            video_id,
            "info",
            "Batch results export completed | "
            f"Files: {export_result['exported_count']}",
        )
    except Exception as error:
        _log_video_event(
            video_id,
            "error",
            "Batch results export failed | "
            f"Error: {error}",
        )

    return {
        "video_id": video_id,
        "batch_size": batch_size,
        "processed_this_batch": len(scenes),
        "completed_this_batch": completed,
        "failed_this_batch": len(failed),
        "total_scenes": total,
        "total_analyzed": analyzed,
        "remaining": remaining,
        "has_more": remaining > 0,
        "failed_scenes": failed,
    }

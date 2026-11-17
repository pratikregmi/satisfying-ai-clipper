import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.scene import Scene
from backend.app.models.video import Video
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


router = APIRouter(
    prefix="/api/videos",
    tags=["AI Scene Analysis"],
)


def _get_scene_thumbnail_path(
    video_id: int,
    stored_path: str,
):
    expected_directory = (
        get_video_storage_paths(video_id)["scene_thumbnails"]
        .resolve()
    )

    try:
        thumbnail_path = resolve_video_storage_path(
            video_id,
            stored_path,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scene thumbnail path: {error}",
        ) from error

    if not thumbnail_path.is_relative_to(expected_directory):
        raise HTTPException(
            status_code=400,
            detail="Scene thumbnail is outside this video's storage folder.",
        )

    if not thumbnail_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Scene thumbnail file is missing.",
        )

    return thumbnail_path


def serialize_analysis(analysis: SceneAnalysis) -> dict:
    return {
        "scene_id": analysis.scene_id,
        "description": analysis.description,
        "characters": json.loads(analysis.characters),
        "actions": json.loads(analysis.actions),
        "objects": json.loads(analysis.objects),
        "setting": analysis.setting,
        "mood": analysis.mood,
        "model_name": analysis.model_name,
        "analyzed_at": analysis.analyzed_at.isoformat(),
    }


@router.post("/{video_id}/scenes/{scene_id}/analyze")
def analyze_single_scene(
    video_id: int,
    scene_id: int,
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)

    if not video:
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    scene = db.get(Scene, scene_id)

    if not scene or scene.video_id != video_id:
        raise HTTPException(
            status_code=404,
            detail="Scene not found.",
        )

    if not scene.thumbnail_path:
        raise HTTPException(
            status_code=404,
            detail="Scene thumbnail has not been generated.",
        )

    thumbnail_path = _get_scene_thumbnail_path(
        video_id,
        scene.thumbnail_path,
    )

    try:
        result = analyze_scene_image(thumbnail_path)

        analysis = db.query(SceneAnalysis).filter(
            SceneAnalysis.scene_id == scene_id
        ).first()

        if analysis is None:
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

        else:
            analysis.description = result["description"]
            analysis.characters = json.dumps(result["characters"])
            analysis.actions = json.dumps(result["actions"])
            analysis.objects = json.dumps(result["objects"])
            analysis.setting = result["setting"]
            analysis.mood = result["mood"]
            analysis.raw_response = result["raw_response"]
            analysis.model_name = result["model_name"]

        db.commit()
        db.refresh(analysis)

        try:
            logger = get_video_logger(video_id)
            logger.info(
                "Manual scene analysis completed | "
                f"Scene ID: {scene_id} | "
                f"Scene number: {scene.scene_number}"
            )

            export_result = refresh_video_results(
                db,
                video_id,
            )

            logger.info(
                "Results refreshed after manual scene analysis | "
                f"Files: {export_result['exported_count']}"
            )

        except Exception as export_error:
            # The analysis is already committed. An export failure
            # must not report the successful analysis as failed.
            try:
                get_video_logger(video_id).error(
                    "Manual scene analysis results export failed | "
                    f"Scene ID: {scene_id} | "
                    f"Error: {export_error}"
                )
            except Exception:
                pass

        return {
            "status": "completed",
            "video_id": video_id,
            "scene_number": scene.scene_number,
            "analysis": serialize_analysis(analysis),
        }

    except Exception as error:
        db.rollback()

        if isinstance(error, HTTPException):
            raise

        raise HTTPException(
            status_code=500,
            detail=f"AI scene analysis failed: {error}",
        ) from error


@router.get("/{video_id}/scenes/{scene_id}/analysis")
def get_scene_analysis(
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

    analysis = db.query(SceneAnalysis).filter(
        SceneAnalysis.scene_id == scene_id
    ).first()

    if analysis is None:
        raise HTTPException(
            status_code=404,
            detail="This scene has not been analyzed yet.",
        )

    return serialize_analysis(analysis)


import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.scene import Scene
from backend.app.models.video import Video
from backend.app.models.scene_analysis import SceneAnalysis
from backend.app.services.scene_analysis_service import analyze_scene_image


router = APIRouter(
    prefix="/api/videos",
    tags=["AI Scene Analysis"],
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
THUMBNAIL_DIR = (PROJECT_ROOT / "media" / "thumbnails").resolve()


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

    thumbnail_path = (
        PROJECT_ROOT / scene.thumbnail_path
    ).resolve()

    if not thumbnail_path.is_relative_to(THUMBNAIL_DIR):
        raise HTTPException(
            status_code=400,
            detail="Invalid scene thumbnail path.",
        )

    if not thumbnail_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Scene thumbnail file is missing.",
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

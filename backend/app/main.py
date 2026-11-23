
from fastapi import FastAPI

from backend.app.core.database import Base, engine
from backend.app.models.video import Video
from backend.app.models.scene import Scene

from backend.app.api.transcriptions import router as transcriptions_router

from backend.app.api.videos import router as videos_router
from backend.app.api.scenes import router as scenes_router

from backend.app.models.scene_analysis import SceneAnalysis
from backend.app.api.scene_analysis import router as scene_analysis_router
from backend.app.api.scene_batch import router as scene_batch_router

from backend.app.models.transcription import (
    Transcription,
    TranscriptSegment,
)

from backend.app.models.scene_transcript import SceneTranscriptMatch

from backend.app.api.scene_transcripts import (
    router as scene_transcripts_router,
)
from backend.app.api.scene_analysis_jobs import (
    router as scene_analysis_jobs_router,
)
from backend.app.models.moment_candidate import MomentCandidate
from backend.app.models.pipeline_job import PipelineJob
from backend.app.models.clip_metadata import ClipMetadata
from backend.app.api.pipeline import router as pipeline_router
from backend.app.api.clip_metadata import router as clip_metadata_router

from backend.app.api.moment_discovery import (
    router as moment_discovery_router,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="SatisfyingAI",
    description="Local AI-powered video clipping and content creation platform",
    version="0.3.0",
)

app.include_router(videos_router)
app.include_router(scenes_router)
app.include_router(transcriptions_router)
app.include_router(scene_transcripts_router)
app.include_router(scene_analysis_router)
app.include_router(scene_batch_router)
app.include_router(scene_analysis_jobs_router)
app.include_router(moment_discovery_router)
app.include_router(pipeline_router)
app.include_router(clip_metadata_router)

@app.get("/")
def home():
    return {
        "application": "SatisfyingAI",
        "status": "running",
        "version": "0.3.0",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "video_engine": "FFmpeg",
        "ai_engine": "Ollama",
    }

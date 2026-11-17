
from pathlib import Path

from faster_whisper import WhisperModel


# Keep one model loaded in memory instead of loading it
# repeatedly for every transcription request.
_model = None
_loaded_model_name = None


def get_whisper_model(model_name: str = "base"):
    global _model, _loaded_model_name

    if _model is None or _loaded_model_name != model_name:
        _model = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",
        )
        _loaded_model_name = model_name

    return _model


def transcribe_video(
    video_path: Path,
    model_name: str = "base",
) -> dict:
    if not video_path.exists():
        raise FileNotFoundError(
            f"Video file not found: {video_path}"
        )

    model = get_whisper_model(model_name)

    segments, info = model.transcribe(
        str(video_path),
        beam_size=5,
        vad_filter=True,
    )

    transcript_segments = []

    for segment in segments:
        text = segment.text.strip()

        if not text:
            continue

        transcript_segments.append({
            "start_time": round(segment.start, 3),
            "end_time": round(segment.end, 3),
            "text": text,
        })

    return {
        "language": info.language,
        "language_probability": info.language_probability,
        "model_name": model_name,
        "segments": transcript_segments,
        "total_segments": len(transcript_segments),
    }

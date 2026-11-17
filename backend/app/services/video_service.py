
import json
import subprocess
from pathlib import Path


def get_video_metadata(file_path: Path) -> dict:
    command = [
        "ffprobe",
        "-v", "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,avg_frame_rate",
        "-of", "json",
        str(file_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )

    data = json.loads(result.stdout)
    streams = data.get("streams", [])

    video_stream = next(
        (s for s in streams if s.get("codec_type") == "video"),
        None,
    )

    if not video_stream:
        raise ValueError("No video stream found.")

    audio_stream = any(
        s.get("codec_type") == "audio" for s in streams
    )

    return {
        "duration": float(data.get("format", {}).get("duration", 0)),
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "frame_rate": video_stream.get("avg_frame_rate", "unknown"),
        "has_audio": audio_stream,
    }


def generate_thumbnail(
    video_path: Path,
    thumbnail_path: Path,
) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-ss", "1",
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", "scale=640:-1",
        str(thumbnail_path),
    ]

    subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )

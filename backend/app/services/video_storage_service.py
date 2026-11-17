import json
import logging
from pathlib import Path

from backend.app.core.database import PROJECT_ROOT


VIDEO_STORAGE_ROOT = PROJECT_ROOT / "media" / "videos"


def get_video_directory(video_id: int) -> Path:
    if video_id < 1:
        raise ValueError("Video ID must be positive.")

    return VIDEO_STORAGE_ROOT / f"video_{video_id}"


def get_video_storage_paths(video_id: int) -> dict[str, Path]:
    root = get_video_directory(video_id)

    return {
        "root": root,
        "original": root / "original",
        "upload_thumbnail": root / "thumbnails" / "upload.jpg",
        "thumbnails": root / "thumbnails",
        "scene_thumbnails": root / "thumbnails" / "scenes",
        "results": root / "results",
        "clips": root / "clips",
        "logs": root / "logs.txt",
    }


def ensure_video_storage(video_id: int) -> dict[str, Path]:
    paths = get_video_storage_paths(video_id)

    for key in (
        "original",
        "thumbnails",
        "scene_thumbnails",
        "results",
        "clips",
    ):
        paths[key].mkdir(parents=True, exist_ok=True)

    return paths


def resolve_video_storage_path(
    video_id: int,
    stored_path: str | Path,
) -> Path:
    """Resolve a stored path and ensure it belongs to this video's folder."""
    root = get_video_directory(video_id).resolve()
    path = Path(stored_path)

    if not path.is_absolute():
        path = PROJECT_ROOT / path

    path = path.resolve()

    if not path.is_relative_to(root):
        raise ValueError(
            f"Path does not belong to video {video_id}: {path}"
        )

    return path


def export_json(
    video_id: int,
    filename: str,
    data: dict | list,
) -> Path:
    if (
        Path(filename).name != filename
        or not filename.endswith(".json")
    ):
        raise ValueError("Invalid JSON export filename.")

    paths = ensure_video_storage(video_id)
    output_path = paths["results"] / filename
    temporary_path = output_path.with_suffix(".json.tmp")

    try:
        with temporary_path.open("w", encoding="utf-8") as output:
            json.dump(
                data,
                output,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
            output.write("\n")

        temporary_path.replace(output_path)

    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return output_path


def get_video_logger(video_id: int) -> logging.Logger:
    paths = ensure_video_storage(video_id)

    logger = logging.getLogger(
        f"satisfyingai.video.{video_id}"
    )
    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_path = str(paths["logs"])

    if not any(
        getattr(handler, "_video_log_path", None) == log_path
        for handler in logger.handlers
    ):
        handler = logging.FileHandler(
            log_path,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(message)s"
            )
        )
        handler._video_log_path = log_path
        logger.addHandler(handler)

    return logger

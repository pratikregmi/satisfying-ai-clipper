import math
import os
import subprocess
import uuid
from pathlib import Path

from backend.app.services.video_service import get_video_metadata
from backend.app.services.video_storage_service import (
    ensure_video_storage,
    get_video_logger,
)


CLIP_PADDING_SECONDS = 5.0


def generate_review_clips(
    video_id: int,
    video_path: Path,
    selected_candidates: list[dict],
) -> dict:
    """
    Generate review clips for final-ranked candidates.

    Each clip includes five seconds before and after the candidate,
    clamped to the original video's duration.

    Existing clips are never overwritten.
    """

    paths = ensure_video_storage(video_id)
    clips_directory = paths["clips"]
    logger = get_video_logger(video_id)

    metadata = get_video_metadata(video_path)
    video_duration = float(metadata["duration"])

    if not math.isfinite(video_duration) or video_duration <= 0:
        raise ValueError(
            f"Invalid source video duration: {video_duration}"
        )

    result = {
        "video_id": video_id,
        "video_duration": video_duration,
        "padding_seconds": CLIP_PADDING_SECONDS,
        "selected_count": len(selected_candidates),
        "generated_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "generated": [],
        "skipped": [],
        "failed": [],
    }

    logger.info(
        "Review clip generation started | "
        "Selected: %s | Padding: %s seconds",
        len(selected_candidates),
        CLIP_PADDING_SECONDS,
    )

    for candidate in selected_candidates:
        candidate_id = None
        temporary_path = None

        try:
            candidate_id = int(candidate["id"])

            output_path = (
                clips_directory
                / f"candidate_{candidate_id}_review.mp4"
            )

            if output_path.exists():
                result["skipped_count"] += 1
                result["skipped"].append({
                    "candidate_id": candidate_id,
                    "filename": output_path.name,
                    "reason": "Clip already exists; not overwritten.",
                })

                logger.info(
                    "Review clip skipped | Candidate: %s | "
                    "Reason: destination already exists",
                    candidate_id,
                )
                continue

            candidate_start = float(candidate["start_time"])
            candidate_end = float(candidate["end_time"])

            if (
                not math.isfinite(candidate_start)
                or not math.isfinite(candidate_end)
                or candidate_end <= candidate_start
            ):
                raise ValueError(
                    "Candidate has invalid start/end timestamps."
                )

            clip_start = max(
                0.0,
                candidate_start - CLIP_PADDING_SECONDS,
            )

            clip_end = min(
                video_duration,
                candidate_end + CLIP_PADDING_SECONDS,
            )

            clip_duration = clip_end - clip_start

            if clip_duration <= 0:
                raise ValueError(
                    "Calculated review clip duration is invalid."
                )

            # Create a unique temporary filename in the destination
            # directory so the final file can be created atomically.
            temporary_path = (
                clips_directory
                / f".candidate_{candidate_id}_{uuid.uuid4().hex}.tmp.mp4"
            )

            command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-nostdin",
                "-n",
                "-ss", f"{clip_start:.6f}",
                "-i", str(video_path),
                "-t", f"{clip_duration:.6f}",
                "-map", "0:v:0",
                "-map", "0:a?",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "22",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                "-avoid_negative_ts", "make_zero",
                str(temporary_path),
            ]

            subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=600,
                check=True,
            )

            if (
                not temporary_path.is_file()
                or temporary_path.stat().st_size == 0
            ):
                raise RuntimeError(
                    "FFmpeg did not produce a valid clip file."
                )

            # os.link fails if the destination already exists.
            # This protects existing clips even if another process
            # creates the same candidate clip simultaneously.
            try:
                os.link(temporary_path, output_path)
            except FileExistsError:
                result["skipped_count"] += 1
                result["skipped"].append({
                    "candidate_id": candidate_id,
                    "filename": output_path.name,
                    "reason": "Clip appeared during generation; not overwritten.",
                })

                logger.info(
                    "Review clip skipped | Candidate: %s | "
                    "Reason: destination already created",
                    candidate_id,
                )
                continue

            clip_info = {
                "candidate_id": candidate_id,
                "filename": output_path.name,
                "clip_start": round(clip_start, 3),
                "clip_end": round(clip_end, 3),
                "duration": round(clip_duration, 3),
                "size_bytes": output_path.stat().st_size,
            }

            result["generated_count"] += 1
            result["generated"].append(clip_info)

            logger.info(
                "Review clip generated | Candidate: %s | "
                "Start: %.3fs | End: %.3fs | Duration: %.3fs | "
                "File: %s",
                candidate_id,
                clip_start,
                clip_end,
                clip_duration,
                output_path.name,
            )

        except Exception as error:
            result["failed_count"] += 1
            result["failed"].append({
                "candidate_id": candidate_id,
                "error": str(error)[:2000],
            })

            logger.exception(
                "Review clip generation failed | Candidate: %s | Error: %s",
                candidate_id,
                error,
            )

        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    logger.info(
        "Review clip generation finished | "
        "Selected: %s | Generated: %s | Skipped: %s | Failed: %s",
        result["selected_count"],
        result["generated_count"],
        result["skipped_count"],
        result["failed_count"],
    )

    return result



# Final output is Shorts-only. Review clips remain separate previews.
def generate_output_clips(
    video_id: int,
    video_path: Path,
    selected_candidates: list[dict],
) -> dict:
    """Render Shorts directly from the unchanged original source."""

    video_path = Path(video_path)
    if not video_path.is_file() or video_path.stat().st_size == 0:
        raise FileNotFoundError(
            f"Original source video is missing or empty: {video_path}"
        )

    metadata = get_video_metadata(video_path)
    video_duration = float(metadata["duration"])

    if not math.isfinite(video_duration) or video_duration <= 0:
        raise ValueError(f"Invalid source video duration: {video_duration}")

    paths = ensure_video_storage(video_id)
    clips_directory = paths["clips"]
    logger = get_video_logger(video_id)

    result = {
        "video_id": video_id,
        "full_screen": False,
        "output_format": "youtube_shorts",
        "resolution": "1080x1920",
        "source": "original_video",
        "source_width": metadata["width"],
        "source_height": metadata["height"],
        "source_frame_rate": metadata["frame_rate"],
        "selected_count": len(selected_candidates),
        "generated_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "generated": [],
        "skipped": [],
        "failed": [],
    }

    logger.info(
        "Shorts generation started | Original source | "
        "1080x1920 | libx264 slow CRF 18 | Selected: %s",
        len(selected_candidates),
    )

    for candidate in selected_candidates:
        candidate_id = None
        temporary_path = None

        try:
            candidate_id = int(candidate["id"])
            output_path = (
                clips_directory / f"candidate_{candidate_id}_shorts.mp4"
            )

            if output_path.exists():
                result["skipped_count"] += 1
                result["skipped"].append({
                    "candidate_id": candidate_id,
                    "filename": output_path.name,
                    "reason": "Output already exists; not overwritten.",
                })
                continue

            start = float(candidate["start_time"])
            end = float(candidate["end_time"])

            if (
                not math.isfinite(start)
                or not math.isfinite(end)
                or end <= start
            ):
                raise ValueError("Candidate has invalid timestamps.")

            clip_start = max(0.0, start - CLIP_PADDING_SECONDS)
            clip_end = min(video_duration, end + CLIP_PADDING_SECONDS)
            clip_duration = clip_end - clip_start

            if clip_duration <= 0:
                raise ValueError("Calculated Shorts duration is invalid.")

            temporary_path = (
                clips_directory
                / f".candidate_{candidate_id}_{uuid.uuid4().hex}.tmp.mp4"
            )

            video_filter = (
                "[0:v]split=2[background][foreground];"
                "[background]"
                "scale=1080:1920:force_original_aspect_ratio=increase:"
                "flags=lanczos,crop=1080:1920,boxblur=20:10[blurred];"
                "[foreground]"
                "scale=1080:1920:force_original_aspect_ratio=decrease:"
                "flags=lanczos[fitted];"
                "[blurred][fitted]overlay=(W-w)/2:(H-h)/2,"
                "setsar=1,format=yuv420p[output]"
            )

            command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-nostdin",
                "-n",
                "-ss", f"{clip_start:.6f}",
                "-i", str(video_path),
                "-t", f"{clip_duration:.6f}",
                "-filter_complex", video_filter,
                "-map", "[output]",
                "-map", "0:a?",
                "-c:v", "libx264",
                "-preset", "slow",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                "-avoid_negative_ts", "make_zero",
                str(temporary_path),
            ]

            subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=1800,
                check=True,
            )

            if (
                not temporary_path.is_file()
                or temporary_path.stat().st_size == 0
            ):
                raise RuntimeError("FFmpeg produced an empty Shorts file.")

            # Atomic creation prevents overwriting an existing output.
            try:
                os.link(temporary_path, output_path)
            except FileExistsError:
                result["skipped_count"] += 1
                result["skipped"].append({
                    "candidate_id": candidate_id,
                    "filename": output_path.name,
                    "reason": "Output appeared during generation; not overwritten.",
                })
                continue

            clip_info = {
                "candidate_id": candidate_id,
                "filename": output_path.name,
                "size_bytes": output_path.stat().st_size,
                "format": "youtube_shorts",
                "resolution": "1080x1920",
                "source": "original_video",
            }

            result["generated_count"] += 1
            result["generated"].append(clip_info)

            logger.info(
                "Shorts generated | Candidate: %s | File: %s | Bytes: %s",
                candidate_id,
                output_path.name,
                clip_info["size_bytes"],
            )

        except Exception as error:
            result["failed_count"] += 1
            result["failed"].append({
                "candidate_id": candidate_id,
                "error": str(error)[:2000],
            })
            logger.exception(
                "Shorts generation failed | Candidate: %s | Error: %s",
                candidate_id,
                error,
            )

        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    logger.info(
        "Shorts generation finished | Generated: %s | "
        "Skipped: %s | Failed: %s",
        result["generated_count"],
        result["skipped_count"],
        result["failed_count"],
    )

    return result

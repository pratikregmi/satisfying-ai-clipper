
from fractions import Fraction
from pathlib import Path
import subprocess
import cv2

from scenedetect import SceneManager, open_video
from scenedetect.detectors import ContentDetector


def detect_scenes(video_path: Path, threshold: float = 27.0):
    video = open_video(str(video_path))

    scene_manager = SceneManager()
    scene_manager.add_detector(
        ContentDetector(
            threshold=threshold,
            min_scene_len=15,
        )
    )

    scene_manager.detect_scenes(video, show_progress=True)
    scene_list = scene_manager.get_scene_list()

    results = []

    for index, (start, end) in enumerate(scene_list, start=1):
        start_seconds = start.get_seconds()
        end_seconds = end.get_seconds()

        results.append({
            "scene_number": index,
            "start_time": start_seconds,
            "end_time": end_seconds,
            "duration": end_seconds - start_seconds,
        })

    return results


from fractions import Fraction
from pathlib import Path
import cv2


def generate_scene_thumbnails(
    video_path: Path,
    scenes: list,
    output_dir: Path,
    frame_rate: str,
) -> list[Path]:

    if not scenes:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        fps = float(Fraction(frame_rate))
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"Invalid frame rate: {frame_rate}")

    if fps <= 0:
        raise ValueError("Video frame rate must be positive.")

    # Map each target frame to its scene number.
    target_frames = {}

    for index, scene in enumerate(scenes, start=1):
        frame_number = max(0, round(scene.start_time * fps))
        target_frames.setdefault(frame_number, []).append(index)

    max_frame = max(target_frames)

    capture = cv2.VideoCapture(str(video_path))

    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    created_paths = {}

    try:
        current_frame = 0

        while current_frame <= max_frame:
            success, frame = capture.read()

            if not success:
                break

            if current_frame in target_frames:
                height, width = frame.shape[:2]

                new_width = 480
                new_height = round(height * new_width / width)

                thumbnail = cv2.resize(
                    frame,
                    (new_width, new_height),
                    interpolation=cv2.INTER_AREA,
                )

                for scene_number in target_frames[current_frame]:
                    output_path = (
                        output_dir
                        / f"scene_{scene_number:04d}.jpg"
                    )

                    saved = cv2.imwrite(
                        str(output_path),
                        thumbnail,
                        [cv2.IMWRITE_JPEG_QUALITY, 90],
                    )

                    if not saved:
                        raise RuntimeError(
                            f"Failed to save thumbnail: {output_path}"
                        )

                    created_paths[scene_number] = output_path

            current_frame += 1

    finally:
        capture.release()

    expected = len(scenes)

    if len(created_paths) != expected:
        raise RuntimeError(
            f"Only generated {len(created_paths)} of {expected} "
            "scene thumbnails. Check the video decoding and frame rate."
        )

    return [
        created_paths[index]
        for index in range(1, expected + 1)
    ]

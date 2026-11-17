
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.moment_candidate import MomentCandidate
from backend.app.models.scene import Scene
from backend.app.models.scene_analysis import SceneAnalysis
from backend.app.models.transcription import TranscriptSegment


DISCOVERY_VERSION = "v1"

MIN_DURATION = 15.0
MAX_DURATION = 60.0

WINDOW_LENGTHS = [15.0, 25.0, 35.0, 45.0, 60.0]

START_INTERVAL = 10.0


def format_timestamp(seconds: float) -> str:
    total_seconds = int(seconds)
    minutes = total_seconds // 60
    remaining_seconds = total_seconds % 60

    return f"{minutes:02d}:{remaining_seconds:02d}"


def build_candidate_windows(scenes: list[Scene]) -> list[dict]:
    """
    Generate overlapping candidate windows using scene boundaries.
    """

    if not scenes:
        return []

    windows = []
    seen_windows = set()

    next_anchor_time = scenes[0].start_time

    for start_index, start_scene in enumerate(scenes):

        if start_scene.start_time < next_anchor_time:
            continue

        next_anchor_time = start_scene.start_time + START_INTERVAL

        for target_length in WINDOW_LENGTHS:

            target_end = start_scene.start_time + target_length

            possible_end_scenes = []

            for end_scene in scenes[start_index:]:

                duration = end_scene.end_time - start_scene.start_time

                if duration < MIN_DURATION:
                    continue

                if duration > MAX_DURATION:
                    break

                possible_end_scenes.append(end_scene)

                if end_scene.end_time >= target_end:
                    break

            if not possible_end_scenes:
                continue

            end_scene = min(
                possible_end_scenes,
                key=lambda scene: abs(
                    scene.end_time - target_end
                ),
            )

            start_time = start_scene.start_time
            end_time = end_scene.end_time
            duration = end_time - start_time

            if duration < MIN_DURATION or duration > MAX_DURATION:
                continue

            window_key = (
                round(start_time, 2),
                round(end_time, 2),
            )

            if window_key in seen_windows:
                continue

            seen_windows.add(window_key)

            window_scenes = [
                scene
                for scene in scenes[start_index:]
                if (
                    scene.start_time < end_time
                    and scene.end_time > start_time
                )
            ]

            if not window_scenes:
                continue

            windows.append(
                {
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                    "scenes": window_scenes,
                }
            )

    return windows


def discover_video_moments(
    db: Session,
    video_id: int,
) -> dict:
    """
    Generate potential video moments using saved scene analyses
    and transcript segments.

    This stage does not call Ollama.
    """

    scenes = list(
        db.scalars(
            select(Scene)
            .where(Scene.video_id == video_id)
            .order_by(Scene.start_time.asc())
        ).all()
    )

    if not scenes:
        raise ValueError(
            f"No scenes found for video {video_id}."
        )

    scene_ids = [scene.id for scene in scenes]

    analyses = list(
        db.scalars(
            select(SceneAnalysis)
            .where(SceneAnalysis.scene_id.in_(scene_ids))
        ).all()
    )

    analysis_by_scene = {
        analysis.scene_id: analysis
        for analysis in analyses
    }

    transcripts = list(
        db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.video_id == video_id)
            .order_by(TranscriptSegment.start_time.asc())
        ).all()
    )

    windows = build_candidate_windows(scenes)

    existing_candidates = list(
        db.scalars(
            select(MomentCandidate)
            .where(
                MomentCandidate.video_id == video_id,
                MomentCandidate.discovery_version == DISCOVERY_VERSION,
            )
        ).all()
    )

    existing_keys = {
        (
            round(candidate.start_time, 2),
            round(candidate.end_time, 2),
        )
        for candidate in existing_candidates
    }

    created_candidates = []
    skipped_candidates = 0

    for window in windows:

        start_time = window["start_time"]
        end_time = window["end_time"]

        candidate_key = (
            round(start_time, 2),
            round(end_time, 2),
        )

        if candidate_key in existing_keys:
            skipped_candidates += 1
            continue

        window_scenes = window["scenes"]

        window_scene_ids = [
            scene.id for scene in window_scenes
        ]

        # Attach dialogue using transcript start times only.
        # Transcript end times are not trusted for boundaries.

        window_transcripts = [
            segment
            for segment in transcripts
            if start_time <= segment.start_time < end_time
        ]

        transcript_lines = [
            segment.text.strip()
            for segment in window_transcripts
            if segment.text.strip()
        ]

        transcript_excerpt = "\n".join(
            transcript_lines
        )

        # Collect existing visual descriptions.

        visual_evidence = []

        for scene in window_scenes:

            analysis = analysis_by_scene.get(scene.id)

            if analysis is None:
                continue

            visual_evidence.append(
                {
                    "scene_id": scene.id,
                    "scene_number": scene.scene_number,
                    "start_time": scene.start_time,
                    "end_time": scene.end_time,
                    "description": analysis.description,
                    "characters": analysis.characters,
                    "actions": analysis.actions,
                    "objects": analysis.objects,
                    "setting": analysis.setting,
                    "mood": analysis.mood,
                }
            )

        suspicious_transcripts = [
            {
                "segment_id": segment.id,
                "start_time": segment.start_time,
                "reported_duration": round(
                    segment.end_time - segment.start_time,
                    2,
                ),
                "text": segment.text,
            }
            for segment in window_transcripts
            if segment.end_time - segment.start_time > 8.0
        ]

        first_dialogue = next(
            (
                line
                for line in transcript_lines
                if line
            ),
            None,
        )

        title = (
            first_dialogue[:100]
            if first_dialogue
            else (
                "Potential moment at "
                + format_timestamp(start_time)
            )
        )

        visual_descriptions = [
            item["description"]
            for item in visual_evidence
            if item["description"]
        ]

        summary_parts = []

        if transcript_lines:
            summary_parts.append(
                "Dialogue: " + " ".join(transcript_lines)
            )

        if visual_descriptions:
            summary_parts.append(
                "Visual context: "
                + " ".join(visual_descriptions[:5])
            )

        summary = "\n\n".join(summary_parts)

        if not summary:
            summary = (
                "Potential moment based on scene timing. "
                "No saved visual descriptions or dialogue "
                "were available for this window."
            )

        evidence = {
            "discovery_version": DISCOVERY_VERSION,
            "scene_count": len(window_scenes),
            "transcript_segment_ids": [
                segment.id
                for segment in window_transcripts
            ],
            "visual_evidence": visual_evidence,
            "suspicious_transcript_intervals": (
                suspicious_transcripts
            ),
            "boundary_method": "scene_boundaries",
            "transcript_timing_method": (
                "transcript_start_time_only"
            ),
        }

        candidate = MomentCandidate(
            video_id=video_id,
            title=title,
            summary=summary,
            start_time=start_time,
            end_time=end_time,
            duration=window["duration"],
            scene_ids=json.dumps(window_scene_ids),
            transcript_excerpt=transcript_excerpt,
            evidence=json.dumps(evidence),
            status="pending",
            discovery_version=DISCOVERY_VERSION,
        )

        db.add(candidate)
        created_candidates.append(candidate)

        existing_keys.add(candidate_key)

    db.commit()

    for candidate in created_candidates:
        db.refresh(candidate)

    return {
        "video_id": video_id,
        "discovery_version": DISCOVERY_VERSION,
        "total_scenes": len(scenes),
        "total_transcript_segments": len(transcripts),
        "total_windows_generated": len(windows),
        "candidates_created": len(created_candidates),
        "candidates_skipped_as_duplicates": skipped_candidates,
        "candidates": [
            {
                "id": candidate.id,
                "title": candidate.title,
                "start_time": candidate.start_time,
                "end_time": candidate.end_time,
                "duration": candidate.duration,
                "scene_count": len(
                    json.loads(candidate.scene_ids)
                ),
                "transcript_excerpt": (
                    candidate.transcript_excerpt[:300]
                ),
                "status": candidate.status,
            }
            for candidate in created_candidates
        ],
    }

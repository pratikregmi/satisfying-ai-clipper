def match_scenes_with_transcripts(scenes, transcript_segments):
    """
    Match transcript segments to scenes using timestamp overlap.

    Both inputs must be sorted by start_time.
    A transcript segment can match multiple scenes.
    """

    matches = []
    segment_index = 0

    for scene in scenes:

        # Skip transcript segments that finish before this scene.
        while (
            segment_index < len(transcript_segments)
            and transcript_segments[segment_index].end_time
            <= scene.start_time
        ):
            segment_index += 1

        current_index = segment_index

        # Check segments that begin before this scene ends.
        while current_index < len(transcript_segments):
            segment = transcript_segments[current_index]

            if segment.start_time >= scene.end_time:
                break

            overlap_start = max(
                scene.start_time,
                segment.start_time,
            )

            overlap_end = min(
                scene.end_time,
                segment.end_time,
            )

            overlap_duration = overlap_end - overlap_start

            if overlap_duration > 0:
                matches.append({
                    "video_id": scene.video_id,
                    "scene_id": scene.id,
                    "transcript_segment_id": segment.id,
                    "overlap_duration": round(
                        overlap_duration,
                        3,
                    ),
                })

            current_index += 1

    return matches

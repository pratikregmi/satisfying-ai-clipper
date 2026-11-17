
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.moment_candidate import MomentCandidate


HUMOR_KEYWORDS = {
    "funny", "joke", "laugh", "hilarious", "silly",
    "oops", "sorry", "what", "why", "really",
    "surprise", "surprised", "no way", "oh no",
    "mistake", "wrong", "crazy", "ridiculous",
}

EMOTION_KEYWORDS = {
    "angry", "sad", "happy", "scared", "shocked",
    "surprised", "excited", "crying", "afraid",
    "worried", "confused", "disappointed",
}

STORY_KEYWORDS = {
    "because", "but", "then", "finally", "suddenly",
    "sorry", "thank", "help", "problem", "together",
    "remember", "why", "what happened",
}

LOW_VALUE_PHRASES = {
    "oh",
    "okay",
    "yeah",
    "yes",
    "no",
    "hmm",
    "ah",
}


def count_keyword_matches(text: str, keywords: set[str]) -> int:
    text = text.lower()

    return sum(
        len(re.findall(r"\b" + re.escape(keyword) + r"\b", text))
        for keyword in keywords
    )


def calculate_dialogue_score(text: str) -> float:
    if not text.strip():
        return 0.0

    words = re.findall(r"\b[\w']+\b", text.lower())

    if not words:
        return 0.0

    if len(words) <= 2 and text.strip().lower().strip(".!?") in LOW_VALUE_PHRASES:
        return 5.0

    length_score = min(len(words) / 35, 1.0) * 35

    unique_word_ratio = len(set(words)) / len(words)
    variety_score = unique_word_ratio * 20

    dialogue_score = min(
        count_keyword_matches(text, HUMOR_KEYWORDS) * 5,
        25,
    )

    story_score = min(
        count_keyword_matches(text, STORY_KEYWORDS) * 4,
        20,
    )

    return round(
        min(
            length_score + variety_score + dialogue_score + story_score,
            100,
        ),
        2,
    )



def calculate_visual_score(candidate: MomentCandidate) -> float:
    try:
        evidence = json.loads(candidate.evidence or "{}")
    except (json.JSONDecodeError, TypeError):
        return 0.0

    scenes = evidence.get("visual_evidence", [])

    if not scenes:
        return 0.0

    generic_actions = {
        "standing",
        "standing still",
        "looking forward",
        "sitting",
        "smiling",
        "mouth open",
        "mouth slightly open",
        "eyes closed",
    }

    meaningful_keywords = {
        "peeking",
        "reacting",
        "gesturing",
        "leaping",
        "running",
        "jumping",
        "chasing",
        "interacting",
        "fighting",
        "playing",
        "throwing",
        "catching",
        "pointing",
        "waving",
        "dancing",
        "falling",
        "hiding",
        "approaching",
        "escaping",
        "surprised",
        "laughing",
        "crying",
        "arguing",
    }

    interaction_keywords = {
        "each other",
        "together",
        "at each other",
        "toward each other",
        "facing",
        "handing",
        "giving",
        "chasing",
        "playing with",
    }

    def parse_list(value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = [value]

        if isinstance(value, list):
            return [
                str(item).strip().lower()
                for item in value
                if str(item).strip()
            ]

        return []

    scene_actions = []
    scene_moods = []
    scene_character_counts = []

    descriptions_available = 0

    for scene in scenes:
        description = scene.get("description")

        if isinstance(description, str) and description.strip():
            descriptions_available += 1

        actions = parse_list(scene.get("actions"))
        characters = parse_list(scene.get("characters"))
        mood = str(scene.get("mood") or "").strip().lower()

        scene_actions.append(actions)
        scene_moods.append(mood)
        scene_character_counts.append(len(characters))

    # 1. Meaningful action evidence.
    all_actions = [
        action
        for actions in scene_actions
        for action in actions
    ]

    if all_actions:
        meaningful_count = sum(
            1
            for action in all_actions
            if action not in generic_actions
            and any(
                keyword in action
                for keyword in meaningful_keywords
            )
        )

        action_score = min(
            meaningful_count / max(len(scenes) * 0.5, 1) * 30,
            30,
        )
    else:
        action_score = 0.0

    # 2. Changes in action patterns between scenes.
    transitions = 0
    meaningful_transitions = 0

    for previous, current in zip(scene_actions, scene_actions[1:]):
        if previous and current:
            transitions += 1

            if set(previous) != set(current):
                meaningful_transitions += 1

    transition_score = (
        meaningful_transitions / transitions * 25
        if transitions
        else 0.0
    )

    # 3. Evidence of interaction between characters.
    interaction_scenes = 0

    for actions, character_count in zip(
        scene_actions,
        scene_character_counts,
    ):
        action_text = " ".join(actions)

        has_interaction = any(
            keyword in action_text
            for keyword in interaction_keywords
        )

        if character_count >= 2 and has_interaction:
            interaction_scenes += 1

    interaction_score = min(
        interaction_scenes / max(len(scenes) * 0.2, 1) * 20,
        20,
    )

    # 4. Mood changes across consecutive scenes.
    valid_moods = [
        mood for mood in scene_moods if mood
    ]

    mood_changes = sum(
        1
        for previous, current in zip(
            valid_moods,
            valid_moods[1:],
        )
        if previous != current
    )

    mood_score = min(
        mood_changes / max(len(valid_moods) * 0.4, 1) * 15,
        15,
    )

    # 5. Description coverage.
    coverage_score = (
        descriptions_available / len(scenes) * 10
    )

    total_score = (
        action_score
        + transition_score
        + interaction_score
        + mood_score
        + coverage_score
    )

    return round(min(total_score, 100.0), 2)


def calculate_emotion_score(candidate: MomentCandidate) -> float:
    text = (
        (candidate.transcript_excerpt or "")
        + " "
        + (candidate.summary or "")
    )

    emotion_count = count_keyword_matches(
        text,
        EMOTION_KEYWORDS,
    )

    return round(min(emotion_count * 15, 100), 2)


def calculate_duration_score(duration: float) -> float:
    if 20 <= duration <= 40:
        return 100.0

    if 15 <= duration < 20:
        return 75.0

    if 40 < duration <= 50:
        return 80.0

    return 60.0


def calculate_overlap_ratio(
    candidate: MomentCandidate,
    selected: MomentCandidate,
) -> float:
    intersection = max(
        0.0,
        min(candidate.end_time, selected.end_time)
        - max(candidate.start_time, selected.start_time),
    )

    shorter_duration = min(
        candidate.duration,
        selected.duration,
    )

    if shorter_duration <= 0:
        return 0.0

    return intersection / shorter_duration


def rank_video_moments(
    db: Session,
    video_id: int,
    max_results: int = 10,
    video_duration: float | None = None,
    temporal_buckets: int = 8,
    overlap_threshold: float = 0.50,
    minimum_score: float = 45.0,
) -> dict:
    candidates = list(
        db.scalars(
            select(MomentCandidate)
            .where(
                MomentCandidate.video_id == video_id,
                MomentCandidate.status == "pending",
            )
            .order_by(MomentCandidate.start_time.asc())
        ).all()
    )

    if not candidates:
        return {
            "video_id": video_id,
            "total_candidates": 0,
            "ranked_candidates": 0,
            "selected_count": 0,
            "selected_candidates": [],
        }

    if video_duration is None or video_duration <= 0:
        video_duration = max(
            candidate.end_time for candidate in candidates
        )

    temporal_buckets = max(1, temporal_buckets)
    video_duration = max(video_duration, 0.001)

    scored_candidates = []

    for candidate in candidates:
        dialogue_score = calculate_dialogue_score(
            candidate.transcript_excerpt or ""
        )

        visual_score = calculate_visual_score(candidate)

        emotion_score = calculate_emotion_score(candidate)

        duration_score = calculate_duration_score(
            candidate.duration
        )

        preliminary_score = (
            dialogue_score * 0.40
            + visual_score * 0.30
            + emotion_score * 0.20
            + duration_score * 0.10
        )

        preliminary_score = round(preliminary_score, 2)

        # Read the saved Qwen evaluation without changing the database.
        try:
            evidence = (
                json.loads(candidate.evidence or "{}")
                if isinstance(candidate.evidence, str)
                else candidate.evidence or {}
            )
        except (json.JSONDecodeError, TypeError):
            evidence = {}

        ai_evaluation = (
            evidence.get("ai_evaluation", {})
            if isinstance(evidence, dict)
            else {}
        )

        ai_overall = candidate.overall_score

        if ai_overall is None:
            ai_overall = ai_evaluation.get("overall_score")

        ai_confidence = candidate.confidence

        if ai_confidence is None:
            ai_confidence = ai_evaluation.get("confidence")

        completeness_score = ai_evaluation.get(
            "completeness_score"
        )

        is_evaluated = ai_overall is not None

        if is_evaluated:
            ai_overall = float(ai_overall)

            confidence = (
                max(0.0, min(float(ai_confidence or 0), 100.0))
                / 100.0
            )

            # Give completeness a smaller contribution than the
            # overall AI evaluation.
            if completeness_score is not None:
                ai_quality_score = (
                    ai_overall * 0.85
                    + float(completeness_score) * 0.15
                )
            else:
                ai_quality_score = ai_overall

            # Low-confidence AI evaluations have less influence.
            ai_weight = 0.70 * confidence

            final_score = (
                preliminary_score * (1 - ai_weight)
                + ai_quality_score * ai_weight
            )

        else:
            confidence = 0.0
            final_score = preliminary_score

        final_score = round(final_score, 2)

        midpoint = (
            candidate.start_time + candidate.end_time
        ) / 2

        bucket_index = min(
            int(midpoint / video_duration * temporal_buckets),
            temporal_buckets - 1,
        )

        bucket_index = max(0, bucket_index)

        scored_candidates.append({
            "candidate": candidate,
            "dialogue_score": dialogue_score,
            "visual_score": visual_score,
            "emotion_score": emotion_score,
            "duration_score": duration_score,
            "preliminary_score": preliminary_score,
            "ai_overall_score": ai_overall,
            "ai_confidence": round(confidence * 100, 2),
            "ai_evaluated": is_evaluated,
            "final_score": final_score,
            "temporal_bucket": bucket_index,
        })

    # Remove candidates below the minimum quality threshold.
    eligible_candidates = [
        item
        for item in scored_candidates
        if item["final_score"] >= minimum_score
    ]

    buckets = {
        index: []
        for index in range(temporal_buckets)
    }

    for item in eligible_candidates:
        buckets[item["temporal_bucket"]].append(item)

    for bucket in buckets.values():
        bucket.sort(
            key=lambda item: item["final_score"],
            reverse=True,
        )

    selected = []

    bucket_positions = {
        index: 0
        for index in range(temporal_buckets)
    }

    # Select high-quality candidates while spreading them
    # across the video's timeline.
    while len(selected) < max_results:
        made_progress = False

        for bucket_index in range(temporal_buckets):
            if len(selected) >= max_results:
                break

            bucket_candidates = buckets[bucket_index]
            position = bucket_positions[bucket_index]

            while position < len(bucket_candidates):
                item = bucket_candidates[position]
                candidate = item["candidate"]

                position += 1

                is_duplicate = any(
                    calculate_overlap_ratio(
                        candidate,
                        selected_item["candidate"],
                    ) >= overlap_threshold
                    for selected_item in selected
                )

                if is_duplicate:
                    continue

                selected.append(item)
                made_progress = True
                break

            bucket_positions[bucket_index] = position

        if not made_progress:
            break

    return {
        "video_id": video_id,
        "total_candidates": len(candidates),
        "ranked_candidates": len(scored_candidates),
        "eligible_candidates": len(eligible_candidates),
        "selected_count": len(selected),
        "temporal_buckets": temporal_buckets,
        "overlap_threshold": overlap_threshold,
        "minimum_score": minimum_score,
        "ai_evaluated_count": sum(
            1 for item in selected if item["ai_evaluated"]
        ),
        "selected_candidates": [
            {
                "id": item["candidate"].id,
                "title": item["candidate"].title,
                "start_time": item["candidate"].start_time,
                "end_time": item["candidate"].end_time,
                "duration": item["candidate"].duration,
                "preliminary_score": item["preliminary_score"],
                "ai_overall_score": item["ai_overall_score"],
                "ai_confidence": item["ai_confidence"],
                "ai_evaluated": item["ai_evaluated"],
                "final_score": item["final_score"],
                "dialogue_score": item["dialogue_score"],
                "visual_score": item["visual_score"],
                "emotion_score": item["emotion_score"],
                "duration_score": item["duration_score"],
                "temporal_bucket": item["temporal_bucket"],
            }
            for item in selected
        ],
    }

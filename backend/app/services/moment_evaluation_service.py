
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

# Register the referenced Video table before loading MomentCandidate.
from backend.app.models.video import Video
from backend.app.models.moment_candidate import MomentCandidate

from backend.app.services.scene_analysis_service import (
    MODEL_NAME,
    OLLAMA_URL,
)


def _parse_list(value) -> list:
    """Convert stored JSON strings or lists into a clean list."""

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [value]

    if isinstance(value, list):
        return [str(item) for item in value if item]

    return []


def _prepare_evidence(candidate: MomentCandidate) -> dict:
    """Prepare a compact evidence package for Qwen."""

    try:
        evidence = json.loads(candidate.evidence or "{}")
    except (json.JSONDecodeError, TypeError):
        evidence = {}

    visual_scenes = evidence.get("visual_evidence", [])

    # Use at most eight representative scenes to limit prompt size.
    if len(visual_scenes) > 8:
        indexes = [
            round(i * (len(visual_scenes) - 1) / 7)
            for i in range(8)
        ]
        visual_scenes = [visual_scenes[i] for i in indexes]

    compact_scenes = []

    for scene in visual_scenes:
        compact_scenes.append({
            "scene_number": scene.get("scene_number"),
            "start_time": scene.get("start_time"),
            "end_time": scene.get("end_time"),
            "description": scene.get("description", ""),
            "characters": _parse_list(scene.get("characters")),
            "actions": _parse_list(scene.get("actions")),
            "mood": scene.get("mood"),
        })

    return {
        "candidate_id": candidate.id,
        "title": candidate.title,
        "start_time": candidate.start_time,
        "end_time": candidate.end_time,
        "duration": candidate.duration,
        "transcript": (candidate.transcript_excerpt or "")[:3500],
        "scene_count": evidence.get("scene_count", len(visual_scenes)),
        "visual_scenes": compact_scenes,
        "suspicious_transcript_intervals": (
            evidence.get("suspicious_transcript_intervals", [])
        ),
    }


def _validate_score(data: dict, field: str) -> float:
    value = data.get(field)

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"AI response field '{field}' must be a number.")

    if not 0 <= value <= 100:
        raise ValueError(f"AI response field '{field}' must be between 0 and 100.")

    return round(float(value), 2)


def evaluate_moment_candidate(
    db: Session,
    candidate_id: int,
) -> dict:
    """
    Evaluate one discovered moment using local Ollama Qwen.

    This evaluates the supplied transcript and saved visual descriptions.
    It does not inspect original video frames or generate clips.
    """

    candidate = db.get(MomentCandidate, candidate_id)

    if candidate is None:
        raise ValueError(f"Moment candidate {candidate_id} was not found.")

    evidence = _prepare_evidence(candidate)

    prompt = """
You are evaluating a potential short-form video moment.

Use ONLY the evidence provided. The visual descriptions were generated
by another AI and may contain mistakes. Do not treat uncertain details
or character identities as facts.

Evaluate whether this is an interesting, understandable, self-contained
moment for a short-form audience.

Consider:
- Hook: Does it quickly attract attention?
- Humor: Is there clear comedic potential?
- Storytelling: Is the sequence coherent and understandable?
- Visual interest: Do the described actions and scene changes suggest
  engaging visuals? Be conservative because you cannot see the images.
- Completeness: Does the moment have a satisfying setup and payoff?
- Dialogue quality: Is the dialogue understandable and engaging?
- Overall: How strong is this candidate as a potential short-form moment?

Important rules:
- Do not reward a candidate merely for having lots of dialogue.
- Penalize garbled, contradictory, or confusing transcript evidence.
- Treat unusually long transcript intervals as unreliable timing evidence.
- Do not assume that a scene description proves an event happened.
- If the candidate appears to start or end mid-conversation, reflect that
  in its completeness score.
- Be honest about uncertainty.
- Scores must be numbers from 0 to 100.
- Return valid JSON only.

Return exactly these fields:
{
  "hook_score": 0,
  "humor_score": 0,
  "storytelling_score": 0,
  "visual_interest_score": 0,
  "completeness_score": 0,
  "dialogue_quality_score": 0,
  "overall_score": 0,
  "confidence": 0,
  "explanation": "A concise explanation of the evaluation.",
  "strengths": ["Evidence-based strength"],
  "weaknesses": ["Evidence-based weakness"]
}

Candidate evidence:
""" + json.dumps(evidence, ensure_ascii=False)

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "format": "json",
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.1,
        },
    }

    request = Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=300) as response:
            result = json.loads(response.read().decode("utf-8"))

    except HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Ollama returned HTTP {error.code}: {error_body}"
        ) from error

    except URLError as error:
        raise RuntimeError(
            "Could not connect to Ollama. Make sure Ollama is running."
        ) from error

    response_text = result.get("message", {}).get("content", "")

    try:
        evaluation = json.loads(response_text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Ollama returned invalid JSON: {response_text}"
        ) from error

    score_fields = [
        "hook_score",
        "humor_score",
        "storytelling_score",
        "visual_interest_score",
        "completeness_score",
        "dialogue_quality_score",
        "overall_score",
        "confidence",
    ]

    for field in score_fields:
        evaluation[field] = _validate_score(evaluation, field)

    if not isinstance(evaluation.get("explanation"), str):
        raise ValueError("AI response explanation must be text.")

    for field in ["strengths", "weaknesses"]:
        if not isinstance(evaluation.get(field), list):
            raise ValueError(f"AI response field '{field}' must be a list.")

        evaluation[field] = [
            str(item) for item in evaluation[field]
        ]

    # Save the supported scores to their existing database columns.
    candidate.humor_score = evaluation["humor_score"]
    candidate.storytelling_score = evaluation["storytelling_score"]
    candidate.visual_interest_score = evaluation["visual_interest_score"]
    candidate.completeness_score = evaluation["completeness_score"]
    candidate.overall_score = evaluation["overall_score"]
    candidate.confidence = evaluation["confidence"]
    candidate.explanation = evaluation["explanation"]

    # Keep additional evaluation fields without changing the database schema.
    try:
        stored_evidence = json.loads(candidate.evidence or "{}")
    except (json.JSONDecodeError, TypeError):
        stored_evidence = {}

    stored_evidence["ai_evaluation"] = {
        **evaluation,
        "model_name": MODEL_NAME,
    }

    candidate.evidence = json.dumps(stored_evidence, ensure_ascii=False)

    db.commit()
    db.refresh(candidate)

    return {
        "candidate_id": candidate.id,
        "title": candidate.title,
        "start_time": candidate.start_time,
        "end_time": candidate.end_time,
        "duration": candidate.duration,
        "evaluation": evaluation,
        "model_name": MODEL_NAME,
        "saved": True,
    }


def evaluate_moment_candidates_batch(
    db: Session,
    candidate_ids: list[int],
    batch_size: int = 3,
) -> dict:
    """
    Evaluate a limited number of candidates sequentially.

    Already evaluated candidates are skipped.
    Each successful evaluation is committed by
    evaluate_moment_candidate().
    Failed candidates do not stop the remaining batch.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")

    results = {
        "requested": len(candidate_ids),
        "processed": 0,
        "evaluated": [],
        "skipped": [],
        "failed": [],
    }

    # Process only the requested batch size.
    for candidate_id in candidate_ids[:batch_size]:
        candidate = db.get(MomentCandidate, candidate_id)

        if candidate is None:
            results["failed"].append({
                "candidate_id": candidate_id,
                "error": "Candidate not found.",
            })
            continue

        # Check whether an AI evaluation was already saved.
        try:
            stored_evidence = json.loads(candidate.evidence or "{}")
        except (json.JSONDecodeError, TypeError):
            stored_evidence = {}

        already_evaluated = (
            isinstance(stored_evidence.get("ai_evaluation"), dict)
            or candidate.overall_score is not None
        )

        if already_evaluated:
            results["skipped"].append(candidate_id)
            continue

        try:
            evaluation_result = evaluate_moment_candidate(
                db,
                candidate_id,
            )

            results["evaluated"].append(evaluation_result)

        except Exception as error:
            db.rollback()

            results["failed"].append({
                "candidate_id": candidate_id,
                "error": str(error),
            })

        results["processed"] += 1

    results["evaluated_count"] = len(results["evaluated"])
    results["skipped_count"] = len(results["skipped"])
    results["failed_count"] = len(results["failed"])

    return results

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.clip_metadata import ClipMetadata
from backend.app.models.moment_candidate import MomentCandidate
from backend.app.services.scene_analysis_service import (
    MODEL_NAME,
    OLLAMA_URL,
)


def _parse_list(value) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [value]

    if isinstance(value, list):
        return [str(item) for item in value if item]

    return []


def _prepare_metadata_evidence(candidate: MomentCandidate) -> dict:
    try:
        evidence = json.loads(candidate.evidence or "{}")
    except (json.JSONDecodeError, TypeError):
        evidence = {}

    visual_scenes = evidence.get("visual_evidence", [])

    if not isinstance(visual_scenes, list):
        visual_scenes = []

    if len(visual_scenes) > 8:
        indexes = [
            round(i * (len(visual_scenes) - 1) / 7)
            for i in range(8)
        ]
        visual_scenes = [visual_scenes[i] for i in indexes]

    compact_scenes = []

    for scene in visual_scenes:
        if not isinstance(scene, dict):
            continue

        compact_scenes.append({
            "scene_number": scene.get("scene_number"),
            "start_time": scene.get("start_time"),
            "end_time": scene.get("end_time"),
            "description": str(scene.get("description") or "")[:500],
            "characters": _parse_list(scene.get("characters")),
            "actions": _parse_list(scene.get("actions")),
            "mood": scene.get("mood"),
        })

    return {
        "candidate_id": candidate.id,
        "candidate_title": candidate.title,
        "candidate_summary": candidate.summary,
        "start_time": candidate.start_time,
        "end_time": candidate.end_time,
        "duration": candidate.duration,
        "transcript": (candidate.transcript_excerpt or "")[:3500],
        "visual_scenes": compact_scenes,
    }


def metadata_to_dict(metadata: ClipMetadata) -> dict:
    try:
        hashtags = json.loads(metadata.hashtags or "[]")
    except (json.JSONDecodeError, TypeError):
        hashtags = []

    if not isinstance(hashtags, list):
        hashtags = []

    return {
        "id": metadata.id,
        "candidate_id": metadata.candidate_id,
        "title": metadata.title,
        "description": metadata.description,
        "hashtags": hashtags,
        "status": metadata.status,
        "model_name": metadata.model_name,
        "error_message": metadata.error_message,
        "created_at": (
            metadata.created_at.isoformat()
            if metadata.created_at else None
        ),
        "updated_at": (
            metadata.updated_at.isoformat()
            if metadata.updated_at else None
        ),
    }


def _validate_metadata(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("AI metadata response must be a JSON object.")

    title = data.get("title")
    description = data.get("description")
    hashtags = data.get("hashtags")

    if not isinstance(title, str) or not title.strip():
        raise ValueError("AI response must contain a non-empty title.")

    if len(title.strip()) > 255:
        raise ValueError("Generated title exceeds 255 characters.")

    if not isinstance(description, str) or not description.strip():
        raise ValueError("AI response must contain a non-empty description.")

    if not isinstance(hashtags, list):
        raise ValueError("AI response hashtags must be a list.")

    cleaned_hashtags = []

    for item in hashtags:
        if not isinstance(item, str):
            continue

        tag = re.sub(r"[^\w]", "", item.strip().lstrip("#"))

        if tag and tag.lower() not in {
            existing.lower() for existing in cleaned_hashtags
        }:
            cleaned_hashtags.append(tag)

    if not 3 <= len(cleaned_hashtags) <= 8:
        raise ValueError("AI must generate between 3 and 8 valid hashtags.")

    return {
        "title": title.strip(),
        "description": description.strip(),
        "hashtags": cleaned_hashtags,
    }


def generate_clip_metadata(
    db: Session,
    video_id: int,
    candidate_id: int,
) -> dict:
    candidate = db.scalar(
        select(MomentCandidate).where(
            MomentCandidate.id == candidate_id,
            MomentCandidate.video_id == video_id,
        )
    )

    if candidate is None:
        raise ValueError(
            f"Candidate {candidate_id} was not found for video {video_id}."
        )

    metadata = db.scalar(
        select(ClipMetadata).where(
            ClipMetadata.candidate_id == candidate_id
        )
    )

    if metadata is None:
        metadata = ClipMetadata(candidate_id=candidate_id)
        db.add(metadata)

    metadata.status = "generating"
    metadata.model_name = MODEL_NAME
    metadata.error_message = None
    db.commit()
    db.refresh(metadata)

    evidence = _prepare_metadata_evidence(candidate)

    prompt = """
You are the YouTube Shorts metadata writer for ChaosReel,
a channel featuring funny and entertaining gaming, podcast,
livestream, and other video moments.

Create metadata for THIS SPECIFIC clip using only the supplied evidence.

Rules:
- Write a catchy, natural, curiosity-building title.
- Keep the title accurate and ideally under 90 characters.
- Explain what actually happens in this moment in the description.
- Make the description engaging, readable, and suitable for YouTube Shorts.
- Generate 3 to 8 relevant hashtags.
- Include #ChaosReel among the hashtags.
- Use other hashtags based on the actual clip content.
- Never invent a game, person, quote, event, reaction, or outcome.
- Do not claim something happened unless supported by the transcript
  or visual evidence.
- If evidence is uncertain, use neutral wording.
- Avoid generic descriptions that could apply to any clip.
- Do not include a separate title or hashtag section inside the description.
- Return valid JSON only.

Return exactly this structure:
{
  "title": "Catchy clip-specific title",
  "description": "A concise explanation of this actual moment.",
  "hashtags": ["ChaosReel", "RelevantTopic", "YouTubeShorts"]
}

Clip evidence:
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
            "temperature": 0.4,
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

        response_text = result.get("message", {}).get("content", "")
        generated = _validate_metadata(json.loads(response_text))

        metadata.title = generated["title"]
        metadata.description = generated["description"]
        metadata.hashtags = json.dumps(
            generated["hashtags"],
            ensure_ascii=False,
        )
        metadata.status = "completed"
        metadata.model_name = MODEL_NAME
        metadata.error_message = None

        db.commit()
        db.refresh(metadata)

        return metadata_to_dict(metadata)

    except HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        failure_message = f"Ollama returned HTTP {error.code}: {error_body}"

    except URLError:
        failure_message = (
            "Could not connect to Ollama. Make sure Ollama is running."
        )

    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        failure_message = f"Metadata validation failed: {error}"

    except Exception as error:
        failure_message = f"Metadata generation failed: {error}"

    db.rollback()

    metadata = db.scalar(
        select(ClipMetadata).where(
            ClipMetadata.candidate_id == candidate_id
        )
    )

    if metadata is None:
        raise RuntimeError(failure_message)

    metadata.status = "failed"
    metadata.error_message = failure_message[:2000]
    metadata.model_name = MODEL_NAME
    db.commit()
    db.refresh(metadata)

    return metadata_to_dict(metadata)

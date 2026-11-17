
import base64
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "qwen3.5:4b"


def analyze_scene_image(image_path: Path) -> dict:
    """
    Analyze one scene thumbnail using the local Ollama vision model.
    """

    if not image_path.is_file():
        raise FileNotFoundError(
            f"Scene thumbnail not found: {image_path}"
        )

    with image_path.open("rb") as image_file:
        image_base64 = base64.b64encode(
            image_file.read()
        ).decode("utf-8")

    prompt = """
Analyze this video scene image.

Return a JSON object with exactly these fields:

{
  "description": "A concise description of what is visibly happening.",
  "characters": ["Visible characters or people"],
  "actions": ["Visible actions"],
  "objects": ["Important visible objects"],
  "setting": "The visible location or environment",
  "mood": "The overall mood or atmosphere"
}

Rules:
- Only describe details supported by the image.
- Do not invent character names or identities.
- Use an empty array when no characters, actions, or objects can be identified.
- Keep the description concise and factual.
- Return valid JSON only.
"""

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_base64],
            }
        ],
        "format": "json",
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.2,
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
        analysis = json.loads(response_text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Ollama returned invalid JSON: {response_text}"
        ) from error

    required_fields = [
        "description",
        "characters",
        "actions",
        "objects",
        "setting",
        "mood",
    ]

    for field in required_fields:
        if field not in analysis:
            raise ValueError(
                f"AI response is missing the field: {field}"
            )

    for field in ["characters", "actions", "objects"]:
        if not isinstance(analysis[field], list):
            raise ValueError(
                f"AI response field '{field}' must be a list."
            )

    return {
        "description": str(analysis["description"]),
        "characters": analysis["characters"],
        "actions": analysis["actions"],
        "objects": analysis["objects"],
        "setting": (
            str(analysis["setting"])
            if analysis["setting"] is not None else None
        ),
        "mood": (
            str(analysis["mood"])
            if analysis["mood"] is not None else None
        ),
        "raw_response": response_text,
        "model_name": MODEL_NAME,
    }
